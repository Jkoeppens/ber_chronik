"""
test_taxonomy_benchmark.py — Label-Alignment-Strategien auf BER-Material

Vergleicht 7 Labeling-Strategien anhand:
  Delta = Sim_own - Sim_best_other  (Trennschärfe des Labels)
  IntraSim = Ø paarweise Cosine-Ähnlichkeit innerhalb eines Clusters

Daten:  data/projects/ber/documents/main/segments.json
Cache:  /tmp/ber_bge_embeddings.npy
Setup:  BGE-M3 + Nachbar-Aggregation (< 100 Zeichen) + KMeans(n=7, seed=42)

Strategien:
  Baseline  — LLM ein Call → name + desc + keywords
  S1        — Medoid (kein LLM)
  S2        — TF-IDF direkt (kein LLM)
  S3        — Stopwort-Filter auf LLM-Text
  S4        — Hybrid: TF-IDF + LLM-Beschreibung
  S5        — BGE-M3 mit Instruktion (kein LLM)
  S6        — k-LLMmeans, 2 Iterationen
"""

import json
import re
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from src.generalized.config import ROOT
from src.generalized.llm import get_provider, TASK_ANALYZE

# ── Konfiguration ──────────────────────────────────────────────────────────────

SEGMENTS_PATH   = Path("data/projects/ber/documents/main/segments.json")
CACHE_PATH      = Path("/tmp/ber_bge_embeddings.npy")

N_CLUSTERS      = 7
SEG_CHARS       = 500
MIN_LENGTH      = 30
SHORT_THRESHOLD = 100
TOP_K_KW        = 8
TOP_K_LLM       = 10
LLM_SEG_CHARS   = 300
TOP_K_SHOW      = 3

S5_INSTRUCTION = (
    "Represent this German urban planning and airport construction text "
    "for topic classification: "
)

_STOPWORDS = {
    "der", "die", "das", "und", "in", "von", "zu", "den", "mit", "ist", "im",
    "dem", "des", "ein", "eine", "sich", "auch", "auf", "an", "für", "es",
    "als", "bei", "aber", "oder", "aus", "hat", "nicht", "wird", "war",
    "waren", "dass", "wenn", "nach", "durch", "um", "so", "wie",
    "über", "bis", "dann", "diese", "dieser", "diesem", "diesen", "dieses",
    "er", "sie", "wir", "ihre", "ihrer", "ihren", "ihrem", "ihres",
    "sein", "seiner", "seinem", "seinen", "seine", "eines", "einem", "einen",
    "werden", "haben", "noch", "mehr", "nur", "schon", "sehr", "hier", "da",
    "vom", "zum", "zur", "vor", "seit", "ob", "am", "gegen",
    "the", "of", "and", "in", "to", "a", "that", "was", "as", "is", "it",
    "for", "by", "on", "with", "an", "at", "be", "this", "were", "had",
    "have", "from", "or", "not", "their", "they", "which", "but", "its",
    "his", "her", "he", "who", "been", "also", "more", "are", "into",
}

SEP  = "─" * 80
SEP2 = "═" * 80

LABEL_SYSTEM = """\
Du siehst häufige Begriffe und Textausschnitte aus Gruppen von Notizen \
zur Berliner Stadtentwicklung und dem Flughafenausbau. Nenne für jede Gruppe \
ein präzises Thema (2-4 Wörter) das diese Gruppe von den anderen abgrenzt."""

LABEL_PROMPT = """\
Hier sind {n} Gruppen von Texten. Benenne jede Gruppe mit einem präzisen Thema \
das sie von den anderen abgrenzt.

{groups}
Antworte für jede Gruppe im Format:

### Gruppe 1: [Thema, 2-4 Wörter]
[Ein Satz der diese Gruppe von den anderen abgrenzt]

### Gruppe 2: ...

Regeln:
- Thema in PascalCase, 2-4 Wörter, auf Deutsch
- Nur die Gruppenblöcke ausgeben, kein Kommentar"""

_S6_SYSTEM = "Du bist ein präziser Forschungsassistent."
_S6_PROMPT = """\
Fasse die folgenden Texte in 2-3 präzisen Sätzen zusammen. \
Benenne das gemeinsame Thema explizit. Keine Aufzählung, kein Markdown.

{texts}"""


# ── Daten & Embeddings ────────────────────────────────────────────────────────

def load_segments() -> tuple[list[str], list[str]]:
    segs = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    content = [s for s in segs
               if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]
    content.sort(key=lambda s: s.get("segment_id", ""))
    return [s["text"][:SEG_CHARS] for s in content], [s.get("segment_id", "?") for s in content]


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


def embed_texts(bge, texts: list[str], max_length: int = 256) -> np.ndarray:
    raw  = bge.encode(texts, batch_size=16, max_length=max_length,
                      return_dense=True, return_sparse=False,
                      return_colbert_vecs=False)["dense_vecs"]
    embs = np.array(raw, dtype=np.float32)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    return embs / np.maximum(norms, 1e-9)


def neighbor_aggregate(embs: np.ndarray, texts: list[str]) -> tuple[np.ndarray, int]:
    enriched = embs.copy()
    n = 0
    for i, text in enumerate(texts):
        if len(text) < SHORT_THRESHOLD:
            neighbors = [embs[i]]
            if i > 0:              neighbors.append(embs[i - 1])
            if i < len(embs) - 1:  neighbors.append(embs[i + 1])
            v = np.mean(neighbors, axis=0)
            enriched[i] = v / max(float(np.linalg.norm(v)), 1e-9)
            n += 1
    return enriched, n


def compute_centroids(embs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    n_clusters = int(labels.max()) + 1
    centroids  = np.zeros((n_clusters, embs.shape[1]), dtype=np.float32)
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        v = embs[idx].mean(axis=0)
        centroids[cid] = v / max(float(np.linalg.norm(v)), 1e-9)
    return centroids


def run_kmeans(embs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.cluster import KMeans
    km     = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto")
    labels = km.fit_predict(embs)
    return labels, km.cluster_centers_


def tfidf_cluster_keywords(texts: list[str], labels: np.ndarray) -> dict[int, list[str]]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(
        max_features=8000, min_df=2, sublinear_tf=True,
        token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß]{3,}\b",
    )
    X     = vec.fit_transform(texts)
    names = vec.get_feature_names_out()
    result: dict[int, list[str]] = {}
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            result[cid] = []
            continue
        mean_scores = np.asarray(X[idx].mean(axis=0)).flatten()
        ranked = mean_scores.argsort()[::-1]
        result[cid] = [names[i] for i in ranked
                       if names[i].lower() not in _STOPWORDS][:TOP_K_KW]
    return result


# ── LLM-Hilfsfunktionen ───────────────────────────────────────────────────────

def build_llm_prompt(embs: np.ndarray, labels: np.ndarray,
                     centroids: np.ndarray, texts: list[str]) -> str:
    kw_map  = tfidf_cluster_keywords(texts, labels)
    groups: list[str] = []
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            groups.append(f"=== Gruppe {cid+1} ===\n(leer)")
            continue
        dists   = np.linalg.norm(embs[idx] - centroids[cid], axis=1)
        top_idx = idx[dists.argsort()[:TOP_K_LLM]].tolist()
        kw_line = "Häufige Begriffe: " + ", ".join(kw_map[cid]) if kw_map[cid] else ""
        snippets = "\n\n".join(
            f"Text {i+1}:\n{texts[j][:LLM_SEG_CHARS]}" for i, j in enumerate(top_idx)
        )
        block = f"=== Gruppe {cid+1} ==="
        if kw_line:
            block += f"\n{kw_line}"
        block += f"\n\n{snippets}"
        groups.append(block)
    return LABEL_PROMPT.format(n=N_CLUSTERS, groups="\n\n".join(groups) + "\n\n")


def parse_all_labels(raw: str, n: int) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = [("Unbekannt", "")] * n
    current_idx  = None
    current_name = ""
    current_desc = ""
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


def _load_nltk_stops() -> set[str]:
    try:
        from nltk.corpus import stopwords as _sw
        _sw.words("german")
        return _STOPWORDS | set(_sw.words("german")) | set(_sw.words("english"))
    except LookupError:
        import nltk
        nltk.download("stopwords", quiet=True)
        from nltk.corpus import stopwords as _sw
        return _STOPWORDS | set(_sw.words("german")) | set(_sw.words("english"))
    except ModuleNotFoundError:
        print("  [Hinweis] nltk nicht installiert — nur interne Stopwörter", flush=True)
        return _STOPWORDS


# ── Metrik ────────────────────────────────────────────────────────────────────

def eval_strategy(
    names:      list[str],
    label_embs: np.ndarray,
    centroids:  np.ndarray,
    seg_embs:   np.ndarray,
    labels:     np.ndarray,
) -> dict:
    """Berechnet Delta + Intra-Cluster-Kohärenz. Gibt vollständiges Ergebnis-Dict zurück."""
    n          = len(names)
    sim_matrix = label_embs @ centroids.T   # (n, n)
    deltas: list[float] = []
    for i in range(n):
        sim_own  = float(sim_matrix[i, i])
        others   = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        deltas.append(sim_own - (max(others) if others else 0.0))

    # Intra-Cluster-Kohärenz
    intra: dict[int, float] = {}
    sizes = [int((labels == cid).sum()) for cid in range(n)]
    for cid in range(n):
        idx = np.where(labels == cid)[0]
        if len(idx) < 2:
            intra[cid] = 1.0 if len(idx) == 1 else 0.0
            continue
        sub     = seg_embs[idx]
        sim_mat = sub @ sub.T
        k       = len(idx)
        mask    = np.triu(np.ones((k, k), dtype=bool), k=1)
        intra[cid] = float(sim_mat[mask].mean())

    total     = sum(sizes)
    intra_avg = sum(intra[c] * sizes[c] for c in range(n)) / total if total else 0.0

    best_i  = int(np.argmax(deltas))
    worst_i = int(np.argmin(deltas))
    return {
        "names":      names,
        "deltas":     deltas,
        "avg":        float(np.mean(deltas)),
        "intra_avg":  intra_avg,
        "intra":      intra,
        "best":       (names[best_i],  float(deltas[best_i])),
        "worst":      (names[worst_i], float(deltas[worst_i])),
        "label_embs": label_embs,
        "centroids":  centroids,
        "labels":     labels,
        "elapsed":    0.0,
        "llm_calls":  0,
    }


def print_delta_table(title: str, names: list[str],
                      label_embs: np.ndarray, centroids: np.ndarray) -> None:
    n          = len(names)
    sim_matrix = label_embs @ centroids.T
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)
    print(f"  {'Cluster':35s}  {'Sim_own':>8}  {'Sim_best_other':>14}  {'Delta':>7}")
    print(f"  {'─'*35}  {'─'*8}  {'─'*14}  {'─'*7}")
    for i, name in enumerate(names):
        sim_own  = float(sim_matrix[i, i])
        others   = [float(sim_matrix[i, j]) for j in range(n) if j != i]
        sim_best = max(others) if others else 0.0
        delta    = sim_own - sim_best
        print(f"  {name[:35]:35s}  {sim_own:8.4f}  {sim_best:14.4f}  {delta:7.4f}")


# ── Strategien ────────────────────────────────────────────────────────────────

def run_baseline(
    provider, bge,
    seg_embs: np.ndarray, texts: list[str],
    labels: np.ndarray, centroids: np.ndarray,
) -> tuple[dict, list[tuple[str, str]], dict[int, list[str]]]:
    """Baseline — LLM beschriftet alle Cluster in einem Call."""
    t0     = time.perf_counter()
    kw_map = tfidf_cluster_keywords(texts, labels)
    prompt = build_llm_prompt(seg_embs, labels, centroids, texts)
    print("  1 LLM-Call…", flush=True)
    raw         = provider.complete(prompt, system=LABEL_SYSTEM) or ""
    label_pairs = parse_all_labels(raw, N_CLUSTERS)

    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kw_str = ", ".join(kw_map.get(i, []))
        text   = f"{name}. {desc}. {kw_str}" if desc else f"{name}. {kw_str}"
        names.append(name)
        label_texts.append(text)
        print(f"    C{i+1}: {name}", flush=True)

    label_embs = embed_texts(bge, label_texts)
    print_delta_table("Baseline  (name + desc + keywords)", names, label_embs, centroids)
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 1
    return res, label_pairs, kw_map


