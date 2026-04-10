"""
test_ner_bert.py — Messung: TF-IDF + kontextuelles mBERT ohne LLM.

Fragestellung: Wie viele Seed-Entities findet die Pipeline?

Ausführen:
  .venv/bin/python notebooks/test_ner_bert.py
"""

import json
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT    = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "data" / "projects" / "osmanisch" / "documents" / "657e2449"

MBERT_MODEL = "bert-base-multilingual-cased"
MBERT_DIM   = 768

STOPWORDS = {
    "Der", "Die", "Das", "Den", "Dem", "Des", "Ein", "Eine", "Einen",
    "Im", "In", "Ist", "Mit", "Von", "Vom", "Zum", "Zur", "Bei",
    "Auch", "Aber", "Oder", "Und", "Wie", "Als", "Auf", "An",
    "Für", "Über", "Unter", "Nach", "Vor", "Noch", "Seit",
    "The", "This", "That", "These", "Those", "Their", "They",
    "Also", "While", "When", "Which", "Were", "Have", "Has",
    "Dabei", "Damit", "Dazu", "Daher", "Doch", "Dann",
    "Ohne", "Gegen", "Zwischen", "Während",
    "Ihrer", "Ihrem", "Ihren", "Seiner", "Seinem", "Seinen",
}

CAPITAL_RE = re.compile(r'^[A-ZÄÖÜ]')

# ── Laden ──────────────────────────────────────────────────────────────────────

segs  = json.loads((DOC_DIR / "segments.json").read_text(encoding="utf-8"))
seed  = json.loads((DOC_DIR / "entities_seed.json").read_text(encoding="utf-8"))
texts = [s["text"] for s in segs if s.get("type") == "content"]

# Seed-Lookup: normalform + alle aliases → typ
seed_lc: dict[str, str] = {}   # token_lc → typ
for e in seed:
    seed_lc[e["normalform"].lower()] = e["typ"]
    for a in e.get("aliases") or []:
        if a:
            seed_lc[a.lower()] = e["typ"]

print(f"Segmente (content): {len(texts)}")
print(f"Seed: {len(seed)} Entities  {dict(Counter(e['typ'] for e in seed))}")
print(f"Seed inkl. Aliases: {len(seed_lc)} Tokens\n")


# ══════════════════════════════════════════════════════════════════════════════
# 1. TF-IDF Kandidaten
# ══════════════════════════════════════════════════════════════════════════════

print("── 1. TF-IDF ──")

from sklearn.feature_extraction.text import TfidfVectorizer

def _tokenize(text):
    toks = re.findall(r'\b[A-ZÄÖÜa-zäöüß][a-zA-ZÄÖÜäöüß\-]{2,}\b', text)
    return [t for t in toks if CAPITAL_RE.match(t) and t not in STOPWORDS and len(t) >= 3]

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    vec = TfidfVectorizer(analyzer=_tokenize, min_df=2, max_df=0.6, sublinear_tf=True)
    mat = vec.fit_transform(texts)

vocab      = vec.get_feature_names_out()
max_scores = np.asarray(mat.max(axis=0)).flatten()
ranked     = sorted(
    [(tok, score) for tok, score in zip(vocab, max_scores) if CAPITAL_RE.match(tok) and tok not in STOPWORDS],
    key=lambda x: -x[1],
)

candidates     = [tok for tok, _ in ranked]         # alle, sortiert nach Score
cand_score     = {tok: score for tok, score in ranked}
cand_in_seed   = [t for t in candidates if t.lower() in seed_lc]
cand_not_seed  = [t for t in candidates if t.lower() not in seed_lc]

print(f"TF-IDF Kandidaten gesamt:        {len(candidates)}")
print(f"davon im Seed (direkt):          {len(cand_in_seed)}")
print(f"davon nicht im Seed:             {len(cand_not_seed)}")
print(f"Seed-Recall über TF-IDF:         {len(cand_in_seed)}/{len(seed)} "
      f"= {len(cand_in_seed)/len(seed)*100:.1f}%")

# Wie viel vom Seed fehlt? — zeige fehlende Normalformen
found_norms_lc = {t.lower() for t in cand_in_seed}
missed = [e["normalform"] for e in seed if e["normalform"].lower() not in found_norms_lc]
print(f"Fehlende Seed-Normalformen (nicht in TF-IDF): {len(missed)}")
print(f"  Beispiele: {missed[:15]}")

