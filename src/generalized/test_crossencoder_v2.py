"""
test_crossencoder_v2.py — BGE-Reranker-v2-m3 vs BGE-M3 Cosine-Similarity

  1. 30 Segmente aus damaskus_test_2 (seed=42)
  2. Labels aus config.json["taxonomy"] (name + beschreibung + keywords)
  3. BGE-M3 Cosine-Similarity (gecachte Embeddings)
  4. BAAI/bge-reranker-v2-m3 Cross-Encoder
  5. Verteilung, Score-Stats, 3 Beispiele pro Kategorie, Vergleich
"""

import json
import random
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

from src.generalized.config import ROOT

SEGMENTS_PATH = Path("data/projects/damaskus_test_2/documents/b1e1d872/segments.json")
CONFIG_PATH   = Path("data/projects/damaskus_test_2/config.json")
EMB_CACHE     = Path("/tmp/test_bge_embeddings.npy")

N_SAMPLE      = 30
SEG_CHARS     = 500
MIN_LENGTH    = 30
SEED          = 42
EXAMPLES      = 3

SEP  = "─" * 80
SEP2 = "=" * 80


# ── Daten laden ─────────────────────────────────────────────────────────────

def load_all_segments() -> tuple[list[str], list[str]]:
    """Alle content-Segmente, nach segment_id sortiert — gleiche Reihenfolge wie Cache."""
    segs = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    content = [s for s in segs
               if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]
    content.sort(key=lambda s: s.get("segment_id", ""))
    return [s["text"][:SEG_CHARS] for s in content], [s.get("segment_id", "?") for s in content]


def load_taxonomy() -> list[dict]:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    tax = cfg.get("taxonomy", [])
    if not tax:
        raise SystemExit(f"Keine Taxonomie in {CONFIG_PATH}")
    return tax


def label_text(cat: dict) -> str:
    parts = [cat["name"]]
    if cat.get("description"):
        parts.append(cat["description"])
    if cat.get("keywords"):
        parts.append("Keywords: " + ", ".join(cat["keywords"]))
    return " — ".join(parts)


# ── BGE-M3 Cosine-Similarity ────────────────────────────────────────────────

def bge_classify(
    seg_embs: np.ndarray,           # (30, 1024) — normalisiert
    label_embs: np.ndarray,         # (n_cats, 1024) — normalisiert
) -> tuple[np.ndarray, np.ndarray]:
    sim      = seg_embs @ label_embs.T          # (30, n_cats)
    cat_idx  = sim.argmax(axis=1)
    scores   = sim[np.arange(len(sim)), cat_idx]
    return cat_idx, scores


# ── BGE-Reranker ────────────────────────────────────────────────────────────