def run_s1_medoid(
    seg_embs: np.ndarray, texts: list[str], seg_ids: list[str], labels: np.ndarray,
) -> dict:
    """S1 Medoid — Segment mit höchster Sim zum Centroid als Label-Embedding."""
    t0        = time.perf_counter()
    centroids = compute_centroids(seg_embs, labels)
    medoid_embs = np.zeros_like(centroids)
    names: list[str] = []
    for cid in range(N_CLUSTERS):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            names.append(f"C{cid+1}")
            continue
        sims = seg_embs[idx] @ centroids[cid]
        best = idx[int(sims.argmax())]
        medoid_embs[cid] = seg_embs[best]
        preview = texts[best].replace("\n", " ")[:55]
        names.append(f"[{seg_ids[best]}]")
        print(f"    C{cid+1}: [{seg_ids[best]}]  \"{preview}…\"")
    print_delta_table("S1 Medoid", names, medoid_embs, centroids)
    res = eval_strategy(names, medoid_embs, centroids, seg_embs, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 0
    return res


def run_s2_tfidf(
    bge,
    seg_embs: np.ndarray, texts: list[str], labels: np.ndarray,
) -> dict:
    """S2 TF-IDF direkt — Top-8-Keywords als Label-Text."""
    t0        = time.perf_counter()
    kw_map    = tfidf_cluster_keywords(texts, labels)
    centroids = compute_centroids(seg_embs, labels)
    names: list[str] = []
    label_texts: list[str] = []
    for cid in range(N_CLUSTERS):
        kws  = kw_map.get(cid, [])
        text = " ".join(kws) if kws else f"Cluster {cid+1}"
        names.append(text[:35])
        label_texts.append(text)
        print(f"    C{cid+1}: {text}")
    label_embs = embed_texts(bge, label_texts)
    print_delta_table("S2 TF-IDF direkt", names, label_embs, centroids)
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 0
    return res


def run_s3_filter(
    bge,
    seg_embs: np.ndarray, labels: np.ndarray,
    label_pairs: list[tuple[str, str]], kw_map: dict[int, list[str]],
) -> dict:
    """S3 Stopwort-Filter — Inhaltswörter aus LLM-Text (DE+EN, nltk)."""
    t0        = time.perf_counter()
    all_stops = _load_nltk_stops()
    centroids = compute_centroids(seg_embs, labels)
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kws     = kw_map.get(i, [])
        raw     = f"{name} {desc} {' '.join(kws)}"
        words   = re.findall(r'\b[a-zA-ZäöüÄÖÜßÀ-ÿ]{2,}\b', raw)
        content = [w for w in words if w.lower() not in all_stops]
        text    = " ".join(content) if content else raw
        names.append(name)
        label_texts.append(text)
        print(f"    C{i+1}: {text[:80]}")
    label_embs = embed_texts(bge, label_texts)
    print_delta_table("S3 Stopwort-Filter", names, label_embs, centroids)
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 0   # reuses Baseline LLM output
    return res


def run_s4_hybrid(
    bge,
    seg_embs: np.ndarray, labels: np.ndarray,
    label_pairs: list[tuple[str, str]], kw_map: dict[int, list[str]],
) -> dict:
    """S4 Hybrid — TF-IDF-Keywords + LLM-Beschreibung."""
    t0        = time.perf_counter()
    centroids = compute_centroids(seg_embs, labels)
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kws    = kw_map.get(i, [])
        kw_str = ", ".join(kws) if kws else name
        text   = f"{kw_str}. {desc}" if desc else kw_str
        names.append(name)
        label_texts.append(text)
        print(f"    C{i+1}: {text[:80]}")
    label_embs = embed_texts(bge, label_texts)
    print_delta_table("S4 Hybrid  (TF-IDF + LLM-Desc)", names, label_embs, centroids)
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 0   # reuses Baseline LLM output
    return res


def run_s5_instruction(
    bge,
    seg_embs_orig: np.ndarray, texts: list[str], labels: np.ndarray,
    label_pairs: list[tuple[str, str]], kw_map: dict[int, list[str]],
) -> dict:
    """S5 BGE-M3 mit Instruktion — Segmente und Labels mit Instruktions-Prefix."""
    t0 = time.perf_counter()
    print("  Segmente mit Instruktion einbetten…", flush=True)
    t_emb = time.perf_counter()
    raw   = bge.encode(
        [S5_INSTRUCTION + t for t in texts],
        batch_size=32, max_length=512,
        return_dense=True, return_sparse=False, return_colbert_vecs=False,
    )["dense_vecs"]
    embs_f = np.array(raw, dtype=np.float32)
    norms  = np.linalg.norm(embs_f, axis=1, keepdims=True)
    embs_f /= np.maximum(norms, 1e-9)
    print(f"  {embs_f.shape}  [{time.perf_counter()-t_emb:.1f}s]", flush=True)

    centroids_f = compute_centroids(embs_f, labels)
    names: list[str] = []
    label_texts: list[str] = []
    for i, (name, desc) in enumerate(label_pairs):
        kw_str   = ", ".join(kw_map.get(i, []))
        baseline = f"{name}. {desc}. {kw_str}" if desc else f"{name}. {kw_str}"
        names.append(name)
        label_texts.append(S5_INSTRUCTION + baseline)
    label_embs = embed_texts(bge, label_texts, max_length=256)
    print_delta_table("S5 BGE-M3 mit Instruktion", names, label_embs, centroids_f)
    res = eval_strategy(names, label_embs, centroids_f, embs_f, labels)
    res["elapsed"]   = time.perf_counter() - t0
    res["llm_calls"] = 0
    return res


def run_s6_kllmmeans(
    provider, bge,
    seg_embs: np.ndarray, texts: list[str],
    n_iter: int = 2,
) -> dict:
    """S6 k-LLMmeans — LLM fasst Cluster zusammen → embed → reassign → wiederholen."""
    t0        = time.perf_counter()
    from sklearn.cluster import KMeans
    labels    = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)
    llm_calls = 0
    label_embs_final: np.ndarray = np.zeros((N_CLUSTERS, seg_embs.shape[1]), dtype=np.float32)

    for iteration in range(1, n_iter + 1):
        print(f"\n  Iteration {iteration}/{n_iter}  ({N_CLUSTERS} LLM-Calls)…", flush=True)
        centroids  = compute_centroids(seg_embs, labels)
        summaries: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                summaries.append(f"Leerer Cluster {cid+1}")
                continue
            dists = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
            top10 = idx[dists.argsort()[:10]]
            body  = "\n\n".join(f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(top10))
            result = (provider.complete(_S6_PROMPT.format(texts=body), system=_S6_SYSTEM)
                      or f"Cluster {cid+1}").strip().replace("\n", " ")
            summaries.append(result)
            llm_calls += 1
            print(f"    C{cid+1}: {result[:70]}…", flush=True)

        label_embs_final = embed_texts(bge, summaries, max_length=512)
        labels           = (seg_embs @ label_embs_final.T).argmax(axis=1)
        dist_str         = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))
        print(f"  Verteilung: {dist_str}")

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table("S6 k-LLMmeans (2 Iterationen)", names, label_embs_final, centroids)
    res = eval_strategy(names, label_embs_final, centroids, seg_embs, labels)
    res["elapsed"]    = time.perf_counter() - t0
    res["llm_calls"]  = llm_calls
    res["summaries"]  = summaries   # final-iteration LLM summaries (one per cluster)
    return res


_S6_PAPER_PROMPT = """\
Schreibe 3-4 Sätze die den Kern dieser Texte zusammenfassen. \
Fokus auf konkrete Themen, Akteure und Ereignisse — kein allgemeines Intro.

{texts}"""

_S6_EXACT_PROMPT = """\
The following are excerpts from German news articles about Berlin airport construction. \
Write a single sentence in German that represents the main topic of these texts concisely.

{texts}"""

_S6_EXACT_SYSTEM = "Du bist ein präziser Forschungsassistent für Medienanalyse."


def _llm_t0(provider, prompt: str, system: str) -> str:
    """LLM-Call mit temperature=0 — Ollama und Anthropic."""
    import requests as _req
    if hasattr(provider, "base_url"):          # OllamaProvider
        payload: dict = {
            "model": provider.model, "prompt": prompt, "stream": False,
            "options": {"num_ctx": 8192, "temperature": 0},
        }
        if system:
            payload["system"] = system
        r = _req.post(f"{provider.base_url}/api/generate", json=payload, timeout=300)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    if hasattr(provider, "_client"):           # AnthropicProvider
        text, _, _ = _anthropic_t0(provider, prompt, system, max_tokens=1024)
        return text
    return provider.complete(prompt, system=system) or ""


_S6_CUMULATIVE_SYSTEM = """\
Du analysierst Texte zur Berliner Stadtentwicklung und dem Flughafenausbau (BER). \
Für jede Gruppe siehst du bisherige Beschreibungen aus früheren Iterationen sowie neue Segmente. \
Synthetisiere alle Informationen zu einer präzisen Beschreibung in 3-4 Sätzen. \
Fokus auf konkrete Themen, Akteure und Ereignisse. \
Grenze jede Gruppe klar von den anderen ab — kein allgemeines Intro, keine Floskeln."""

_S6_ROLLING_SYSTEM = """\
Du analysierst Texte zur Berliner Stadtentwicklung und dem Flughafenausbau (BER). \
Für jede Gruppe siehst du die vorherige Beschreibung sowie neue Segmente. \
Verfeinere die Beschreibung basierend auf den neuen Segmenten in 3-4 Sätzen. \
Fokus auf konkrete Themen, Akteure und Ereignisse. \
Grenze jede Gruppe klar von den anderen ab — kein allgemeines Intro, keine Floskeln."""

_S6_TFIDF_ANCHOR_SYSTEM = (
    "Du analysierst Gruppen von Texten über den Berliner Flughafen BER. "
    "Schreibe präzise, kontrastierende Beschreibungen — kein allgemeines Intro, keine Floskeln."
)

_S6_TFIDF_ANCHOR_PROMPT = """\
Du analysierst {n} Gruppen von Texten über den Berliner Flughafen BER.

Für jede Gruppe sind folgende Keywords konstant charakteristisch \
(diese sollen in deiner Beschreibung vorkommen):

{keyword_section}
{prev_section}
Neue Beispieltexte:
{segment_section}

Verfeinere die Beschreibungen unter Einbeziehung der Keywords und Beispieltexte. \
Jede Gruppe muss sich klar von den anderen unterscheiden.

Antworte für jede Gruppe im Format (kein weiterer Text):

## Gruppe 1: [2-4 Wörter Titel]
[2-3 Sätze Beschreibung die die Keywords einschließt]

## Gruppe 2: ...
"""

_S6_ANTHROPIC_SYSTEM = """\
Du analysierst Texte zur Berliner Stadtentwicklung und dem Flughafenausbau (BER). \
Beschreibe jede Gruppe in 3-4 konkreten Sätzen. \
Fokus auf konkrete Themen, Akteure und Ereignisse — kein allgemeines Intro, keine Floskeln. \
Grenze jede Gruppe klar von den anderen ab."""

_S6_ANTHROPIC_PROMPT = """\
Hier sind {n} Gruppen von Texten. Schreibe für jede Gruppe 3-4 Sätze \
die den Kern zusammenfassen. Kontrastiere die Gruppen: jede Beschreibung \
soll klar machen, was diese Gruppe von den anderen unterscheidet.

{groups}
Antworte für jede Gruppe exakt in diesem Format (kein Markdown):

GRUPPE 1:
[3-4 Sätze]

GRUPPE 2:
[3-4 Sätze]
"""

# Anthropic Preise (Stand 2025, USD pro 1M Token)
_ANTHROPIC_PRICES = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6":         (3.00, 15.00),
    "claude-opus-4-7":           (15.00, 75.00),
}


