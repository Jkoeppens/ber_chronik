"""
test_cluster_quality.py — Testet ob der Embedding-Space Entity-Typen trennt.

Test 1 – Intra/Inter-Typ-Similarity:
  Paarweise Cosine-Similarity innerhalb Person, innerhalb Ort,
  und Person↔Ort als Baseline. Frage: sind Typen separierbar?

Test 2 – Person-Zentrum: Top-30 Tokens aus Segmenten
  Zeigt bekannte (Seed) und unbekannte Tokens mit hoher Similarity.

Test 3 – Ort-Zentrum: identisch.

Test 4 – K-Means k=3 auf Person-Embeddings:
  Bilden sich inhaltlich sinnvolle Untergruppen?
  Pro Cluster-Zentrum: Top-10 unbekannte Corpus-Tokens.

Test 7 – Unterraum-Analyse:
  A: Differenzvektor Person vs. Ort; Projektions-Overlap.
  B: Unbekannte Corpus-Tokens auf diese Achse projiziert.
  C: PCA auf allen Seed-Embeddings; Silhouette in PC-Raum vs. Vollraum.
  D: Linear Probing — LogisticRegression 5-Fold CV; Confusion Matrix.

Test 8 – Classifier statt Cosine-Similarity:
  LogReg auf Seed-Embeddings → Wahrscheinlichkeit pro Typ für alle Corpus-Tokens.
  Top-20 neue Kandidaten pro Typ mit Konfidenz; Vergleich mit Cosine-Top-20.

Test 9 – Kontextuelle Embeddings (mBERT):
  Token im Satzkontext einbetten via mean-pooling der BERT-Token-Positionen.
  Vergleich statisch vs. kontextuell: Silhouette, Classifier-Accuracy, Diff-Overlap.
"""

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans, DBSCAN
from sklearn.metrics import silhouette_score

SEGMENTS_PATH = Path("data/projects/osmanisch/documents/657e2449/segments.json")
SEED_PATH     = Path("data/projects/osmanisch/documents/657e2449/entities_seed.json")
MODEL_NAME    = "paraphrase-multilingual-mpnet-base-v2"
TOP_N         = 30

CAPITAL_RE = re.compile(
    r'\b([A-ZÄÖÜÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÕÙÚÛÝ\u0400-\u042F]'
    r'[\w\u00C0-\u024F\u1E00-\u1EFF\u0400-\u04FF]{2,})\b'
)

DE_STOP = {
    "Das","Die","Der","Den","Des","Ein","Eine","Einen","Einem","Eines",
    "Und","Oder","Aber","Auch","Als","Mit","Von","Vom","Zur","Zum",
    "Nicht","Noch","Nach","Vor","Über","Durch","Für","Bei","Seit",
    "Aus","An","Am","Im","In","Es","Er","Sie","Wir","Ihr","Ich",
    "Dass","Wenn","Wie","Was","Wo","Ob","Da","So","Nu","Bu",
    "Dabei","Doch","Dann","Schon","Außerdem","Gleichzeitig","Einige",
    "Andere","Viele","Erst","Erste","Bereits",
}
EN_STOP = {
    "The","This","That","These","Those","Then","There","Their","They",
    "Some","Many","Other","Also","When","What","Where","Who","Which",
    "And","But","Not","With","From","For","Into","More","Most",
    "On","In","At","Re","By","Or","As","An","Of","To",
    "He","She","We","It","His","Her","Its","Our","Was","Were",
    "Had","Has","Have","Been","Being","After","Before","During",
    "First","Second","New","Old","One","Two","Three",
}
STOP_ALL = DE_STOP | EN_STOP


# ── Helpers ───────────────────────────────────────────────────────────────────

def cosine_sim_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(N,D) × (M,D) → (N,M) cosine similarity. Inputs must be L2-normalised."""
    return a @ b.T


def stats(arr: np.ndarray, label: str) -> None:
    print(f"  {label:<30}  mean={arr.mean():.3f}  "
          f"min={arr.min():.3f}  max={arr.max():.3f}  "
          f"std={arr.std():.3f}  n={arr.size}")


def sep_score(intra: np.ndarray, inter: np.ndarray) -> str:
    """Δ mean + Cohen's d as separation signal."""
    delta = intra.mean() - inter.mean()
    pooled_std = np.sqrt((intra.var() + inter.var()) / 2) + 1e-9
    d = delta / pooled_std
    return f"Δmean={delta:+.3f}  Cohen's d={d:.2f}"


# ── Load data ─────────────────────────────────────────────────────────────────

print("Lade Daten…")
seed     = json.loads(SEED_PATH.read_text(encoding="utf-8"))
segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
content_segs = [s for s in segments if s.get("type") == "content"]
print(f"Seed: {len(seed)} Entities  |  Content-Segmente: {len(content_segs)}")

# Seed nach Typ aufteilen
by_type: dict[str, list[str]] = {}
seed_lc: set[str] = set()
for ent in seed:
    typ = ent.get("typ", "?")
    names = [ent.get("normalform", "")] + list(ent.get("aliases") or [])
    names = [n.strip() for n in names if n and n.strip()]
    by_type.setdefault(typ, []).extend(names)
    for n in names:
        for w in n.lower().split():
            seed_lc.add(w)
        seed_lc.add(n.lower())

for typ, names in by_type.items():
    print(f"  {typ}: {len(names)} Namen/Aliases")

# Corpus-Tokens
counter: Counter = Counter()
for seg in content_segs:
    for m in CAPITAL_RE.finditer(seg.get("text", "")):
        tok = m.group(1)
        if len(tok) >= 3 and tok not in STOP_ALL:
            counter[tok] += 1
corpus_tokens = list(counter.keys())
print(f"Corpus-Tokens (großgeschrieben, ≥3): {len(corpus_tokens)}")

# ── Modell laden + Embeddings berechnen ───────────────────────────────────────

print(f"\nLade Modell {MODEL_NAME} …")
model = SentenceTransformer(MODEL_NAME)


def embed(texts: list[str]) -> np.ndarray:
    return model.encode(texts, batch_size=256, normalize_embeddings=True,
                        show_progress_bar=False)


print("Bette Seed-Entities ein …")
seed_vecs: dict[str, np.ndarray] = {}
for typ, names in by_type.items():
    if names:
        seed_vecs[typ] = embed(names)

print(f"Bette {len(corpus_tokens)} Corpus-Tokens ein …")
corpus_vecs = embed(corpus_tokens)


# ══════════════════════════════════════════════════════════════════════════════
# TEST 1 – Paarweise Intra/Inter-Typ Similarity
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 1 – Intra/Inter-Typ Cosine-Similarity (paarweise)")
print("=" * 65)
print("Frage: Clustern Personen stärker zusammen als Personen zu Orten?\n")

target_pairs = [
    ("Person",       "Person",       "Person ↔ Person (intra)"),
    ("Ort",          "Ort",          "Ort    ↔ Ort    (intra)"),
    ("Organisation", "Organisation", "Org    ↔ Org    (intra)"),
    ("Person",       "Ort",          "Person ↔ Ort    (inter)"),
    ("Person",       "Organisation", "Person ↔ Org    (inter)"),
    ("Ort",          "Organisation", "Ort    ↔ Org    (inter)"),
]

sim_cache: dict[tuple[str, str], np.ndarray] = {}
for t1, t2, label in target_pairs:
    if t1 not in seed_vecs or t2 not in seed_vecs:
        print(f"  {label}: zu wenig Daten")
        continue
    v1, v2 = seed_vecs[t1], seed_vecs[t2]
    mat = cosine_sim_matrix(v1, v2)
    if t1 == t2:
        # Exclude self-similarity (diagonal)
        idx = np.triu_indices(len(mat), k=1) if mat.shape[0] == mat.shape[1] else (slice(None),)
        if mat.shape[0] == mat.shape[1] and mat.shape[0] > 1:
            flat = mat[np.triu_indices(mat.shape[0], k=1)]
        else:
            flat = mat.flatten()
    else:
        flat = mat.flatten()
    sim_cache[(t1, t2)] = flat
    stats(flat, label)

# Separation signal
if ("Person","Person") in sim_cache and ("Person","Ort") in sim_cache:
    print(f"\n  Person intra vs. Person↔Ort: "
          f"{sep_score(sim_cache[('Person','Person')], sim_cache[('Person','Ort')])}")
