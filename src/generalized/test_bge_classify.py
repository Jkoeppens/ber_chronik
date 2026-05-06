"""
test_bge_classify.py — BGE-M3 + Nachbar-Aggregation + KMeans + LLM (ein Call)

  1. BGE-M3 Embeddings (gecacht)
  2. Nachbar-Aggregation für Segmente < 100 Zeichen
  3. KMeans(n=7)
  4. Ein LLM-Call für alle Cluster
  5. Labels + Top-3 Segmente pro Cluster
"""

import json
import re
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from src.generalized.config import ROOT
from src.generalized.llm import get_provider, TASK_ANALYZE

SEGMENTS_PATH   = Path("data/projects/damaskus_test_2/documents/b1e1d872/segments.json")
CACHE_PATH      = Path("/tmp/test_bge_embeddings.npy")

N_CLUSTERS      = 7
TOP_K_LLM       = 10     # Segmente pro Cluster im LLM-Prompt
LLM_SEG_CHARS   = 300    # Zeichen pro Segment im LLM-Prompt
TOP_K_KW        = 8      # TF-IDF Keywords pro Cluster
TOP_K_SHOW      = 3      # Segmente pro Cluster in der Ausgabe
SEG_CHARS       = 500
MIN_LENGTH      = 30
SHORT_THRESHOLD = 100

_STOPWORDS = {
    # Deutsch
    "der", "die", "das", "und", "in", "von", "zu", "den", "mit", "ist", "im",
    "dem", "des", "ein", "eine", "sich", "auch", "auf", "an", "für", "es",
    "als", "bei", "aber", "oder", "aus", "hat", "nicht", "wird", "war",
    "waren", "dass", "wenn", "nach", "durch", "um", "so", "wie", "durch",
    "über", "bis", "dann", "diese", "dieser", "diesem", "diesen", "dieses",
    "er", "sie", "wir", "ihre", "ihre", "ihrer", "ihren", "ihrem", "ihres",
    "sein", "seiner", "seinem", "seinen", "seine", "eines", "einem", "einen",
    "werden", "haben", "noch", "mehr", "nur", "schon", "sehr", "hier", "da",
    "vom", "zum", "zur", "vor", "seit", "ob", "am", "gegen",
    # Englisch
    "the", "of", "and", "in", "to", "a", "that", "was", "as", "is", "it",
    "for", "by", "on", "with", "an", "at", "be", "this", "were", "had",
    "have", "from", "or", "not", "their", "they", "which", "but", "its",
    "his", "her", "he", "who", "been", "also", "more", "are", "into",
}

SEP  = "─" * 80
SEP2 = "=" * 80

LABEL_SYSTEM = """\
Du siehst häufige Begriffe und Textausschnitte aus Gruppen von Forschungsnotizen \
zur osmanischen Geschichte. Nenne für jede Gruppe ein präzises Thema (2-4 Wörter) \
das diese Gruppe von den anderen abgrenzt."""

LABEL_PROMPT = """\
Hier sind {n} Gruppen von Forschungsnotizen. Benenne jede Gruppe mit einem \
präzisen Thema das sie von den anderen abgrenzt.

{groups}
Antworte für jede Gruppe im Format:

### Gruppe 1: [Thema, 2-4 Wörter]
[Ein Satz der diese Gruppe von den anderen abgrenzt]

### Gruppe 2: ...

Regeln:
- Thema in PascalCase, 2-4 Wörter, auf Deutsch
- Nur die Gruppenblöcke ausgeben, kein Kommentar"""


def load_segments() -> tuple[list[str], list[str]]:
    segs = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    content = [s for s in segs
               if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]
    content.sort(key=lambda s: s.get("segment_id", ""))
    texts = [s["text"][:SEG_CHARS] for s in content]
    ids   = [s.get("segment_id", "?") for s in content]
    return texts, ids


