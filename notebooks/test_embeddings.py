"""
test_embeddings.py — Testet ob Embedding-Clustering Eigennamen gruppiert.

Lädt segments.json, bettet alle capitalisierten Token-Kandidaten ein,
clustert mit DBSCAN und gibt die 50 größten Cluster aus.
Misst außerdem Recall gegen entities_proposal.json.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN

SEGMENTS_PATH  = Path("data/projects/osmanisch/documents/657e2449/segments.json")
ENTITIES_PATH  = Path("data/projects/osmanisch/documents/657e2449/entities_proposal.json")
MODEL_NAME     = "paraphrase-multilingual-mpnet-base-v2"
DBSCAN_EPS     = 0.25   # cosine distance threshold
DBSCAN_MIN     = 2      # min samples per cluster

# ── 1. Segmente laden ─────────────────────────────────────────────────────────

segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
content_segs = [s for s in segments if s.get("type") == "content"]
print(f"Content-Segmente: {len(content_segs)}")

# ── 2. Kandidaten extrahieren ─────────────────────────────────────────────────

CAPITAL_RE = re.compile(r'\b([A-ZÄÖÜÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÕÙÚÛÝА-ЯЁ][a-zäöüàáâãèéêëìíîïòóôõùúûýа-яё\w]{1,})\b')

DE_STOP = {
    "Das", "Die", "Der", "Den", "Des", "Ein", "Eine", "Einen", "Einem", "Eines",
    "Und", "Oder", "Aber", "Auch", "Als", "Mit", "Von", "Vom", "Zur", "Zum",
    "Nicht", "Noch", "Nach", "Vor", "Über", "Durch", "Für", "Bei", "Seit",
    "Aus", "An", "Am", "Im", "In", "Es", "Er", "Sie", "Wir", "Ihr", "Ich",
    "Dass", "Wenn", "Wie", "Was", "Wo", "Ob", "Da", "So", "Nu", "Bu",
    "Dabei", "Doch", "Dann", "Schon", "Außerdem", "Gleichzeitig", "Einige",
    "Andere", "Viele", "Erst", "Erste", "Bereits",
}
EN_STOP = {
    "The", "This", "That", "These", "Those", "Then", "There", "Their", "They",
    "Some", "Many", "Other", "Also", "When", "What", "Where", "Who", "Which",
    "And", "But", "Not", "With", "From", "For", "Into", "More", "Most",
    "On", "In", "At", "Re", "By", "Or", "As", "An", "Of", "To",
    "He", "She", "We", "It", "His", "Her", "Its", "Our", "Was", "Were",
    "Had", "Has", "Have", "Been", "Being", "After", "Before", "During",
    "First", "Second", "New", "Old", "One", "Two", "Three",
}
# Osmanische/türkische Titel die allein keine Entities sind
TITLES = {"Bey", "Pasha", "Pascha", "Pasa", "Effendi", "Hanim", "Agha", "Sultan",
          "Mu", "Pa", "Beg"}

STOP_ALL = DE_STOP | EN_STOP | TITLES

def _is_noise(tok: str) -> bool:
    if len(tok) < 3:
        return True
    if tok.isupper() and len(tok) <= 3:   # reine Abkürzungen wie "Pa", "Mu"
        return True
    if tok in STOP_ALL:
        return True
    return False

counter: Counter = Counter()
for seg in content_segs:
    for m in CAPITAL_RE.finditer(seg.get("text", "")):
        tok = m.group(1)
        if not _is_noise(tok):
            counter[tok] += 1

candidates = [tok for tok, cnt in counter.items() if cnt >= 2]
print(f"Kandidaten (≥2×, gefiltert): {len(candidates)}")

# ── 3. Embeddings berechnen ───────────────────────────────────────────────────

print(f"Lade Modell: {MODEL_NAME} …")
model = SentenceTransformer(MODEL_NAME)

print("Berechne Embeddings …")
embeddings = model.encode(candidates, batch_size=256, show_progress_bar=True,
                          normalize_embeddings=True)

# ── 4. DBSCAN-Clustering ──────────────────────────────────────────────────────

print(f"Clustere mit DBSCAN (eps={DBSCAN_EPS}, min_samples={DBSCAN_MIN}) …")
db = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN, metric="cosine", n_jobs=-1)
labels = db.fit_predict(embeddings)

n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
n_noise    = (labels == -1).sum()
print(f"Cluster: {n_clusters}  Rauschen: {n_noise}/{len(candidates)}\n")

# ── 5. Cluster aufbauen ───────────────────────────────────────────────────────

clusters: dict[int, list[str]] = defaultdict(list)
for tok, lbl in zip(candidates, labels):
    if lbl != -1:
        clusters[lbl].append(tok)

# Lookup: token (lowercase) → cluster-id
tok_to_cluster: dict[str, int] = {}
for lbl, tokens in clusters.items():
    for tok in tokens:
        tok_to_cluster[tok.lower()] = lbl

# ── 6. Recall-Messung ────────────────────────────────────────────────────────

entities = json.loads(ENTITIES_PATH.read_text(encoding="utf-8"))

# Alle Kandidaten + Noise als lowercase-Set für einfaches Lookup
candidate_set = {c.lower() for c in candidates}  # nur gefilterte Kandidaten
all_tokens_lc = {tok.lower() for tok in counter}  # ungefiltert (mehr Coverage)

found      = []
not_found  = []

for ent in entities:
    names = [ent.get("normalform", "")] + list(ent.get("aliases", []))
    names = [n for n in names if n]

    # Prüfe ob irgendeiner der Namen (oder ein Token daraus) im Clustering auftaucht
    hit = False
    hit_tokens = []
    for name in names:
        name_lc = name.lower()
        # Exakter Treffer
        if name_lc in tok_to_cluster:
            hit = True
            hit_tokens.append(name)
            continue
        # Token-Level: mind. ein Wort des Namens im Cluster
        for word in name_lc.split():
            if len(word) >= 3 and word in tok_to_cluster:
                hit = True
                hit_tokens.append(f"{name} (via '{word}')")
                break
        # Auch Noise-Kandidaten zählen (wurden extrahiert, aber nicht geclustert)
        if not hit and name_lc in all_tokens_lc:
            hit = True
            hit_tokens.append(f"{name} [noise/singleton]")

    if hit:
        found.append((ent, hit_tokens))
    else:
        not_found.append(ent)

recall = len(found) / len(entities) if entities else 0

print("=" * 60)
print(f"RECALL-MESSUNG  ({len(entities)} bekannte Entities)")
print("=" * 60)
print(f"  Gefunden:     {len(found):3d}  ({recall*100:.1f}%)")
print(f"  Nicht gefunden: {len(not_found):3d}  ({(1-recall)*100:.1f}%)")

if not_found:
    print(f"\nNICHT GEFUNDEN ({len(not_found)}):")
    for ent in not_found:
        aliases = ", ".join(ent.get("aliases", []))
        print(f"  [{ent.get('typ','?'):12s}] {ent['normalform']}"
              + (f"  (aliases: {aliases})" if aliases and aliases != ent['normalform'] else ""))

# ── 7. Cluster-Ausgabe ────────────────────────────────────────────────────────

sorted_clusters = sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)

print("\n" + "=" * 60)
print(f"TOP 50 CLUSTER (von {len(sorted_clusters)} gesamt)")
print("=" * 60)
for rank, (lbl, tokens) in enumerate(sorted_clusters[:50], 1):
    tok_sorted = sorted(tokens, key=lambda t: counter[t], reverse=True)
    print(f"\n[{rank:2d}] Cluster {lbl} — {len(tokens)} Varianten")
    print("    " + ", ".join(tok_sorted[:20]) + ("…" if len(tok_sorted) > 20 else ""))