def _anthropic_t0(
    provider,
    prompt: str,
    system: str,
    max_tokens: int = 2048,
) -> tuple[str, int, int]:
    """Anthropic-Call mit temperature=0. Gibt (text, input_tokens, output_tokens) zurück."""
    kwargs: dict = dict(
        model=provider.model,
        max_tokens=max_tokens,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    msg = provider._client.messages.create(**kwargs)
    return msg.content[0].text.strip(), msg.usage.input_tokens, msg.usage.output_tokens


def _parse_gruppe_summaries(raw: str, n: int) -> list[str]:
    """Parst 'GRUPPE N:\\n...' Format aus einem kombinierten LLM-Response."""
    summaries = [f"Gruppe {i+1}" for i in range(n)]
    parts = re.split(r"\bGRUPPE\s+(\d+)\s*:", raw, flags=re.IGNORECASE)
    # parts = ["preamble", "1", "text1", "2", "text2", ...]
    i = 1
    while i + 1 < len(parts):
        try:
            idx = int(parts[i]) - 1
        except ValueError:
            i += 2
            continue
        text = parts[i + 1].strip().replace("\n", " ")
        if 0 <= idx < n:
            summaries[idx] = text
        i += 2
    return summaries


def _parse_gruppe_titled(raw: str, n: int) -> list[tuple[str, str]]:
    """Parst '## Gruppe N: Titel\\nBeschreibung' → [(title, body), ...]."""
    results: list[tuple[str, str]] = [("", f"Gruppe {i+1}") for i in range(n)]
    pattern = re.compile(r"^##\s*Gruppe\s+(\d+)\s*[:\-–—]?\s*(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(raw))
    for k, m in enumerate(matches):
        idx   = int(m.group(1)) - 1
        title = m.group(2).strip()
        end   = matches[k + 1].start() if k + 1 < len(matches) else len(raw)
        body  = raw[m.end():end].strip().replace("\n", " ")
        if 0 <= idx < n:
            results[idx] = (title, body)
    return results


def run_s6_tfidf_anchor(
    anthropic_provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    km_interval: int = 5,
    max_km_iter: int = 20,
    m: int = 10,
) -> dict:
    """S6-tfidf-anchor — rolling context + feste TF-IDF-Keyword-Anker.

    TF-IDF-Keywords einmal aus initialen KMeans-Labels berechnet, danach konstant.
    Jede Iteration: kontrastiver Call mit Keywords + vorheriger Beschreibung + neuen
    Segmenten (k-means++ Sampling). Format: '## Gruppe N: Titel\\nBeschreibung'.
    """
    t0  = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    rng    = np.random.default_rng(42)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    kw_map_fixed = tfidf_cluster_keywords(texts, labels)   # never updated
    label_embs   = compute_centroids(seg_embs, labels)

    prev_descs: list[str | None]   = [None] * N_CLUSTERS
    summaries: list[str]           = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    prev_label_embs: np.ndarray | None = None
    llm_calls  = 0
    total_in   = 0
    total_out  = 0
    logs: list[dict] = []
    prev_llm_iter: int | None = None

    for km_iter in range(1, max_km_iter + 1):
        if km_iter % km_interval != 0:
            labels = (seg_embs @ label_embs.T).argmax(axis=1)
            continue

        centroids = compute_centroids(seg_embs, labels)

        # Keyword section (constant)
        kw_section = "\n".join(
            f"Gruppe {cid+1} Keywords: {', '.join(kw_map_fixed.get(cid, []))}"
            for cid in range(N_CLUSTERS)
        )

        # Previous description section
        if any(d is not None for d in prev_descs):
            prev_lines = "\n".join(
                f"Gruppe {cid+1}: {prev_descs[cid]}" if prev_descs[cid]
                else f"Gruppe {cid+1}: (keine)"
                for cid in range(N_CLUSTERS)
            )
            prev_section = (
                f"\nVorherige Beschreibungen (Iteration {prev_llm_iter}):\n"
                f"{prev_lines}\n"
            )
        else:
            prev_section = ""

        # Segment section — k-means++ sampling
        seg_blocks: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                seg_blocks.append(f"--- Gruppe {cid+1} ---\n(Leer)")
                continue
            sample_idx = _kmeanspp_sample(seg_embs, idx, m, rng)
            snips = "\n\n".join(
                f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(sample_idx)
            )
            seg_blocks.append(f"--- Gruppe {cid+1} ---\n{snips}")

        prompt = _S6_TFIDF_ANCHOR_PROMPT.format(
            n=N_CLUSTERS,
            keyword_section=kw_section,
            prev_section=prev_section,
            segment_section="\n\n".join(seg_blocks),
        )
        raw, in_tok, out_tok = _anthropic_t0(
            anthropic_provider, prompt, _S6_TFIDF_ANCHOR_SYSTEM, max_tokens=2048,
        )
        parsed = _parse_gruppe_titled(raw, N_CLUSTERS)
        llm_calls += 1
        total_in  += in_tok
        total_out += out_tok

        new_summaries = [
            f"{title}. {body}" if body else title
            for title, body in parsed
        ]
        new_label_embs = embed_texts(bge, new_summaries, max_length=512)

        if prev_label_embs is not None:
            stabs           = np.array([float(prev_label_embs[i] @ new_label_embs[i])
                                        for i in range(N_CLUSTERS)])
            label_stability: float | None = float(stabs.mean())
        else:
            stabs           = np.ones(N_CLUSTERS)
            label_stability = None

        prev_label_embs = new_label_embs
        label_embs      = new_label_embs
        prev_descs      = [body if body else title for title, body in parsed]
        summaries       = new_summaries

        new_labels  = (seg_embs @ label_embs.T).argmax(axis=1)
        changed     = int((new_labels != labels).sum())
        change_pct  = changed / n
        labels      = new_labels

        dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))

        # ── Inline output ─────────────────────────────────────────────────────
        W = 72
        print(f"\n{'═'*W}", flush=True)
        print(f"  ═══ S6-tfidf-anchor | Iteration {km_iter} ═══", flush=True)
        stab_part = f"  Label-Stab. Ø: {label_stability:.4f}  |  " if label_stability is not None else "  "
        print(f"  Wechsel: {change_pct*100:.1f}%  |{stab_part}{dist_str}", flush=True)
        print(f"{'═'*W}", flush=True)

        for cid, (title, body) in enumerate(parsed):
            sim_tag = (
                f"  [Sim zu Iter {prev_llm_iter}: {stabs[cid]:.4f}]"
                if prev_llm_iter is not None and label_stability is not None
                else ""
            )
            print(f"\nC{cid+1}: {title}{sim_tag}", flush=True)
            print(f'  "{body}"', flush=True)

        logs.append({
            "km_iter":          km_iter,
            "summaries":        new_summaries[:],
            "parsed":           parsed[:],
            "label_stability":  label_stability,
            "stabs_per_cid":    stabs.tolist(),
            "change_pct":       change_pct,
            "dist_str":         dist_str,
        })
        prev_llm_iter = km_iter

    model       = anthropic_provider.model
    p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
    cost_usd    = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000

    print(f"\n  Tokens: {total_in:,} input + {total_out:,} output", flush=True)
    print(f"  Kosten: ${cost_usd:.4f}  ({llm_calls} Calls, {model})", flush=True)

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"S6-tfidf-anchor ({llm_calls} Calls, ${cost_usd:.4f})",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]        = time.perf_counter() - t0
    res["llm_calls"]      = llm_calls
    res["summaries"]      = summaries
    res["iteration_logs"] = logs
    res["in_tokens"]      = total_in
    res["out_tokens"]     = total_out
    res["cost_usd"]       = cost_usd
    return res


def run_s6_anthropic(
    anthropic_provider,
    bge,
    seg_embs: np.ndarray, texts: list[str],
    km_interval: int = 5,
    max_km_iter: int = 20,
    change_thr: float = 0.02,
    stability_thr: float = 0.97,
) -> dict:
    """S6-anthropic — spaced k-LLMmeans mit einem kombinierten Anthropic-Call pro LLM-Schritt.

    Pro LLM-Schritt: alle N_CLUSTERS Cluster in einem einzigen Prompt → kontrastive Labels.
    Temperature=0, Token-Tracking, Kostenabschätzung.
    """
    t0 = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    label_embs      = compute_centroids(seg_embs, labels)
    prev_label_embs: np.ndarray | None = None
    summaries       = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    llm_calls       = 0
    total_in        = 0
    total_out       = 0
    label_stability: float | None = None
    converged_at    = max_km_iter

    print(f"\n  {'Iter':>4}  {'Wechsel%':>9}  {'Stab. Ø':>9}  {'LLM':>4}  "
          f"{'Tok-In':>8}  {'Tok-Out':>8}  Verteilung")
    print(f"  {'─'*4}  {'─'*9}  {'─'*9}  {'─'*4}  {'─'*8}  {'─'*8}  {'─'*42}")

    for km_iter in range(1, max_km_iter + 1):
        llm_this_iter = (km_iter % km_interval == 0)

        # ── Kombinierter Anthropic-Call ────────────────────────────────────────
        if llm_this_iter:
            centroids = compute_centroids(seg_embs, labels)
            kw_map    = tfidf_cluster_keywords(texts, labels)

            groups: list[str] = []
            for cid in range(N_CLUSTERS):
                idx = np.where(labels == cid)[0]
                if len(idx) == 0:
                    groups.append(f"--- GRUPPE {cid+1} ---\n(Leer)")
                    continue
                dists = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
                top10 = idx[dists.argsort()[:10]]
                kws   = ", ".join(kw_map.get(cid, []))
                snips = "\n\n".join(f"[{i+1}] {texts[j][:300]}"
                                    for i, j in enumerate(top10))
                block = f"--- GRUPPE {cid+1} ---"
                if kws:
                    block += f"\nHäufige Begriffe: {kws}"
                block += f"\n\n{snips}"
                groups.append(block)

            prompt = _S6_ANTHROPIC_PROMPT.format(
                n=N_CLUSTERS,
                groups="\n\n".join(groups) + "\n\n",
            )
            raw, in_tok, out_tok = _anthropic_t0(
                anthropic_provider, prompt, _S6_ANTHROPIC_SYSTEM, max_tokens=2048,
            )
            new_summaries = _parse_gruppe_summaries(raw, N_CLUSTERS)
            llm_calls += 1
            total_in  += in_tok
            total_out += out_tok

            new_label_embs = embed_texts(bge, new_summaries, max_length=512)

            if prev_label_embs is not None:
                stabs = np.array([float(prev_label_embs[i] @ new_label_embs[i])
                                  for i in range(N_CLUSTERS)])
                label_stability = float(stabs.mean())

            prev_label_embs = new_label_embs
            label_embs      = new_label_embs
            summaries       = new_summaries

        # ── KMeans-Schritt ────────────────────────────────────────────────────
        new_labels = (seg_embs @ label_embs.T).argmax(axis=1)
        changed    = int((new_labels != labels).sum())
        change_pct = changed / n
        labels     = new_labels

        dist_str  = "  ".join(f"C{i+1}={int((labels==i).sum())}"
                               for i in range(N_CLUSTERS))
        llm_mark  = "LLM" if llm_this_iter else ""
        stab_str  = f"{label_stability:.4f}" if (llm_this_iter and label_stability is not None) \
                    else "        —"
        tok_in_s  = f"{in_tok:,}"  if llm_this_iter else ""
        tok_out_s = f"{out_tok:,}" if llm_this_iter else ""
        print(f"  {km_iter:>4}  {change_pct*100:>8.1f}%  {stab_str:>9}  {llm_mark:<4}  "
              f"{tok_in_s:>8}  {tok_out_s:>8}  {dist_str}")

        if (llm_calls >= 1
                and change_pct < change_thr
                and label_stability is not None
                and label_stability > stability_thr):
            converged_at = km_iter
            print(f"\n  ✓ Konvergenz nach Iteration {km_iter}  "
                  f"({llm_calls} Calls, Wechsel={change_pct*100:.1f}%, Stab={label_stability:.4f})")
            break
    else:
        print(f"\n  ⚠ Kein Konvergenz nach {max_km_iter} Iterationen  ({llm_calls} Calls)")

    # Kosten
    model = anthropic_provider.model
    p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
    cost_usd = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000

    print(f"\n  Tokens gesamt: {total_in:,} input + {total_out:,} output")
    print(f"  Kosten (geschätzt): ${cost_usd:.4f}  (Modell: {model})")

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"S6-anthropic ({converged_at} Iter., {llm_calls} Calls, ${cost_usd:.4f})",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]    = time.perf_counter() - t0
    res["llm_calls"]  = llm_calls
    res["summaries"]  = summaries
    res["n_iter"]     = converged_at
    res["in_tokens"]  = total_in
    res["out_tokens"] = total_out
    res["cost_usd"]   = cost_usd
    return res


