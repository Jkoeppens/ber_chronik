"""
test_optimal_clusters.py — Optimale Cluster-Anzahl auf BER-Material

Testet k=3..12 mit drei Methoden:
  B — Elbow (Inertia, zweite Ableitung)
  C — Silhouette (sklearn)
  D — Gap-Statistik (10 Referenz-Datasets)
"""

import json
import time
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

PROJECTS_DIR  = Path("data/projects")
PROJECT       = "ber"
DOCUMENT      = "main"
K_MIN, K_MAX  = 3, 12
N_REF         = 10   # Referenz-Datasets für Gap-Statistik
RANDOM_SEED   = 42

# ── Daten laden ───────────────────────────────────────────────────────────────

def load_data() -> tuple[np.ndarray, int]:
    cache_path = PROJECTS_DIR / PROJECT / "documents" / DOCUMENT / "bge_embeddings.npy"
    seg_path   = PROJECTS_DIR / PROJECT / "documents" / DOCUMENT / "segments.json"

    if not cache_path.exists():
        raise FileNotFoundError(f"Cache fehlt: {cache_path}")
    if not seg_path.exists():
        raise FileNotFoundError(f"Segmente fehlen: {seg_path}")

    embs = np.load(cache_path)
    segs = json.loads(seg_path.read_text(encoding="utf-8"))
    n_content = sum(1 for s in segs if s.get("type") == "content")
    print(f"Embeddings: {embs.shape}  |  content-Segmente: {n_content}")
    return embs, n_content


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _kmeans_inertia(embs: np.ndarray, k: int) -> float:
    km = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init="auto")
    km.fit(embs)
    return float(km.inertia_)


def _ascii_plot(ks: list[int], scores: list[float], width: int = 50, label: str = "") -> str:
    lo, hi = min(scores), max(scores)
    span   = hi - lo if hi != lo else 1.0
    lines  = [f"  {label}"]
    for k, s in zip(ks, scores):
        bar_len = int((s - lo) / span * width)
        marker  = "█" * bar_len
        lines.append(f"  k={k:2d}  {marker:<{width}}  {s:.4f}")
    return "\n".join(lines)


def _second_derivative(values: list[float]) -> list[float]:
    """Zweite Ableitung via finite differences (Länge = len(values) - 2)."""
    d1 = [values[i+1] - values[i] for i in range(len(values) - 1)]
    d2 = [d1[i+1] - d1[i] for i in range(len(d1) - 1)]
    return d2


# ── Methode B — Elbow ────────────────────────────────────────────────────────

def method_b_elbow(embs: np.ndarray, ks: list[int]) -> dict:
    print("\n── Methode B: Elbow (Inertia) ──────────────────────────────────────")
    t0       = time.perf_counter()
    inertias = []
    for k in ks:
        inertia = _kmeans_inertia(embs, k)
        inertias.append(inertia)
        print(f"  k={k:2d}  Inertia={inertia:.1f}", flush=True)

    # Knick = größte zweite Ableitung (Index i → k = ks[i+1])
    d2       = _second_derivative(inertias)
    knick_i  = int(np.argmax(d2)) + 1   # offset: d2 startet bei ks[1]
    best_k   = ks[knick_i]
    elapsed  = time.perf_counter() - t0

    print(f"\n{_ascii_plot(ks, inertias, label='Inertia (höher = schlechter)')}")
    print(f"\n  Zweite Ableitung: {[f'{v:.1f}' for v in d2]}")
    print(f"  → Elbow bei k={best_k}  (stärkster Knick an Position {knick_i})")
    print(f"  Laufzeit: {elapsed:.2f}s")

    return {"method": "Elbow", "best_k": best_k, "scores": dict(zip(ks, inertias)),
            "elapsed": elapsed, "unit": "Inertia (niedriger = besser)"}


# ── Methode C — Silhouette ───────────────────────────────────────────────────

