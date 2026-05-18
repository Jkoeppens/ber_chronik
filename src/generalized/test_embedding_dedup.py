"""
test_embedding_dedup.py — Embedding-Clustering als Ersatz für _llm_group testen.

Vergleicht Cosine-Similarity-Clustering (sentence-transformers) gegen LLM-Gruppierung
auf den Roh-Entities aus dem GLiNER-Run auf damaskus_test_2/b1e1d872.

Setup:
  pip install sentence-transformers --break-system-packages

Caching: GLiNER-Output und LLM-Group-Output werden in /tmp gespeichert.
  Erster Lauf: ~7–8 min (GLiNER ~30s + LLM-Group ~6 min + Embedding-Clustering <10s)
  Folgeläufe: ~30s (nur GLiNER + Embeddings, LLM-Group aus Cache)

CLI:
  python -m src.generalized.test_embedding_dedup
  python -m src.generalized.test_embedding_dedup --no-llm   # überspringt LLM-Group (kein API-Call)
  python -m src.generalized.test_embedding_dedup --force    # ignoriert Cache, läuft alles neu
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from src.generalized.config import (
    GLINER_LABELS,
    GLINER_MAX_CHARS,
    GLINER_MODEL,
    GLINER_THRESHOLD,
    PROJECTS_DIR,
    ROOT,
)
from src.generalized.entity_utils import _merge, _normalize_entity

PROJECT = "damaskus_test_2"
DOC     = "b1e1d872"

THRESHOLDS  = [0.80, 0.85, 0.90]
EMB_MODEL   = "paraphrase-multilingual-MiniLM-L12-v2"
CACHE_DIR   = Path("/tmp/ber_chronik_emb_test")
CACHE_GLINER = CACHE_DIR / "pre_group.json"
CACHE_LLM    = CACHE_DIR / "llm_grouped.json"


# ── GLiNER-Phase (identisch zu entity_gliner, ohne LLM-Schritte) ─────────────

_LABEL_TO_TYPE = {
    "Person":                   "Person",
    "Organisation":             "Organisation",
    "geographischer Ort":       "Ort",
    "politische Bewegung":      "Organisation",
    "religiöse Institution":    "Organisation",
    "Zeitung oder Publikation": "Organisation",
}


def _chunk(text: str, max_chars: int = GLINER_MAX_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split = text.rfind(". ", 0, max_chars)
        split = (split + 1) if split != -1 else max_chars
        chunks.append(text[:split].strip())
        text = text[split:].strip()
    return [c for c in chunks if c]


def run_gliner_phase(segments: list[dict]) -> list[dict]:
    """Führt GLiNER-Extraktion + _merge aus, ohne LLM-Schritte."""
    from gliner import GLiNER

    def _skip(s: dict) -> bool:
        if s.get("item_type") == "videoRecording":
            return True
        if s.get("item_type") is None and len(s.get("text", "")) > 20_000:
            return True
        return False

    content_segs = [s for s in segments
                    if s.get("type") == "content" and not _skip(s)]
    print(f"  GLiNER: {len(content_segs)} Segmente (θ={GLINER_THRESHOLD}) …")

    t0  = time.perf_counter()
    model = GLiNER.from_pretrained(GLINER_MODEL)
    print(f"  Modell geladen in {time.perf_counter()-t0:.1f}s")

    raw: list[dict] = []
    for seg in content_segs:
        text = seg.get("text", "")
        if not text:
            continue
        for chunk in _chunk(text):
            try:
                ents = model.predict_entities(chunk, GLINER_LABELS, threshold=GLINER_THRESHOLD)
            except Exception as exc:
                print(f"  WARNING: {exc}", file=sys.stderr)
                continue
            for ent in ents:
                typ  = _LABEL_TO_TYPE.get(ent["label"], "Konzept")
                norm = ent["text"].strip()
                if not norm:
                    continue
                n = _normalize_entity(
                    {"normalform": norm, "typ": typ, "aliases": [],
                     "score": round(ent["score"], 3)},
                    "gliner", frozenset(),
                )
                if n is not None:
                    raw.append(n)

    deduped = _merge([raw])
    elapsed = time.perf_counter() - t0
    print(f"  {len(raw)} Roh-Entities → {len(deduped)} nach _merge()  [{elapsed:.1f}s]")
    return deduped


# ── Embedding-Clustering ──────────────────────────────────────────────────────

def _embed(entities: list[dict], model) -> np.ndarray:
    texts = [e.get("normalform", "") for e in entities]
    embs  = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return np.array(embs, dtype=np.float32)


def _union_find_cluster(entities: list[dict], embs: np.ndarray, threshold: float):
    n = len(entities)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    # Similarity-Matrix (dot product auf normierten Vektoren = Cosine)
    sim = embs @ embs.T

    merges: list[tuple[str, str, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            s = float(sim[i, j])
            if s >= threshold:
                if find(i) != find(j):
                    merges.append((
                        entities[i]["normalform"],
                        entities[j]["normalform"],
                        s,
                    ))
                union(i, j)

    # Cluster aufbauen
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    result: list[dict] = []
    for root, indices in groups.items():
        cluster = [entities[i] for i in indices]
        # Normalform: die vollständigste (meiste Wörter, bei Gleichstand längster String)
        best = max(cluster, key=lambda e: (
            len(e.get("normalform", "").split()),
            len(e.get("normalform", "")),
        ))
        # Alle Aliases zusammenführen
        all_aliases: set[str] = set()
        for e in cluster:
            if e.get("normalform") != best["normalform"]:
                all_aliases.add(e["normalform"])
            all_aliases.update(e.get("aliases", []))
        all_aliases.discard(best["normalform"])
        # Typ: Mehrheit
        typ = Counter(e.get("typ", "Konzept") for e in cluster).most_common(1)[0][0]
        # Score: Maximum
        scores = [e.get("score") for e in cluster if e.get("score") is not None]
        score  = max(scores) if scores else None

        result.append({
            "normalform": best["normalform"],
            "typ":        typ,
            "aliases":    sorted(all_aliases),
            "score":      score,
            "_cluster_size": len(cluster),
        })

    return result, merges


# ── LLM-Group (mit Cache) ─────────────────────────────────────────────────────

def run_llm_group(pre_group: list[dict]) -> list[dict]:
    from src.generalized.llm import get_provider, TASK_EXTRACT
    from src.generalized.entity_llm import _llm_group

    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_EXTRACT)
    print(f"  _llm_group: {len(pre_group)} Entities …")
    t0      = time.perf_counter()
    grouped = _llm_group(pre_group, provider, frozenset())
    print(f"  → {len(grouped)} Entities  [{time.perf_counter()-t0:.1f}s]")
    return grouped


# ── Ausgabe ───────────────────────────────────────────────────────────────────

W = 64


def _print_header(title: str) -> None:
    print(f"\n{'═' * W}")
    print(f"  {title}")
    print(f"{'═' * W}")


def _type_dist(entities: list[dict]) -> str:
    d = Counter(e.get("typ", "?") for e in entities)
    return " | ".join(f"{t}: {d.get(t, 0)}" for t in ["Person", "Organisation", "Ort", "Konzept"])


def print_cluster_report(
    pre_group: list[dict],
    clustered: list[dict],
    merges: list[tuple[str, str, float]],
    threshold: float,
    elapsed: float,
    llm_grouped: list[dict] | None,
) -> None:
    _print_header(f"Embedding-Clustering  θ={threshold}")

    reduction = len(pre_group) - len(clustered)
    print(f"  Input   : {len(pre_group):4d} Entities")
    print(f"  Output  : {len(clustered):4d} Entities   "
          f"(−{reduction},  {reduction/len(pre_group)*100:.0f}% Reduktion)  "
          f"[{elapsed:.1f}s]")
    print(f"  Typen   : {_type_dist(clustered)}")

    # Cluster-Größen-Verteilung
    sizes = Counter(e.get("_cluster_size", 1) for e in clustered)
    merged_clusters = sum(v for k, v in sizes.items() if k > 1)
    print(f"  Cluster : {merged_clusters} zusammengeführt  "
          f"(2er: {sizes.get(2,0)},  3er: {sizes.get(3,0)},  4+: {sum(v for k,v in sizes.items() if k>=4)})")

    # Top Merges (höchste Similarity)
    top_merges = sorted(merges, key=lambda x: -x[2])[:8]
    if top_merges:
        print(f"\n  Beispiel-Merges (höchste Similarity):")
        for a, b, s in top_merges:
            print(f"    {s:.3f}  \"{a}\"  +  \"{b}\"")

    # Beispiel Nicht-Merges: Paare die knapp unter dem Threshold liegen
    # Dafür schauen wir welche Paare sim ∈ [threshold-0.05, threshold) haben
    print(f"\n  Beispiel Grenzfälle (sim nahe θ, aber getrennt):")
    _print_near_threshold_pairs(pre_group, threshold, n=5)

    # Vergleich gegen LLM-Group
    if llm_grouped is not None:
        _print_vs_llm(clustered, llm_grouped, threshold)


def _print_near_threshold_pairs(entities: list[dict], threshold: float, n: int = 5) -> None:
    """Zeigt Paare die knapp unter dem Threshold liegen (wurden NICHT gemergt)."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMB_MODEL)
        texts = [e.get("normalform", "") for e in entities]
        embs  = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        embs  = np.array(embs, dtype=np.float32)
        sim   = embs @ embs.T
    except Exception:
        return

    lo = threshold - 0.06
    candidates = []
    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            s = float(sim[i, j])
            if lo <= s < threshold:
                candidates.append((s, entities[i]["normalform"], entities[j]["normalform"]))

    candidates.sort(reverse=True)
    for s, a, b in candidates[:n]:
        print(f"    {s:.3f}  \"{a}\"  vs  \"{b}\"  → getrennt")
    if not candidates:
        print("    (keine Paare in diesem Bereich)")