def print_s6_anthropic_report(
    res_anth: dict,
    res_paper: dict,
    texts: list[str],
) -> None:
    """Finale Cluster-Beschreibungen (Anthropic) + Vergleich gegen Ollama S6-paper."""
    labels    = res_anth["labels"]
    summaries = res_anth.get("summaries", [])
    deltas    = res_anth["deltas"]
    kw_map    = tfidf_cluster_keywords(texts, labels)
    n_iter    = res_anth.get("n_iter", "?")
    cost      = res_anth.get("cost_usd", 0.0)

    W = 80
    print(f"\n{'═'*W}")
    print(f"  S6-anthropic — Finale Cluster-Beschreibungen  "
          f"({n_iter} Iter., ${cost:.4f})")
    print(f"{'═'*W}")
    for cid in range(N_CLUSTERS):
        size    = int((labels == cid).sum())
        summary = summaries[cid] if cid < len(summaries) else ""
        kws     = ", ".join(kw_map.get(cid, []))
        delta   = deltas[cid] if cid < len(deltas) else 0.0
        print(f"\nC{cid+1}  ({size} Seg.)  Delta={delta:+.4f}")
        print(f"  {summary}")
        print(f"  TF-IDF: {kws}")

    # Vergleich
    print(f"\n{'─'*W}")
    print("  Vergleich: Ollama S6-paper vs. Anthropic S6")
    print(f"{'─'*W}")
    rows = [
        ("Ollama S6-paper", res_paper),
        ("Anthropic S6",    res_anth),
    ]
    print(f"  {'Variante':<22}  {'Ø Delta':>9}  {'IntraSim':>9}  "
          f"{'Calls':>6}  {'Token-In':>9}  {'Kosten':>9}  {'Laufzeit':>9}")
    print(f"  {'─'*22}  {'─'*9}  {'─'*9}  {'─'*6}  {'─'*9}  {'─'*9}  {'─'*9}")
    for name, res in rows:
        in_tok = res.get("in_tokens", 0)
        c_usd  = res.get("cost_usd", 0.0)
        c_str  = f"${c_usd:.4f}" if c_usd else "  (lokal)"
        print(f"  {name:<22}  {res['avg']:>+9.4f}  {res.get('intra_avg',0):>9.4f}  "
              f"{res['llm_calls']:>6}  {in_tok:>9,}  {c_str:>9}  {res.get('elapsed',0):>8.1f}s")


def run_s6_paper(
    provider, bge,
    seg_embs: np.ndarray, texts: list[str],
    km_interval: int = 5,
    max_km_iter: int = 20,
    change_thr: float = 0.02,
    stability_thr: float = 0.97,
) -> dict:
    """S6-paper — k-LLMmeans nach Paper-Spezifikation.

    Spaced LLM-Calls alle km_interval KMeans-Iterationen,
    dazwischen normales KMeans mit letzten LLM-Embeddings als Centroids.
    Temperature=0 (deterministisch). Konvergenz: Wechsel<2% UND Stab>0.97.
    """
    t0 = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    # Initialisierung: normalisierte Centroids als Label-Embeddings (kein LLM)
    label_embs      = compute_centroids(seg_embs, labels)
    prev_label_embs: np.ndarray | None = None
    summaries       = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    llm_calls       = 0
    label_stability: float | None = None
    converged_at    = max_km_iter

    print(f"\n  {'Iter':>4}  {'Wechsel%':>9}  {'Stab. Ø':>9}  {'LLM':>4}  Verteilung")
    print(f"  {'─'*4}  {'─'*9}  {'─'*9}  {'─'*4}  {'─'*50}")

    for km_iter in range(1, max_km_iter + 1):
        llm_this_iter = (km_iter % km_interval == 0)

        # ── LLM-Schritt (alle km_interval Iterationen) ────────────────────────
        if llm_this_iter:
            centroids      = compute_centroids(seg_embs, labels)
            new_summaries: list[str] = []
            for cid in range(N_CLUSTERS):
                idx = np.where(labels == cid)[0]
                if len(idx) == 0:
                    new_summaries.append(f"Leerer Cluster {cid+1}")
                    continue
                dists = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
                top10 = idx[dists.argsort()[:10]]
                body  = "\n\n".join(f"[{i+1}] {texts[j][:300]}"
                                    for i, j in enumerate(top10))
                result = _llm_t0(
                    provider, _S6_PAPER_PROMPT.format(texts=body), _S6_SYSTEM
                ).replace("\n", " ") or f"Cluster {cid+1}"
                new_summaries.append(result)
                llm_calls += 1

            new_label_embs = embed_texts(bge, new_summaries, max_length=512)

            # Label-Stabilität: Cosine zwischen alten und neuen Label-Embeddings
            if prev_label_embs is not None:
                stabs           = np.array([float(prev_label_embs[i] @ new_label_embs[i])
                                            for i in range(N_CLUSTERS)])
                label_stability = float(stabs.mean())
            prev_label_embs = new_label_embs
            label_embs      = new_label_embs
            summaries       = new_summaries

        # ── KMeans-Schritt (immer) ────────────────────────────────────────────
        new_labels  = (seg_embs @ label_embs.T).argmax(axis=1)
        changed     = int((new_labels != labels).sum())
        change_pct  = changed / n
        labels      = new_labels

        # Ausgabe-Zeile
        dist_str  = "  ".join(f"C{i+1}={int((labels==i).sum())}"
                               for i in range(N_CLUSTERS))
        llm_mark  = "LLM" if llm_this_iter else ""
        stab_str  = f"{label_stability:.4f}" if (llm_this_iter and label_stability is not None) else "        —"
        print(f"  {km_iter:>4}  {change_pct*100:>8.1f}%  {stab_str:>9}  {llm_mark:<4}  {dist_str}")

        # ── Konvergenzprüfung (erst nach mindestens einem LLM-Call) ──────────
        if (llm_calls >= N_CLUSTERS
                and change_pct < change_thr
                and label_stability is not None
                and label_stability > stability_thr):
            converged_at = km_iter
            print(f"\n  ✓ Konvergenz nach KMeans-Iteration {km_iter}  "
                  f"({llm_calls} LLM-Calls, Wechsel={change_pct*100:.1f}%, "
                  f"Stab={label_stability:.4f})")
            break
    else:
        print(f"\n  ⚠ Kein Konvergenz nach {max_km_iter} Iterationen  "
              f"({llm_calls} LLM-Calls)")

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"S6-paper ({converged_at} KMeans-Iter., {llm_calls} LLM-Calls gesamt)",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]    = time.perf_counter() - t0
    res["llm_calls"]  = llm_calls
    res["summaries"]  = summaries
    res["n_iter"]     = converged_at
    return res


def print_s6_paper_report(
    res_paper: dict,
    res_2iter: dict,
    res_conv:  dict,
    texts: list[str],
) -> None:
    """Finale Cluster-Tabelle (volle Beschreibungen) + Vergleich."""
    labels    = res_paper["labels"]
    summaries = res_paper.get("summaries", [])
    deltas    = res_paper["deltas"]
    kw_map    = tfidf_cluster_keywords(texts, labels)
    n_iter    = res_paper.get("n_iter", "?")

    W = 80
    print(f"\n{'═'*W}")
    print(f"  S6-paper — Finale Cluster-Beschreibungen ({n_iter} KMeans-Iter.)")
    print(f"{'═'*W}")
    for cid in range(N_CLUSTERS):
        size    = int((labels == cid).sum())
        summary = summaries[cid] if cid < len(summaries) else ""
        kws     = ", ".join(kw_map.get(cid, []))
        delta   = deltas[cid] if cid < len(deltas) else 0.0
        print(f"\nC{cid+1}  ({size} Seg.)  Delta={delta:+.4f}")
        print(f"  LLM: {summary}")
        print(f"  TF-IDF: {kws}")

    # Vergleich
    print(f"\n{'─'*W}")
    print("  Vergleich der drei k-LLMmeans-Varianten")
    print(f"{'─'*W}")
    variants = [
        ("S6  2-Iter (fix)",   res_2iter),
        ("S6-conv (max 10It)", res_conv),
        ("S6-paper (max 20It)", res_paper),
    ]
    print(f"  {'Variante':<24}  {'Ø Delta':>9}  {'IntraSim':>9}  {'LLM-Calls':>10}  {'Laufzeit':>10}")
    print(f"  {'─'*24}  {'─'*9}  {'─'*9}  {'─'*10}  {'─'*10}")
    for name, res in variants:
        print(f"  {name:<24}  {res['avg']:>+9.4f}  {res.get('intra_avg',0):>9.4f}  "
              f"{res['llm_calls']:>10}  {res.get('elapsed',0):>9.1f}s")


def run_s6_convergence(
    provider, bge,
    seg_embs: np.ndarray, texts: list[str],
    max_iter: int = 10,
    change_thr: float = 0.02,
    stability_thr: float = 0.97,
) -> dict:
    """S6-conv — k-LLMmeans mit Konvergenzkriterium statt fixer Iterationszahl."""
    t0 = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)
    llm_calls      = 0
    label_embs_cur: np.ndarray | None = None
    summaries      = [""] * N_CLUSTERS
    converged_at   = max_iter

    for iteration in range(1, max_iter + 1):
        print(f"\n  Iteration {iteration}/{max_iter}  ({N_CLUSTERS} LLM-Calls)…", flush=True)
        centroids = compute_centroids(seg_embs, labels)

        new_summaries: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                new_summaries.append(f"Leerer Cluster {cid+1}")
                continue
            dists = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
            top10 = idx[dists.argsort()[:10]]
            body  = "\n\n".join(f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(top10))
            result = (provider.complete(_S6_PROMPT.format(texts=body), system=_S6_SYSTEM)
                      or f"Cluster {cid+1}").strip().replace("\n", " ")
            new_summaries.append(result)
            llm_calls += 1
            print(f"    C{cid+1}: {result[:75]}…", flush=True)

        new_label_embs = embed_texts(bge, new_summaries, max_length=512)
        new_labels     = (seg_embs @ new_label_embs.T).argmax(axis=1)

        # ── Metriken ──────────────────────────────────────────────────────────
        changed    = int((new_labels != labels).sum())
        change_pct = changed / n

        if label_embs_cur is not None:
            stabilities     = np.array([float(label_embs_cur[i] @ new_label_embs[i])
                                        for i in range(N_CLUSTERS)])
            label_stability = float(stabilities.mean())
        else:
            stabilities     = np.ones(N_CLUSTERS, dtype=np.float32)
            label_stability = 1.0

        # Welche Cluster verlieren am meisten Segmente?
        cluster_outflow = sorted(
            [(cid,
              int((new_labels[np.where(labels == cid)[0]] != cid).sum()),
              int((labels == cid).sum()))
             for cid in range(N_CLUSTERS)],
            key=lambda x: x[1], reverse=True,
        )

        # Ausgabe
        print(f"  Segment-Wechsel:  {change_pct*100:.1f}%  ({changed} Segmente)")
        if label_embs_cur is not None:
            stab_str = "  ".join(f"C{i+1}={s:.3f}" for i, s in enumerate(stabilities))
            print(f"  Label-Stabilität: Ø {label_stability:.4f}  [{stab_str}]")
        top3 = [(cid, out, tot) for cid, out, tot in cluster_outflow[:3] if out > 0]
        if top3:
            parts = "  ".join(f"C{cid+1}:{out}/{tot}({out/max(tot,1)*100:.0f}%)"
                              for cid, out, tot in top3)
            print(f"  Stärkste Veränderungen: {parts}")
        dist_str = "  ".join(f"C{i+1}={int((new_labels==i).sum())}"
                             for i in range(N_CLUSTERS))
        print(f"  Verteilung: {dist_str}")

        # State-Update
        labels         = new_labels
        label_embs_cur = new_label_embs
        summaries      = new_summaries

        # Konvergenzprüfung (erst ab Iteration 2, beide Kriterien)
        if iteration >= 2 and change_pct < change_thr and label_stability > stability_thr:
            converged_at = iteration
            print(f"\n  ✓ Konvergenz nach Iteration {iteration}  "
                  f"(Wechsel={change_pct*100:.1f}% < {change_thr*100:.0f}%,  "
                  f"Stabilität={label_stability:.4f} > {stability_thr:.2f})")
            break
    else:
        print(f"\n  ⚠ Kein Konvergenz nach {max_iter} Iterationen erreicht")

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    label_embs_cur = label_embs_cur if label_embs_cur is not None else np.zeros(
        (N_CLUSTERS, seg_embs.shape[1]), dtype=np.float32)
    print_delta_table(f"S6-conv ({converged_at} Iterationen)", names, label_embs_cur, centroids)
    res = eval_strategy(names, label_embs_cur, centroids, seg_embs, labels)
    res["elapsed"]    = time.perf_counter() - t0
    res["llm_calls"]  = llm_calls
    res["summaries"]  = summaries
    res["n_iter"]     = converged_at
    return res


