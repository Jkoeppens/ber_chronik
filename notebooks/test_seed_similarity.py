"""
test_seed_similarity.py — Testet ob Seed-Entities als Zentren im Embedding-Space
neue, noch unbekannte Entities in den Segmenten finden.

Ablauf:
1. Seed aus entities_proposal.json laden → getrennt nach Typ
2. Pro Typ: Durchschnittsvektor aller Normalformen + Aliases berechnen
3. Alle großgeschriebenen Tokens aus segments.json einbetten
4. Cosine-Similarity jedes Tokens gegen jeden Typ-Zentrum messen
5. Top-30 je Typ über Schwellwert 0.6 die NICHT in der Seed-Liste sind
"""

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

# ── Konfiguration ─────────────────────────────────────────────────────────────

SEGMENTS_PATH = Path("data/projects/osmanisch/documents/657e2449/segments.json")
SEED_PATH     = Path("data/projects/osmanisch/documents/657e2449/entities_proposal.json")
MODEL_NAME    = "paraphrase-multilingual-mpnet-base-v2"
SIM_THRESHOLD = 0.60
TOP_N         = 30
FREQ_MIN      = 1          # Min. Häufigkeit im Text

CAPITAL_RE = re.compile(
    r'\b([A-ZÄÖÜÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÕÙÚÛÝА-ЯЁ]'
    r'[a-zäöüàáâãèéêëìíîïòóôõùúûýа-яё\w]{1,})\b'
)

# Breit gefasste Stoplist – materialneutral
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
STOP_ALL = DE_STOP | EN_STOP

# ── 1. Seed laden ─────────────────────────────────────────────────────────────

seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))

TYPES = ["Person", "Ort", "Organisation", "Konzept"]

seed_by_type: dict[str, list[str]] = {t: [] for t in TYPES}
seed_tokens_lc: set[str] = set()  # alle Seed-Strings als lowercase-Set

for ent in seed:
    typ = ent.get("typ", "")
    if typ not in seed_by_type:
        continue
    names = [ent.get("normalform", "")] + list(ent.get("aliases") or [])
    names = [n.strip() for n in names if n and n.strip()]
    seed_by_type[typ].extend(names)
    for n in names:
        # Auch Einzelwörter aus mehrwortigen Aliases indexieren
        for w in n.lower().split():
            seed_tokens_lc.add(w)
        seed_tokens_lc.add(n.lower())

for t, names in seed_by_type.items():
    print(f"Seed {t:14s}: {len(names):3d} Namen/Aliases")

# ── 2. Segmente laden & Kandidaten extrahieren ────────────────────────────────

segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
content_segs = [s for s in segments if s.get("type") == "content"]
print(f"\nContent-Segmente: {len(content_segs)}")

counter: Counter = Counter()
for seg in content_segs:
    for m in CAPITAL_RE.finditer(seg.get("text", "")):
        tok = m.group(1)
        if len(tok) >= 3 and tok not in STOP_ALL:
            counter[tok] += 1

candidates = [tok for tok, cnt in counter.items() if cnt >= FREQ_MIN]
print(f"Kandidaten (≥{FREQ_MIN}×): {len(candidates)}")

# ── 3. Modell & Embeddings ────────────────────────────────────────────────────

print(f"\nLade Modell: {MODEL_NAME} …")
model = SentenceTransformer(MODEL_NAME)

# Typ-Zentren aus Seed berechnen
print("Berechne Seed-Zentren …")
type_centers: dict[str, np.ndarray] = {}
for typ in TYPES:
    names = seed_by_type[typ]
    if not names:
        print(f"  {typ}: keine Seed-Namen, übersprungen")
        continue
    vecs = model.encode(names, batch_size=256, normalize_embeddings=True, show_progress_bar=False)
    type_centers[typ] = vecs.mean(axis=0)
    # Erneut normalisieren (Mittelwert ist nicht unit-length)
    norm = np.linalg.norm(type_centers[typ])
    if norm > 0:
        type_centers[typ] /= norm
    print(f"  {typ:14s}: Zentrum aus {len(names)} Namen berechnet")

# Kandidaten-Embeddings
print(f"\nBerechne {len(candidates)} Kandidaten-Embeddings …")
cand_vecs = model.encode(candidates, batch_size=256, normalize_embeddings=True,
                          show_progress_bar=True)

# ── 4. Similarity messen & Ausgabe ───────────────────────────────────────────

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two L2-normalized vectors."""
    return float(np.dot(a, b))  # already normalized → dot = cosine

print("\n" + "=" * 65)
for typ in TYPES:
    if typ not in type_centers:
        continue
    center = type_centers[typ]

    sims = [(candidates[i], cosine_sim(cand_vecs[i], center))
            for i in range(len(candidates))]

    # Filter: über Schwellwert AND nicht im Seed
    novel = [
        (tok, sim) for tok, sim in sims
        if sim >= SIM_THRESHOLD
        and tok.lower() not in seed_tokens_lc
        # Einzelne Wörter aus Seed ebenfalls ausschließen
        and not any(tok.lower() == w for w in seed_tokens_lc)
    ]
    novel.sort(key=lambda x: -x[1])

    print(f"\nTOP-{TOP_N} neue Kandidaten  →  Typ: {typ}  (≥{SIM_THRESHOLD})")
    print(f"{'Token':<28}  Sim   Freq")
    print("-" * 45)
    for tok, sim in novel[:TOP_N]:
        freq = counter[tok]
        print(f"  {tok:<26}  {sim:.3f}  {freq:4d}×")

    print(f"\n  Gesamt über Schwellwert (neu): {len(novel)}")

# ── 5. Overlap-Check: Wie viele Seed-Namen wurden selbst gefunden? ────────────
print("\n" + "=" * 65)
print("SELF-CHECK: Werden Seed-Namen im oberen Ähnlichkeitsbereich erkannt?")
print("(Seed-Token das als Kandidat vorkommt und sim >= 0.5 zu korrektem Zentrum)")
print()
for typ in TYPES:
    if typ not in type_centers:
        continue
    center = type_centers[typ]
    hits = []
    for i, tok in enumerate(candidates):
        if tok.lower() in seed_tokens_lc:
            sim = cosine_sim(cand_vecs[i], center)
            if sim >= 0.50:
                hits.append((tok, sim))
    hits.sort(key=lambda x: -x[1])
    print(f"  {typ:14s}: {len(hits)} Treffer  "
          + (", ".join(f"{t}({s:.2f})" for t, s in hits[:8])
             + ("…" if len(hits) > 8 else "")) )