def _print_vs_llm(emb: list[dict], llm: list[dict], threshold: float) -> None:
    emb_norms = {(e.get("normalform") or "").lower() for e in emb}
    llm_norms = {(e.get("normalform") or "").lower() for e in llm}

    # Alle Alias-Formen in emb-Ergebnis
    emb_all: set[str] = set()
    for e in emb:
        emb_all.add((e.get("normalform") or "").lower())
        for a in e.get("aliases", []):
            emb_all.add(a.lower())

    only_llm = [e for e in llm if (e.get("normalform") or "").lower() not in emb_all]
    only_emb = [e for e in emb if (e.get("normalform") or "").lower() not in llm_norms]
    both     = [e for e in emb if (e.get("normalform") or "").lower() in llm_norms]

    print(f"\n  ─ Vergleich gegen LLM-Group (θ={threshold}) ─")
    print(f"  LLM-Group : {len(llm):3d} Entities")
    print(f"  Embedding : {len(emb):3d} Entities")
    print(f"  Beide     : {len(both):3d}  |  Nur LLM: {len(only_llm):3d}  |  Nur Embedding: {len(only_emb):3d}")

    # LLM-Fehler: was hat LLM falsch zusammengeführt?
    # Entities im LLM-Output mit vielen Aliases die semantisch unpassend wirken
    suspicious_llm = [
        e for e in llm
        if len(e.get("aliases", [])) >= 3
        and (e.get("normalform") or "").lower() not in emb_norms
    ][:5]
    if suspicious_llm:
        print(f"\n  LLM hat zusammengeführt, Embedding nicht (Kandidaten für Fehler):")
        for e in suspicious_llm:
            aliases = ", ".join(f'"{a}"' for a in e.get("aliases", [])[:4])
            print(f"    \"{e.get('normalform')}\" ← {aliases}")

    # Was LLM nicht findet, Embedding schon
    if only_emb:
        print(f"\n  Nur Embedding ({len(only_emb)}; erste 8):")
        for e in sorted(only_emb, key=lambda x: x.get("normalform", "").lower())[:8]:
            cs = e.get("_cluster_size", 1)
            mark = f"[merged {cs}]" if cs > 1 else ""
            print(f"    {e.get('typ','?'):<16} \"{e.get('normalform','')}\"  {mark}")

    # Was LLM findet, Embedding nicht
    if only_llm:
        print(f"\n  Nur LLM ({len(only_llm)}; erste 8):")
        for e in sorted(only_llm, key=lambda x: x.get("normalform", "").lower())[:8]:
            aliases = ", ".join(f'"{a}"' for a in e.get("aliases", [])[:2])
            print(f"    {e.get('typ','?'):<16} \"{e.get('normalform','')}\"  {aliases}")