def run_s6_ablation(
    anthropic_provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    use_rolling: bool = True,
    use_tfidf: bool = True,
    km_interval: int = 5,
    max_km_iter: int = 20,
    m: int = 10,
) -> dict:
    """Ablation von S6-tfidf-anchor: use_rolling / use_tfidf unabhängig schaltbar.

    V-A: use_rolling=True,  use_tfidf=False  — nur rollierender Kontext
    V-B: use_rolling=False, use_tfidf=True   — nur TF-IDF-Anker
    Beide: kontrastiver kombinierter Call, gleiche k-means++ Sampling-Logik.
    """
    variant = (
        "V-A rolling" if (use_rolling and not use_tfidf) else
        "V-B tfidf"   if (use_tfidf   and not use_rolling) else
        "combined"
    )
    t0  = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    rng    = np.random.default_rng(42)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    kw_map_fixed: dict[int, list[str]] = (
        tfidf_cluster_keywords(texts, labels) if use_tfidf else {}
    )
    label_embs      = compute_centroids(seg_embs, labels)
    prev_descs: list[str | None]       = [None] * N_CLUSTERS
    summaries: list[str]               = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    prev_label_embs: np.ndarray | None = None
    llm_calls   = 0
    total_in    = 0
    total_out   = 0
    logs: list[dict] = []
    prev_llm_iter: int | None = None

    for km_iter in range(1, max_km_iter + 1):
        if km_iter % km_interval != 0:
            labels = (seg_embs @ label_embs.T).argmax(axis=1)
            continue

        centroids = compute_centroids(seg_embs, labels)

        # ── Prompt-Aufbau ──────────────────────────────────────────────────────
        parts: list[str] = [
            f"Du analysierst {N_CLUSTERS} Gruppen von Texten über den Berliner Flughafen BER.\n"
        ]
        if use_tfidf:
            kw_lines = "\n".join(
                f"Gruppe {cid+1} Keywords: {', '.join(kw_map_fixed.get(cid, []))}"
                for cid in range(N_CLUSTERS)
            )
            parts.append(
                "Für jede Gruppe sind folgende Keywords konstant charakteristisch "
                "(diese sollen in deiner Beschreibung vorkommen):\n\n"
                f"{kw_lines}\n"
            )
        if use_rolling and any(d is not None for d in prev_descs):
            prev_lines = "\n".join(
                f"Gruppe {cid+1}: {prev_descs[cid]}" if prev_descs[cid]
                else f"Gruppe {cid+1}: (keine)"
                for cid in range(N_CLUSTERS)
            )
            parts.append(
                f"Vorherige Beschreibungen (Iteration {prev_llm_iter}):\n{prev_lines}\n"
            )

        seg_blocks: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                seg_blocks.append(f"--- Gruppe {cid+1} ---\n(Leer)")
                continue
            sample_idx = _kmeanspp_sample(seg_embs, idx, m, rng)
            snips = "\n\n".join(
                f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(sample_idx)
            )
            seg_blocks.append(f"--- Gruppe {cid+1} ---\n{snips}")

        parts.append("Neue Beispieltexte:\n" + "\n\n".join(seg_blocks) + "\n")
        action = "Verfeinere die" if use_rolling else "Schreibe"
        parts.append(
            f"{action} Beschreibungen. "
            "Jede Gruppe muss sich klar von den anderen unterscheiden.\n\n"
            "Antworte für jede Gruppe im Format (kein weiterer Text):\n\n"
            + "\n\n".join(
                f"## Gruppe {cid+1}: [2-4 Wörter Titel]\n[2-3 Sätze Beschreibung]"
                for cid in range(N_CLUSTERS)
            )
        )
        prompt = "\n\n".join(parts)

        raw, in_tok, out_tok = _anthropic_t0(
            anthropic_provider, prompt, _S6_TFIDF_ANCHOR_SYSTEM, max_tokens=2048,
        )
        parsed     = _parse_gruppe_titled(raw, N_CLUSTERS)
        llm_calls += 1
        total_in  += in_tok
        total_out += out_tok

        new_summaries = [
            f"{title}. {body}" if body else title
            for title, body in parsed
        ]
        new_label_embs = embed_texts(bge, new_summaries, max_length=512)

        if prev_label_embs is not None:
            stabs           = np.array([float(prev_label_embs[i] @ new_label_embs[i])
                                        for i in range(N_CLUSTERS)])
            label_stability: float | None = float(stabs.mean())
        else:
            stabs           = np.ones(N_CLUSTERS)
            label_stability = None

        prev_label_embs = new_label_embs
        label_embs      = new_label_embs
        prev_descs      = [body if body else title for title, body in parsed]
        summaries       = new_summaries

        new_labels  = (seg_embs @ label_embs.T).argmax(axis=1)
        changed     = int((new_labels != labels).sum())
        change_pct  = changed / n
        labels      = new_labels

        dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))

        W = 72
        print(f"\n{'═'*W}", flush=True)
        print(f"  ═══ {variant} | Iteration {km_iter} ═══", flush=True)
        stab_part = f"  Label-Stab. Ø: {label_stability:.4f}  |  " if label_stability is not None else "  "
        print(f"  Wechsel: {change_pct*100:.1f}%  |{stab_part}{dist_str}", flush=True)
        print(f"{'═'*W}", flush=True)
        for cid, (title, body) in enumerate(parsed):
            sim_tag = (
                f"  [Sim zu Iter {prev_llm_iter}: {stabs[cid]:.4f}]"
                if prev_llm_iter is not None and label_stability is not None
                else ""
            )
            print(f"\nC{cid+1}: {title}{sim_tag}", flush=True)
            print(f'  "{body}"', flush=True)

        logs.append({
            "km_iter":          km_iter,
            "summaries":        new_summaries[:],
            "parsed":           parsed[:],
            "label_stability":  label_stability,
            "stabs_per_cid":    stabs.tolist(),
            "change_pct":       change_pct,
            "dist_str":         dist_str,
        })
        prev_llm_iter = km_iter

    model       = anthropic_provider.model
    p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
    cost_usd    = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000

    print(f"\n  Tokens: {total_in:,} input + {total_out:,} output", flush=True)
    print(f"  Kosten: ${cost_usd:.4f}  ({llm_calls} Calls, {model})", flush=True)

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"{variant} ({llm_calls} Calls, ${cost_usd:.4f})",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]        = time.perf_counter() - t0
    res["llm_calls"]      = llm_calls
    res["summaries"]      = summaries
    res["iteration_logs"] = logs
    res["in_tokens"]      = total_in
    res["out_tokens"]     = total_out
    res["cost_usd"]       = cost_usd
    res["variant"]        = variant
    return res


def _kmeanspp_sample(
    embs: np.ndarray, idx: np.ndarray, m: int, rng: np.random.Generator
) -> np.ndarray:
    """K-means++ sampling: selects m diverse documents from cluster idx.

    Seed = point closest to cluster centroid; subsequent selections weighted
    by squared distance to the nearest already-selected point (classic k-means++).
    """
    if len(idx) <= m:
        return idx
    centroid = embs[idx].mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 1e-9:
        centroid /= norm
    dists = np.linalg.norm(embs[idx] - centroid, axis=1)
    selected = [int(dists.argmin())]
    min_sq_dists = np.full(len(idx), np.inf)
    for _ in range(m - 1):
        last_emb = embs[idx[selected[-1]]]
        d2 = np.sum((embs[idx] - last_emb) ** 2, axis=1)
        min_sq_dists = np.minimum(min_sq_dists, d2)
        min_sq_dists[np.array(selected)] = 0.0
        total = min_sq_dists.sum()
        if total <= 1e-15:
            break
        new_pos = int(rng.choice(len(idx), p=min_sq_dists / total))
        selected.append(new_pos)
    return idx[np.array(selected, dtype=int)]


def run_s6_paper_exact(
    anthropic_provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    T: int = 120,
    l: int = 20,
    m: int = 10,
) -> dict:
    """k-LLMmeans — Algorithm 1 (paper-exact).

    T=120 iterations, LLM every l=20 steps (6 rounds × 7 clusters = 42 calls).
    Sampling: k-means++ within cluster (diverse, not Top-N by distance).
    Provider: Anthropic Claude Sonnet, temperature=0.
    Prompt: single German sentence per cluster.
    """
    t0    = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    rng    = np.random.default_rng(42)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)

    label_embs = compute_centroids(seg_embs, labels)
    summaries  = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    llm_calls  = 0
    total_in   = 0
    total_out  = 0

    print(f"\n  T={T}, l={l}, m={m}, Modell={anthropic_provider.model}, T=0")
    print(f"  {'Iter':>5}  {'Wechsel%':>9}  {'LLM':>4}  Verteilung")
    print(f"  {'─'*5}  {'─'*9}  {'─'*4}  {'─'*52}")

    for t in range(1, T + 1):
        llm_this_iter = (t % l == 0)

        if llm_this_iter:
            new_summaries: list[str] = []
            round_in  = 0
            round_out = 0
            for cid in range(N_CLUSTERS):
                idx = np.where(labels == cid)[0]
                if len(idx) == 0:
                    new_summaries.append(f"Leerer Cluster {cid+1}")
                    continue
                sample_idx = _kmeanspp_sample(seg_embs, idx, m, rng)
                body = "\n\n".join(
                    f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(sample_idx)
                )
                result, in_tok, out_tok = _anthropic_t0(
                    anthropic_provider,
                    _S6_EXACT_PROMPT.format(texts=body),
                    _S6_EXACT_SYSTEM,
                    max_tokens=200,
                )
                result = result.replace("\n", " ").strip() or f"Cluster {cid+1}"
                new_summaries.append(result)
                llm_calls += 1
                round_in  += in_tok
                round_out += out_tok
                print(f"    t={t} C{cid+1}: {result[:80]}", flush=True)

            total_in  += round_in
            total_out += round_out
            label_embs = embed_texts(bge, new_summaries, max_length=512)
            summaries  = new_summaries

        new_labels = (seg_embs @ label_embs.T).argmax(axis=1)
        changed    = int((new_labels != labels).sum())
        change_pct = changed / n
        labels     = new_labels

        if t == 1 or llm_this_iter or t == T:
            dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))
            llm_mark = "LLM" if llm_this_iter else ""
            print(f"  {t:>5}  {change_pct*100:>8.1f}%  {llm_mark:<4}  {dist_str}")

    model    = anthropic_provider.model
    p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
    cost_usd = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000

    print(f"\n  Tokens: {total_in:,} input + {total_out:,} output")
    print(f"  Kosten: ${cost_usd:.4f}  (Modell: {model}, {llm_calls} Calls)")

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"S6-exact (T={T}, l={l}, m={m}, {llm_calls} Calls, ${cost_usd:.4f})",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]    = time.perf_counter() - t0
    res["llm_calls"]  = llm_calls
    res["summaries"]  = summaries
    res["in_tokens"]  = total_in
    res["out_tokens"] = total_out
    res["cost_usd"]   = cost_usd
    return res


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def print_summary_table(results: dict[str, dict]) -> None:
    SEP_W = "═" * 140
    print(f"\n{SEP_W}")
    print("  ZUSAMMENFASSUNG")
    print(SEP_W)
    print(f"  {'Strategie':<18}  {'Ø Delta':>9}  {'IntraSim':>9}  "
          f"{'Beste Cluster':<28}  {'Schlechteste Cluster':<28}  "
          f"{'Laufzeit':>9}  {'LLM':>4}  {'Kosten':>9}")
    print(f"  {'─'*18}  {'─'*9}  {'─'*9}  {'─'*28}  {'─'*28}  {'─'*9}  {'─'*4}  {'─'*9}")
    for label, res in results.items():
        avg         = res["avg"]
        intra       = res.get("intra_avg", 0.0)
        best_n, bd  = res["best"]
        worst_n, wd = res["worst"]
        elapsed     = res.get("elapsed", 0.0)
        llm         = res.get("llm_calls", 0)
        cost        = res.get("cost_usd", 0.0)
        llm_note    = f"{llm}†" if label in ("S3 Filter", "S4 Hybrid") else str(llm)
        cost_str    = f"${cost:.4f}" if cost > 0 else "lokal"
        print(f"  {label:<18}  {avg:>+9.4f}  {intra:>9.4f}  "
              f"{best_n[:24]:<24}  Δ={bd:>+.3f}  "
              f"{worst_n[:24]:<24}  Δ={wd:>+.3f}  "
              f"{elapsed:>7.1f}s  {llm_note:>4}  {cost_str:>9}")
    print(SEP_W)
    print("  † S3/S4 verwenden den LLM-Call der Baseline (kein zusätzlicher Call)")
    print(SEP_W)