if ("Ort","Ort") in sim_cache and ("Person","Ort") in sim_cache:
    print(f"  Ort intra vs. Person↔Ort:    "
          f"{sep_score(sim_cache[('Ort','Ort')], sim_cache[('Person','Ort')])}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 2 – Top-30 Corpus-Tokens nah am Person-Zentrum
# ══════════════════════════════════════════════════════════════════════════════

def center(vecs: np.ndarray) -> np.ndarray:
    c = vecs.mean(axis=0)
    n = np.linalg.norm(c)
    return c / n if n > 0 else c


def top_tokens_near_center(
    typ: str,
    n: int = TOP_N,
) -> None:
    if typ not in seed_vecs:
        print(f"  Kein Typ '{typ}' im Seed.")
        return
    c = center(seed_vecs[typ])
    sims = corpus_vecs @ c           # dot product = cosine (L2-normalised)
    order = np.argsort(-sims)

    in_seed_count  = 0
    new_count      = 0
    rows = []
    for i in order[:n]:
        tok  = corpus_tokens[i]
        sim  = float(sims[i])
        freq = counter[tok]
        known = tok.lower() in seed_lc or any(
            tok.lower() == w
            for name in (by_type.get(typ) or [])
            for w in name.lower().split()
        )
        marker = "✓ Seed" if known else "? neu "
        if known: in_seed_count += 1
        else:     new_count += 1
        rows.append((tok, sim, freq, marker))

    # Type separation: how does this typ-center score vs. other-typ tokens?
    other_typ = "Ort" if typ == "Person" else "Person"
    other_names = by_type.get(other_typ, [])
    if other_names:
        ov = seed_vecs[other_typ]
        other_sims = (ov @ c)
        print(f"\n  Vergleich: {typ}-Zentrum vs. {other_typ}-Namen: "
              f"mean={other_sims.mean():.3f}  "
              f"(typ-eigene Seed-Namen: mean={(seed_vecs[typ] @ c).mean():.3f})")

    print(f"\n{'Token':<26}  {'Sim':>5}  {'Freq':>5}  Status")
    print("-" * 52)
    for tok, sim, freq, marker in rows:
        print(f"  {tok:<24}  {sim:.3f}  {freq:5d}×  {marker}")
    print(f"\n  Seed-Tokens unter Top-{n}: {in_seed_count}  |  Neue Kandidaten: {new_count}")


print("\n" + "=" * 65)
print("TEST 2 – Top-30 Corpus-Tokens nah am Person-Zentrum")
print("=" * 65)
print("Frage: Sind unbekannte Tokens mit hoher Similarity echte Personennamen?\n")
top_tokens_near_center("Person")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 3 – Top-30 Corpus-Tokens nah am Ort-Zentrum
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 3 – Top-30 Corpus-Tokens nah am Ort-Zentrum")
print("=" * 65)
print("Frage: Sind Person- und Ort-Zentrum im Embedding-Space trennbar?\n")
top_tokens_near_center("Ort")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 4 – K-Means k=3 auf Person-Embeddings
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 4 – K-Means k=3 auf Person-Seed-Embeddings")
print("=" * 65)
print("Frage: Bilden sich inhaltlich sinnvolle Untergruppen?\n")

K = 3
person_names  = by_type.get("Person", [])
person_vecs   = seed_vecs.get("Person")

if person_vecs is None or len(person_names) < K:
    print(f"  Zu wenig Person-Daten ({len(person_names)} Namen).")
else:
    km = KMeans(n_clusters=K, n_init=20, random_state=42)
    km.fit(person_vecs)
    labels = km.labels_
    centers = km.cluster_centers_
    # Re-normalise centers (KMeans operates in Euclidean space)
    norms = np.linalg.norm(centers, axis=1, keepdims=True)
    centers_normed = centers / np.where(norms > 0, norms, 1)

    # ── Cluster-Zusammensetzung ───────────────────────────────────────────────
    for k in range(K):
        members = [person_names[i] for i, lbl in enumerate(labels) if lbl == k]
        # Intra-cluster mean similarity to this center
        mask = labels == k
        intra_sims = person_vecs[mask] @ centers_normed[k]

        print(f"Cluster {k+1}  ({len(members)} Namen, "
              f"intra-sim mean={intra_sims.mean():.3f})")

        # Show up to 20 members, sorted by similarity to center descending
        member_sims = list(zip(members, intra_sims.tolist()))
        member_sims.sort(key=lambda x: -x[1])
        line = ", ".join(f"{n}({s:.2f})" for n, s in member_sims[:20])
        if len(member_sims) > 20:
            line += f" … +{len(member_sims)-20} weitere"
        print(f"  {line}\n")

    # ── Top-10 unbekannte Corpus-Tokens pro Cluster-Zentrum ──────────────────
    print("-" * 65)
    print("Top-10 unbekannte Corpus-Tokens pro Cluster-Zentrum:\n")

    for k in range(K):
        c = centers_normed[k]
        sims = corpus_vecs @ c
        order = np.argsort(-sims)

        rows = []
        for i in order:
            tok  = corpus_tokens[i]
            sim  = float(sims[i])
            known = tok.lower() in seed_lc
            if known:
                continue  # only show unknown tokens
            rows.append((tok, sim, counter[tok]))
            if len(rows) == 10:
                break

        # For context: what's the mean sim of seed Persons to this center?
        seed_sim_mean = float((person_vecs @ c).mean())
        # And what's the mean sim of seed Orte (if any)?
        ort_sim_mean  = float((seed_vecs["Ort"] @ c).mean()) if "Ort" in seed_vecs else float("nan")

        print(f"Cluster {k+1}-Zentrum  "
              f"(Person-Seed mean={seed_sim_mean:.3f}, Ort-Seed mean={ort_sim_mean:.3f})")
        print(f"  {'Token':<24}  {'Sim':>5}  {'Freq':>5}")
        print(f"  {'-'*40}")
        for tok, sim, freq in rows:
            print(f"  {tok:<24}  {sim:.3f}  {freq:5d}×")
        print()

    # ── Vergleich: Homogenität pro Cluster vs. Gesamt-Zentrum ────────────────
    print("-" * 65)
    print("Homogenitäts-Vergleich: Cluster-Zentren vs. ein Gesamt-Zentrum\n")
    global_center = center(person_vecs)
    global_top10_new = []
    for i in np.argsort(-(corpus_vecs @ global_center)):
        tok = corpus_tokens[i]
        if tok.lower() not in seed_lc:
            global_top10_new.append(tok)
        if len(global_top10_new) == 10:
            break

    # Per-cluster top-10 new tokens (deduplicated across clusters)
    per_cluster_new: list[list[str]] = []
    for k in range(K):
        c = centers_normed[k]
        rows_k = []
        for i in np.argsort(-(corpus_vecs @ c)):
            tok = corpus_tokens[i]
            if tok.lower() not in seed_lc:
                rows_k.append(tok)
            if len(rows_k) == 10:
                break
        per_cluster_new.append(rows_k)

    all_cluster_new = set(t for r in per_cluster_new for t in r)
    overlap_with_global = all_cluster_new & set(global_top10_new)

    print(f"  Gesamt-Zentrum Top-10 neu: {', '.join(global_top10_new)}")
    for k, rows_k in enumerate(per_cluster_new):
        unique_to_cluster = [t for t in rows_k if t not in set(global_top10_new)]
        print(f"  Cluster {k+1} Top-10 neu:    {', '.join(rows_k)}")
        if unique_to_cluster:
            print(f"    → nur in diesem Cluster: {', '.join(unique_to_cluster)}")
    print(f"\n  Überschneidung Cluster∪ ∩ Global: {len(overlap_with_global)}/10 Tokens")
    unique_across_clusters = all_cluster_new - set(global_top10_new)
    print(f"  Nur durch Cluster gefunden (nicht im Global-Top-10): "
          f"{len(unique_across_clusters)} Tokens")
    if unique_across_clusters:
        print(f"    {', '.join(sorted(unique_across_clusters))}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 5 – Optimales k per Silhouette-Score, alle Typen
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 5 – Optimales k per Silhouette-Score (alle Typen ≥ 5 Einträge)")
print("=" * 65)

MIN_ENTRIES = 5
TOP_NEW     = 5

for typ in ("Person", "Ort", "Organisation", "Konzept"):
    names = by_type.get(typ, [])
    vecs  = seed_vecs.get(typ)
    if vecs is None or len(names) < MIN_ENTRIES:
        print(f"\n{typ}: übersprungen ({len(names)} Namen < {MIN_ENTRIES})")
        continue

    n      = len(vecs)
    k_max  = min(8, n // 3)
    k_min  = 2
    if k_min > k_max:
        print(f"\n{typ}: zu wenige Einträge für k-Sweep ({n} Namen, k_max={k_max})")
        continue

    print(f"\n{'─'*65}")
    print(f"Typ: {typ}  ({n} Namen/Aliases, k={k_min}…{k_max})")
    print(f"{'─'*65}")

    # ── Silhouette-Sweep ──────────────────────────────────────────────────────
    scores: list[tuple[int, float, KMeans]] = []
    for k in range(k_min, k_max + 1):
        km_k = KMeans(n_clusters=k, n_init=20, random_state=42)
        lbls = km_k.fit_predict(vecs)
        # Silhouette requires ≥2 distinct labels
        if len(set(lbls)) < 2:
            continue
        sil = silhouette_score(vecs, lbls, metric="cosine")
        scores.append((k, sil, km_k))

    if not scores:
        print("  Keine auswertbaren k-Werte.")
        continue

    # Print score table
    print(f"  {'k':>3}  {'Silhouette':>11}  {'Δ':>7}")
    prev = None
    for k, sil, _ in scores:
        delta = f"{sil - prev:+.4f}" if prev is not None else "      —"
        marker = " ◀ max" if sil == max(s for _, s, _ in scores) else ""
        print(f"  {k:>3}  {sil:>11.4f}  {delta}{marker}")
        prev = sil

    best_k, best_sil, best_km = max(scores, key=lambda t: t[1])
    print(f"\n  Optimales k = {best_k}  (Silhouette = {best_sil:.4f})")

    labels  = best_km.labels_
    centers = best_km.cluster_centers_
    norms   = np.linalg.norm(centers, axis=1, keepdims=True)
    centers = centers / np.where(norms > 0, norms, 1)

    # ── Cluster-Zusammensetzung ───────────────────────────────────────────────
    print()
    for k in range(best_k):
        mask    = labels == k
        members = [names[i] for i, lbl in enumerate(labels) if lbl == k]
        c       = centers[k]
        intra   = float(vecs[mask].dot(c).mean())

        member_sims = sorted(zip(members, vecs[mask].dot(c).tolist()),
                             key=lambda x: -x[1])
        shown = ", ".join(f"{nm}({s:.2f})" for nm, s in member_sims[:12])
        if len(member_sims) > 12:
            shown += f" … +{len(member_sims)-12}"
        print(f"  Cluster {k+1}/{best_k}  n={len(members)}  intra={intra:.3f}")
        print(f"    {shown}")

        # Top-5 new corpus tokens near this cluster center
        new_rows = []
        for i in np.argsort(-(corpus_vecs @ c)):
            tok = corpus_tokens[i]
            if tok.lower() not in seed_lc:
                new_rows.append((tok, float(corpus_vecs[i] @ c), counter[tok]))
            if len(new_rows) == TOP_NEW:
                break
        cands = "  ".join(f"{t}({s:.2f}, {f}×)" for t, s, f in new_rows)
        print(f"    → neu: {cands}\n")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 6 – K-Means+Elbow-Schutz vs. DBSCAN (alle Typen ≥ 5 Einträge)
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 6 – Verfahrensvergleich: K-Means+Elbow vs. DBSCAN")
print("=" * 65)

ELBOW_DELTA   = 0.02          # min. Silhouette-Gewinn um weiterzumachen
NOISE_CEILING = 0.30          # max. erlaubter Rausch-Anteil bei DBSCAN
DBSCAN_EPS_CANDIDATES  = [0.10, 0.15, 0.20, 0.25]
DBSCAN_MIN_SAMPLES     = 2
TOP_NEW_6   = 5
MIN_ENTRIES_6 = 5


def _top_new(center_vec: np.ndarray, n: int = TOP_NEW_6) -> list[tuple[str, float, int]]:
    """Top-n unbekannte Corpus-Tokens nach Cosine-Similarity zum Zentrum."""
    sims = corpus_vecs @ center_vec
    rows = []
    for i in np.argsort(-sims):
        tok = corpus_tokens[i]
        if tok.lower() not in seed_lc:
            rows.append((tok, float(sims[i]), counter[tok]))
        if len(rows) == n:
            break
    return rows


def _format_new(rows: list[tuple[str, float, int]]) -> str:
    return "  ".join(f"{t}({s:.2f},{f}×)" for t, s, f in rows)


def _cluster_center(vecs: np.ndarray, mask: np.ndarray) -> np.ndarray:
    c = vecs[mask].mean(axis=0)
    n = np.linalg.norm(c)
    return c / n if n > 0 else c


# ─── summary table collected across types ────────────────────────────────────
summary_rows: list[dict] = []

for typ in ("Person", "Ort", "Organisation", "Konzept"):
    names = by_type.get(typ, [])
    vecs  = seed_vecs.get(typ)
    if vecs is None or len(names) < MIN_ENTRIES_6:
        continue
    n = len(vecs)

    print(f"\n{'═'*65}")
    print(f"  TYP: {typ}  ({n} Namen/Aliases)")
    print(f"{'═'*65}")

    # ── Verfahren A: K-Means + Elbow-Schutz ──────────────────────────────────
    print("\n  ── Verfahren A: K-Means + Elbow-Schutz (Δ < 0.02 stoppt) ──────")

    k_max_a = min(8, n // 3)
    scores_a: list[tuple[int, float, KMeans]] = []
    for k in range(2, k_max_a + 1):
        km = KMeans(n_clusters=k, n_init=20, random_state=42)
        lbls = km.fit_predict(vecs)
        if len(set(lbls)) < 2:
            continue
        sil = silhouette_score(vecs, lbls, metric="cosine")
        scores_a.append((k, sil, km))

    # Elbow-protected selection: first k where gain < ELBOW_DELTA
    chosen_a_idx = 0
    for i in range(1, len(scores_a)):
        gain = scores_a[i][1] - scores_a[i-1][1]
        if gain < ELBOW_DELTA:
            break
        chosen_a_idx = i
    best_k_a, best_sil_a, best_km_a = scores_a[chosen_a_idx]

    # Print score sweep
    print(f"  {'k':>3}  {'Silhouette':>10}  {'Δ':>7}  {'gewählt':>8}")
    prev_sil = None
    for i, (k, sil, _) in enumerate(scores_a):
        delta_str = f"{sil - prev_sil:+.4f}" if prev_sil is not None else "      —"
        chosen_str = "◀ gewählt" if i == chosen_a_idx else ""
        print(f"  {k:>3}  {sil:>10.4f}  {delta_str}  {chosen_str}")
        prev_sil = sil

    print(f"\n  → k={best_k_a}  Silhouette={best_sil_a:.4f}")

    labels_a  = best_km_a.labels_
    centers_a = best_km_a.cluster_centers_.copy()
    norms_a   = np.linalg.norm(centers_a, axis=1, keepdims=True)
    centers_a /= np.where(norms_a > 0, norms_a, 1)

    new_tokens_a: list[str] = []
    for k in range(best_k_a):
        mask    = labels_a == k
        members = [names[i] for i, lbl in enumerate(labels_a) if lbl == k]
        c       = centers_a[k]
        intra   = float(vecs[mask].dot(c).mean())
        ms      = sorted(zip(members, vecs[mask].dot(c).tolist()), key=lambda x: -x[1])
        shown   = ", ".join(f"{nm}({s:.2f})" for nm, s in ms[:8])
        if len(ms) > 8:
            shown += f" +{len(ms)-8}"
        top_new = _top_new(c)
        new_tokens_a += [t for t, _, _ in top_new]
        print(f"\n  A-Cluster {k+1}/{best_k_a}  n={len(members)}  intra={intra:.3f}")
        print(f"    {shown}")
        print(f"    → neu: {_format_new(top_new)}")

    # ── Verfahren B: DBSCAN ───────────────────────────────────────────────────
    print(f"\n  ── Verfahren B: DBSCAN (min_samples={DBSCAN_MIN_SAMPLES}, "
          f"eps-Kandidaten={DBSCAN_EPS_CANDIDATES}) ──")

    best_eps_b    = None
    best_db_b     = None
    best_n_clust  = -1
    best_noise_r  = 1.0

    print(f"  {'eps':>6}  {'Cluster':>8}  {'Rauschen':>9}  {'Rausch-%':>9}  {'OK':>4}")
    for eps in DBSCAN_EPS_CANDIDATES:
        db = DBSCAN(eps=eps, min_samples=DBSCAN_MIN_SAMPLES, metric="cosine")
        lbls = db.fit_predict(vecs)
        n_clust = len(set(lbls)) - (1 if -1 in lbls else 0)
        n_noise = (lbls == -1).sum()
        noise_r = n_noise / n if n > 0 else 1.0
        ok = "✓" if noise_r < NOISE_CEILING and n_clust >= 2 else "✗"
        print(f"  {eps:>6.2f}  {n_clust:>8}  {n_noise:>9}  {noise_r:>8.0%}  {ok:>4}")
        # Prefer: noise_r < ceiling, then maximize clusters, then minimize noise
        if noise_r < NOISE_CEILING and n_clust >= 2:
            if (n_clust > best_n_clust or
                    (n_clust == best_n_clust and noise_r < best_noise_r)):
                best_n_clust = n_clust
                best_noise_r = noise_r
                best_eps_b   = eps
                best_db_b    = db

    new_tokens_b: list[str] = []
    if best_db_b is None:
        print("\n  → Kein DBSCAN-Parameter erfüllt die Bedingungen.")
    else:
        labels_b = best_db_b.labels_
        n_noise_b = (labels_b == -1).sum()
        print(f"\n  → bestes eps={best_eps_b}  "
              f"Cluster={best_n_clust}  Rauschen={n_noise_b}/{n} "
              f"({best_noise_r:.0%})")

        clust_ids = sorted(set(labels_b) - {-1})
        for cid in clust_ids:
            mask    = labels_b == cid
            members = [names[i] for i, lbl in enumerate(labels_b) if lbl == cid]
            c       = _cluster_center(vecs, mask)
            intra   = float(vecs[mask].dot(c).mean())
            ms      = sorted(zip(members, vecs[mask].dot(c).tolist()), key=lambda x: -x[1])
            shown   = ", ".join(f"{nm}({s:.2f})" for nm, s in ms[:8])
            if len(ms) > 8:
                shown += f" +{len(ms)-8}"
            top_new = _top_new(c)
            new_tokens_b += [t for t, _, _ in top_new]
            print(f"\n  B-Cluster {cid+1}/{best_n_clust}  n={len(members)}  intra={intra:.3f}")
            print(f"    {shown}")
            print(f"    → neu: {_format_new(top_new)}")

        # Noise members
        noise_members = [names[i] for i, lbl in enumerate(labels_b) if lbl == -1]
        if noise_members:
            shown_noise = ", ".join(noise_members[:15])
            if len(noise_members) > 15:
                shown_noise += f" … +{len(noise_members)-15}"
            print(f"\n  Rauschen ({n_noise_b}): {shown_noise}")

    # ── Mini-Vergleich ────────────────────────────────────────────────────────
    set_a = set(new_tokens_a)
    set_b = set(new_tokens_b)
    only_a  = set_a - set_b
    only_b  = set_b - set_a
    overlap = set_a & set_b
    print(f"\n  ── Kandidaten-Vergleich ({typ}) ──")
    print(f"  A gesamt: {len(set_a)}  B gesamt: {len(set_b)}  "
          f"Überschneidung: {len(overlap)}")
    if only_a:
        print(f"  Nur A:   {', '.join(sorted(only_a))}")
    if only_b:
        print(f"  Nur B:   {', '.join(sorted(only_b))}")

    summary_rows.append({
        "typ":     typ,
        "n":       n,
        "km_k":    best_k_a,
        "km_sil":  best_sil_a,
        "db_eps":  best_eps_b,
        "db_k":    best_n_clust if best_db_b else 0,
        "db_noise":f"{best_noise_r:.0%}" if best_db_b else "—",
        "only_a":  len(only_a),
        "only_b":  len(only_b),
        "overlap": len(overlap),
    })

# ── Gesamtvergleich ───────────────────────────────────────────────────────────
print(f"\n{'═'*65}")
print("  GESAMTVERGLEICH")
print(f"{'═'*65}")
print(f"  {'Typ':<14}  {'n':>4}  "
      f"{'A: k':>5}  {'A: Sil':>7}  "
      f"{'B: eps':>7}  {'B: k':>5}  {'B: Rausch':>9}  "
      f"{'nur-A':>6}  {'nur-B':>6}  {'∩':>4}")
print(f"  {'-'*85}")
for r in summary_rows:
    db_eps = f"{r['db_eps']:.2f}" if r['db_eps'] else "  —"
    print(f"  {r['typ']:<14}  {r['n']:>4}  "
          f"{r['km_k']:>5}  {r['km_sil']:>7.4f}  "
          f"{db_eps:>7}  {r['db_k']:>5}  {r['db_noise']:>9}  "
          f"{r['only_a']:>6}  {r['only_b']:>6}  {r['overlap']:>4}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 7 – Unterraum-Analyse
# ══════════════════════════════════════════════════════════════════════════════

from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import confusion_matrix

print("\n" + "=" * 65)
print("TEST 7 – Unterraum-Analyse: Wo trennen sich Typen?")
print("=" * 65)

# ── Teil A – Differenzvektor Person vs. Ort ───────────────────────────────────

print("\n── Teil A: Differenzvektor Person vs. Ort ──────────────────────")

if "Person" in seed_vecs and "Ort" in seed_vecs:
    person_center_7 = seed_vecs["Person"].mean(axis=0)
    person_center_7 /= np.linalg.norm(person_center_7)
    ort_center_7 = seed_vecs["Ort"].mean(axis=0)
    ort_center_7 /= np.linalg.norm(ort_center_7)

    diff_vector = person_center_7 - ort_center_7
    diff_vector = diff_vector / np.linalg.norm(diff_vector)

    person_proj = seed_vecs["Person"] @ diff_vector
    ort_proj    = seed_vecs["Ort"]    @ diff_vector

    print(f"  Person-Projektionen:  mean={person_proj.mean():+.3f}  "
          f"std={person_proj.std():.3f}  min={person_proj.min():+.3f}  max={person_proj.max():+.3f}")
    print(f"  Ort-Projektionen:     mean={ort_proj.mean():+.3f}  "
          f"std={ort_proj.std():.3f}  min={ort_proj.min():+.3f}  max={ort_proj.max():+.3f}")

    # Overlap: Anteil Person-Projektionen < Ort-Median und umgekehrt
    ort_median = float(np.median(ort_proj))
    person_median = float(np.median(person_proj))
    person_below_ort_med = (person_proj < ort_median).mean()
    ort_above_person_med = (ort_proj > person_median).mean()
    print(f"  Overlap: {person_below_ort_med*100:.1f}% der Personen unter Ort-Median  |  "
          f"{ort_above_person_med*100:.1f}% der Orte über Person-Median")
    print(f"  Trennbarkeit auf Diff-Achse: "
          + ("gut ✓" if person_below_ort_med < 0.20 and ort_above_person_med < 0.20 else
             "mäßig" if person_below_ort_med < 0.40 and ort_above_person_med < 0.40 else "schwach ✗"))

    # Teil B – Unbekannte Corpus-Tokens auf Diff-Achse projizieren
    print("\n── Teil B: Unbekannte Corpus-Tokens auf Diff-Achse ────────────")

    # Filter: nur Tokens die nicht im Seed sind
    novel_mask = np.array([corpus_tokens[i].lower() not in seed_lc
                           for i in range(len(corpus_tokens))])
    novel_tokens = [corpus_tokens[i] for i in range(len(corpus_tokens)) if novel_mask[i]]
    novel_vecs   = corpus_vecs[novel_mask]

    novel_proj = novel_vecs @ diff_vector

    # Sort
    order = np.argsort(novel_proj)[::-1]
    TOP_B = 15

    print(f"  Top-{TOP_B} Person-seitig (hoher Wert):")
    for idx in order[:TOP_B]:
        tok = novel_tokens[idx]
        print(f"    {tok:<28}  proj={novel_proj[idx]:+.3f}  freq={counter[tok]}×")

    print(f"\n  Top-{TOP_B} Ort-seitig (niedriger Wert):")
    for idx in order[-TOP_B:][::-1]:
        tok = novel_tokens[idx]
        print(f"    {tok:<28}  proj={novel_proj[idx]:+.3f}  freq={counter[tok]}×")
else:
    print("  Person oder Ort fehlen in seed_vecs — Teil A+B übersprungen.")
    diff_vector = None

# ── Teil C – PCA auf allen Seed-Embeddings ────────────────────────────────────

print("\n── Teil C: PCA auf Seed-Embeddings (alle Typen) ───────────────")

TYPES_7 = [t for t in ["Person", "Ort", "Organisation", "Konzept"] if t in seed_vecs]

all_vecs_c  = np.vstack([seed_vecs[t] for t in TYPES_7])
all_labels_c = np.concatenate([[t] * len(seed_vecs[t]) for t in TYPES_7])

pca = PCA(n_components=min(10, all_vecs_c.shape[1]))
pca.fit(all_vecs_c)
explained = pca.explained_variance_ratio_

print(f"  Erklärte Varianz: PC1={explained[0]*100:.2f}%  PC2={explained[1]*100:.2f}%  "
      f"PC3={explained[2]*100:.2f}%  Σ(PC1+PC2)={sum(explained[:2])*100:.2f}%")

proj_c = pca.transform(all_vecs_c)

# Typ-Mittelwert im PCA-Raum
print(f"\n  Typ-Zentren in PC1/PC2:")
print(f"  {'Typ':<14}  {'PC1-mean':>9}  {'PC2-mean':>9}  {'n':>4}")
for t in TYPES_7:
    mask_t = all_labels_c == t
    p = proj_c[mask_t]
    print(f"  {t:<14}  {p[:,0].mean():>+9.3f}  {p[:,1].mean():>+9.3f}  {mask_t.sum():>4}")

# Vergleich: Typ-Separierung in PC-Raum vs. Cosine-Sim im Vollraum
# → Silhouette auf PC1+PC2 vs. Silhouette auf allen 768 Dims
le = LabelEncoder()
labels_enc = le.fit_transform(all_labels_c)

if len(set(labels_enc)) >= 2:
    sil_full = silhouette_score(all_vecs_c,   labels_enc, metric="cosine")
    sil_pc2  = silhouette_score(proj_c[:, :2], labels_enc, metric="euclidean")
    sil_pc10 = silhouette_score(proj_c,        labels_enc, metric="euclidean")
    print(f"\n  Silhouette-Score:")
    print(f"    Voller 768-dim Raum (cosine):  {sil_full:.4f}")
    print(f"    PC1+PC2 (euclidean):           {sil_pc2:.4f}")
    print(f"    PC1..PC10 (euclidean):         {sil_pc10:.4f}")
    better = "PC1+PC2 besser" if sil_pc2 > sil_full else "Vollraum besser"
    print(f"  → {better} für Typ-Trennung")

# ── Teil D – Linear Probing ────────────────────────────────────────────────────

print("\n── Teil D: Linear Probing (LogisticRegression, 5-Fold CV) ─────")

# Nur Typen mit ≥5 Einträgen (Rohzahl, nicht Aliases)
type_counts_raw = {t: sum(1 for e in seed if e.get("typ") == t) for t in TYPES_7}
valid_types = [t for t in TYPES_7 if type_counts_raw[t] >= 5]

if len(valid_types) < 2:
    print("  Zu wenige Typen mit ≥5 Einträgen — übersprungen.")
else:
    # Matrix aus Seed-Embeddings (alle Aliases pro Entity → nehme einen Vektor pro Entity)
    # Um sauber zu bleiben: einen Vektor pro Name/Alias (wie bereits in seed_vecs)
    X = np.vstack([seed_vecs[t] for t in valid_types])
    y_raw = np.concatenate([[t] * len(seed_vecs[t]) for t in valid_types])
    le_d = LabelEncoder()
    y = le_d.fit_transform(y_raw)

    clf = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")

    print(f"  Klassen: {list(le_d.classes_)}  (n={len(y)})")
    print(f"  5-Fold CV Accuracy:  mean={scores.mean():.3f}  std={scores.std():.3f}")
    print(f"  Scores pro Fold: " + "  ".join(f"{s:.3f}" for s in scores))

    # Confusion Matrix auf vollem Datensatz (Train=Test, nur für Überblick)
    clf.fit(X, y)
    y_pred = clf.predict(X)
    cm = confusion_matrix(y, y_pred)

    print(f"\n  Confusion Matrix (Train=Test):")
    header = "  " + " " * 14 + "".join(f"{le_d.classes_[j]:>14}" for j in range(len(le_d.classes_)))
    print(header)
    for i, row in enumerate(cm):
        row_str = "  " + f"{le_d.classes_[i]:<14}" + "".join(f"{v:>14}" for v in row)
        print(row_str)

    # Per-Klasse Precision/Recall aus CM
    print(f"\n  Per-Klasse (aus CM, Train=Test — obere Schranke):")
    for i, cls in enumerate(le_d.classes_):
        tp = cm[i, i]
        prec = tp / cm[:, i].sum() if cm[:, i].sum() > 0 else 0.0
        rec  = tp / cm[i, :].sum() if cm[i, :].sum() > 0 else 0.0
        print(f"    {cls:<14}  Prec={prec:.2f}  Rec={rec:.2f}  n={cm[i].sum()}")

    print(f"\n  Interpretation:")
    acc = scores.mean()
    baseline = 1.0 / len(valid_types)
    print(f"    Baseline (Zufall): {baseline:.3f}  →  Gewinn: {(acc-baseline)/baseline*100:.0f}% über Zufall")
    if acc > 0.80:
        print("    → Typ-Information im Embedding deutlich vorhanden ✓")
    elif acc > 0.60:
        print("    → Mäßige Typ-Information; Cosine-Similarity allein reicht möglicherweise nicht")
    else:
        print("    → Schwache Typ-Trennung; andere Features nötig ✗")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 8 – Classifier statt Cosine-Similarity
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 8 – Classifier-basierte Typ-Zuweisung")
print("=" * 65)

TOP_CLF = 20

TYPES_8 = [t for t in ["Person", "Ort", "Organisation", "Konzept"] if t in seed_vecs]
type_counts_8 = {t: sum(1 for e in seed if e.get("typ") == t) for t in TYPES_8}
valid_8 = [t for t in TYPES_8 if type_counts_8[t] >= 5]

if len(valid_8) < 2:
    print("  Zu wenige Typen mit ≥5 Einträgen — übersprungen.")
    clf8 = None
else:
    X8 = np.vstack([seed_vecs[t] for t in valid_8])
    y8_raw = np.concatenate([[t] * len(seed_vecs[t]) for t in valid_8])
    le8 = LabelEncoder()
    y8 = le8.fit_transform(y8_raw)

    clf8 = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
    clf8.fit(X8, y8)
    print(f"  Classifier trainiert auf {len(y8)} Embeddings, Klassen: {list(le8.classes_)}")

    # Unbekannte Corpus-Tokens klassifizieren
    novel_mask8 = np.array([corpus_tokens[i].lower() not in seed_lc
                             for i in range(len(corpus_tokens))])
    novel_tokens8 = [corpus_tokens[i] for i in range(len(corpus_tokens)) if novel_mask8[i]]
    novel_vecs8   = corpus_vecs[novel_mask8]

    proba8 = clf8.predict_proba(novel_vecs8)  # (N, n_classes)

    # Cosine-Similarity Kandidaten aus Test 2/3 (als Vergleich)
    # Rekonstruiere: center pro Typ, top-20 per cosine
    cosine_cands: dict[str, set[str]] = {}
    for t in valid_8:
        c = seed_vecs[t].mean(axis=0)
        c /= np.linalg.norm(c)
        sims = novel_vecs8 @ c
        top_idx = np.argsort(sims)[::-1][:TOP_CLF]
        cosine_cands[t] = {novel_tokens8[i] for i in top_idx}

    print()
    clf_cands: dict[str, list[tuple[str, float]]] = {}
    for ci, t in enumerate(le8.classes_):
        col = proba8[:, ci]
        top_idx = np.argsort(col)[::-1][:TOP_CLF]
        cands = [(novel_tokens8[i], float(col[i])) for i in top_idx]
        clf_cands[t] = cands

        cos_set = cosine_cands.get(t, set())
        clf_set = {tok for tok, _ in cands}
        only_clf   = clf_set - cos_set
        only_cos   = cos_set - clf_set
        both       = clf_set & cos_set

        print(f"  ── Typ: {t} ─────────────────────────────────────")
        print(f"  {'Token':<28}  {'Prob':>6}  {'Freq':>5}  {'Methode'}")
        print(f"  {'-'*58}")
        for tok, prob in cands:
            tag = "beide" if tok in cos_set else "clf  "
            print(f"  {tok:<28}  {prob:>6.3f}  {counter[tok]:>5}×  {tag}")
        print(f"\n  Überschneidung mit Cosine-Top-{TOP_CLF}: {len(both)}  "
              f"nur CLF: {len(only_clf)}  nur Cosine: {len(only_cos)}")
        print()


# ══════════════════════════════════════════════════════════════════════════════
# TEST 9 – Kontextuelle Embeddings (mBERT token-level)
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 9 – Kontextuelle Embeddings (mBERT mean-pooling per Token)")
print("=" * 65)

import torch
from transformers import AutoTokenizer, AutoModel

BERT_MODEL = "bert-base-multilingual-cased"
MAX_BERT_SEGS = 300   # Obergrenze für Segmente (Laufzeit)
TOP_CTX = 5           # max. Sätze pro Token

print(f"  Lade {BERT_MODEL} …")
bert_tok = AutoTokenizer.from_pretrained(BERT_MODEL)
bert_model = AutoModel.from_pretrained(BERT_MODEL)
bert_model.eval()

# Wähle Kandidaten zum Vergleich: alle Seed-Namen der validen Typen
# + die Top-10 Corpus-Novel-Tokens pro Typ (aus Classifier)
compare_tokens: list[str] = []
compare_types: list[str] = []

for t in valid_8:
    for name in by_type[t][:20]:   # max 20 Seed-Namen pro Typ
        compare_tokens.append(name)
        compare_types.append(t)

print(f"  Vergleichs-Tokens: {len(compare_tokens)} Seed-Namen über {len(valid_8)} Typen")

# Segmente vorbereiten (gekürzte Liste für Laufzeit)
ctx_segs = [s.get("text", "") for s in content_segs if len(s.get("text","")) > 20]
ctx_segs = ctx_segs[:MAX_BERT_SEGS]
print(f"  Nutze {len(ctx_segs)} Segmente (von {len(content_segs)} gesamt)")


def bert_contextual_embedding(token: str, segments: list[str],
                               top_ctx: int = TOP_CTX) -> np.ndarray | None:
    """
    Mittleres kontextuelles Embedding eines Tokens über alle Segmente
    in denen es vorkommt. Nutzt mean-pooling der WordPiece-Subtoken-Vektoren
    an der Token-Position aus der letzten BERT-Schicht.
    Gibt None zurück wenn der Token in keinem Segment gefunden wird.
    """
    token_lower = token.lower()
    # Finde Segmente mit diesem Token (case-insensitive)
    hit_segs = [s for s in segments if token_lower in s.lower()][:top_ctx]
    if not hit_segs:
        return None

    vecs = []
    for sent in hit_segs:
        enc = bert_tok(sent, return_tensors="pt", truncation=True,
                       max_length=128, padding=True)
        with torch.no_grad():
            out = bert_model(**enc)
        hidden = out.last_hidden_state[0]  # (seq_len, 768)

        # Finde Position(en) des Tokens via Subword-Matching
        ids = enc["input_ids"][0].tolist()
        subwords = bert_tok.convert_ids_to_tokens(ids)

        # Alle zusammenhängenden Subword-Spans die dem Token entsprechen
        tok_lower_pieces = bert_tok.tokenize(token.lower())
        n = len(tok_lower_pieces)
        span_vecs = []
        for start in range(len(subwords) - n + 1):
            window = [sw.lstrip("##").lower() for sw in subwords[start:start+n]]
            target = [p.lstrip("##").lower() for p in tok_lower_pieces]
            if window == target:
                span_vecs.append(hidden[start:start+n].mean(dim=0).numpy())
        if span_vecs:
            vecs.append(np.mean(span_vecs, axis=0))

    if not vecs:
        return None

    mean_vec = np.mean(vecs, axis=0).astype(np.float32)
    norm = np.linalg.norm(mean_vec)
    return mean_vec / norm if norm > 0 else None


print("  Berechne kontextuelle Embeddings für Vergleichs-Tokens …")
ctx_vecs_list: list[np.ndarray] = []
ctx_tokens_valid: list[str] = []
ctx_types_valid: list[str] = []

for tok, typ in zip(compare_tokens, compare_types):
    v = bert_contextual_embedding(tok, ctx_segs)
    if v is not None:
        ctx_vecs_list.append(v)
        ctx_tokens_valid.append(tok)
        ctx_types_valid.append(typ)

if len(ctx_vecs_list) < 4:
    print("  Zu wenige Treffer in Segmenten — Test 9 übersprungen.")
else:
    ctx_mat = np.vstack(ctx_vecs_list)
    print(f"  Kontextuelle Embeddings: {ctx_mat.shape[0]} Tokens mit Treffer "
          f"(von {len(compare_tokens)} versucht)")

    le9 = LabelEncoder()
    y9 = le9.fit_transform(ctx_types_valid)

    # ── Silhouette-Vergleich ──
    print("\n  ── Silhouette-Vergleich: statisch vs. kontextuell ──────────")

    # Statische Embeddings für dieselben Tokens
    static_vecs9 = embed(ctx_tokens_valid)  # re-use embed() from SentenceTransformer

    if len(set(y9)) >= 2:
        sil_static = silhouette_score(static_vecs9, y9, metric="cosine")
        sil_ctx    = silhouette_score(ctx_mat,      y9, metric="cosine")
        print(f"  Statisch (SentenceTransformer):  Silhouette={sil_static:.4f}")
        print(f"  Kontextuell (mBERT):              Silhouette={sil_ctx:.4f}")
        winner = "kontextuell ✓" if sil_ctx > sil_static else "statisch ✓"
        print(f"  → {winner} besser für Typ-Trennung auf diesen Tokens")

    # ── Classifier-Accuracy Vergleich ──
    print("\n  ── Classifier-Accuracy: statisch vs. kontextuell ──────────")
    valid_cls9 = [t for t in le9.classes_ if list(ctx_types_valid).count(t) >= 3]
    if len(valid_cls9) >= 2:
        mask9 = np.array([t in valid_cls9 for t in ctx_types_valid])
        X9s = static_vecs9[mask9]
        X9c = ctx_mat[mask9]
        y9f = le9.transform([ctx_types_valid[i] for i in range(len(ctx_types_valid)) if mask9[i]])

        n_splits9 = min(5, min(np.bincount(y9f)))
        if n_splits9 >= 2:
            cv9 = StratifiedKFold(n_splits=n_splits9, shuffle=True, random_state=42)
            clf9s = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
            clf9c = LogisticRegression(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
            acc_s = cross_val_score(clf9s, X9s, y9f, cv=cv9, scoring="accuracy").mean()
            acc_c = cross_val_score(clf9c, X9c, y9f, cv=cv9, scoring="accuracy").mean()
            print(f"  Statisch  {n_splits9}-Fold Accuracy: {acc_s:.3f}")
            print(f"  Kontextuell {n_splits9}-Fold Accuracy: {acc_c:.3f}")
            winner2 = "kontextuell" if acc_c > acc_s + 0.02 else (
                      "statisch" if acc_s > acc_c + 0.02 else "gleichauf")
            print(f"  → {winner2} gewinnt")
        else:
            print("  Zu wenige Samples pro Klasse für Cross-Validation.")
    else:
        print("  Zu wenige Klassen mit ≥3 Samples — Classifier-Vergleich übersprungen.")

    # ── Differenzvektor-Overlap Vergleich ──
    print("\n  ── Differenzvektor Person vs. Ort ──────────────────────────")
    if "Person" in set(ctx_types_valid) and "Ort" in set(ctx_types_valid):
        p_mask9 = np.array([t == "Person" for t in ctx_types_valid])
        o_mask9 = np.array([t == "Ort"    for t in ctx_types_valid])

        if p_mask9.sum() >= 2 and o_mask9.sum() >= 2:
            for label, mat in [("Statisch   ", static_vecs9), ("Kontextuell", ctx_mat)]:
                pc = mat[p_mask9].mean(axis=0); pc /= np.linalg.norm(pc)
                oc = mat[o_mask9].mean(axis=0); oc /= np.linalg.norm(oc)
                dv = pc - oc; dv /= np.linalg.norm(dv)
                pp = mat[p_mask9] @ dv
                op = mat[o_mask9] @ dv
                p_below = (pp < float(np.median(op))).mean()
                o_above = (op > float(np.median(pp))).mean()
                print(f"  {label}:  Person mean={pp.mean():+.3f}  Ort mean={op.mean():+.3f}  "
                      f"Overlap P<Ort-Med={p_below*100:.0f}%  O>P-Med={o_above*100:.0f}%")
        else:
            print("  Nicht genug Person/Ort Tokens mit Kontext-Treffer.")
    else:
        print("  Person oder Ort nicht in ctx_types_valid — Differenzvektor übersprungen.")

    print("\n  ── Fazit ────────────────────────────────────────────────────")
    print("  Kontextuelle Embeddings sind aufwändiger (mBERT pro Satz).")
    print("  Lohnt sich wenn Silhouette oder Accuracy ≥0.05 besser.")
    if len(set(y9)) >= 2 and 'sil_ctx' in dir():
        delta_sil = sil_ctx - sil_static
        print(f"  Silhouette-Gewinn: {delta_sil:+.4f}  "
              + ("→ kontextuelle Embeddings lohnen sich ✓" if delta_sil > 0.05
                 else "→ Gewinn marginal, statische Embeddings ausreichend"))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 10 – End-to-End: TF-IDF → kontextuelle Embeddings → Classifier
# ══════════════════════════════════════════════════════════════════════════════
#
# Verbindet: TF-IDF-Kandidaten (neu) + bert_contextual_embedding (Test 9)
#            + Classifier auf ctx_mat/ctx_types_valid (Test 9)
# Fragestellung: Wie viele Seed-Entities findet diese Pipeline?
#
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 10 – End-to-End: TF-IDF → kontextuelle Embeddings → Classifier")
print("=" * 65)

# ── Voraussetzung: Test 9 muss gelaufen sein ──────────────────────────────────
if "ctx_mat" not in dir() or ctx_mat.shape[0] < 4:
    print("  Test 9 nicht ausgeführt oder zu wenige kontextuelle Embeddings — übersprungen.")
else:

    # ── Schritt 1: TF-IDF → Kandidaten ───────────────────────────────────────
    print("\n── Schritt 1: TF-IDF Kandidaten ────────────────────────────────")

    import warnings as _warnings
    from sklearn.feature_extraction.text import TfidfVectorizer

    _texts = [s.get("text", "") for s in content_segs]

    def _tfidf_tokenize(text):
        return [m.group(1) for m in CAPITAL_RE.finditer(text)
                if len(m.group(1)) >= 3 and m.group(1) not in STOP_ALL]

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore")
        _tfidf = TfidfVectorizer(
            analyzer=_tfidf_tokenize,
            min_df=2,
            max_df=0.6,
            sublinear_tf=True,
        )
        _mat = _tfidf.fit_transform(_texts)

    _vocab      = _tfidf.get_feature_names_out()
    _max_scores = np.asarray(_mat.max(axis=0).toarray()).flatten()
    _ranked     = sorted(
        [(tok, sc) for tok, sc in zip(_vocab, _max_scores)
         if tok not in STOP_ALL],
        key=lambda x: -x[1],
    )
    tfidf_candidates = [tok for tok, _ in _ranked]   # alle, absteigend nach Score
    tfidf_score      = {tok: sc for tok, sc in _ranked}

    # Recall: wie viele Seed-Normalformen sind direkt im TF-IDF-Pool?
    seed_norms_lc = {e["normalform"].lower() for e in seed}
    tfidf_in_seed = [t for t in tfidf_candidates if t.lower() in seed_lc]
    tfidf_recall_norms = {t.lower() for t in tfidf_candidates} & seed_norms_lc

    print(f"  TF-IDF Kandidaten gesamt:         {len(tfidf_candidates)}")
    print(f"  davon im Seed (inkl. Aliases):    {len(tfidf_in_seed)}")
    print(f"  Seed-Recall auf Normalformen:     "
          f"{len(tfidf_recall_norms)}/{len(seed_norms_lc)} = "
          f"{len(tfidf_recall_norms)/len(seed_norms_lc)*100:.1f}%")

    missed_norms = sorted(seed_norms_lc - {t.lower() for t in tfidf_candidates})
    print(f"  Fehlende Seed-Normalformen ({len(missed_norms)}): "
          f"{missed_norms[:12]}{' …' if len(missed_norms) > 12 else ''}")

    # ── Schritt 2: Kontextuelle Embeddings für TF-IDF-Kandidaten ─────────────
    print("\n── Schritt 2: Kontextuelle mBERT-Embeddings (Test-9-Funktion) ──")

    cand_ctx_vecs: dict[str, np.ndarray] = {}
    n_no_ctx = 0
    for i, tok in enumerate(tfidf_candidates, 1):
        if i % 100 == 0:
            print(f"  {i}/{len(tfidf_candidates)} …", flush=True)
        v = bert_contextual_embedding(tok, ctx_segs)
        if v is not None:
            cand_ctx_vecs[tok] = v
        else:
            n_no_ctx += 1

    print(f"  Kandidaten mit Kontext-Embedding: {len(cand_ctx_vecs)}/{len(tfidf_candidates)}")
    print(f"  Ohne Kontext (nicht im Korpus):   {n_no_ctx}")

    # ── Schritt 3: Classifier trainiert auf ctx_mat (Test 9) ─────────────────
    print("\n── Schritt 3: Classifier auf kontextuellen Seed-Embeddings ────")

    from sklearn.linear_model    import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.preprocessing   import LabelEncoder

    # ctx_mat / ctx_types_valid aus Test 9: kontextuelle Embeddings der Seed-Namen
    _valid_cls = [t for t, n in Counter(ctx_types_valid).items() if n >= 3]
    if len(_valid_cls) < 2:
        print("  Zu wenige Klassen mit ≥3 Samples — abgebrochen.")
    else:
        _mask10   = np.array([t in _valid_cls for t in ctx_types_valid])
        X10       = ctx_mat[_mask10]
        y10_raw   = [ctx_types_valid[i] for i in range(len(ctx_types_valid)) if _mask10[i]]
        le10      = LabelEncoder()
        y10       = le10.fit_transform(y10_raw)

        _n_splits = min(5, min(Counter(y10_raw).values()))
        _cv10     = StratifiedKFold(n_splits=_n_splits, shuffle=True, random_state=42)
        clf10     = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs", random_state=42)

        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            _cv_acc = cross_val_score(clf10, X10, y10, cv=_cv10, scoring="accuracy")

        clf10.fit(X10, y10)
        print(f"  Klassen: {list(le10.classes_)}  n={len(y10)}")
        print(f"  {_n_splits}-Fold CV Accuracy: {_cv_acc.mean():.3f} ± {_cv_acc.std():.3f}")
        print(f"  Train-Accuracy:  {(clf10.predict(X10) == y10).mean():.3f}")

        # ── Schritt 4: Auf Kandidaten anwenden ───────────────────────────────
        print("\n── Schritt 4: Ausgabe ──────────────────────────────────────────")

        if cand_ctx_vecs:
            _cnames  = list(cand_ctx_vecs.keys())
            _cmatrix = np.vstack([cand_ctx_vecs[n] for n in _cnames])
            _probas  = clf10.predict_proba(_cmatrix)
            _pred    = le10.classes_[np.argmax(_probas, axis=1)]
            _confs   = _probas.max(axis=1)

            # Lokales Lookup: token_lc → typ (seed_lc im Modul ist ein set, kein dict)
            _seed_type_lc: dict[str, str] = {}
            for _e in seed:
                _typ = _e.get("typ", "")
                for _nm in [_e.get("normalform", "")] + list(_e.get("aliases") or []):
                    if _nm:
                        _seed_type_lc[_nm.lower()] = _typ

            # Seed-Entities im Pool: Typ korrekt?
            _seed_hits = [(n, t, c) for n, t, c in zip(_cnames, _pred, _confs)
                          if n.lower() in seed_lc]
            _correct   = sum(1 for n, t, c in _seed_hits
                             if _seed_type_lc.get(n.lower()) == t)
            print(f"  Seed-Entities im Kandidaten-Pool:       {len(_seed_hits)}")
            print(f"  davon Typ korrekt:                      "
                  f"{_correct}/{len(_seed_hits)} = "
                  f"{_correct/len(_seed_hits)*100:.1f}%" if _seed_hits else "  0")

            # Neue Kandidaten (nicht im Seed), conf ≥ 0.5
            _new = sorted(
                [(n, t, c) for n, t, c in zip(_cnames, _pred, _confs)
                 if n.lower() not in seed_lc and c >= 0.5],
                key=lambda x: -x[2],
            )
            print(f"  Neue Kandidaten (conf ≥ 0.50):          {len(_new)}")

            print(f"\n  Top-20 neue Kandidaten:")
            print(f"  {'Token':<30}  {'Typ':<14}  {'Conf':>6}  {'TF-IDF':>7}")
            for n, t, c in _new[:20]:
                sc = tfidf_score.get(n, 0.0)
                print(f"  {n:<30}  {t:<14}  {c:.3f}  {sc:.4f}")

            # Zusammenfassung: alle 5 Kernzahlen
            print(f"\n  ── Kernzahlen ──────────────────────────────────────────────")
            print(f"  1. TF-IDF Kandidaten gesamt:            {len(tfidf_candidates)}")
            print(f"  2. Kandidaten mit Kontext-Embedding:    {len(cand_ctx_vecs)}")
            print(f"  3. Seed-Recall (TF-IDF, Normalformen):  "
                  f"{len(tfidf_recall_norms)}/{len(seed_norms_lc)} "
                  f"= {len(tfidf_recall_norms)/len(seed_norms_lc)*100:.1f}%")
            print(f"  4. CV-Accuracy (kontextueller Clf):     "
                  f"{_cv_acc.mean():.3f} ± {_cv_acc.std():.3f}")
            print(f"  5. Typ-Acc auf Seed im Pool:            "
                  f"{_correct}/{len(_seed_hits)}"
                  + (f" = {_correct/len(_seed_hits)*100:.1f}%" if _seed_hits else ""))


# ══════════════════════════════════════════════════════════════════════════════
# TEST 12 – Top-50 Gewichts-Dimensionen des Test-7-Classifiers
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 12 – Unterraum der 50 informativsten Dimensionen (aus Test 7)")
print("=" * 65)
print("Fragestellung: Verbessert der 50-dim Unterraum die Typ-Trennung?")

# Prüfe ob clf aus Test 7 vorhanden
_clf12_ok = False
try:
    _coef = clf.coef_          # shape (n_classes, 768) oder (1, 768) bei 2 Klassen
    _clf12_ok = True
except NameError:
    print("  clf aus Test 7 nicht verfügbar — Test 12 übersprungen.")

if _clf12_ok:
    # ── Schritt 1: Top-50 Dimensionen ─────────────────────────────────────────
    # Maximaler absoluter Gewicht über alle Klassen pro Dimension
    _max_abs_weight = np.abs(_coef).max(axis=0)   # shape (768,)
    _top50_idx = np.argsort(-_max_abs_weight)[:50]
    _top50_idx_sorted = np.sort(_top50_idx)        # für Reproduzierbarkeit

    print(f"\n  Classifier-Koeffizienten: shape={_coef.shape}")
    print(f"  Top-50 Dimensionen (max |Gewicht|):")
    print(f"    Min-Gewicht in Top-50: {_max_abs_weight[_top50_idx[-1]]:.4f}")
    print(f"    Max-Gewicht in Top-50: {_max_abs_weight[_top50_idx[0]]:.4f}")
    print(f"    Gewichts-Masse Top-50 / gesamt: "
          f"{_max_abs_weight[_top50_idx].sum() / _max_abs_weight.sum() * 100:.1f}%")

    # ── Schritt 2: Projektion ─────────────────────────────────────────────────
    # X und y_raw aus Test 7D wiederverwenden
    _X12_full = X                                  # (N, 768), L2-normalisiert
    _X12_sub  = _X12_full[:, _top50_idx_sorted]    # (N, 50)

    # Re-normalisieren im Unterraum
    _norms = np.linalg.norm(_X12_sub, axis=1, keepdims=True)
    _norms = np.where(_norms > 0, _norms, 1.0)
    _X12_sub_norm = _X12_sub / _norms

    # ── Schritt 3: Silhouette ─────────────────────────────────────────────────
    print(f"\n── Silhouette-Score ──")
    _y12 = y   # LabelEncoder aus Test 7D

    if len(set(_y12)) >= 2:
        _sil_full = silhouette_score(_X12_full,     _y12, metric="cosine")
        _sil_sub  = silhouette_score(_X12_sub_norm, _y12, metric="cosine")
        print(f"  Voller 768-dim Raum (cosine):   {_sil_full:.4f}")
        print(f"  Top-50-dim Unterraum (cosine):  {_sil_sub:.4f}")
        _sil_delta = _sil_sub - _sil_full
        _sil_dir = "besser" if _sil_delta > 0 else "schlechter"
        print(f"  Δ = {_sil_delta:+.4f}  → Unterraum {_sil_dir} für Typ-Trennung")
    else:
        print("  Zu wenige Klassen für Silhouette.")
        _sil_full = _sil_sub = None

    # ── Schritt 4: CV-Accuracy im Unterraum ───────────────────────────────────
    print(f"\n── Classifier-Accuracy (5-Fold CV) ──")
    from sklearn.linear_model import LogisticRegression as _LR12
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    _clf12_full = _LR12(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
    _clf12_sub  = _LR12(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
    _cv12 = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    import warnings as _w12
    with _w12.catch_warnings():
        _w12.simplefilter("ignore")
        _acc_full = cross_val_score(_clf12_full, _X12_full,     _y12, cv=_cv12, scoring="accuracy")
        _acc_sub  = cross_val_score(_clf12_sub,  _X12_sub_norm, _y12, cv=_cv12, scoring="accuracy")

    print(f"  Voller 768-dim Raum:   mean={_acc_full.mean():.3f}  std={_acc_full.std():.3f}")
    print(f"  Top-50-dim Unterraum:  mean={_acc_sub.mean():.3f}  std={_acc_sub.std():.3f}")
    _acc_delta = _acc_sub.mean() - _acc_full.mean()
    _acc_dir = "besser" if _acc_delta > 0 else "schlechter"
    print(f"  Δ = {_acc_delta:+.3f}  → Unterraum {_acc_dir} für Klassifikation")

    # ── Schritt 5: Top-10 informativste Dimensionen pro Klasse ───────────────
    print(f"\n── Top-10 Dimensionen mit höchstem |Gewicht| pro Klasse ──")
    for _ci, _cname in enumerate(le_d.classes_):
        _top10_cls = np.argsort(-np.abs(_coef[_ci]))[:10]
        _ws = _coef[_ci, _top10_cls]
        _parts = "  ".join(f"dim{_d}({_v:+.3f})" for _d, _v in zip(_top10_cls, _ws))
        print(f"  {_cname:<14}: {_parts}")

    # ── Fazit ─────────────────────────────────────────────────────────────────
    print(f"\n── Fazit ──")
    if _sil_sub is not None and _sil_sub > _sil_full and _acc_sub.mean() >= _acc_full.mean() - 0.02:
        print("  → Unterraum ist kompakter UND klassifizierbar; Dim-Reduktion lohnt sich ✓")
    elif _sil_sub is not None and _sil_sub > _sil_full:
        print("  → Silhouette besser, aber Classifier-Accuracy sinkt; Trade-off")
    elif _acc_sub.mean() >= _acc_full.mean() - 0.02:
        print("  → Classifier-Accuracy vergleichbar; 50 Dim reichen für Klassifikation ✓")
    else:
        print("  → Vollraum bleibt besser; die 768 Dim enthalten verteilte Typ-Information ✗")


# ══════════════════════════════════════════════════════════════════════════════
# TEST 13 – Stabilität der Top-50 Dimensionen über 5 zufällige 80/20-Splits
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("TEST 13 – Stabilität der Top-50 Dimensionen (5× 80/20 Split)")
print("=" * 65)
print("Fragestellung: Sind die informativsten Dimensionen stabil oder Rauschen?")

_clf13_ok = False
try:
    _ = clf.coef_
    _ = X
    _ = y
    _clf13_ok = True
except NameError:
    print("  clf / X / y aus Test 7 nicht verfügbar — Test 13 übersprungen.")

if _clf13_ok:
    import warnings as _w13
    from sklearn.model_selection import StratifiedShuffleSplit
    from sklearn.linear_model import LogisticRegression as _LR13

    N_SPLITS_13 = 5
    TOP_K_13    = 50

    _sss = StratifiedShuffleSplit(
        n_splits=N_SPLITS_13, test_size=0.2, random_state=42
    )

    _top50_per_split: list[set[int]] = []
    _holdout_accs: list[float] = []

    print(f"\n  Split  Train  Holdout  HoldoutAcc  Top-{TOP_K_13} Dims (erste 10 …)")
    print(f"  " + "-" * 63)

    for _si, (_train_idx, _test_idx) in enumerate(
        _sss.split(X, y), start=1
    ):
        _X_tr, _X_te = X[_train_idx], X[_test_idx]
        _y_tr, _y_te = y[_train_idx], y[_test_idx]

        _c13 = _LR13(max_iter=1000, C=1.0, solver="lbfgs", random_state=42)
        with _w13.catch_warnings():
            _w13.simplefilter("ignore")
            _c13.fit(_X_tr, _y_tr)

        _hacc = (_c13.predict(_X_te) == _y_te).mean()
        _holdout_accs.append(_hacc)

        _maw = np.abs(_c13.coef_).max(axis=0)   # (768,)
        _top50 = set(np.argsort(-_maw)[:TOP_K_13].tolist())
        _top50_per_split.append(_top50)

        _preview = sorted(_top50)[:10]
        print(f"  {_si:>5}  {len(_train_idx):>5}  {len(_test_idx):>7}  "
              f"{_hacc:.3f}       {_preview} …")

    # ── Überschneidungsanalyse ─────────────────────────────────────────────────
    print(f"\n── Überschneidung zwischen den {N_SPLITS_13} Splits ──")

    # Dimensionen die in allen 5 Splits auftauchen
    _in_all = set.intersection(*_top50_per_split)
    # Dimensionen die in ≥4 von 5 Splits auftauchen
    from collections import Counter as _C13
    _dim_count = _C13(d for s in _top50_per_split for d in s)
    _in_4of5 = {d for d, n in _dim_count.items() if n >= 4}
    _in_3of5 = {d for d, n in _dim_count.items() if n >= 3}

    print(f"  In allen 5 Splits:    {len(_in_all):>3} Dimensionen  "
          f"{sorted(_in_all)}")
    print(f"  In ≥4 von 5 Splits:   {len(_in_4of5):>3} Dimensionen")
    print(f"  In ≥3 von 5 Splits:   {len(_in_3of5):>3} Dimensionen")

    # Paarweise Jaccard-Matrix
    print(f"\n── Paarweise Jaccard-Ähnlichkeit (Top-{TOP_K_13}) ──")
    print(f"  {'':>6}" + "".join(f"  Split{j+1}" for j in range(N_SPLITS_13)))
    for _i in range(N_SPLITS_13):
        _row = f"  Split{_i+1}"
        for _j in range(N_SPLITS_13):
            _inter = len(_top50_per_split[_i] & _top50_per_split[_j])
            _union = len(_top50_per_split[_i] | _top50_per_split[_j])
            _jac   = _inter / _union if _union > 0 else 1.0
            _row  += f"   {_jac:.3f}"
        print(_row)

    # Mittlere paarweise Jaccard (off-diagonal)
    _jacc_vals = []
    for _i in range(N_SPLITS_13):
        for _j in range(_i + 1, N_SPLITS_13):
            _inter = len(_top50_per_split[_i] & _top50_per_split[_j])
            _union = len(_top50_per_split[_i] | _top50_per_split[_j])
            _jacc_vals.append(_inter / _union if _union > 0 else 1.0)
    _mean_jacc = float(np.mean(_jacc_vals))

    print(f"\n  Mittlere paarweise Jaccard: {_mean_jacc:.3f}")
    print(f"  Holdout-Accuracy:           "
          f"mean={np.mean(_holdout_accs):.3f}  "
          f"std={np.std(_holdout_accs):.3f}  "
          f"min={min(_holdout_accs):.3f}  max={max(_holdout_accs):.3f}")

    # ── Stabilitäts-Histogramm ────────────────────────────────────────────────
    print(f"\n── Häufigkeitsverteilung: wie oft taucht eine Dimension auf? ──")
    _freq_hist = Counter(_dim_count.values())
    print(f"  Vorkommen  Anzahl Dimensionen")
    for _k in sorted(_freq_hist.keys(), reverse=True):
        _bar = "█" * min(_freq_hist[_k], 40)
        print(f"  {_k}×          {_freq_hist[_k]:>4}   {_bar}")

    # ── Fazit ─────────────────────────────────────────────────────────────────
    print(f"\n── Fazit ──")
    if len(_in_all) >= 20:
        print(f"  → {len(_in_all)} stabile Kerndimensionen in allen Splits: "
              f"hohe Stabilität ✓")
    elif len(_in_all) >= 10:
        print(f"  → {len(_in_all)} Kerndimensionen in allen Splits: "
              f"mäßige Stabilität")
    else:
        print(f"  → Nur {len(_in_all)} Dimensionen in allen Splits: "
              f"wenig stabil; eher Rauschen ✗")

    if _mean_jacc >= 0.5:
        print(f"  → Mittlere Jaccard {_mean_jacc:.3f} ≥ 0.5: "
              f"Unterraum ist reproduzierbar ✓")
    elif _mean_jacc >= 0.3:
        print(f"  → Mittlere Jaccard {_mean_jacc:.3f}: moderate Reproduzierbarkeit")
    else:
        print(f"  → Mittlere Jaccard {_mean_jacc:.3f} < 0.3: "
              f"Dimensionen variieren stark ✗")


# ══════════════════════════════════════════════════════════════════════════════
# ZUSAMMENFASSUNG
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("ZUSAMMENFASSUNG")
print("=" * 65)
print("""
Interpretation:
  Intra-Similarity >> Inter-Similarity  → Typen sind separierbar ✓
  Δmean > 0.05, Cohen's d > 0.5        → praktisch nutzbare Trennung ✓
  Viele echte Personennamen in Top-30   → Seed-Similarity-Ansatz funktioniert ✓
  Person-Tokens auch in Ort-Top-30      → Überlappung, Typ-Disambiguierung nötig
""")