print(f"\nTop-20 Nicht-Seed-Kandidaten (plausible neue Entities?):")
print(f"  {'Rang':>4}  {'Token':<30}  {'Score':>6}")
for i, tok in enumerate(cand_not_seed[:20], 1):
    print(f"  {i:>4}  {tok:<30}  {cand_score[tok]:.4f}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. Kontextuelle mBERT-Embeddings
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 2. Kontextuelle mBERT-Embeddings ──")

import torch
from transformers import AutoTokenizer, AutoModel

print(f"Lade {MBERT_MODEL} …", flush=True)
tokenizer  = AutoTokenizer.from_pretrained(MBERT_MODEL)
bert_model = AutoModel.from_pretrained(MBERT_MODEL)
bert_model.eval()


def embed_contextual(token: str, sentences: list[str]) -> np.ndarray | None:
    """
    Kontextuell: Token im Satz → mBERT → Subtoken-Durchschnitt.
    Rückgabe: L2-normalisierter Durchschnittsvektor über alle Vorkommen, oder None.
    """
    tok_clean = re.sub(r'[^\w]', '', token).lower()
    vecs = []
    for sent in sentences:
        words = sent.split()
        matches = [i for i, w in enumerate(words)
                   if re.sub(r'[^\w]', '', w).lower() == tok_clean]
        if not matches:
            continue
        enc = tokenizer(
            words, return_tensors="pt", truncation=True,
            max_length=512, is_split_into_words=True,
        )
        with torch.no_grad():
            hidden = bert_model(**enc).last_hidden_state[0]
        w_ids = enc.word_ids(batch_index=0)
        for wi in matches:
            idxs = [j for j, w in enumerate(w_ids) if w == wi]
            if not idxs:
                continue
            v = hidden[idxs].mean(dim=0).cpu().numpy().astype(np.float32)
            n = np.linalg.norm(v)
            if n > 0:
                vecs.append(v / n)
    if not vecs:
        return None
    avg = np.mean(vecs, axis=0).astype(np.float32)
    n = np.linalg.norm(avg)
    return avg / n if n > 0 else avg


# Seed-Entities kontextuell einbetten
print("Bette Seed-Entities kontextuell ein …", flush=True)
seed_vecs, seed_types, seed_names = [], [], []
n_seed_no_ctx = 0
for e in seed:
    v = embed_contextual(e["normalform"], texts)
    if v is not None:
        seed_vecs.append(v)
        seed_types.append(e["typ"])
        seed_names.append(e["normalform"])
    else:
        n_seed_no_ctx += 1

print(f"Seed-Entities mit Kontext im Korpus: {len(seed_vecs)}/{len(seed)}")
print(f"Seed-Entities ohne Kontext:          {n_seed_no_ctx}")

# TF-IDF Kandidaten einbetten (alle, nicht nur Top-N)
print(f"Bette {len(candidates)} TF-IDF-Kandidaten kontextuell ein …", flush=True)
cand_vecs: dict[str, np.ndarray] = {}
for i, tok in enumerate(candidates, 1):
    if i % 50 == 0:
        print(f"  {i}/{len(candidates)} …", flush=True)
    v = embed_contextual(tok, texts)
    if v is not None:
        cand_vecs[tok] = v

print(f"Kandidaten mit Kontext:  {len(cand_vecs)}/{len(candidates)}")
print(f"Kandidaten ohne Kontext: {len(candidates) - len(cand_vecs)}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Classifier — Accuracy + Typ-Erkennung
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 3. Logistic Regression Classifier ──")

from sklearn.linear_model    import LogisticRegression
from sklearn.model_selection  import StratifiedKFold, cross_val_score
from sklearn.preprocessing    import LabelEncoder

# Nur Typen mit ≥5 Embeddings
type_counts = Counter(seed_types)
valid_types = [t for t, n in type_counts.items() if n >= 5]
mask = [i for i, t in enumerate(seed_types) if t in valid_types]
X_seed = np.vstack([seed_vecs[i] for i in mask])
y_raw  = [seed_types[i] for i in mask]

le   = LabelEncoder()
y    = le.fit_transform(y_raw)
clf  = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs", random_state=42)

n_splits = min(5, min(Counter(y_raw).values()))
cv       = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    cv_scores = cross_val_score(clf, X_seed, y, cv=cv, scoring="accuracy")

clf.fit(X_seed, y)
train_acc = (clf.predict(X_seed) == y).mean()

print(f"Klassen:                 {list(le.classes_)}")
print(f"Trainingsgröße:          {len(y)} Seed-Embeddings")
print(f"{n_splits}-fold CV Accuracy:     {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
print(f"Train-Accuracy:          {train_acc:.3f}")

# Auf Kandidaten anwenden — nur die mit Kontext-Embedding
if cand_vecs:
    cnames  = list(cand_vecs.keys())
    cmatrix = np.vstack([cand_vecs[n] for n in cnames])
    probas  = clf.predict_proba(cmatrix)
    pred_types = le.classes_[np.argmax(probas, axis=1)]
    confs      = probas.max(axis=1)

    # Für Seed-Entities im Kandidaten-Pool: Typ korrekt?
    seed_in_cands = [(n, t, c)
                     for n, t, c in zip(cnames, pred_types, confs)
                     if n.lower() in seed_lc]
    correct_type = sum(1 for n, t, c in seed_in_cands if seed_lc.get(n.lower()) == t)
    print(f"\nSeed-Entities im Kandidaten-Pool:     {len(seed_in_cands)}")
    print(f"davon Typ korrekt (von Classifier):   {correct_type} "
          f"({correct_type/len(seed_in_cands)*100:.1f}% wenn >0)")

    # Neue Kandidaten: nicht im Seed, conf ≥ 0.5
    new_high_conf = [
        (n, t, c) for n, t, c in zip(cnames, pred_types, confs)
        if n.lower() not in seed_lc and c >= 0.5
    ]
    new_high_conf.sort(key=lambda x: -x[2])
    print(f"Neue Kandidaten (conf ≥ 0.50):        {len(new_high_conf)}")

    print(f"\nTop-20 neue Kandidaten (conf ≥ 0.50):")
    print(f"  {'Token':<30}  {'Typ':<14}  {'Conf':>6}")
    for n, t, c in new_high_conf[:20]:
        print(f"  {n:<30}  {t:<14}  {c:.3f}")


# ══════════════════════════════════════════════════════════════════════════════
# 4. DBSCAN — Schreibvarianten
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 4. DBSCAN Schreibvarianten ──")

from sklearn.cluster import DBSCAN

if len(cand_vecs) >= 4:
    cnames  = list(cand_vecs.keys())
    cmatrix = np.vstack([cand_vecs[n] for n in cnames])

    print(f"{'eps':>5}  {'Cluster':>7}  {'Noise':>6}  {'Noise%':>7}")
    for eps in [0.10, 0.15, 0.18, 0.20, 0.25, 0.30]:
        lbls       = DBSCAN(eps=eps, min_samples=2, metric="cosine", n_jobs=-1).fit_predict(cmatrix)
        n_cl       = len(set(lbls)) - (1 if -1 in lbls else 0)
        n_noise    = int((lbls == -1).sum())
        marker = " ← aktuell" if abs(eps - 0.18) < 0.001 else ""
        print(f"{eps:>5.2f}  {n_cl:>7}  {n_noise:>6}  {n_noise/len(cnames)*100:>6.1f}%{marker}")

    # Cluster-Inhalt bei eps=0.18
    lbls_018 = DBSCAN(eps=0.18, min_samples=2, metric="cosine", n_jobs=-1).fit_predict(cmatrix)
    clusters = defaultdict(list)
    for name, lbl in zip(cnames, lbls_018):
        clusters[lbl].append(name)
    multi = {lbl: toks for lbl, toks in clusters.items() if lbl != -1 and len(toks) > 1}
    print(f"\nMehrfach-Cluster bei eps=0.18: {len(multi)}")
    for lbl, toks in sorted(multi.items(), key=lambda x: -len(x[1]))[:15]:
        # Markiere Tokens die im Seed sind
        tagged = [f"{t}{'*' if t.lower() in seed_lc else ''}" for t in sorted(toks)]
        print(f"  [{lbl:>3}] {' | '.join(tagged)}")
    print("  (* = im Seed)")
else:
    print("Zu wenige Kandidaten für DBSCAN.")


# ══════════════════════════════════════════════════════════════════════════════
# Zusammenfassung
# ══════════════════════════════════════════════════════════════════════════════

print("\n── Zusammenfassung ──")
print(f"TF-IDF Kandidaten gesamt:            {len(candidates)}")
print(f"Kandidaten mit Kontext-Embedding:    {len(cand_vecs)}")
print(f"Seed-Recall (TF-IDF):                {len(cand_in_seed)}/{len(seed)} = {len(cand_in_seed)/len(seed)*100:.1f}%")
if seed_vecs:
    print(f"Seed-Entities mit Kontext:           {len(seed_vecs)}/{len(seed)}")
print(f"CV-Accuracy Classifier:              {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
if cand_vecs and seed_in_cands:
    print(f"Typ-Acc auf Seed im Kandidaten-Pool: {correct_type}/{len(seed_in_cands)} = {correct_type/len(seed_in_cands)*100:.1f}%")