def print_qualitative(
    title: str,
    names: list[str],
    descs: list[str],
    seg_embs: np.ndarray,
    texts: list[str],
    seg_ids: list[str],
    labels: np.ndarray,
) -> None:
    """Top-K Segmente pro Cluster (nach Nähe zum Centroid)."""
    centroids = compute_centroids(seg_embs, labels)
    print(f"\n{SEP2}")
    print(f"  {title} — Qualitative Inspektion  (Top-{TOP_K_SHOW} pro Cluster)")
    print(SEP2)
    for cid, name in enumerate(names):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            continue
        dists   = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
        top_idx = idx[dists.argsort()[:TOP_K_SHOW]]
        pad     = "─" * max(0, 55 - len(name))
        desc    = descs[cid] if cid < len(descs) else ""
        print(f"\n── {name}  ({len(idx)} Seg.)  {pad}")
        if desc:
            print(f"   {desc[:100]}")
        for rank, i in enumerate(top_idx, 1):
            preview = texts[i].replace("\n", " ")[:115]
            print(f"   {rank}. [{seg_ids[i]}]  \"{preview}\"")


def print_s6_final_labels(
    res_s6: dict,
    texts: list[str],
) -> None:
    """Zeigt die finalen LLM-Beschreibungen von S6 k-LLMmeans."""
    summaries = res_s6.get("summaries", [])
    labels    = res_s6["labels"]
    kw_map    = tfidf_cluster_keywords(texts, labels)

    W = 80
    print(f"\n{'═'*W}")
    print("  ═══ S6: k-LLMmeans — finale Labels ═══")
    print(f"{'═'*W}")
    for cid, summary in enumerate(summaries):
        size = int((labels == cid).sum())
        kws  = ", ".join(kw_map.get(cid, []))
        print(f"\nC{cid+1} ({size} Segmente):")
        print(f"  LLM-Text: \"{summary}\"")
        print(f"  TF-IDF Keywords: {kws}")


def print_s6_convergence_report(
    res_conv: dict,
    res_2iter: dict,
    texts: list[str],
) -> None:
    """Finale Cluster-Tabelle und Vergleich gegen 2-Iterationen-Version."""
    labels    = res_conv["labels"]
    summaries = res_conv.get("summaries", [])
    deltas    = res_conv["deltas"]
    kw_map    = tfidf_cluster_keywords(texts, labels)
    n_iter    = res_conv.get("n_iter", "?")

    W = 108
    print(f"\n{'═'*W}")
    print(f"  S6-conv — Finale Cluster-Tabelle  ({n_iter} Iterationen bis Konvergenz)")
    print(f"{'═'*W}")
    print(f"  {'C':<4}  {'LLM-Label (gekürzt)':<55}  {'TF-IDF Keywords':<35}  {'Seg.':>5}  {'Delta':>7}")
    print(f"  {'─'*4}  {'─'*55}  {'─'*35}  {'─'*5}  {'─'*7}")
    for cid in range(N_CLUSTERS):
        size    = int((labels == cid).sum())
        summary = (summaries[cid] if cid < len(summaries) else "")[:55]
        kws     = ", ".join(kw_map.get(cid, []))[:35]
        delta   = deltas[cid] if cid < len(deltas) else 0.0
        print(f"  C{cid+1:<3}  {summary:<55}  {kws:<35}  {size:>5}  {delta:>+7.4f}")

    # Vergleich gegen S6 2-Iterationen
    print(f"\n  Vergleich: 2-Iterationen (fest) vs. {n_iter} Iterationen (Konvergenz)")
    print(f"  {'Metrik':<22}  {'2-Iter':>10}  {f'Conv ({n_iter}It)':>12}  {'Diff':>10}")
    print(f"  {'─'*22}  {'─'*10}  {'─'*12}  {'─'*10}")
    for metric, key in [("Ø Delta", "avg"), ("IntraSim", "intra_avg")]:
        v2   = float(res_2iter.get(key, 0.0))
        vc   = float(res_conv.get(key, 0.0))
        diff = vc - v2
        sign = "+" if diff >= 0 else ""
        if key == "avg":
            print(f"  {metric:<22}  {v2:>+10.4f}  {vc:>+12.4f}  {sign}{diff:.4f}")
        else:
            print(f"  {metric:<22}  {v2:>10.4f}  {vc:>12.4f}  {sign}{diff:.4f}")
    llm2 = res_2iter["llm_calls"]
    llmc = res_conv["llm_calls"]
    t2   = res_2iter["elapsed"]
    tc   = res_conv["elapsed"]
    print(f"  {'LLM-Calls':<22}  {llm2:>10}  {llmc:>12}  {llmc-llm2:>+10}")
    print(f"  {'Laufzeit':<22}  {t2:>9.1f}s  {tc:>11.1f}s  {tc-t2:>+9.1f}s")


def print_detailed_cluster_report(
    title: str,
    res: dict,
    seg_embs: np.ndarray,
    texts: list[str],
    seg_ids: list[str],
    top_k: int = 5,
    bottom_k: int = 3,
) -> None:
    """Top-K und Bottom-K Segmente pro Cluster mit IntraSim und Delta."""
    labels    = res["labels"]
    centroids = res["centroids"]
    names     = res["names"]
    deltas    = res["deltas"]
    intra     = res["intra"]
    summaries = res.get("summaries", [""] * len(names))

    W = 80
    print(f"\n{'═'*W}")
    print(f"  ═══ {title} ═══")
    print(f"{'═'*W}")

    for cid, name in enumerate(names):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            print(f"\nCluster {cid+1} — \"{name}\"  (leer)")
            continue

        sims        = seg_embs[idx] @ centroids[cid]
        order_desc  = sims.argsort()[::-1]
        order_asc   = sims.argsort()
        top_indices = idx[order_desc[:top_k]]
        bot_indices = idx[order_asc[:bottom_k]]
        top_sims    = sims[order_desc[:top_k]]
        bot_sims    = sims[order_asc[:bottom_k]]

        intra_score = intra.get(cid, 0.0)
        delta_score = deltas[cid] if cid < len(deltas) else 0.0
        summary     = summaries[cid] if cid < len(summaries) else ""

        print(f"\nCluster {cid+1} — \"{name}\"  ({len(idx)} Seg.)")
        if summary:
            print(f"  Zusammenfassung: {summary[:120]}")
        print(f"  IntraSim: {intra_score:.4f}  |  Delta: {delta_score:+.4f}")

        print(f"  Top-{top_k}:")
        for rank, (i, s) in enumerate(zip(top_indices, top_sims), 1):
            preview = texts[i].replace("\n", " ")[:200]
            print(f"    [{rank}] [{seg_ids[i]}]  sim={s:.4f}  \"{preview}\"")

        print(f"  Bottom-{bottom_k}  (am wenigsten typisch):")
        for rank, (i, s) in enumerate(zip(bot_indices, bot_sims), 1):
            preview = texts[i].replace("\n", " ")[:200]
            print(f"    [{rank}] [{seg_ids[i]}]  sim={s:.4f}  \"{preview}\"")


def print_s2_s6_comparison(
    res_s2: dict,
    res_s6: dict,
    seg_ids: list[str],
    texts: list[str],
) -> None:
    """Vergleicht Cluster-Zuordnungen zwischen S2 und S6."""
    labels_s2   = res_s2["labels"]
    labels_s6   = res_s6["labels"]
    names_s2    = res_s2["names"]
    summaries_s6 = res_s6.get("summaries", [""] * N_CLUSTERS)
    n           = len(labels_s2)

    # Cross-tabulation (S2-Zeile, S6-Spalte)
    matrix = np.zeros((N_CLUSTERS, N_CLUSTERS), dtype=int)
    for s2c, s6c in zip(labels_s2, labels_s6):
        matrix[s2c, s6c] += 1

    same_id = int(np.diag(matrix).sum())
    # Beste 1-zu-1-Zuordnung S2→S6 (dominant = der S6-Cluster mit den meisten Segmenten aus S2i)
    dominant         = matrix.argmax(axis=1)
    best_match_count = sum(int(matrix[i, dominant[i]]) for i in range(N_CLUSTERS))
    moved            = n - best_match_count

    W = 80
    print(f"\n{'═'*W}")
    print("  S2 vs S6 — Cluster-Vergleich")
    print(f"{'═'*W}")
    print(f"  Gesamt: {n} Segmente")
    print(f"  Gleiche Cluster-ID:           {same_id:4d}  ({same_id/n*100:.1f}%)")
    print(f"  Bestes Matching (1:1 dominant): {best_match_count:4d}  ({best_match_count/n*100:.1f}%)")
    print(f"  Cluster gewechselt:             {moved:4d}  ({moved/n*100:.1f}%)")

    # Cluster-Größen nebeneinander
    print(f"\n  {'C':<5}  {'S2 Keywords':<36}  {'S2-Gr.':>6}  "
          f"{'S6 Zusammenfassung':<40}  {'S6-Gr.':>6}")
    print(f"  {'─'*5}  {'─'*36}  {'─'*6}  {'─'*40}  {'─'*6}")
    for cid in range(N_CLUSTERS):
        s2_size = int((labels_s2 == cid).sum())
        s6_size = int((labels_s6 == cid).sum())
        s2_name = names_s2[cid][:36]
        s6_sum  = (summaries_s6[cid] if cid < len(summaries_s6) else "")[:40]
        print(f"  C{cid+1:<4}  {s2_name:<36}  {s2_size:>6}  {s6_sum:<40}  {s6_size:>6}")

    # Wechsel-Matrix
    print(f"\n  Wechsel-Matrix  (Zeilen=S2-Cluster, Spalten=S6-Cluster, [x]=diagonal):")
    row_label = "S2\\S6"
    header = f"  {row_label:>6}" + "".join(f"  {'C'+str(j+1):>5}" for j in range(N_CLUSTERS))
    print(header)
    print(f"  {'─'*6}" + "  ─────" * N_CLUSTERS)
    for i in range(N_CLUSTERS):
        row = f"  {'C'+str(i+1):>6}"
        for j in range(N_CLUSTERS):
            count = int(matrix[i, j])
            if i == j:
                row += f"  [{count:3}]"
            elif count > 0:
                row += f"  {count:>5}"
            else:
                row += f"  {'·':>5}"
        print(row)

    # Dominante Zuordnung + Wechsler-Zusammenfassung
    print(f"\n  Dominante Zuordnung S2-Cluster → S6-Cluster:")
    for i in range(N_CLUSTERS):
        j        = int(dominant[i])
        count    = int(matrix[i, j])
        s2_total = int((labels_s2 == i).sum())
        wechsler = s2_total - count
        s2_name  = names_s2[i][:30]
        s6_sum   = (summaries_s6[j] if j < len(summaries_s6) else f"C{j+1}")[:60]
        print(f"    S2-C{i+1} \"{s2_name}\"  →  S6-C{j+1}:  {count}/{s2_total} gleich,  {wechsler} gewechselt")
        print(f"          S6: \"{s6_sum}\"")

    # Beispiel-Wechsler (Segmente deren S6-Cluster vom dominanten S2→S6 abweicht)
    expected_s6 = np.array([dominant[labels_s2[k]] for k in range(n)])
    moved_mask  = labels_s6 != expected_s6
    moved_indices = np.where(moved_mask)[0]

    if len(moved_indices) > 0:
        rng    = np.random.default_rng(42)
        sample = rng.choice(moved_indices, size=min(5, len(moved_indices)), replace=False)
        sample.sort()
        print(f"\n  Beispiel-Wechsler  ({len(moved_indices)} insgesamt, zeige max. 5):")
        for k in sample:
            preview = texts[k].replace("\n", " ")[:120]
            print(f"    [{seg_ids[k]}]  S2:C{labels_s2[k]+1} → S6:C{labels_s6[k]+1}")
            print(f"               \"{preview}\"")