def reranker_classify(
    texts: list[str],
    label_texts: list[str],
    model,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Für jedes Segment × Kategorie ein Score; argmax → Kategorie.
    Pairs: (label, segment) — label als Query, segment als Passage.
    """
    n_segs = len(texts)
    n_cats = len(label_texts)
    pairs  = [
        (label_texts[c], texts[s])
        for s in range(n_segs)
        for c in range(n_cats)
    ]
    t0   = time.perf_counter()
    flat = model.predict(pairs, show_progress_bar=False)
    t_inf = time.perf_counter() - t0
    scores_mat = np.array(flat, dtype=np.float32).reshape(n_segs, n_cats)
    cat_idx    = scores_mat.argmax(axis=1)
    scores     = scores_mat[np.arange(n_segs), cat_idx]
    print(f"  Inference: {n_segs}×{n_cats}={len(pairs)} Paare  [{t_inf:.1f}s]")
    return cat_idx, scores, scores_mat


# ── Ausgabe ──────────────────────────────────────────────────────────────────

def print_distribution(title: str, cats: list[dict], cat_idx: np.ndarray, scores: np.ndarray) -> None:
    n = len(cat_idx)
    print(f"\n{SEP}")
    print(f"  VERTEILUNG — {title}")
    print(SEP)
    for i, cat in enumerate(cats):
        mask  = cat_idx == i
        count = int(mask.sum())
        bar   = "█" * int(count / n * 40) if count else ""
        avg   = float(scores[mask].mean()) if count else 0.0
        print(f"  {cat['name']:30s}  {count:3d} ({count/n*100:5.1f}%)  {bar}  Ø={avg:.3f}")
    print(f"\n  Score-Spanne: min={scores.min():.3f}  Ø={scores.mean():.3f}  max={scores.max():.3f}")


def print_examples(
    cats: list[dict],
    cat_idx: np.ndarray,
    scores: np.ndarray,
    texts: list[str],
    seg_ids: list[str],
) -> None:
    print(f"\n{SEP}")
    print(f"  BEISPIELE  (top-{EXAMPLES} pro Kategorie)")
    print(SEP)
    for i, cat in enumerate(cats):
        mask = np.where(cat_idx == i)[0]
        if len(mask) == 0:
            continue
        top = mask[scores[mask].argsort()[::-1][:EXAMPLES]]
        pad = "─" * max(0, 50 - len(cat["name"]))
        print(f"\n── {cat['name']}  ({len(mask)} Segmente) {pad}")
        for rank, idx in enumerate(top, 1):
            preview = texts[idx].replace("\n", " ")[:110]
            print(f"  {rank}. [{seg_ids[idx]}] score={scores[idx]:.4f}")
            print(f"     \"{preview}\"")


def print_comparison(
    cats: list[dict],
    idx_bge: np.ndarray,
    idx_rnk: np.ndarray,
    scores_bge: np.ndarray,
    scores_rnk: np.ndarray,
    texts: list[str],
    seg_ids: list[str],
) -> None:
    agree    = (idx_bge == idx_rnk).sum()
    disagree = [(i, idx_bge[i], idx_rnk[i]) for i in range(len(idx_bge)) if idx_bge[i] != idx_rnk[i]]

    print(f"\n{SEP}")
    print(f"  VERGLEICH — BGE-M3 Cosine vs BGE-Reranker")
    print(SEP)
    print(f"  Übereinstimmung: {agree}/{len(idx_bge)} ({agree/len(idx_bge)*100:.0f}%)")

    if disagree:
        print(f"  Abweichungen ({len(disagree)}):")
        for i, ib, ir in disagree:
            preview = texts[i].replace("\n", " ")[:90]
            print(f"\n  [{seg_ids[i]}]")
            print(f"    BGE-M3   → {cats[ib]['name']}  (score={scores_bge[i]:.3f})")
            print(f"    Reranker → {cats[ir]['name']}  (score={scores_rnk[i]:.3f})")
            print(f"    \"{preview}\"")


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ROOT / ".env")
    t_start = time.perf_counter()

    # ── Daten ────────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SETUP")
    print(SEP2)

    all_texts, all_ids = load_all_segments()
    taxonomy           = load_taxonomy()
    label_texts        = [label_text(c) for c in taxonomy]

    random.seed(SEED)
    sample_idx = sorted(random.sample(range(len(all_texts)), N_SAMPLE))
    texts      = [all_texts[i] for i in sample_idx]
    seg_ids    = [all_ids[i]   for i in sample_idx]

    print(f"Segmente gesamt : {len(all_texts)}")
    print(f"Stichprobe      : {N_SAMPLE}  (seed={SEED})")
    print(f"Kategorien      : {len(taxonomy)}")
    for i, cat in enumerate(taxonomy):
        print(f"  [{i+1}] {cat['name']}")
    print(f"\nLabel-Strings:")
    for lt in label_texts:
        print(f"  · {lt[:95]}")

    # ── BGE-M3 Embeddings laden ───────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 1 — BGE-M3 Cosine-Similarity")
    print(SEP2)

    if not EMB_CACHE.exists():
        raise SystemExit(f"Cache nicht gefunden: {EMB_CACHE}\n→ Erst test_bge_classify.py ausführen.")
    all_embs = np.load(str(EMB_CACHE))
    if all_embs.shape[0] != len(all_texts):
        raise SystemExit(f"Cache-Größe {all_embs.shape[0]} ≠ Segmente {len(all_texts)}")
    print(f"Cache geladen: {EMB_CACHE}  {all_embs.shape}")

    seg_embs = all_embs[sample_idx]         # (30, 1024)

    print("Lade BGE-M3 für Label-Embeddings…", flush=True)
    from FlagEmbedding import BGEM3FlagModel
    t0  = time.perf_counter()
    bge = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    print(f"Modell geladen  [{time.perf_counter()-t0:.1f}s]")

    raw       = bge.encode(label_texts, batch_size=16, max_length=256,
                           return_dense=True, return_sparse=False,
                           return_colbert_vecs=False)["dense_vecs"]
    label_embs = np.array(raw, dtype=np.float32)
    norms      = np.linalg.norm(label_embs, axis=1, keepdims=True)
    label_embs /= np.maximum(norms, 1e-9)

    t_bge = time.perf_counter()
    idx_bge, scores_bge = bge_classify(seg_embs, label_embs)
    print(f"Klassifiziert: {N_SAMPLE} Segmente  [{time.perf_counter()-t_bge:.3f}s]")

    # ── BGE-Reranker ─────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print("  SCHRITT 2 — BGE-Reranker-v2-m3")
    print(SEP2)

    print("Lade BAAI/bge-reranker-v2-m3  (sentence-transformers CrossEncoder)…", flush=True)
    from sentence_transformers.cross_encoder import CrossEncoder
    t0      = time.perf_counter()
    reranker = CrossEncoder("BAAI/bge-reranker-v2-m3")
    print(f"Modell geladen  [{time.perf_counter()-t0:.1f}s]")

    idx_rnk, scores_rnk, _ = reranker_classify(texts, label_texts, reranker)

    # ── Ausgabe ───────────────────────────────────────────────────────────────
    print_distribution("BGE-M3 Cosine", taxonomy, idx_bge, scores_bge)
    print_distribution("BGE-Reranker-v2-m3", taxonomy, idx_rnk, scores_rnk)
    print_examples(taxonomy, idx_rnk, scores_rnk, texts, seg_ids)
    print_comparison(taxonomy, idx_bge, idx_rnk, scores_bge, scores_rnk, texts, seg_ids)

    elapsed = time.perf_counter() - t_start
    print(f"\n{SEP}")
    print(f"  LAUFZEIT  Gesamt: {elapsed:.1f}s")
    print(SEP2 + "\n")


if __name__ == "__main__":
    main()
