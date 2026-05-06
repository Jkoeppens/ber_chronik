"""
test_crossencoder_classify.py — Cross-Encoder-Klassifizierung vs. LLM-Klassifizierung

Drei Schritte:
  1. SBERT Embeddings (gecacht in /tmp/test_embeddings.npy)
  2. HDBSCAN Exploration (Cluster-Struktur im Embedding-Raum)
  3. Cross-Encoder Klassifizierung + Vergleich gegen classified.json

Keine Schreiboperationen in Projektdateien.

Aufruf:
    python -m src.generalized.test_crossencoder_classify
"""

import json
import time
from collections import Counter
from pathlib import Path

# ── Konfiguration ─────────────────────────────────────────────────────────────
SEGMENTS_PATH   = Path("data/projects/damaskus_test_2/documents/b1e1d872/segments.json")
CLASSIFIED_PATH = Path("data/projects/damaskus_test_2/documents/b1e1d872/classified.json")
EMBEDDINGS_CACHE = Path("/tmp/test_embeddings.npy")

EMB_MODEL      = "paraphrase-multilingual-MiniLM-L12-v2"
CE_MODEL_MMARCO = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
CE_MODEL_NLI    = "cross-encoder/nli-deberta-v3-small"
SEG_CHARS = 500
PREVIEW   = 300   # Zeichen für Segment-Vorschau in Clustern
EX_CHARS  = 200   # Zeichen für Beispiel-Segmente in Ausgabe

kategorien = [
    {
        "name": "Arabischer Nationalismus",
        "beschreibung": "Arabische Reformbewegungen und antikoloniale Argumentation im späten Osmanischen Reich",
    },
    {
        "name": "Islamische Reform",
        "beschreibung": "Islamische Reformtheologie, Salafismus und religiöse Erneuerungsbewegungen",
    },
    {
        "name": "Osmanische Verwaltung",
        "beschreibung": "Osmanische Provinzialverwaltung und Beziehungen zwischen Zentrum und Peripherie",
    },
    {
        "name": "Pressewesen",
        "beschreibung": "Arabischsprachige Periodika, Druckwesen und osmanische Zensurpolitik",
    },
    {
        "name": "Politische Bewegungen",
        "beschreibung": "Arabischer und osmanischer Nationalismus als politische Organisationen und Parteien",
    },
]

W = 80


# ── Daten laden ───────────────────────────────────────────────────────────────

def load_segments() -> tuple[list[str], list[str]]:
    raw   = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    pool  = [s for s in raw if s.get("type") == "content"]
    texts = [s.get("text", "")[:SEG_CHARS] for s in pool]
    ids   = [s.get("segment_id", f"s{i:04d}") for i, s in enumerate(pool)]
    return texts, ids


def load_classified() -> dict[str, str]:
    if not CLASSIFIED_PATH.exists():
        return {}
    data = json.loads(CLASSIFIED_PATH.read_text(encoding="utf-8"))
    return {r["segment_id"]: r.get("category") for r in data if r.get("category")}


# ── Schritt 1: SBERT Embeddings ───────────────────────────────────────────────

def step1_embeddings(texts: list[str]):
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.preprocessing import normalize

    print(f"\n{'─'*W}")
    print(f"  SCHRITT 1 — SBERT Embeddings  [{EMB_MODEL}]")
    print(f"{'─'*W}")

    if EMBEDDINGS_CACHE.exists():
        t0   = time.perf_counter()
        embs = np.load(str(EMBEDDINGS_CACHE))
        elapsed = time.perf_counter() - t0
        if embs.shape[0] == len(texts):
            print(f"  Cache geladen: {EMBEDDINGS_CACHE}  ({embs.shape})  [{elapsed:.2f}s]")
            return normalize(embs)
        print(f"  Cache-Größe passt nicht ({embs.shape[0]} vs {len(texts)}) — neu berechnen")

    print(f"  {len(texts)} Segmente × {SEG_CHARS} Zeichen → Embeddings…", flush=True)
    t0        = time.perf_counter()
    model     = SentenceTransformer(EMB_MODEL)
    embs      = model.encode(texts, show_progress_bar=False, batch_size=64)
    elapsed   = time.perf_counter() - t0

    np.save(str(EMBEDDINGS_CACHE), embs)
    print(f"  Gespeichert: {EMBEDDINGS_CACHE}")
    print(f"  Shape: {embs.shape}  |  Laufzeit: {elapsed:.1f}s")
    return normalize(embs)


