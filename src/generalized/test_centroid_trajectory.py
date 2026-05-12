"""
test_centroid_trajectory.py — Centroid-Trajektorie über LLM-Iterationen

Zwei Sampling-Methoden auf BER-Material (Anthropic API):
  topn    — Top-N Segmente nach Cosine-Similarity zum Cluster-Centroid
  kmeanspp — k-means++ diverse Auswahl (bestehende Implementierung)

Output: data/.../centroid_trajectory/
  trajectory_topn_<timestamp>.csv
  trajectory_kmeanspp_<timestamp>.csv
  segments_<timestamp>.csv
  run_metadata_<timestamp>.json

PCA wird auf allen Segment-Embeddings + allen Centroid-Positionen beider
Läufe gemeinsam berechnet — einheitlicher 2D-Raum für Overlay.
"""

import csv
import json
import random
import re as _re
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

import src.generalized.test_tfidf_anchor_taxonomy as _bge
from src.generalized.config import PROJECTS_DIR

load_dotenv()

# ── Konfiguration ─────────────────────────────────────────────────────────────

PROJECT                = "ber"
DOCUMENT               = "main"
N_ITER                 = 10
N_CLUSTERS             = 7
N_SEGMENTS_PER_CLUSTER = 10
RANDOM_SEED            = 42
SAMPLING_METHODS       = ["topn", "kmeanspp"]
PROVIDER               = _bge.PROVIDER
MODEL                  = _bge.MODEL_ANTHROPIC if PROVIDER == "anthropic" else _bge.MODEL_OLLAMA

SEG_PATH   = PROJECTS_DIR / PROJECT / "documents" / DOCUMENT / "segments.json"
CACHE_PATH = PROJECTS_DIR / PROJECT / "documents" / DOCUMENT / "bge_embeddings.npy"
OUT_DIR    = PROJECTS_DIR / PROJECT / "documents" / DOCUMENT / "centroid_trajectory"

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


# ── Sampling ──────────────────────────────────────────────────────────────────

def _topn_sample(seg_embs: np.ndarray, idx: np.ndarray, centroid: np.ndarray, m: int) -> np.ndarray:
    """Top-M Segmente: höchste Cosine-Similarity zum Centroid."""
    if len(idx) <= m:
        return idx
    sims = seg_embs[idx] @ centroid
    return idx[sims.argsort()[::-1][:m]]


def _sample_cluster(method: str, seg_embs, idx, centroid, m, rng) -> np.ndarray:
    if len(idx) == 0:
        return np.array([], dtype=int)
    if method == "topn":
        return _topn_sample(seg_embs, idx, centroid, m)
    return _bge._kmeanspp_sample(seg_embs, idx, m, rng)


def _extract_gruppe_block(raw: str, cid: int) -> str:
    """Extrahiert den '## Gruppe N'-Block für cluster_id cid (0-basiert) aus raw."""
    parts = _re.split(r"^##\s*Gruppe\s+(\d+)\s*$", raw, flags=_re.MULTILINE)
    i = 1
    while i + 1 < len(parts):
        try:
            idx = int(parts[i]) - 1
        except ValueError:
            i += 2
            continue
        if idx == cid:
            return f"## Gruppe {cid + 1}\n{parts[i + 1].strip()}"
        i += 2
    return ""


# ── Einzelner Lauf ────────────────────────────────────────────────────────────