def compute_embeddings(model, texts: list[str]) -> np.ndarray:
    t0  = time.perf_counter()
    raw = model.encode(
        texts, batch_size=32, max_length=512,
        return_dense=True, return_sparse=False, return_colbert_vecs=False,
    )["dense_vecs"]
    embs  = np.array(raw, dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs /= np.maximum(norms, 1e-9)
    print(f"  Embeddings: {embs.shape}  [{time.perf_counter()-t0:.1f}s]")
    return embs


def neighbor_aggregate(embs: np.ndarray, texts: list[str]) -> tuple[np.ndarray, int]:
    enriched = embs.copy()
    n = 0
    for i, text in enumerate(texts):
        if len(text) < SHORT_THRESHOLD:
            neighbors = [embs[i]]
            if i > 0:             neighbors.append(embs[i - 1])
            if i < len(embs) - 1: neighbors.append(embs[i + 1])
            v = np.mean(neighbors, axis=0)
            enriched[i] = v / max(np.linalg.norm(v), 1e-9)
            n += 1
    return enriched, n


def run_kmeans(embs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.cluster import KMeans
    km     = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto")
    labels = km.fit_predict(embs)
    return labels, km.cluster_centers_


def tfidf_cluster_keywords(texts: list[str], labels: np.ndarray) -> dict[int, list[str]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(
        max_features=8000,
        min_df=2,
        sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß]{3,}\b",
    )
    X = vec.fit_transform(texts)
    names = vec.get_feature_names_out()
    result: dict[int, list[str]] = {}
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            result[cid] = []
            continue
        mean_scores = np.asarray(X[idx].mean(axis=0)).flatten()
        ranked = mean_scores.argsort()[::-1]
        keywords = [names[i] for i in ranked
                    if names[i].lower() not in _STOPWORDS][:TOP_K_KW]
        result[cid] = keywords
    return result


def build_llm_prompt(embs, labels, centroids, texts) -> tuple[str, list[list[int]]]:
    kw_map = tfidf_cluster_keywords(texts, labels)
    groups: list[str] = []
    top_per_cluster: list[list[int]] = []

    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            top_per_cluster.append([])
            groups.append(f"=== Gruppe {cid+1} ===\n(leer)")
            continue

        dists   = np.linalg.norm(embs[idx] - centroids[cid], axis=1)
        top_idx = idx[dists.argsort()[:TOP_K_LLM]].tolist()
        top_per_cluster.append(top_idx)

        kw_line = "Häufige Begriffe: " + ", ".join(kw_map[cid]) if kw_map[cid] else ""
        snippets = "\n\n".join(
            f"Text {i+1}:\n{texts[j][:LLM_SEG_CHARS]}" for i, j in enumerate(top_idx)
        )
        block = f"=== Gruppe {cid+1} ==="
        if kw_line:
            block += f"\n{kw_line}"
        block += f"\n\n{snippets}"
        groups.append(block)

    prompt = LABEL_PROMPT.format(n=N_CLUSTERS, groups="\n\n".join(groups) + "\n\n")
    return prompt, top_per_cluster


def parse_all_labels(raw: str, n: int) -> list[tuple[str, str]]:
    """Parst ## Gruppe N: Name / Beschreibung für alle n Gruppen."""
    results: list[tuple[str, str]] = [("Unbekannt", "")] * n
    current_idx  = None
    current_desc = ""
    current_name = ""

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^#{2,4}\s*Gruppe\s+(\d+):\s*(.+)", line, re.I)
        if m:
            if current_idx is not None and 0 <= current_idx < n:
                results[current_idx] = (current_name, current_desc)
            current_idx  = int(m.group(1)) - 1
            current_name = re.sub(r"\*+", "", m.group(2)).strip()
            current_desc = ""
        elif current_idx is not None and not current_desc and line:
            current_desc = line

    if current_idx is not None and 0 <= current_idx < n:
        results[current_idx] = (current_name, current_desc)

    return results


# ── Test-Funktionen ───────────────────────────────────────────────────────────

def compute_centroids(embs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """L2-normalisierter Schwerpunkt pro Cluster (aus Segment-Embeddings)."""
    n_clusters = int(labels.max()) + 1
    centroids  = np.zeros((n_clusters, embs.shape[1]), dtype=np.float32)
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        v = embs[idx].mean(axis=0)
        centroids[cid] = v / max(float(np.linalg.norm(v)), 1e-9)
    return centroids


def embed_label_texts(bge, texts: list[str]) -> np.ndarray:
    """Bette eine kleine Liste von Texten mit BGE-M3 ein (L2-normalisiert)."""
    raw  = bge.encode(texts, batch_size=16, max_length=256,
                      return_dense=True, return_sparse=False,
                      return_colbert_vecs=False)["dense_vecs"]
    embs = np.array(raw, dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / np.maximum(norms, 1e-9)


def print_label_centroid_alignment(
    label_pairs: list[tuple[str, str]],
    label_embs:  np.ndarray,
    centroids:   np.ndarray,
) -> int:
    """Test 1 — Alignment zwischen Label-Embedding und Cluster-Centroid.
    Gibt den Index des Clusters mit dem niedrigsten Delta zurück."""
    n          = len(label_pairs)
    sim_matrix = label_embs @ centroids.T   # (n_labels, n_clusters)

    rows: list[tuple[int, str, float, float, float]] = []
    for i, (name, _) in enumerate(label_pairs):
        sim_own        = float(sim_matrix[i, i])
        others         = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        sim_best_other = max(others) if others else 0.0
        delta          = sim_own - sim_best_other
        rows.append((i, name, sim_own, sim_best_other, delta))

    worst_idx = min(range(len(rows)), key=lambda k: rows[k][4])

    print(f"\n{SEP}")
    print("  TEST 1 — Label-Centroid-Alignment")
    print(SEP)
    print(f"  {'Cluster':30s}  {'Sim_own':>8}  {'Sim_best_other':>14}  {'Delta':>7}")
    print(f"  {'─'*30}  {'─'*8}  {'─'*14}  {'─'*7}")
    for i, name, sim_own, sim_best_other, delta in rows:
        flag = "  ← schwächste Trennung" if i == worst_idx else ""
        print(f"  {name:30s}  {sim_own:8.4f}  {sim_best_other:14.4f}  {delta:7.4f}{flag}")

    return worst_idx


def run_test2_description_edit(
    bge,
    label_pairs: list[tuple[str, str]],
    label_embs:  np.ndarray,
    centroids:   np.ndarray,
    seg_embs:    np.ndarray,
    seg_ids:     list[str],
    texts:       list[str],
    kw_map:      dict[int, list[str]],
    worst_idx:   int,
) -> None:
    """Test 2 — Verbesserte Beschreibung → Segmentverschiebung."""
    name, desc = label_pairs[worst_idx]
    kws        = kw_map.get(worst_idx, [])

    original_text = f"{name}. {desc}" if desc else name
    improved_desc = "Themen: " + ", ".join(kws) if kws else desc
    improved_text = f"{name}. {improved_desc}"

    print(f"\n{SEP}")
    print("  TEST 2 — Beschreibungs-Edit")
    print(SEP)
    print(f"  Cluster : {name}  (schwächste Trennung aus Test 1)")
    print(f"  Vorher  : {original_text[:110]}")
    print(f"  Nachher : {improved_text[:110]}")

    # Neues Label-Embedding
    improved_emb               = embed_label_texts(bge, [improved_text])[0]
    new_label_embs             = label_embs.copy()
    new_label_embs[worst_idx]  = improved_emb

    # Cosine-Klassifikation: vorher / nachher
    assign_before = (seg_embs @ label_embs.T).argmax(axis=1)
    assign_after  = (seg_embs @ new_label_embs.T).argmax(axis=1)

    in_before = set(int(i) for i in np.where(assign_before == worst_idx)[0])
    in_after  = set(int(i) for i in np.where(assign_after  == worst_idx)[0])
    stayed    = in_before & in_after
    left      = in_before - in_after
    arrived   = in_after  - in_before

    print(f"\n  Segmente vorher : {len(in_before)}")
    print(f"  Segmente nachher: {len(in_after)}")
    print(f"  Geblieben       : {len(stayed)}")

    if left:
        print(f"\n  Abgewandert ({len(left)}):")
        for i in sorted(left)[:5]:
            dest    = label_pairs[int(assign_after[i])][0]
            preview = texts[i].replace("\n", " ")[:80]
            print(f"    [{seg_ids[i]}] → {dest}")
            print(f"      \"{preview}\"")

    if arrived:
        print(f"\n  Dazugekommen ({len(arrived)}):")
        for i in sorted(arrived)[:5]:
            src     = label_pairs[int(assign_before[i])][0]
            preview = texts[i].replace("\n", " ")[:80]
            print(f"    [{seg_ids[i]}] von {src}")
            print(f"      \"{preview}\"")

    # Delta-Vergleich
    n = len(label_pairs)
    sim_own_before    = float(label_embs[worst_idx]  @ centroids[worst_idx])
    sim_own_after     = float(improved_emb           @ centroids[worst_idx])
    best_other_before = max(float(label_embs[worst_idx] @ centroids[j]) for j in range(n) if j != worst_idx)
    best_other_after  = max(float(improved_emb           @ centroids[j]) for j in range(n) if j != worst_idx)
    delta_before      = sim_own_before - best_other_before
    delta_after       = sim_own_after  - best_other_after
    change            = delta_after - delta_before
    direction         = "↑ besser" if change > 0.001 else ("↓ schlechter" if change < -0.001 else "→ kaum Änderung")

    print(f"\n  Delta vorher : {delta_before:+.4f}")
    print(f"  Delta nachher: {delta_after:+.4f}")
    print(f"  Änderung     : {change:+.4f}  ({direction})")


def main() -> None:
    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_ANALYZE)

    t0 = time.perf_counter()

    # ── 1. Embeddings ───────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 1 — BGE-M3 Embeddings")
    print(SEP2)

    texts, seg_ids = load_segments()
    print(f"Segmente: {len(texts)}  (sortiert, ≤{SEG_CHARS} Zeichen)")

    from FlagEmbedding import BGEM3FlagModel
    t_load = time.perf_counter()
    bge = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    print(f"Modell geladen  [{time.perf_counter()-t_load:.1f}s]")

    if CACHE_PATH.exists():
        embs = np.load(str(CACHE_PATH))
        if embs.shape[0] == len(texts):
            print(f"Cache: {CACHE_PATH}  {embs.shape}")
        else:
            embs = compute_embeddings(bge, texts)
            np.save(str(CACHE_PATH), embs)
    else:
        embs = compute_embeddings(bge, texts)
        np.save(str(CACHE_PATH), embs)

    # ── 2. Nachbar-Aggregation ──────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  SCHRITT 2 — Nachbar-Aggregation  (< {SHORT_THRESHOLD} Zeichen)")
    print(SEP2)

    embs, n_enriched = neighbor_aggregate(embs, texts)
    print(f"  {n_enriched} / {len(texts)} Segmente angereichert ({n_enriched/len(texts)*100:.1f}%)")

    # ── 3. KMeans ───────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  SCHRITT 3 — KMeans  (n={N_CLUSTERS})")
    print(SEP2)

    labels, centroids = run_kmeans(embs)
    for cid in range(N_CLUSTERS):
        print(f"  Cluster {cid+1}: {int((labels == cid).sum())} Segmente")

    # ── 4. LLM — ein Call für alle Cluster ─────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  SCHRITT 4 — LLM  [{provider.model}]  (ein Call für alle {N_CLUSTERS} Cluster)")
    print(SEP2)

    prompt, top_per_cluster = build_llm_prompt(embs, labels, centroids, texts)
    t_llm = time.perf_counter()
    raw   = provider.complete(prompt, system=LABEL_SYSTEM) or ""
    print(f"  LLM-Laufzeit: {time.perf_counter()-t_llm:.1f}s")

    label_pairs = parse_all_labels(raw, N_CLUSTERS)

    # ── 5. Ausgabe ──────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  ERGEBNIS")
    print(SEP2)

    for cid, ((name, desc), top_idx) in enumerate(zip(label_pairs, top_per_cluster)):
        cluster_size = int((labels == cid).sum())
        pad = "─" * max(0, 56 - len(name))
        print(f"\n── {name}  ({cluster_size} Segmente) {pad}")
        if desc:
            print(f"   {desc}")
        for rank, seg_i in enumerate(top_idx[:TOP_K_SHOW], 1):
            preview = texts[seg_i].replace("\n", " ")[:120]
            print(f"   {rank}. [{seg_ids[seg_i]}]  \"{preview}\"")

    # ── Test 1 & 2 ─────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 6 — Tests: Label-Centroid-Alignment & Beschreibungs-Edit")
    print(SEP2)

    kw_map        = tfidf_cluster_keywords(texts, labels)
    centroids_sem = compute_centroids(embs, labels)

    label_text_list = [
        f"{name}. {desc}" if desc else name
        for name, desc in label_pairs
    ]
    print("Lade Label-Embeddings…", flush=True)
    label_embs = embed_label_texts(bge, label_text_list)

    worst_idx = print_label_centroid_alignment(label_pairs, label_embs, centroids_sem)
    run_test2_description_edit(
        bge, label_pairs, label_embs, centroids_sem,
        embs, seg_ids, texts, kw_map, worst_idx,
    )

    elapsed = time.perf_counter() - t0
    print(f"\n{SEP}")
    print(f"  Gesamt: {elapsed:.1f}s  (Embeddings aus Cache)")
    print(SEP2 + "\n")


if __name__ == "__main__":
    main()