# ── Schritt 2: HDBSCAN Exploration ───────────────────────────────────────────

def step2_hdbscan(emb_norm, texts: list[str]) -> None:
    import numpy as np
    import hdbscan
    from sklearn.decomposition import PCA

    print(f"\n{'─'*W}")
    print(f"  SCHRITT 2 — HDBSCAN Exploration  (PCA 50 → HDBSCAN)")
    print(f"{'─'*W}")

    # PCA vorschalten: HDBSCAN findet in 384-dim normalisierten Embeddings
    # keine Cluster (alle Noise) — PCA komprimiert auf dichtere Struktur
    n_components = min(50, emb_norm.shape[1], emb_norm.shape[0] - 1)
    t_pca = time.perf_counter()
    reduced = PCA(n_components=n_components).fit_transform(emb_norm)
    t_pca = time.perf_counter() - t_pca
    print(f"  PCA: {emb_norm.shape[1]}d → {n_components}d  [{t_pca:.2f}s]", flush=True)

    t0    = time.perf_counter()
    model = hdbscan.HDBSCAN(
        min_cluster_size=8,
        min_samples=3,
        core_dist_n_jobs=1,   # macOS OpenMP-Fix
        metric="euclidean",
    )
    labels  = model.fit_predict(reduced)
    elapsed = time.perf_counter() - t0

    unique   = sorted(set(labels))
    n_clust  = len([l for l in unique if l >= 0])
    n_noise  = int((labels == -1).sum())
    print(f"  Cluster: {n_clust}  |  Noise: {n_noise}/{len(texts)}  |  Laufzeit: {elapsed:.1f}s\n")

    counts = Counter(labels)
    for cid in sorted(counts, key=lambda x: (-counts[x], x)):
        if cid == -1:
            continue
        size    = counts[cid]
        indices = [i for i, lb in enumerate(labels) if lb == cid]
        bar     = "█" * min(size, 40)
        print(f"  Cluster {cid:3d}  n={size:4d}  {bar}")
        for idx in indices[:3]:
            preview = texts[idx].replace("\n", " ").strip()[:PREVIEW]
            print(f"    · {preview}")
        print()

    if n_noise:
        print(f"  Noise (-1): {n_noise} Segmente (kein Cluster zugewiesen)")


# ── Schritt 3: Cross-Encoder Klassifizierung ──────────────────────────────────

def _confidence(scores: list[float]) -> str:
    s = sorted(scores, reverse=True)
    gap = s[0] - s[1] if len(s) > 1 else 1.0
    if gap > 0.3:
        return "high"
    if gap > 0.1:
        return "medium"
    return "low"


def _softmax(logits):
    import numpy as np
    arr = np.array(logits)
    e   = np.exp(arr - arr.max(axis=-1, keepdims=True))
    return (e / e.sum(axis=-1, keepdims=True)).tolist()