def run_trajectory(
    bge,
    seg_embs: np.ndarray,
    texts: list[str],
    sampling_method: str,
    n_iter: int = N_ITER,
    n_clusters: int = N_CLUSTERS,
    m: int = N_SEGMENTS_PER_CLUSTER,
) -> tuple[list[dict], np.ndarray]:
    """
    Gibt (records, final_labels) zurück.
    records: eine Zeile pro Cluster × Iteration (inkl. Iter 0 = math).
    """
    rng    = np.random.default_rng(RANDOM_SEED)
    labels = KMeans(n_clusters=n_clusters, random_state=RANDOM_SEED, n_init="auto").fit_predict(seg_embs)
    math_centroids = _bge._compute_centroids(seg_embs, labels)

    records: list[dict] = []

    # ── Iteration 0: mathematische Centroids (kein LLM) ──────────────────────
    for cid in range(n_clusters):
        records.append({
            "sampling_method": sampling_method,
            "cluster_id":      cid,
            "iteration":       0,
            "centroid_type":   "math",
            "centroid_emb":    math_centroids[cid].copy(),
            "llm_input_texts": [],
            "llm_output_text": "",
            "label_sim":       None,
        })

    label_embs    = math_centroids.copy()
    summaries     = [f"Cluster {i+1}" for i in range(n_clusters)]
    prev_descs    = [None] * n_clusters
    prev_llm_iter = None

    # ── Iterationen 1..n_iter ─────────────────────────────────────────────────
    for it in range(1, n_iter + 1):
        labels = (seg_embs @ label_embs.T).argmax(axis=1)
        kw_map = _bge._compute_tfidf_keywords(texts, labels, n_clusters=n_clusters)

        # Keyword-Sektion
        kw_lines = []
        for cid in range(n_clusters):
            kws = kw_map.get(cid, [])
            if not kws:
                import sys as _sys
                print(f"  WARNING: C{cid+1} keine Keywords", file=_sys.stderr)
            kw_lines.append(f"Gruppe {cid+1} Keywords: {', '.join(kws)}")
        keyword_section = "\n".join(kw_lines)

        # Rolling-Context-Sektion
        if any(d is not None for d in prev_descs):
            prev_lines = "\n".join(
                f"Gruppe {cid+1}: {prev_descs[cid]}" if prev_descs[cid]
                else f"Gruppe {cid+1}: (keine)"
                for cid in range(n_clusters)
            )
            prev_section = f"\nVorherige Beschreibung (Iteration {prev_llm_iter}):\n{prev_lines}\n"
        else:
            prev_section = ""

        # Sampling + Segment-Blöcke
        sampled_per_cluster: dict[int, list[str]] = {}
        seg_blocks: list[str] = []
        for cid in range(n_clusters):
            idx = np.where(labels == cid)[0]
            if len(idx) == 0:
                sampled_per_cluster[cid] = []
                seg_blocks.append(f"--- Gruppe {cid+1} ---\n(Leer)")
                continue
            sample_idx    = _sample_cluster(sampling_method, seg_embs, idx, label_embs[cid], m, rng)
            sampled_texts = [texts[j][:300] for j in sample_idx]
            sampled_per_cluster[cid] = sampled_texts
            snips = "\n\n".join(f"[{i+1}] {t}" for i, t in enumerate(sampled_texts))
            seg_blocks.append(f"--- Gruppe {cid+1} ---\n{snips}")

        prompt = _bge._PROMPT_TEMPLATE.format(
            n=n_clusters,
            keyword_section=keyword_section,
            prev_section=prev_section,
            segment_section="\n\n".join(seg_blocks),
        )

        print(f"  [{sampling_method}] Iter {it}/{n_iter} → LLM…", flush=True)
        t0 = time.perf_counter()
        raw, in_tok, out_tok = _bge._llm_call(prompt)
        print(f"    {time.perf_counter()-t0:.1f}s  {in_tok}+{out_tok} tok", flush=True)

        parsed = _bge._parse_llm_response(raw, n_clusters)

        # Neue Label-Texte (Fallback auf altes Summary wenn LLM None zurückgibt)
        new_summaries = []
        for cid in range(n_clusters):
            if parsed[cid] is not None:
                _t, _b = parsed[cid]
                new_summaries.append(f"{_t}. {_b}" if _b else _t)
            else:
                new_summaries.append(summaries[cid])

        # Alle neuen Labels in einem Batch embedden
        new_embs = _bge._embed_texts(bge, new_summaries)

        for cid in range(n_clusters):
            sim = float(label_embs[cid] @ new_embs[cid])
            records.append({
                "sampling_method": sampling_method,
                "cluster_id":      cid,
                "iteration":       it,
                "centroid_type":   "llm",
                "centroid_emb":    new_embs[cid].copy(),
                "llm_input_texts": sampled_per_cluster.get(cid, []),
                "llm_output_text": _extract_gruppe_block(raw, cid),
                "label_sim":       sim,
            })
            label_embs[cid] = new_embs[cid]
            if parsed[cid] is not None:
                _t, _b = parsed[cid]
                prev_descs[cid] = _b or _t
                summaries[cid]  = new_summaries[cid]

        prev_llm_iter = it

    return records, labels


# ── CSV-Output ────────────────────────────────────────────────────────────────

_TRAJ_FIELDS = [
    "sampling_method", "cluster_id", "iteration",
    "pca_x", "pca_y", "centroid_type",
    "llm_input_texts", "llm_output_text", "label_sim",
]

