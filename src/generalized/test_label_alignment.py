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


def embed_label_texts(bge, texts: list[str], max_length: int = 256) -> np.ndarray:
    """Bette eine kleine Liste von Texten mit BGE-M3 ein (L2-normalisiert)."""
    raw  = bge.encode(texts, batch_size=16, max_length=max_length,
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


# ── Strategie-Hilfsfunktionen ─────────────────────────────────────────────────

def print_strategy_delta(
    title: str,
    names: list[str],
    label_embs: np.ndarray,
    centroids: np.ndarray,
) -> float:
    """Delta-Tabelle für eine Strategie. Gibt Gesamt-Ø Delta zurück."""
    n          = len(names)
    sim_matrix = label_embs @ centroids.T   # (n, n)

    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    print(f"  {'Cluster':35s}  {'Sim_own':>8}  {'Sim_best_other':>14}  {'Delta':>7}")
    print(f"  {'─'*35}  {'─'*8}  {'─'*14}  {'─'*7}")

    deltas: list[float] = []
    for i, name in enumerate(names):
        sim_own  = float(sim_matrix[i, i])
        others   = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        sim_best = max(others) if others else 0.0
        delta    = sim_own - sim_best
        deltas.append(delta)
        print(f"  {name[:35]:35s}  {sim_own:8.4f}  {sim_best:14.4f}  {delta:7.4f}")

    avg = float(np.mean(deltas))
    print(f"\n  Gesamt-Ø Delta: {avg:+.4f}")
    return avg


def compute_intra_sim(seg_embs: np.ndarray, labels: np.ndarray) -> dict[int, float]:
    result: dict[int, float] = {}
    for cid in np.unique(labels).tolist():
        idx = np.where(labels == cid)[0]
        if len(idx) < 2:
            result[int(cid)] = 1.0
            continue
        sub     = seg_embs[idx]
        sim_mat = sub @ sub.T
        k       = len(idx)
        mask    = np.triu(np.ones((k, k), dtype=bool), k=1)
        result[int(cid)] = float(sim_mat[mask].mean())
    return result


def print_intra_sim_table(
    title: str,
    names: list[str],
    seg_embs: np.ndarray,
    labels: np.ndarray,
) -> float:
    """Intra-Cluster-Kohärenz-Tabelle. Gibt gewichtetes Ø zurück."""
    intra  = compute_intra_sim(seg_embs, labels)
    n      = len(names)
    sizes  = {cid: int((labels == cid).sum()) for cid in range(n)}
    total  = sum(sizes.values())

    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    print(f"  {'Cluster':35s}  {'Größe':>6}  {'IntraSim':>10}")
    print(f"  {'─'*35}  {'─'*6}  {'─'*10}")

    weighted_sum = 0.0
    for i, name in enumerate(names):
        sim           = intra.get(i, 0.0)
        sz            = sizes.get(i, 0)
        weighted_sum += sim * sz
        print(f"  {name[:35]:35s}  {sz:6d}  {sim:10.4f}")

    avg = weighted_sum / total if total else 0.0
    print(f"\n  Gesamt-Ø IntraSim (gewichtet): {avg:.4f}")
    return avg


# ── Strategie 1 — k-LLMmeans ─────────────────────────────────────────────────

_S1_SYSTEM = "Du bist ein präziser Forschungsassistent."
_S1_PROMPT = """\
Fasse die folgenden Forschungsnotizen in 2-3 präzisen Sätzen zusammen. \
Benenne das gemeinsame Thema explizit. Keine Aufzählung, kein Markdown.

{texts}"""


def run_strategy1(provider, bge, seg_embs: np.ndarray, texts: list[str], n_iter: int = 2) -> None:
    t0 = time.perf_counter()
    print(f"\n{SEP2}")
    print("  STRATEGIE 1 — k-LLMmeans")
    print(SEP2)

    from sklearn.cluster import KMeans
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    for iteration in range(1, n_iter + 1):
        print(f"\n  Iteration {iteration}/{n_iter}  ({N_CLUSTERS} LLM-Calls)…", flush=True)
        centroids = compute_centroids(seg_embs, labels)

        summaries: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                summaries.append(f"Leerer Cluster {cid + 1}")
                continue
            dists  = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
            top10  = idx[dists.argsort()[:10]]
            body   = "\n\n".join(f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(top10))
            result = provider.complete(_S1_PROMPT.format(texts=body), system=_S1_SYSTEM) or f"Cluster {cid + 1}"
            summary = result.strip().replace("\n", " ")
            summaries.append(summary)
            print(f"    C{cid+1}: {summary[:72]}…", flush=True)

        label_embs_iter = embed_label_texts(bge, summaries, max_length=512)
        labels          = (seg_embs @ label_embs_iter.T).argmax(axis=1)
        centroids_new   = compute_centroids(seg_embs, labels)

        dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))
        print(f"  Verteilung: {dist_str}")
        print_strategy_delta(
            f"STRATEGIE 1 — k-LLMmeans  (Iteration {iteration})",
            [f"C{i+1}" for i in range(N_CLUSTERS)],
            label_embs_iter, centroids_new,
        )

    print(f"\n  Laufzeit: {time.perf_counter() - t0:.1f}s")