def print_summary_table(results: list[tuple[float, int, int, float]]) -> None:
    _print_header("Zusammenfassung: Embedding-Clustering alle Thresholds")
    print(f"  {'θ':<6} {'Input':<8} {'Output':<8} {'Reduktion':<12} {'Zeit'}")
    print(f"  {'-'*6} {'-'*8} {'-'*8} {'-'*12} {'-'*8}")
    for threshold, n_in, n_out, elapsed in results:
        red = (n_in - n_out) / n_in * 100
        print(f"  {threshold:<6.2f} {n_in:<8} {n_out:<8} {n_in-n_out:<5} ({red:.0f}%)    {elapsed:.1f}s")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Embedding-Clustering vs LLM-Group Benchmark"
    )
    ap.add_argument("--no-llm",  action="store_true",
                    help="LLM-Group überspringen (kein API-Call, kein Vergleich)")
    ap.add_argument("--force",   action="store_true",
                    help="Cache ignorieren, alles neu berechnen")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(ROOT / ".env")

    doc_dir   = PROJECTS_DIR / PROJECT / "documents" / DOC
    seg_path  = doc_dir / "segments.json"
    if not seg_path.exists():
        print(f"FEHLER: {seg_path} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    segments = json.loads(seg_path.read_text(encoding="utf-8"))

    print()
    print("Embedding-Clustering vs LLM-Group")
    print(f"  Dokument  : {PROJECT}/{DOC}")
    print(f"  Modell    : {EMB_MODEL}")
    print(f"  Thresholds: {THRESHOLDS}")

    # ── Schritt 1: GLiNER → pre-group entities ────────────────────────────────
    print(f"\n[1/3] GLiNER-Phase (pre-group)")
    if not args.force and CACHE_GLINER.exists():
        pre_group = json.loads(CACHE_GLINER.read_text(encoding="utf-8"))
        print(f"  Cache: {len(pre_group)} Entities geladen aus {CACHE_GLINER}")
    else:
        pre_group = run_gliner_phase(segments)
        CACHE_GLINER.write_text(
            json.dumps(pre_group, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  → {CACHE_GLINER} gespeichert")

    # ── Schritt 2: LLM-Group (Referenz, optional) ─────────────────────────────
    llm_grouped: list[dict] | None = None
    if not args.no_llm:
        print(f"\n[2/3] LLM-Group (Referenz)")
        if not args.force and CACHE_LLM.exists():
            llm_grouped = json.loads(CACHE_LLM.read_text(encoding="utf-8"))
            print(f"  Cache: {len(llm_grouped)} Entities geladen aus {CACHE_LLM}")
        else:
            llm_grouped = run_llm_group(pre_group)
            CACHE_LLM.write_text(
                json.dumps(llm_grouped, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  → {CACHE_LLM} gespeichert")
    else:
        print(f"\n[2/3] LLM-Group übersprungen (--no-llm)")

    # ── Schritt 3: Embeddings berechnen ───────────────────────────────────────
    print(f"\n[3/3] Embeddings berechnen ({len(pre_group)} Entities) …")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("FEHLER: sentence-transformers nicht installiert.\n"
              "  pip install sentence-transformers --break-system-packages",
              file=sys.stderr)
        sys.exit(1)

    t0    = time.perf_counter()
    model = SentenceTransformer(EMB_MODEL)
    embs  = _embed(pre_group, model)
    print(f"  Embeddings berechnet in {time.perf_counter()-t0:.1f}s  "
          f"(shape: {embs.shape})")

    # ── Clustering bei allen Thresholds ──────────────────────────────────────
    summary: list[tuple[float, int, int, float]] = []

    for threshold in THRESHOLDS:
        t0 = time.perf_counter()
        clustered, merges = _union_find_cluster(pre_group, embs, threshold)
        elapsed = time.perf_counter() - t0
        summary.append((threshold, len(pre_group), len(clustered), elapsed))
        print_cluster_report(pre_group, clustered, merges, threshold, elapsed, llm_grouped)

    print_summary_table(summary)

    if llm_grouped is not None:
        _print_header("Qualitäts-Einschätzung")
        print(f"  LLM-Group Ziel      : {len(llm_grouped)} Entities")
        best_threshold = min(THRESHOLDS,
            key=lambda t: abs(summary[[x[0] for x in summary].index(t)][2] - len(llm_grouped)))
        best_n = next(n for th, _, n, _ in summary if th == best_threshold)
        print(f"  Nächster Embedding  : θ={best_threshold} → {best_n} Entities")
        print()
        print("  LLM-Group-Fehler-Muster aus diesem Run:")
        for e in (llm_grouped or []):
            aliases = e.get("aliases", [])
            if len(aliases) >= 3:
                # Prüfe ob aliases semantisch unähnlich zu normalform sind
                pass
        print("  → Siehe Vergleich-Sektionen oben für Details.")

    print()


if __name__ == "__main__":
    main()
