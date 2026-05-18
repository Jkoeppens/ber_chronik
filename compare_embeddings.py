"""
Vergleich MiniLM vs. BGE-M3 für Entity-Clustering.

Standalone-Script, kein Commit nötig.
Aufruf: .venv/bin/python compare_embeddings.py
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

# ── Entities aus classified.json extrahieren ──────────────────────────────────

classified = json.loads(
    Path("data/projects/obsidian_12/documents/ad944d12/classified.json").read_text()
)
# Alle Actors einsammeln + deduplizieren als minimale Entity-Liste
raw_actors: dict[str, int] = {}
for row in classified:
    for a in row.get("actors", []):
        raw_actors[a] = raw_actors.get(a, 0) + 1

# Nur Actors mit ≥2 Nennungen, maximal 25 — damit das Ergebnis lesbar bleibt
candidates = sorted(
    [a for a, n in raw_actors.items() if n >= 2],
    key=lambda a: -raw_actors[a],
)[:25]

entities = [{"normalform": a, "typ": "Org", "score": raw_actors[a]} for a in candidates]

print(f"Eingabe: {len(entities)} Entities")
for e in entities:
    print(f"  {e['score']:2d}×  {e['normalform']!r}")
print()

THRESHOLD = 0.82  # analog zu EMB_THRESHOLD in entity_gliner.py


# ── Union-Find Clustering (modellunabhängig) ──────────────────────────────────

def cluster(embs: np.ndarray, labels: list[str], threshold: float) -> list[list[str]]:
    n = len(labels)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sim = embs @ embs.T
    for i in range(n):
        for j in range(i + 1, n):
            if float(sim[i, j]) >= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[str]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(labels[i])
    return [g for g in groups.values() if len(g) > 1]   # nur echte Cluster


texts = [e["normalform"] for e in entities]


# ── 1. MiniLM ─────────────────────────────────────────────────────────────────

print("=" * 60)
print("Modell 1: paraphrase-multilingual-MiniLM-L12-v2 (lokal)")
print("=" * 60)
t0 = time.perf_counter()
from sentence_transformers import SentenceTransformer
miniLM = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
t_load_mini = time.perf_counter() - t0

t1 = time.perf_counter()
embs_mini = miniLM.encode(texts, show_progress_bar=False, normalize_embeddings=True)
embs_mini = np.array(embs_mini, dtype=np.float32)
t_encode_mini = time.perf_counter() - t1

clusters_mini = cluster(embs_mini, texts, THRESHOLD)
t_total_mini = time.perf_counter() - t0

print(f"Ladezeit:    {t_load_mini:.2f}s")
print(f"Encode-Zeit: {t_encode_mini:.3f}s")
print(f"Gesamt:      {t_total_mini:.2f}s")
print(f"Gefundene Merge-Cluster ({len(clusters_mini)}):")
if clusters_mini:
    for g in clusters_mini:
        print(f"  → {g}")
else:
    print("  (keine)")
print()


# ── 2. BGE-M3 ─────────────────────────────────────────────────────────────────

print("=" * 60)
print("Modell 2: BAAI/bge-m3 (lokal, FP16)")
print("=" * 60)
t0 = time.perf_counter()
from FlagEmbedding import BGEM3FlagModel
bge = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
t_load_bge = time.perf_counter() - t0

t1 = time.perf_counter()
out = bge.encode(texts, batch_size=12, max_length=512, return_dense=True)
embs_bge = np.array(out["dense_vecs"], dtype=np.float32)
norms = np.linalg.norm(embs_bge, axis=1, keepdims=True)
embs_bge = embs_bge / np.where(norms == 0, 1, norms)
t_encode_bge = time.perf_counter() - t1

clusters_bge = cluster(embs_bge, texts, THRESHOLD)
t_total_bge = time.perf_counter() - t0

print(f"Ladezeit:    {t_load_bge:.2f}s")
print(f"Encode-Zeit: {t_encode_bge:.3f}s")
print(f"Gesamt:      {t_total_bge:.2f}s")
print(f"Gefundene Merge-Cluster ({len(clusters_bge)}):")
if clusters_bge:
    for g in clusters_bge:
        print(f"  → {g}")
else:
    print("  (keine)")
print()


# ── 3. Voyage AI ─────────────────────────────────────────────────────────────

print("=" * 60)
print("Modell 3: voyage-4 (API, input_type='query')")
print("=" * 60)
import os
from dotenv import load_dotenv
load_dotenv(".env")
import voyageai

vo = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

t0 = time.perf_counter()
result = vo.embed(texts, model="voyage-4", input_type="query")
embs_voyage = np.array(result.embeddings, dtype=np.float32)
norms = np.linalg.norm(embs_voyage, axis=1, keepdims=True)
embs_voyage = embs_voyage / np.where(norms == 0, 1, norms)
t_voyage = time.perf_counter() - t0

clusters_voyage = cluster(embs_voyage, texts, THRESHOLD)

print(f"API-Latenz:  {t_voyage:.3f}s  (kein Laden, reine Netzwerkzeit)")
print(f"Gefundene Merge-Cluster ({len(clusters_voyage)}):")
if clusters_voyage:
    for g in clusters_voyage:
        print(f"  → {g}")
else:
    print("  (keine)")
print()


# ── Vergleich ─────────────────────────────────────────────────────────────────

print("=" * 60)
print("Vergleich (threshold = {})".format(THRESHOLD))
print("=" * 60)

all_clusters = {
    "MiniLM":  clusters_mini,
    "BGE-M3":  clusters_bge,
    "Voyage-4": clusters_voyage,
}

# Zeittabelle
print(f"\n{'Modell':<12}  {'Encode/API':>10}  {'Gesamt':>8}")
print("-" * 36)
print(f"{'MiniLM':<12}  {t_encode_mini:>9.3f}s  {t_total_mini:>7.2f}s")
print(f"{'BGE-M3':<12}  {t_encode_bge:>9.3f}s  {t_total_bge:>7.2f}s")
print(f"{'Voyage-4':<12}  {t_voyage:>9.3f}s  {'(API)':>7}")

# Cluster-Tabelle
all_keys = sorted(
    {frozenset(g) for clusters in all_clusters.values() for g in clusters},
    key=lambda s: (-len(s), sorted(s)[0]),
)
print(f"\n{'Cluster':<50}  {'MiniLM':>7}  {'BGE-M3':>7}  {'Voyage':>7}")
print("-" * 76)
for key in all_keys:
    label = ", ".join(sorted(key))[:48]
    row = {name: ("✓" if key in {frozenset(g) for g in cl} else "✗")
           for name, cl in all_clusters.items()}
    print(f"{label:<50}  {row['MiniLM']:>7}  {row['BGE-M3']:>7}  {row['Voyage-4']:>7}")

# Unikate
for name, cl in all_clusters.items():
    s = {frozenset(g) for g in cl}
    others = {frozenset(g) for n, c in all_clusters.items() if n != name for g in c}
    unique = s - others
    if unique:
        print(f"\nNur {name} findet:")
        for g in unique:
            print(f"  {sorted(g)}")