# ── Strategie 2 — Centroid direkt ────────────────────────────────────────────

def run_strategy2(seg_embs: np.ndarray, texts: list[str], labels: np.ndarray) -> None:
    t0 = time.perf_counter()
    print(f"\n{SEP2}")
    print("  STRATEGIE 2 — Centroid direkt  (kein LLM)")
    print(SEP2)

    kw_map = tfidf_cluster_keywords(texts, labels)
    names  = [
        ", ".join(kw_map.get(cid, [])[:3]) or f"Cluster {cid + 1}"
        for cid in range(N_CLUSTERS)
    ]
    for cid, name in enumerate(names):
        print(f"  C{cid+1}  ({int((labels==cid).sum()):3d} Seg.)  {name}")

    print_intra_sim_table(
        "STRATEGIE 2 — Centroid direkt  (Intra-Cluster-Kohärenz)",
        names, seg_embs, labels,
    )
    print(f"\n  Laufzeit: {time.perf_counter() - t0:.1f}s")


# ── Strategie 3 — Dual Centroid ───────────────────────────────────────────────

def run_strategy3(
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    labels_init: np.ndarray,
    alpha: float = 0.7,
    max_iter: int = 5,
) -> None:
    t0 = time.perf_counter()
    print(f"\n{SEP2}")
    print(f"  STRATEGIE 3 — Dual Centroid  (α={alpha:.1f} BGE-M3 + {1-alpha:.1f} TF-IDF)")
    print(SEP2)

    from sklearn.feature_extraction.text import TfidfVectorizer

    vec = TfidfVectorizer(
        max_features=8000, min_df=2, sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß]{3,}\b",
    )
    X      = vec.fit_transform(texts)   # (n_segs, n_features), rows L2-normalisiert
    labels = labels_init.copy()

    for iteration in range(1, max_iter + 1):
        sem_centroids = compute_centroids(seg_embs, labels)   # (K, dim)

        tfidf_c = np.zeros((N_CLUSTERS, X.shape[1]), dtype=np.float64)
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                continue
            v    = np.asarray(X[idx].mean(axis=0)).flatten()
            norm = np.linalg.norm(v)
            tfidf_c[cid] = v / max(norm, 1e-9)

        sim_sem   = seg_embs @ sem_centroids.T                          # (n, K) float32
        sim_tfidf = np.asarray(X.dot(tfidf_c.T), dtype=np.float64)     # (n, K)
        score     = alpha * sim_sem + (1 - alpha) * sim_tfidf
        new_labels = np.asarray(score.argmax(axis=1)).flatten().astype(np.int32)

        moved = int((new_labels != labels).sum())
        print(f"  Iteration {iteration}: {moved} Segmente verschoben", flush=True)
        labels = new_labels
        if moved == 0:
            print("  → konvergiert")
            break

    # Label = TF-IDF Top-3-Phrase eingebettet mit BGE-M3
    kw_map = tfidf_cluster_keywords(texts, labels)
    names  = [
        ", ".join(kw_map.get(cid, [])[:3]) or f"Cluster {cid + 1}"
        for cid in range(N_CLUSTERS)
    ]
    print("\n  Einbetten der Keyword-Labels…", flush=True)
    label_embs_s3   = embed_label_texts(bge, names)
    centroids_final = compute_centroids(seg_embs, labels)

    print_strategy_delta(
        "STRATEGIE 3 — Dual Centroid  (Delta: TF-IDF-Labels vs sem. Centroids)",
        names, label_embs_s3, centroids_final,
    )
    print(f"\n  Laufzeit: {time.perf_counter() - t0:.1f}s")