def step3_crossencoder(
    texts: list[str],
    seg_ids: list[str],
    existing: dict[str, str],
    model_name: str,
    is_nli: bool = False,
) -> tuple[list[dict], float]:
    """
    Klassifiziert alle Segmente mit einem CrossEncoder-Modell.

    is_nli=True:  Modell gibt (n_pairs, 3) Logits zurück
                  [contradiction, neutral, entailment].
                  Score = softmax(logits)[entailment].
                  Pairs: (text, hypothesis) wobei hypothesis
                  = "Dieser Text behandelt: {name} — {beschreibung}."

    is_nli=False: Modell gibt (n_pairs,) Retrieval-Scores zurück.
                  Pairs: (category_query, text).
    """
    import numpy as np
    from sentence_transformers import CrossEncoder

    print(f"\n{'─'*W}")
    mode_label = "NLI (entailment)" if is_nli else "Retrieval-Ranking"
    print(f"  SCHRITT 3 — Cross-Encoder [{mode_label}]")
    print(f"  Modell: {model_name}")
    print(f"{'─'*W}")
    print(f"  Lade Modell…", flush=True)

    model     = CrossEncoder(model_name)
    cat_names = [k["name"] for k in kategorien]

    if is_nli:
        # Hypothesis: Segment enthält Aussagen über diese Kategorie
        hypotheses = [
            f"Dieser Text behandelt folgendes Thema: {k['name']} — {k['beschreibung']}."
            for k in kategorien
        ]
    else:
        hypotheses = [f"{k['name']}: {k['beschreibung']}" for k in kategorien]

    print(f"  Klassifiziere {len(texts)} Segmente…", flush=True)
    t0 = time.perf_counter()

    results = []
    for i, (text, sid) in enumerate(zip(texts, seg_ids)):
        if is_nli:
            pairs  = [(text, hyp) for hyp in hypotheses]
            raw    = model.predict(pairs)          # shape (n_cats, 3)
            probs  = _softmax(raw)                 # shape (n_cats, 3)
            scores = [row[2] for row in probs]     # entailment column
        else:
            pairs  = [(hyp, text) for hyp in hypotheses]
            scores = model.predict(pairs).tolist() # shape (n_cats,)

        best = int(max(range(len(scores)), key=lambda j: scores[j]))
        results.append({
            "segment_id": sid,
            "text":       text,
            "category":   cat_names[best],
            "confidence": _confidence(scores),
            "scores":     {cat_names[j]: round(scores[j], 4) for j in range(len(scores))},
            "existing":   existing.get(sid),
        })
        if (i + 1) % 100 == 0:
            print(f"  … {i+1}/{len(texts)}", flush=True)

    elapsed = time.perf_counter() - t0
    print(f"  Laufzeit: {elapsed:.1f}s  ({elapsed/len(texts)*1000:.0f}ms/Segment)")
    return results, elapsed


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def print_results(results: list[dict], label: str) -> None:
    cat_names = [k["name"] for k in kategorien]

    # ── Verteilung + Konfidenz-Verteilung ─────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  VERTEILUNG — {label}")
    print(f"{'─'*W}")
    counts       = Counter(r["category"] for r in results)
    conf_by_cat: dict[str, list[str]] = {n: [] for n in cat_names}
    for r in results:
        conf_by_cat[r["category"]].append(r["confidence"])

    for name in cat_names:
        n     = counts.get(name, 0)
        pct   = n / len(results) * 100
        bar   = "█" * min(round(pct / 2), 40)
        confs = conf_by_cat[name]
        h  = confs.count("high")
        m  = confs.count("medium")
        lo = confs.count("low")
        print(f"  {name:30s}  {n:4d} ({pct:4.1f}%)  {bar}")
        if n:
            h_pct  = h  / n * 100
            m_pct  = m  / n * 100
            lo_pct = lo / n * 100
            print(f"  {'':30s}  high={h:3d}({h_pct:4.0f}%)  medium={m:3d}({m_pct:4.0f}%)  low={lo:3d}({lo_pct:4.0f}%)")

    # ── 5 Segmente höchste Konfidenz + 5 niedrigste (Grenzdokumente) ──────────
    by_cat: dict[str, list[dict]] = {n: [] for n in cat_names}
    for r in results:
        by_cat[r["category"]].append(r)

    print(f"\n{'─'*W}")
    print(f"  BEISPIELE PRO KATEGORIE  (top-5 Konfidenz  |  bottom-5 Grenzdokumente)")
    print(f"{'─'*W}")

    for name in cat_names:
        items = by_cat[name]
        if not items:
            continue
        sorted_desc = sorted(items, key=lambda r: -r["scores"][name])
        sorted_asc  = sorted(items, key=lambda r:  r["scores"][name])
        top5    = sorted_desc[:5]
        bottom5 = sorted_asc[:5]

        print(f"\n── {name} ({counts.get(name,0)} Segmente) " + "─" * max(0, W - len(name) - 16))

        print(f"  ▲ Höchste Konfidenz:")
        for i, r in enumerate(top5, 1):
            score   = r["scores"][name]
            preview = r["text"].replace("\n", " ").strip()[:EX_CHARS]
            print(f"    {i}. [{r['segment_id']}] score={score:.4f}  conf={r['confidence']}")
            print(f"       \"{preview}\"")

        print(f"  ▼ Niedrigste Konfidenz (Grenzdokumente):")
        for i, r in enumerate(bottom5, 1):
            score   = r["scores"][name]
            # Zeig auch den score der zweitbesten Kategorie
            runner  = sorted(r["scores"].items(), key=lambda x: -x[1])[1]
            preview = r["text"].replace("\n", " ").strip()[:EX_CHARS]
            print(f"    {i}. [{r['segment_id']}] score={score:.4f}  2nd={runner[0]}({runner[1]:.4f})")
            print(f"       \"{preview}\"")