def write_trajectory_csv(records: list[dict], coords_2d: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TRAJ_FIELDS)
        w.writeheader()
        for i, rec in enumerate(records):
            w.writerow({
                "sampling_method": rec["sampling_method"],
                "cluster_id":      rec["cluster_id"],
                "iteration":       rec["iteration"],
                "pca_x":           f"{coords_2d[i, 0]:.6f}",
                "pca_y":           f"{coords_2d[i, 1]:.6f}",
                "centroid_type":   rec["centroid_type"],
                "llm_input_texts": json.dumps(rec["llm_input_texts"], ensure_ascii=False),
                "llm_output_text": rec["llm_output_text"],
                "label_sim":       f"{rec['label_sim']:.6f}" if rec["label_sim"] is not None else "",
            })
    print(f"  → {path}  ({len(records)} Zeilen)")


def write_segments_csv(
    seg_ids: list[str],
    labels: np.ndarray,
    seg_2d: np.ndarray,
    texts: list[str],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["segment_id", "cluster_id", "pca_x", "pca_y", "text"])
        w.writeheader()
        for i, (sid, cid) in enumerate(zip(seg_ids, labels)):
            w.writerow({
                "segment_id": sid,
                "cluster_id": int(cid),
                "pca_x":      f"{seg_2d[i, 0]:.6f}",
                "pca_y":      f"{seg_2d[i, 1]:.6f}",
                "text":       texts[i][:300],
            })
    print(f"  → {path}  ({len(seg_ids)} Segmente)")


def write_metadata(ts: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "timestamp":     ts,
        "seed":          RANDOM_SEED,
        "n_iter":        N_ITER,
        "n_clusters":    N_CLUSTERS,
        "n_segments_per_cluster": N_SEGMENTS_PER_CLUSTER,
        "sampling_methods": SAMPLING_METHODS,
        "provider":      PROVIDER,
        "model":         MODEL,
        "bge_cache":     str(CACHE_PATH),
        "segments_path": str(SEG_PATH),
    }
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  → {path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ts      = datetime.now().strftime("%Y%m%d_%H%M")
    t_total = time.perf_counter()

    print(f"Seed:     {RANDOM_SEED}")
    print(f"Iter:     {N_ITER}, Cluster: {N_CLUSTERS}")
    print(f"Sampling: {SAMPLING_METHODS}")
    print(f"Provider: {PROVIDER}/{MODEL}")

    texts, seg_ids = _bge.load_segments(SEG_PATH)
    print(f"Segmente: {len(texts)}", flush=True)

    bge      = _bge._load_bge()
    seg_embs = _bge._compute_segment_embeddings(bge, texts, CACHE_PATH)
    seg_embs = _bge._neighbor_aggregate(seg_embs, texts)

    all_records: list[dict] = []
    all_labels:  dict[str, np.ndarray] = {}

    for method in SAMPLING_METHODS:
        print(f"\n── Lauf: {method} {'─' * (50 - len(method))}")
        records, labels = run_trajectory(bge, seg_embs, texts, method)
        all_records.append((method, records, labels))
        all_labels[method] = labels

    # ── PCA auf allem gemeinsam ───────────────────────────────────────────────
    print("\nPCA…", flush=True)
    flat_records  = [r for _, recs, _ in all_records for r in recs]
    centroid_embs = np.array([r["centroid_emb"] for r in flat_records])
    all_for_pca   = np.vstack([seg_embs, centroid_embs])

    pca = PCA(n_components=2, random_state=RANDOM_SEED)
    pca.fit(all_for_pca)
    print(f"  Erklärte Varianz: PC1={pca.explained_variance_ratio_[0]:.3f}  "
          f"PC2={pca.explained_variance_ratio_[1]:.3f}", flush=True)

    seg_2d       = pca.transform(seg_embs)
    centroid_2d  = pca.transform(centroid_embs)

    # ── CSV schreiben ─────────────────────────────────────────────────────────
    print("\nSchreibe CSV…", flush=True)
    offset = 0
    for method, records, labels in all_records:
        n = len(records)
        coords = centroid_2d[offset: offset + n]
        offset += n
        write_trajectory_csv(records, coords, OUT_DIR / f"trajectory_{method}_{ts}.csv")

    first_labels = all_records[0][2]
    write_segments_csv(seg_ids, first_labels, seg_2d, texts, OUT_DIR / f"segments_{ts}.csv")
    write_metadata(ts, OUT_DIR / f"run_metadata_{ts}.json")

    print(f"\nGesamt: {time.perf_counter()-t_total:.1f}s")


if __name__ == "__main__":
    main()