# ── Strategie 4 — Medoid ─────────────────────────────────────────────────────

def run_strategy4(
    seg_embs: np.ndarray,
    texts: list[str],
    seg_ids: list[str],
    labels: np.ndarray,
) -> None:
    t0 = time.perf_counter()
    print(f"\n{SEP2}")
    print("  STRATEGIE 4 — Medoid  (kein LLM)")
    print(SEP2)

    centroids   = compute_centroids(seg_embs, labels)
    medoid_embs = np.zeros_like(centroids)
    names: list[str] = []

    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            names.append(f"(leer {cid + 1})")
            continue
        sims = seg_embs[idx] @ centroids[cid]
        best = idx[int(sims.argmax())]
        medoid_embs[cid] = seg_embs[best]
        preview = texts[best].replace("\n", " ")[:65]
        names.append(f"[{seg_ids[best]}]")
        print(f"  C{cid+1}: Medoid=[{seg_ids[best]}]  \"{preview}…\"")

    print_strategy_delta(
        "STRATEGIE 4 — Medoid  (Delta: Medoid-Emb vs Centroids)",
        names, medoid_embs, centroids,
    )
    print(f"\n  Laufzeit: {time.perf_counter() - t0:.1f}s")


# ── LLM-Label-Strategien A–D ──────────────────────────────────────────────────

def _eval_label_strategy(
    names: list[str],
    label_embs: np.ndarray,
    centroids: np.ndarray,
) -> dict:
    """Berechnet Delta pro Cluster. Gibt Ergebnis-Dict zurück."""
    n          = len(names)
    sim_matrix = label_embs @ centroids.T
    deltas: list[float] = []
    for i in range(n):
        sim_own  = float(sim_matrix[i, i])
        others   = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        deltas.append(sim_own - (max(others) if others else 0.0))
    best_i  = int(np.argmax(deltas))
    worst_i = int(np.argmin(deltas))
    return {
        "names":  names,
        "deltas": deltas,
        "avg":    float(np.mean(deltas)),
        "best":   (names[best_i],  float(deltas[best_i])),
        "worst":  (names[worst_i], float(deltas[worst_i])),
    }