def print_disagreements(results: list[dict], label: str, max_show: int = 10) -> None:
    """Segmente wo Cross-Encoder und LLM unterschiedlicher Meinung sind."""
    with_existing = [r for r in results if r["existing"]]
    if not with_existing:
        return

    # Konfusionsmatrix: LLM → CE
    confusion: dict[str, Counter] = {}
    for r in with_existing:
        llm_cat = r["existing"]
        ce_cat  = r["category"]
        confusion.setdefault(llm_cat, Counter())[ce_cat] += 1

    print(f"\n{'─'*W}")
    print(f"  VERGLEICH — {label}  vs.  LLM-Klassifizierung")
    print(f"  ({len(with_existing)} Segmente mit beiden Klassifizierungen)")
    print(f"{'─'*W}")

    print(f"\n  LLM-Kategorie → CE-Kategorie (Top-2 pro LLM-Kategorie):\n")
    for llm_cat in sorted(confusion, key=lambda c: -sum(confusion[c].values())):
        total    = sum(confusion[llm_cat].values())
        top2     = confusion[llm_cat].most_common(2)
        top2_str = "  |  ".join(f"{ce}: {n} ({n/total*100:.0f}%)" for ce, n in top2)
        print(f"  {llm_cat:40s}  n={total:4d}  →  {top2_str}")

    # Unstimmige Segmente — nach CE-Konfidenz sortiert (interessanteste zuerst)
    cat_names = [k["name"] for k in kategorien]
    disagree = [
        r for r in with_existing
        if r["existing"] != r["category"] and r["confidence"] in ("high", "medium")
    ]
    disagree.sort(key=lambda r: -r["scores"][r["category"]])

    print(f"\n  Unstimmigkeiten (CE high/medium, CE ≠ LLM):  {len(disagree)} Segmente")
    print(f"  Top {max_show} nach CE-Konfidenz:\n")
    for r in disagree[:max_show]:
        ce_score  = r["scores"][r["category"]]
        preview   = r["text"].replace("\n", " ").strip()[:EX_CHARS]
        print(f"  [{r['segment_id']}]  LLM: {r['existing']}")
        print(f"  {'':12s}   CE: {r['category']} (score={ce_score:.4f}, conf={r['confidence']})")
        print(f"  \"{preview}\"")
        print()


def print_timing_comparison(t_mmarco: float, t_nli: float, n: int) -> None:
    print(f"\n{'─'*W}")
    print(f"  LAUFZEIT-VERGLEICH")
    print(f"{'─'*W}")
    print(f"  mmarco  : {t_mmarco:6.1f}s  ({t_mmarco/n*1000:.0f}ms/Segment)")
    print(f"  nli-deb : {t_nli:6.1f}s  ({t_nli/n*1000:.0f}ms/Segment)")
    ratio = t_nli / t_mmarco if t_mmarco > 0 else float("inf")
    print(f"  Faktor  : {ratio:.1f}x  ({'nli schneller' if ratio < 1 else 'mmarco schneller'})")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not SEGMENTS_PATH.exists():
        raise FileNotFoundError(f"Nicht gefunden: {SEGMENTS_PATH}")

    texts, seg_ids = load_segments()
    existing       = load_classified()
    print(f"Segmente: {len(texts)}  |  classified.json: {len(existing)} Einträge")

    emb_norm = step1_embeddings(texts)
    step2_hdbscan(emb_norm, texts)

    results_mmarco, t_mmarco = step3_crossencoder(
        texts, seg_ids, existing, CE_MODEL_MMARCO, is_nli=False
    )
    results_nli, t_nli = step3_crossencoder(
        texts, seg_ids, existing, CE_MODEL_NLI, is_nli=True
    )

    print_results(results_mmarco, f"mmarco  [{CE_MODEL_MMARCO}]")
    print_results(results_nli,    f"NLI     [{CE_MODEL_NLI}]")

    print_disagreements(results_mmarco, f"mmarco")
    print_disagreements(results_nli,    f"nli-deberta")

    print_timing_comparison(t_mmarco, t_nli, len(texts))
    print(f"\n{'='*W}")


if __name__ == "__main__":
    main()