def run_s6_momentum(
    anthropic_provider,
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    alpha: float = 0.7,
    km_interval: int = 5,
    max_km_iter: int = 20,
) -> dict:
    """S6-momentum — k-LLMmeans mit Exponential-Moving-Average auf Label-Embeddings.

    Nach jedem LLM-Call:
        label_embs ← normalize(α · prev_label_embs + (1-α) · llm_embs)

    Kontrastiver kombinierter Call wie S6-anth (alle Cluster in einem Prompt).
    Temperature=0. Iteration-by-Iteration output inkl. voller LLM-Texte.
    """
    t0    = time.perf_counter()
    from sklearn.cluster import KMeans

    n      = len(texts)
    labels = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto").fit_predict(seg_embs)
    label_embs      = compute_centroids(seg_embs, labels)
    prev_label_embs: np.ndarray | None = None
    summaries        = [f"Cluster {i+1}" for i in range(N_CLUSTERS)]
    llm_calls        = 0
    total_in         = 0
    total_out        = 0
    iteration_logs: list[dict] = []
    prev_llm_iter: int | None  = None

    for km_iter in range(1, max_km_iter + 1):
        if km_iter % km_interval != 0:
            new_labels = (seg_embs @ label_embs.T).argmax(axis=1)
            labels     = new_labels
            continue

        # ── Kombinierter Anthropic-Call ────────────────────────────────────────
        centroids = compute_centroids(seg_embs, labels)
        kw_map    = tfidf_cluster_keywords(texts, labels)

        groups: list[str] = []
        for cid in range(N_CLUSTERS):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                groups.append(f"--- GRUPPE {cid+1} ---\n(Leer)")
                continue
            dists = np.linalg.norm(seg_embs[idx] - centroids[cid], axis=1)
            top10 = idx[dists.argsort()[:10]]
            kws   = ", ".join(kw_map.get(cid, []))
            snips = "\n\n".join(f"[{i+1}] {texts[j][:300]}" for i, j in enumerate(top10))
            block = f"--- GRUPPE {cid+1} ---"
            if kws:
                block += f"\nHäufige Begriffe: {kws}"
            block += f"\n\n{snips}"
            groups.append(block)

        prompt = _S6_ANTHROPIC_PROMPT.format(
            n=N_CLUSTERS,
            groups="\n\n".join(groups) + "\n\n",
        )
        raw, in_tok, out_tok = _anthropic_t0(
            anthropic_provider, prompt, _S6_ANTHROPIC_SYSTEM, max_tokens=2048
        )
        new_summaries = _parse_gruppe_summaries(raw, N_CLUSTERS)
        llm_calls += 1
        total_in  += in_tok
        total_out += out_tok

        new_llm_embs = embed_texts(bge, new_summaries, max_length=512)

        # ── Momentum-Update ────────────────────────────────────────────────────
        if prev_label_embs is not None:
            momentum_raw   = alpha * prev_label_embs + (1.0 - alpha) * new_llm_embs
            norms          = np.linalg.norm(momentum_raw, axis=1, keepdims=True)
            new_label_embs = momentum_raw / np.maximum(norms, 1e-9)
            stabs          = np.array([float(prev_label_embs[i] @ new_label_embs[i])
                                       for i in range(N_CLUSTERS)])
            label_stability: float | None = float(stabs.mean())
        else:
            new_label_embs  = new_llm_embs
            stabs           = np.ones(N_CLUSTERS)
            label_stability = None

        prev_label_embs = new_label_embs
        label_embs      = new_label_embs
        summaries       = new_summaries

        new_labels  = (seg_embs @ label_embs.T).argmax(axis=1)
        changed     = int((new_labels != labels).sum())
        change_pct  = changed / n
        labels      = new_labels

        dist_str = "  ".join(f"C{i+1}={int((labels==i).sum())}" for i in range(N_CLUSTERS))

        # ── Formatierter Iterations-Output ─────────────────────────────────────
        W = 72
        print(f"\n{'═'*W}", flush=True)
        print(f"  ═══ α={alpha} | Iteration {km_iter} ═══", flush=True)
        stab_part = f"  Label-Stab. Ø: {label_stability:.4f}  |  " if label_stability is not None else "  "
        print(f"  Wechsel: {change_pct*100:.1f}%  |{stab_part}{dist_str}", flush=True)
        print(f"{'═'*W}", flush=True)

        for cid in range(N_CLUSTERS):
            summary = new_summaries[cid] if cid < len(new_summaries) else ""
            if prev_llm_iter is not None and label_stability is not None:
                sim_tag = f"  [Sim zu Iter {prev_llm_iter}: {stabs[cid]:.4f}]"
            else:
                sim_tag = ""
            print(f"\nC{cid+1}:{sim_tag}", flush=True)
            print(f'  "{summary}"', flush=True)

        iteration_logs.append({
            "km_iter":          km_iter,
            "summaries":        new_summaries[:],
            "label_stability":  label_stability,
            "stabs_per_cid":    stabs.tolist(),
            "change_pct":       change_pct,
            "dist_str":         dist_str,
        })
        prev_llm_iter = km_iter

    model       = anthropic_provider.model
    p_in, p_out = _ANTHROPIC_PRICES.get(model, (3.00, 15.00))
    cost_usd    = total_in * p_in / 1_000_000 + total_out * p_out / 1_000_000

    print(f"\n  Tokens: {total_in:,} input + {total_out:,} output", flush=True)
    print(f"  Kosten: ${cost_usd:.4f}  ({llm_calls} kombinierte Calls, {model})", flush=True)

    names     = [f"C{i+1}" for i in range(N_CLUSTERS)]
    centroids = compute_centroids(seg_embs, labels)
    print_delta_table(
        f"S6-momentum α={alpha} ({llm_calls} Calls, ${cost_usd:.4f})",
        names, label_embs, centroids,
    )
    res = eval_strategy(names, label_embs, centroids, seg_embs, labels)
    res["elapsed"]        = time.perf_counter() - t0
    res["llm_calls"]      = llm_calls
    res["summaries"]      = summaries
    res["iteration_logs"] = iteration_logs
    res["in_tokens"]      = total_in
    res["out_tokens"]     = total_out
    res["cost_usd"]       = cost_usd
    res["alpha"]          = alpha
    return res


def print_s6_momentum_summary(results_by_alpha: dict) -> None:
    """Abschließende Zusammenfassung aller α-Varianten: Drift, Konvergenz, Delta."""
    W = 80
    print(f"\n{'═'*W}")
    print("  S6-momentum — Zusammenfassung (alle α-Varianten)")
    print(f"{'═'*W}")

    # Metriken-Tabelle
    print(f"\n  {'α':>5}  {'Ø Delta':>9}  {'IntraSim':>9}  {'Calls':>6}  {'Kosten':>9}  {'Laufzeit':>8}")
    print(f"  {'─'*5}  {'─'*9}  {'─'*9}  {'─'*6}  {'─'*9}  {'─'*8}")
    for alpha, res in results_by_alpha.items():
        cost = res.get("cost_usd", 0.0)
        print(f"  {alpha:>5}  {res['avg']:>+9.4f}  {res.get('intra_avg', 0):>9.4f}  "
              f"{res['llm_calls']:>6}  ${cost:.4f}  {res.get('elapsed', 0):>7.1f}s")

    # Label-Drift-Tabelle
    all_logs = {alpha: res.get("iteration_logs", []) for alpha, res in results_by_alpha.items()}
    max_llm  = max((len(lg) for lg in all_logs.values()), default=0)
    if max_llm > 0:
        print(f"\n  Label-Drift (Sim Ø zwischen aufeinanderfolgenden Momentum-Embeddings):")
        iters = [lg["km_iter"] for lg in next(iter(all_logs.values()))]
        hdr   = f"  {'α':>5}  " + "  ".join(f"It{it:>2}" for it in iters[:max_llm])
        print(hdr)
        print(f"  {'─'*5}  " + "  ─────" * max_llm)
        for alpha, logs in all_logs.items():
            cells = []
            for log in logs[:max_llm]:
                s = log["label_stability"]
                cells.append(f"{s:.4f}" if s is not None else "    —")
            print(f"  {alpha:>5}  " + "  ".join(cells))

    # Konvergenz
    print(f"\n  Konvergenz (Wechsel% < 2%):")
    for alpha, logs in all_logs.items():
        converged = [lg for lg in logs if lg["change_pct"] < 0.02]
        if converged:
            lg = converged[0]
            print(f"    α={alpha}: konvergiert bei KMeans-Iter {lg['km_iter']} "
                  f"({lg['change_pct']*100:.1f}%)")
        else:
            last = logs[-1]["change_pct"] if logs else float("nan")
            print(f"    α={alpha}: NICHT konvergiert  (letzter Wechsel={last*100:.1f}%)")

    # Inhaltlicher Drift
    print(f"\n  Inhaltlicher Label-Drift:")
    for alpha, res in results_by_alpha.items():
        logs  = res.get("iteration_logs", [])
        stabs = [lg["label_stability"] for lg in logs if lg["label_stability"] is not None]
        if stabs:
            print(f"    α={alpha}: Stab. Ø={sum(stabs)/len(stabs):.4f}  "
                  f"min={min(stabs):.4f}  max={max(stabs):.4f}  "
                  f"→ {'stabil' if min(stabs) > 0.90 else 'driftet'}")
        else:
            print(f"    α={alpha}: (keine Vergleichswerte)")


def print_s6_exact_report(res_exact: dict, texts: list[str]) -> None:
    """Finale Cluster-Labels (S6-exact, Algorithm 1) + Metriken."""
    labels    = res_exact["labels"]
    summaries = res_exact.get("summaries", [])
    deltas    = res_exact["deltas"]
    kw_map    = tfidf_cluster_keywords(texts, labels)
    cost      = res_exact.get("cost_usd", 0.0)
    n_calls   = res_exact.get("llm_calls", 0)
    in_tok    = res_exact.get("in_tokens", 0)
    out_tok   = res_exact.get("out_tokens", 0)
    elapsed   = res_exact.get("elapsed", 0.0)

    W = 80
    print(f"\n{'═'*W}")
    print(f"  S6-exact (Algorithm 1) — Finale Labels")
    print(f"  {n_calls} LLM-Calls  |  {in_tok:,} input + {out_tok:,} output Tokens  "
          f"|  ${cost:.4f}  |  {elapsed:.1f}s")
    print(f"{'═'*W}")
    for cid in range(N_CLUSTERS):
        size    = int((labels == cid).sum())
        summary = summaries[cid] if cid < len(summaries) else ""
        kws     = ", ".join(kw_map.get(cid, []))
        delta   = deltas[cid] if cid < len(deltas) else 0.0
        print(f"\nC{cid+1}  ({size} Seg.)  Delta={delta:+.4f}  IntraSim={res_exact['intra'].get(cid, 0.0):.4f}")
        print(f"  Label:  \"{summary}\"")
        print(f"  TF-IDF: {kws}")

    print(f"\n{'─'*W}")
    print(f"  Ø Delta={res_exact['avg']:+.4f}  |  Ø IntraSim={res_exact.get('intra_avg', 0.0):.4f}")


def print_ablation_comparison(
    res_anchor: dict,
    res_rolling: dict,
    res_tfidf: dict,
) -> None:
    """Vergleich: S6-tfidf-anchor vs. V-A (rolling only) vs. V-B (tfidf only)."""
    W = 80
    print(f"\n{'═'*W}")
    print("  Ablation — Beitrag der Komponenten")
    print(f"{'═'*W}")
    print(f"\n  {'Variante':<22}  {'Ø Delta':>9}  {'IntraSim':>9}  "
          f"{'Stab. Iter4':>11}  {'letzter Wechsel%':>16}  {'Kosten':>9}")
    print(f"  {'─'*22}  {'─'*9}  {'─'*9}  {'─'*11}  {'─'*16}  {'─'*9}")

    for name, res in [
        ("S6-tfidf-anchor", res_anchor),
        ("V-A rolling only", res_rolling),
        ("V-B tfidf only",   res_tfidf),
    ]:
        logs      = res.get("iteration_logs", [])
        last_log  = logs[-1] if logs else {}
        last_stab = last_log.get("label_stability")
        last_chg  = last_log.get("change_pct", float("nan"))
        s_str     = f"{last_stab:.4f}" if last_stab is not None else "    —"
        cost      = res.get("cost_usd", 0.0)
        print(f"  {name:<22}  {res['avg']:>+9.4f}  {res.get('intra_avg', 0):>9.4f}  "
              f"{s_str:>11}  {last_chg*100:>15.1f}%  ${cost:.4f}")

    # Additive decomposition relative to S6-anth baseline (+0.1181)
    base  = 0.1181
    delta_a = res_rolling["avg"]
    delta_b = res_tfidf["avg"]
    delta_c = res_anchor["avg"]
    print(f"\n  Beitrag relativ zu S6-anth (Baseline +{base:.4f}):")
    print(f"    V-A rolling allein:  {delta_a - base:>+.4f}  (→ {delta_a:>+.4f} gesamt)")
    print(f"    V-B tfidf allein:    {delta_b - base:>+.4f}  (→ {delta_b:>+.4f} gesamt)")
    print(f"    Kombination:         {delta_c - base:>+.4f}  (→ {delta_c:>+.4f} gesamt)")
    synergy = delta_c - delta_a - delta_b + base
    print(f"    Synergieeffekt:      {synergy:>+.4f}  "
          f"({'superadditiv' if synergy > 0 else 'subadditiv'})")