def run_label_baseline(
    bge,
    label_pairs: list[tuple[str, str]],
    kw_map: dict[int, list[str]],
    centroids: np.ndarray,
) -> dict:
    """Baseline — name + beschreibung + tfidf-keywords."""
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kw_str = ", ".join(kw_map.get(i, []))
        text   = f"{name}. {desc}. {kw_str}" if desc else f"{name}. {kw_str}"
        names.append(name)
        label_texts.append(text)
    label_embs = embed_label_texts(bge, label_texts)
    print_strategy_delta("Baseline  (name + desc + keywords)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


_SA_SYSTEM = "Du bist ein präziser Forschungsassistent."
_SA_PROMPT = """\
Verwende diese Wörter in deiner Antwort: {keywords}
Was ist das gemeinsame Thema dieser Texte?

{texts}

Antworte mit: 2-4 Wörter Thema. Ein Satz Beschreibung. Nur diese zwei Zeilen, kein Markdown."""


def run_label_strategy_A(
    provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    labels: np.ndarray,
    kw_map: dict[int, list[str]],
    centroids: np.ndarray,
) -> dict:
    """Strategie A — Keywords-first: LLM pro Cluster, TF-IDF-Keywords im Prompt."""
    print(f"  {N_CLUSTERS} LLM-Calls…", flush=True)
    names: list[str] = []
    label_texts: list[str] = []
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            names.append(f"C{cid+1}")
            label_texts.append(f"Cluster {cid+1}")
            continue
        dists  = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
        top10  = idx[dists.argsort()[:10]]
        body   = "\n\n".join(f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(top10))
        kw_str = ", ".join(kw_map.get(cid, []))
        result = (provider.complete(
            _SA_PROMPT.format(keywords=kw_str, texts=body),
            system=_SA_SYSTEM,
        ) or f"Cluster {cid+1}").strip()
        names.append(f"C{cid+1}")
        label_texts.append(result)
        print(f"    C{cid+1}: {result[:72].replace(chr(10), ' ')}…", flush=True)
    label_embs = embed_label_texts(bge, label_texts, max_length=512)
    print_strategy_delta("Strategie A  (Keywords-first Prompt)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


def run_label_strategy_B(
    bge,
    label_pairs: list[tuple[str, str]],
    kw_map: dict[int, list[str]],
    centroids: np.ndarray,
) -> dict:
    """Strategie B — Stopwort-Filterung: Nur Inhaltswörter aus LLM-Text (DE+EN+AR)."""
    import re as _re
    try:
        from nltk.corpus import stopwords as _nltk_sw
        _nltk_sw.words('german')   # probe — triggers LookupError if corpus missing
        all_stops = (
            _STOPWORDS
            | set(_nltk_sw.words('german'))
            | set(_nltk_sw.words('english'))
            | set(_nltk_sw.words('arabic'))
        )
    except LookupError:
        import nltk
        nltk.download('stopwords', quiet=True)
        from nltk.corpus import stopwords as _nltk_sw
        all_stops = (
            _STOPWORDS
            | set(_nltk_sw.words('german'))
            | set(_nltk_sw.words('english'))
            | set(_nltk_sw.words('arabic'))
        )
    except ModuleNotFoundError:
        print("  [Hinweis] nltk nicht installiert — nur interne Stopwörter", flush=True)
        all_stops = _STOPWORDS
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kws  = kw_map.get(i, [])
        raw  = f"{name} {desc} {' '.join(kws)}"
        words   = _re.findall(r'\b[a-zA-ZäöüÄÖÜßÀ-ÿ]{2,}\b', raw)
        content = [w for w in words if w.lower() not in all_stops]
        text    = " ".join(content) if content else raw
        names.append(name)
        label_texts.append(text)
        print(f"    C{i+1}: {text[:80]}", flush=True)
    label_embs = embed_label_texts(bge, label_texts)
    print_strategy_delta("Strategie B  (Stopwort-Filterung)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


def run_label_strategy_C(
    provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    labels: np.ndarray,
    centroids: np.ndarray,
) -> dict:
    """Strategie C — Breiter Kontext: Top-20 × 150 Zeichen, ein LLM-Call."""
    TOP_K_C     = 20
    SEG_CHARS_C = 150
    kw_map_c    = tfidf_cluster_keywords(texts, labels)
    groups: list[str] = []
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            groups.append(f"=== Gruppe {cid+1} ===\n(leer)")
            continue
        dists   = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
        top_idx = idx[dists.argsort()[:TOP_K_C]].tolist()
        kw_line = ("Häufige Begriffe: " + ", ".join(kw_map_c.get(cid, []))) if kw_map_c.get(cid) else ""
        snippets = "\n\n".join(f"Text {i+1}:\n{texts[j][:SEG_CHARS_C]}" for i, j in enumerate(top_idx))
        block = f"=== Gruppe {cid+1} ==="
        if kw_line:
            block += f"\n{kw_line}"
        block += f"\n\n{snippets}"
        groups.append(block)
    prompt = LABEL_PROMPT.format(n=N_CLUSTERS, groups="\n\n".join(groups) + "\n\n")
    print("  1 LLM-Call (Top-20 × 150 Zeichen)…", flush=True)
    raw    = provider.complete(prompt, system=LABEL_SYSTEM) or ""
    parsed = parse_all_labels(raw, N_CLUSTERS)
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(parsed):
        names.append(name)
        label_texts.append(f"{name}. {desc}" if desc else name)
        print(f"    C{i+1}: {name}", flush=True)
    label_embs = embed_label_texts(bge, label_texts)
    print_strategy_delta("Strategie C  (Breiter Kontext: Top-20 × 150)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


def run_label_strategy_D(
    bge,
    label_pairs: list[tuple[str, str]],
    kw_map: dict[int, list[str]],
    centroids: np.ndarray,
) -> dict:
    """Strategie D — Hybrid: TF-IDF-Keywords vorne + LLM-Beschreibung hinten."""
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kws    = kw_map.get(i, [])
        kw_str = ", ".join(kws) if kws else name
        text   = f"{kw_str}. {desc}" if desc else kw_str
        names.append(name)
        label_texts.append(text)
        print(f"    C{i+1}: {text[:80]}", flush=True)
    label_embs = embed_label_texts(bge, label_texts)
    print_strategy_delta("Strategie D  (Hybrid: Keywords + LLM-Desc)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


def print_strategy_abcd_comparison(results: dict) -> None:
    SEP_W = "=" * 104
    print(f"\n{SEP_W}")
    print("  VERGLEICH — LLM-Label-Strategien")
    print(SEP_W)
    baseline_avg = results.get("Baseline", {}).get("avg", 0.0)
    print(f"  {'Strategie':<22}  {'Ø Delta':>9}  {'vs Baseline':>11}  "
          f"{'Bester Cluster':<32}  {'Schlechtester Cluster'}")
    print(f"  {'─'*22}  {'─'*9}  {'─'*11}  {'─'*32}  {'─'*32}")
    for label, res in results.items():
        avg         = res["avg"]
        diff_s      = f"{avg - baseline_avg:+.4f}" if label != "Baseline" else "    —   "
        best_n, bd  = res["best"]
        worst_n, wd = res["worst"]
        print(f"  {label:<22}  {avg:>+9.4f}  {diff_s:>11}  "
              f"{best_n[:22]:<22}  Δ={bd:+.3f}    {worst_n[:22]:<22}  Δ={wd:+.3f}")
    print(SEP_W)


# ── Strategien E & F ──────────────────────────────────────────────────────────

def run_label_strategy_E(
    bge,
    kw_map: dict[int, list[str]],
    centroids: np.ndarray,
) -> dict:
    """Strategie E — TF-IDF direkt als Label (Top-8-Keywords, kein LLM)."""
    names: list[str] = []
    label_texts: list[str] = []
    for cid in range(N_CLUSTERS):
        kws  = kw_map.get(cid, [])
        text = " ".join(kws) if kws else f"Cluster {cid + 1}"
        names.append(text[:35])
        label_texts.append(text)
        print(f"    C{cid+1}: {text}", flush=True)
    label_embs = embed_label_texts(bge, label_texts)
    print_strategy_delta("Strategie E  (TF-IDF direkt als Label)", names, label_embs, centroids)
    return _eval_label_strategy(names, label_embs, centroids)


def run_label_strategy_F(
    bge,
    texts: list[str],
    labels: np.ndarray,
    label_pairs: list[tuple[str, str]],
    kw_map: dict[int, list[str]],
) -> dict:
    """Strategie F — Instruktions-Prefix für Segment- und Label-Embeddings."""
    INSTR = "Represent this Ottoman history research note for topic classification: "

    print("  Segmente mit Instruktion einbetten…", flush=True)
    t0  = time.perf_counter()
    raw = bge.encode(
        [INSTR + t for t in texts],
        batch_size=32, max_length=512,
        return_dense=True, return_sparse=False, return_colbert_vecs=False,
    )["dense_vecs"]
    embs_f = np.array(raw, dtype=np.float32)
    norms  = np.linalg.norm(embs_f, axis=1, keepdims=True)
    embs_f /= np.maximum(norms, 1e-9)
    print(f"  {embs_f.shape}  [{time.perf_counter() - t0:.1f}s]", flush=True)

    centroids_f = compute_centroids(embs_f, labels)

    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kw_str   = ", ".join(kw_map.get(i, []))
        baseline = f"{name}. {desc}. {kw_str}" if desc else f"{name}. {kw_str}"
        names.append(name)
        label_texts.append(INSTR + baseline)

    label_embs = embed_label_texts(bge, label_texts, max_length=256)
    print_strategy_delta(
        "Strategie F  (BGE-M3 mit Instruktion)", names, label_embs, centroids_f,
    )
    return _eval_label_strategy(names, label_embs, centroids_f)


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

    # ── Schritt 7 — Strategievergleich ─────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 7 — Strategievergleich")
    print(SEP2)

    run_strategy1(provider, bge, embs, texts)
    run_strategy2(embs, texts, labels)
    run_strategy3(bge, embs, texts, labels)
    run_strategy4(embs, texts, seg_ids, labels)

    # ── Schritt 8 — LLM-Label-Strategien A–D ──────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 8 — LLM-Label-Strategien A–D")
    print(SEP2)

    strat_results: dict = {}

    print("\nBaseline…")
    strat_results["Baseline"] = run_label_baseline(bge, label_pairs, kw_map, centroids_sem)

    print(f"\nStrategie A — Keywords-first Prompt…")
    t_a = time.perf_counter()
    strat_results["A: Keywords-first"] = run_label_strategy_A(
        provider, bge, embs, texts, labels, kw_map, centroids_sem)
    print(f"  Laufzeit: {time.perf_counter()-t_a:.1f}s")

    print(f"\nStrategie B — Stopwort-Filterung…")
    t_b = time.perf_counter()
    strat_results["B: Stopwort-Filter"] = run_label_strategy_B(
        bge, label_pairs, kw_map, centroids_sem)
    print(f"  Laufzeit: {time.perf_counter()-t_b:.1f}s")

    print(f"\nStrategie C — Breiter Kontext…")
    t_c = time.perf_counter()
    strat_results["C: Breiter Kontext"] = run_label_strategy_C(
        provider, bge, embs, texts, labels, centroids_sem)
    print(f"  Laufzeit: {time.perf_counter()-t_c:.1f}s")

    print(f"\nStrategie D — Hybrid…")
    t_d = time.perf_counter()
    strat_results["D: Hybrid"] = run_label_strategy_D(
        bge, label_pairs, kw_map, centroids_sem)
    print(f"  Laufzeit: {time.perf_counter()-t_d:.1f}s")

    print_strategy_abcd_comparison(strat_results)

    # ── Schritt 9 — Strategien E & F ──────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 9 — Strategien E & F")
    print(SEP2)

    # Medoid-Referenz (deterministisch, <0.1s)
    centroids_s4   = compute_centroids(embs, labels)
    medoid_embs_s4 = np.zeros_like(centroids_s4)
    medoid_names_s4: list[str] = []
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) > 0:
            best = idx[int((embs[idx] @ centroids_s4[cid]).argmax())]
            medoid_embs_s4[cid] = embs[best]
            medoid_names_s4.append(f"[{seg_ids[best]}]")
        else:
            medoid_names_s4.append(f"C{cid+1}")
    medoid_s4_res = _eval_label_strategy(medoid_names_s4, medoid_embs_s4, centroids_s4)

    ef_results: dict = {
        "Baseline":   strat_results["Baseline"],
        "S4: Medoid": medoid_s4_res,
    }

    print("\nStrategie E — TF-IDF direkt…")
    ef_results["E: TF-IDF direkt"] = run_label_strategy_E(bge, kw_map, centroids_sem)

    print("\nStrategie F — BGE-M3 mit Instruktion…")
    ef_results["F: BGE+Instruktion"] = run_label_strategy_F(
        bge, texts, labels, label_pairs, kw_map)

    print_strategy_abcd_comparison(ef_results)

    elapsed = time.perf_counter() - t0
    print(f"\n{SEP}")
    print(f"  Gesamt: {elapsed:.1f}s  (Embeddings aus Cache)")
    print(SEP2 + "\n")


if __name__ == "__main__":
    main()