def method_c_silhouette(embs: np.ndarray, ks: list[int]) -> dict:
    print("\n── Methode C: Silhouette ───────────────────────────────────────────")
    t0     = time.perf_counter()
    scores = []
    for k in ks:
        km     = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init="auto")
        labels = km.fit_predict(embs)
        score  = float(silhouette_score(embs, labels, sample_size=min(3000, len(embs)),
                                        random_state=RANDOM_SEED))
        scores.append(score)
        print(f"  k={k:2d}  Silhouette={score:.4f}", flush=True)

    best_k  = ks[int(np.argmax(scores))]
    elapsed = time.perf_counter() - t0

    print(f"\n{_ascii_plot(ks, scores, label='Silhouette (höher = besser)')}")
    print(f"\n  → Bestes k={best_k}  (Silhouette={max(scores):.4f})")
    print(f"  Laufzeit: {elapsed:.2f}s")

    return {"method": "Silhouette", "best_k": best_k, "scores": dict(zip(ks, scores)),
            "elapsed": elapsed, "unit": "Silhouette (höher = besser)"}


# ── Methode D — Gap-Statistik ────────────────────────────────────────────────

def method_d_gap(embs: np.ndarray, ks: list[int]) -> dict:
    print("\n── Methode D: Gap-Statistik ────────────────────────────────────────")
    print(f"  {N_REF} Referenz-Datasets pro k…", flush=True)
    t0   = time.perf_counter()
    rng  = np.random.default_rng(RANDOM_SEED)

    # Bounding box der Daten für Uniform-Referenz
    lo = embs.min(axis=0)
    hi = embs.max(axis=0)

    gaps = []
    for k in ks:
        # Inertia auf echten Daten
        km_real   = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init="auto")
        km_real.fit(embs)
        log_w_k   = np.log(km_real.inertia_)

        # Inertia auf Referenz-Daten (gleichverteilte Punkte im selben Bounding-Box)
        ref_log_w = []
        for _ in range(N_REF):
            ref   = rng.uniform(lo, hi, size=embs.shape).astype(np.float32)
            km_r  = KMeans(n_clusters=k, random_state=RANDOM_SEED, n_init="auto")
            km_r.fit(ref)
            ref_log_w.append(np.log(km_r.inertia_))

        gap = float(np.mean(ref_log_w) - log_w_k)
        gaps.append(gap)
        print(f"  k={k:2d}  Gap={gap:.4f}", flush=True)

    best_k  = ks[int(np.argmax(gaps))]
    elapsed = time.perf_counter() - t0

    print(f"\n{_ascii_plot(ks, gaps, label='Gap (höher = besser)')}")
    print(f"\n  → Bestes k={best_k}  (Gap={max(gaps):.4f})")
    print(f"  Laufzeit: {elapsed:.2f}s")

    return {"method": "Gap", "best_k": best_k, "scores": dict(zip(ks, gaps)),
            "elapsed": elapsed, "unit": "Gap (höher = besser)"}


# ── Zusammenfassung ───────────────────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    SEP = "─" * 60
    print(f"\n{'═'*60}")
    print("  Zusammenfassung")
    print(f"{'═'*60}")
    print(f"  {'Methode':12}  {'Empfehlung':>12}  {'Laufzeit':>10}  Einheit")
    print(f"  {SEP}")
    for r in results:
        print(f"  {r['method']:12}  k={r['best_k']:>10}  {r['elapsed']:>8.2f}s  {r['unit']}")
    print(f"  {SEP}")

    votes: dict[int, int] = {}
    for r in results:
        votes[r["best_k"]] = votes.get(r["best_k"], 0) + 1
    consensus = max(votes, key=lambda k: (votes[k], -k))
    print(f"\n  Mehrheit: k={consensus}  ({votes[consensus]}/{len(results)} Stimmen)")
    print(f"  Alle Stimmen: {dict(sorted(votes.items()))}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    embs, _ = load_data()
    ks      = list(range(K_MIN, K_MAX + 1))

    results = [
        method_b_elbow(embs, ks),
        method_c_silhouette(embs, ks),
        method_d_gap(embs, ks),
    ]

    print_summary(results)


if __name__ == "__main__":
    main()