def print_s6_anchor_report(res_anchor: dict, texts: list[str]) -> None:
    """Finale Labels (S6-tfidf-anchor) + Vergleichstabelle."""
    labels   = res_anchor["labels"]
    logs     = res_anchor.get("iteration_logs", [])
    kw_map   = tfidf_cluster_keywords(texts, labels)
    cost     = res_anchor.get("cost_usd", 0.0)
    deltas   = res_anchor["deltas"]
    intra    = res_anchor["intra"]

    W = 80
    print(f"\n{'═'*W}")
    print(f"  S6-tfidf-anchor — Finale Labels  "
          f"({res_anchor['llm_calls']} Calls, ${cost:.4f})")
    print(f"{'═'*W}")

    final_log = logs[-1] if logs else None
    for cid in range(N_CLUSTERS):
        size  = int((labels == cid).sum())
        delta = deltas[cid] if cid < len(deltas) else 0.0
        isc   = intra.get(cid, 0.0)
        if final_log and cid < len(final_log.get("parsed", [])):
            title, body = final_log["parsed"][cid]
        else:
            title, body = f"C{cid+1}", ""
        kws = ", ".join(kw_map.get(cid, []))
        print(f"\nC{cid+1}: {title}  ({size} Seg.)  Delta={delta:+.4f}  IntraSim={isc:.4f}")
        print(f'  "{body}"')
        print(f"  TF-IDF: {kws}")

    # Stability per iteration
    print(f"\n{'─'*W}")
    print("  Label-Stabilität per Iteration:")
    for log in logs:
        stab   = log["label_stability"]
        chg    = log["change_pct"]
        s_str  = f"{stab:.4f}" if stab is not None else "    —"
        print(f"    Iter {log['km_iter']:>2}: Stab={s_str}  Wechsel={chg*100:.1f}%  {log['dist_str']}")

    # Comparison table
    print(f"\n{'─'*W}")
    print("  Vergleich:")
    print(f"  {'Variante':<20}  {'Ø Delta':>9}  {'IntraSim':>9}  "
          f"{'Stab. Iter4':>11}  {'letzter Wechsel%':>16}")
    print(f"  {'─'*20}  {'─'*9}  {'─'*9}  {'─'*11}  {'─'*16}")
    reference = [
        ("S6-anth",        +0.1181, 0.5000, 0.81,   33.0),
        ("α=0.7 Momentum", +0.1134, 0.5063, 0.9886,  7.4),
    ]
    for name, avg, isc, stab, chg in reference:
        print(f"  {name:<20}  {avg:>+9.4f}  {isc:>9.4f}  {stab:>11.4f}  {chg:>15.1f}%")
    last_log  = logs[-1] if logs else {}
    last_stab = last_log.get("label_stability")
    last_chg  = last_log.get("change_pct", float("nan"))
    s_str     = f"{last_stab:.4f}" if last_stab is not None else "    —"
    print(f"  {'S6-tfidf-anchor':<20}  {res_anchor['avg']:>+9.4f}  "
          f"{res_anchor.get('intra_avg',0):>9.4f}  {s_str:>11}  "
          f"{last_chg*100:>15.1f}%")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_ANALYZE)
    t_total  = time.perf_counter()

    # ── 1. Embeddings ──────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SETUP — BGE-M3 Embeddings + KMeans")
    print(SEP2)

    texts, seg_ids = load_segments()
    print(f"Segmente: {len(texts)}  (sortiert, ≤{SEG_CHARS} Zeichen)")

    from FlagEmbedding import BGEM3FlagModel
    t_load = time.perf_counter()
    bge    = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    print(f"Modell geladen  [{time.perf_counter()-t_load:.1f}s]")

    if CACHE_PATH.exists():
        embs = np.load(str(CACHE_PATH))
        if embs.shape[0] == len(texts):
            print(f"Cache: {CACHE_PATH}  {embs.shape}")
        else:
            print("Cache-Größe stimmt nicht — neu berechnen…")
            embs = compute_embeddings(bge, texts)
            np.save(str(CACHE_PATH), embs)
    else:
        embs = compute_embeddings(bge, texts)
        np.save(str(CACHE_PATH), embs)

    # ── 2. Nachbar-Aggregation ─────────────────────────────────────────────────
    embs, n_enriched = neighbor_aggregate(embs, texts)
    print(f"Nachbar-Aggregation: {n_enriched}/{len(texts)} Segmente angereichert "
          f"({n_enriched/len(texts)*100:.1f}%)")

    # ── 3. KMeans ─────────────────────────────────────────────────────────────
    print(f"\nKMeans  n={N_CLUSTERS}, seed=42…", flush=True)
    labels, _km_centers = run_kmeans(embs)
    for cid in range(N_CLUSTERS):
        print(f"  C{cid+1}: {int((labels==cid).sum())} Segmente")
    centroids = compute_centroids(embs, labels)

    # ── 4. Strategien ──────────────────────────────────────────────────────────
    results: dict[str, dict] = {}

    print(f"\n{SEP2}")
    print("  Baseline")
    print(SEP2)
    baseline_res, label_pairs, kw_map = run_baseline(
        provider, bge, embs, texts, labels, centroids)
    results["Baseline"] = baseline_res

    print(f"\n{SEP2}")
    print("  S1 — Medoid")
    print(SEP2)
    results["S1 Medoid"] = run_s1_medoid(embs, texts, seg_ids, labels)

    print(f"\n{SEP2}")
    print("  S2 — TF-IDF direkt")
    print(SEP2)
    results["S2 TF-IDF"] = run_s2_tfidf(bge, embs, texts, labels)

    print(f"\n{SEP2}")
    print("  S3 — Stopwort-Filter  (reuses Baseline LLM output)")
    print(SEP2)
    results["S3 Filter"] = run_s3_filter(bge, embs, labels, label_pairs, kw_map)

    print(f"\n{SEP2}")
    print("  S4 — Hybrid  (reuses Baseline LLM output)")
    print(SEP2)
    results["S4 Hybrid"] = run_s4_hybrid(bge, embs, labels, label_pairs, kw_map)

    print(f"\n{SEP2}")
    print("  S5 — BGE-M3 mit Instruktion")
    print(SEP2)
    results["S5 Instr."] = run_s5_instruction(
        bge, embs, texts, labels, label_pairs, kw_map)

    # Anthropic-Provider für alle S6-Varianten (T=0, schnell, kein Ollama-Hang)
    from src.generalized.llm import AnthropicProvider
    try:
        s6_provider = AnthropicProvider(model="claude-haiku-4-5-20251001")
        print(f"  S6-Provider: Anthropic ({s6_provider.model})", flush=True)
    except Exception as e:
        print(f"  S6-Provider: Ollama (Anthropic nicht verfügbar: {e})", flush=True)
        s6_provider = provider

    print(f"\n{SEP2}")
    print("  S6 — k-LLMmeans  (2 Iterationen, Anthropic)")
    print(SEP2)
    results["S6 k-LLM"] = run_s6_kllmmeans(s6_provider, bge, embs, texts)

    print(f"\n{SEP2}")
    print("  S6-conv — k-LLMmeans mit Konvergenz  (max. 10 Iter., Anthropic)")
    print(SEP2)
    res_s6_conv = run_s6_convergence(s6_provider, bge, embs, texts)

    print(f"\n{SEP2}")
    print("  S6-paper — k-LLMmeans Paper-Spezifikation  "
          "(spaced, max. 20 Iter., T=0, Anthropic)")
    print(SEP2)
    res_s6_paper = run_s6_paper(s6_provider, bge, embs, texts)

    print(f"\n{SEP2}")
    print("  S6-anth — k-LLMmeans kombinierter Call  "
          "(1 Call/Schritt, max. 20 Iter., T=0, Anthropic)")
    print(SEP2)
    try:
        res_s6_anth = run_s6_anthropic(s6_provider, bge, embs, texts)
        results["S6-anth"] = res_s6_anth
        _has_anthropic = True
    except Exception as e:
        print(f"  [S6-anth übersprungen: {e}]")
        res_s6_anth = None
        _has_anthropic = False

    print(f"\n{SEP2}")
    print("  S6-momentum — exponential label smoothing  (α ∈ {0.5, 0.7, 0.9})")
    print(SEP2)
    s6_momentum_results: dict = {}
    for _alpha in [0.5, 0.7, 0.9]:
        print(f"\n  ── α={_alpha} ─────────────────────────────────────────────")
        s6_momentum_results[_alpha] = run_s6_momentum(
            s6_provider, bge, embs, texts, alpha=_alpha,
        )
    print_s6_momentum_summary(s6_momentum_results)

    print(f"\n{SEP2}")
    print("  S6-tfidf-anchor — rolling context + feste TF-IDF-Anker  (4 Iter., Haiku)")
    print(SEP2)
    try:
        res_s6_anchor = run_s6_tfidf_anchor(s6_provider, bge, embs, texts)
        results["S6-anchor"] = res_s6_anchor
        _has_anchor = True
    except Exception as e:
        print(f"  [S6-tfidf-anchor übersprungen: {e}]")
        res_s6_anchor = None
        _has_anchor = False

    print(f"\n{SEP2}")
    print("  S6-exact — k-LLMmeans Algorithm 1  "
          "(T=120, l=20, k-means++ sampling, Sonnet T=0)")
    print(SEP2)
    try:
        s6_sonnet = AnthropicProvider(model="claude-sonnet-4-6")
        print(f"  Provider: Anthropic ({s6_sonnet.model})", flush=True)
        res_s6_exact = run_s6_paper_exact(s6_sonnet, bge, embs, texts)
        results["S6-exact"] = res_s6_exact
        _has_exact = True
    except Exception as e:
        print(f"  [S6-exact übersprungen: {e}]")
        res_s6_exact = None
        _has_exact = False

    print(f"\n{SEP2}")
    print("  Ablation: V-A (rolling only) + V-B (tfidf only)  (4 Iter., Haiku)")
    print(SEP2)
    res_va: dict | None = None
    res_vb: dict | None = None
    _has_ablation = False
    try:
        print("  V-A: rollierender Kontext, kein TF-IDF-Anker", flush=True)
        res_va = run_s6_ablation(s6_provider, bge, embs, texts, use_rolling=True, use_tfidf=False)
        print("  V-B: TF-IDF-Anker, kein rollierender Kontext", flush=True)
        res_vb = run_s6_ablation(s6_provider, bge, embs, texts, use_rolling=False, use_tfidf=True)
        _has_ablation = True
    except Exception as e:
        print(f"  [Ablation übersprungen: {e}]")

    # ── 5. Zusammenfassung ─────────────────────────────────────────────────────
    print_summary_table(results)

    # ── 6. S6 finale Labels ───────────────────────────────────────────────────
    print_s6_final_labels(results["S6 k-LLM"], texts)

    # ── 7. Qualitative Inspektion (Baseline) ───────────────────────────────────
    baseline_names = [name for name, _ in label_pairs]
    baseline_descs = [desc for _, desc in label_pairs]
    print_qualitative(
        "Baseline", baseline_names, baseline_descs,
        embs, texts, seg_ids, labels,
    )

    # ── 8. Detaillierte Berichte S2 und S6 ────────────────────────────────────
    print_detailed_cluster_report(
        "S2: TF-IDF", results["S2 TF-IDF"], embs, texts, seg_ids,
        top_k=5, bottom_k=3,
    )
    print_detailed_cluster_report(
        "S6: k-LLMmeans", results["S6 k-LLM"], embs, texts, seg_ids,
        top_k=5, bottom_k=3,
    )

    # ── 9. Vergleich S2 vs S6 ─────────────────────────────────────────────────
    print_s2_s6_comparison(results["S2 TF-IDF"], results["S6 k-LLM"], seg_ids, texts)

    # ── 10. S6-conv Convergence-Report ────────────────────────────────────────
    print_s6_convergence_report(res_s6_conv, results["S6 k-LLM"], texts)

    # ── 11. S6-paper Report ───────────────────────────────────────────────────
    print_s6_paper_report(res_s6_paper, results["S6 k-LLM"], res_s6_conv, texts)

    # ── 12. S6-anthropic Report ───────────────────────────────────────────────
    if _has_anthropic and res_s6_anth is not None:
        print_s6_anthropic_report(res_s6_anth, res_s6_paper, texts)

    # ── 13. S6-exact Report ───────────────────────────────────────────────────
    if _has_exact and res_s6_exact is not None:
        print_s6_exact_report(res_s6_exact, texts)

    # ── 14. S6-tfidf-anchor Report ────────────────────────────────────────────
    if _has_anchor and res_s6_anchor is not None:
        print_s6_anchor_report(res_s6_anchor, texts)

    # ── 15. Ablation Vergleich ────────────────────────────────────────────────
    if _has_ablation and res_s6_anchor is not None and res_va is not None and res_vb is not None:
        print_ablation_comparison(res_s6_anchor, res_va, res_vb)

    print(f"\n{SEP}")
    print(f"  Gesamt: {time.perf_counter()-t_total:.1f}s")
    print(SEP2 + "\n")


if __name__ == "__main__":
    main()
