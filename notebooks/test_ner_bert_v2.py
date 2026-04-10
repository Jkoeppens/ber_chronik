"""
test_ner_bert_v2.py — Messung: BERT-Classifier auf allen Korpus-Tokens

Pipeline:
  1. Seed 80/20 splitten (Train / Holdout)
  2. mBERT: alle Segmente einmal durchlaufen → pro unique Token ein
     gemittelter kontextueller Vektor (ein Forward-Pass pro Segment)
  3. Classifier auf Train-Seed-Embeddings trainieren
  4. Classifier auf ALLE Korpus-Tokens anwenden (Schwelle 0.7)
  5. DBSCAN auf Kandidaten-Embeddings → Schreibvarianten
  6. Recall auf Holdout-Entities messen

Keine TF-IDF, keine Großschreibfilter, kein LLM.

Ausführen:
  .venv/bin/python notebooks/test_ner_bert_v2.py
"""

import json
import random
import re
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT    = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "data" / "projects" / "osmanisch" / "documents" / "657e2449"

MBERT_MODEL    = "bert-base-multilingual-cased"
MBERT_DIM      = 768
CONF_THRESHOLD = 0.7
TRAIN_RATIO    = 0.8
MIN_TOKEN_LEN  = 3    # Tokens < 3 Zeichen überspringen (Artikel, Präpositionen)
RANDOM_SEED    = 42

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


# ── Laden ──────────────────────────────────────────────────────────────────────

segs  = json.loads((DOC_DIR / "segments.json").read_text(encoding="utf-8"))
seed  = json.loads((DOC_DIR / "entities_seed.json").read_text(encoding="utf-8"))
content_segs = [s for s in segs if s.get("type") == "content"]

print(f"Content-Segmente: {len(content_segs)}")
print(f"Seed: {len(seed)} Entities  {dict(Counter(e['typ'] for e in seed))}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Seed 80 / 20 splitten
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 1. Seed-Split ──")

# Stratifiziert nach Typ
by_type: dict[str, list[dict]] = defaultdict(list)
for e in seed:
    by_type[e["typ"]].append(e)

train_seed, holdout_seed = [], []
for typ, entities in by_type.items():
    shuffled = entities[:]
    random.shuffle(shuffled)
    n_train = max(1, int(len(shuffled) * TRAIN_RATIO))
    train_seed.extend(shuffled[:n_train])
    holdout_seed.extend(shuffled[n_train:])

print(f"Train:   {len(train_seed)} Entities  "
      + "  ".join(f"{t}:{sum(1 for e in train_seed if e['typ']==t)}"
                  for t in by_type))
print(f"Holdout: {len(holdout_seed)} Entities  "
      + "  ".join(f"{t}:{sum(1 for e in holdout_seed if e['typ']==t)}"
                  for t in by_type))

# Lookup: welche Token-Strings gehören zu Train / Holdout?
def _entity_tokens(entities: list[dict]) -> set[str]:
    result: set[str] = set()
    for e in entities:
        for nm in [e.get("normalform","")] + list(e.get("aliases") or []):
            nm = nm.strip()
            if nm:
                result.add(nm.lower())
                for w in nm.split():
                    if len(w) >= MIN_TOKEN_LEN:
                        result.add(w.lower())
    return result - {""}

train_lc   = _entity_tokens(train_seed)
holdout_lc = _entity_tokens(holdout_seed)


# ══════════════════════════════════════════════════════════════════════════════
# 2. mBERT: ein Forward-Pass pro Segment → gemittelte Tokenvektoren
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 2. mBERT kontextuelle Embeddings ──")

import torch
from transformers import AutoTokenizer, AutoModel

print(f"Lade {MBERT_MODEL} …", flush=True)
tokenizer  = AutoTokenizer.from_pretrained(MBERT_MODEL)
bert_model = AutoModel.from_pretrained(MBERT_MODEL)
bert_model.eval()


def embed_all_segments(
    segments: list[dict],
    min_len: int = MIN_TOKEN_LEN,
) -> dict[str, np.ndarray]:
    """
    Ein mBERT-Forward-Pass pro Segment.
    Gibt pro unique Token (case-sensitiv) einen L2-normierten
    Durchschnittsvektor über alle Vorkommen im Korpus zurück.
    """
    word_vecs_raw: dict[str, list[np.ndarray]] = defaultdict(list)

    for seg_i, seg in enumerate(segments):
        if (seg_i + 1) % 100 == 0:
            print(f"  {seg_i + 1}/{len(segments)} Segmente …", flush=True)

        text  = seg.get("text", "").strip()
        words = text.split()
        if not words:
            continue

        enc = tokenizer(
            words,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            is_split_into_words=True,
        )
        with torch.no_grad():
            hidden = bert_model(**enc).last_hidden_state[0]

        w_ids = enc.word_ids(batch_index=0)
        for wi, word in enumerate(words):
            if len(word) < min_len:
                continue
            idxs = [j for j, w in enumerate(w_ids) if w == wi]
            if not idxs:
                continue
            vec = hidden[idxs].mean(dim=0).cpu().numpy().astype(np.float32)
            n   = np.linalg.norm(vec)
            if n > 0:
                word_vecs_raw[word].append(vec / n)

    # Durchschnitt über alle Vorkommen (L2-normalisiert)
    result: dict[str, np.ndarray] = {}
    for word, vecs in word_vecs_raw.items():
        avg = np.mean(vecs, axis=0).astype(np.float32)
        n   = np.linalg.norm(avg)
        result[word] = avg / n if n > 0 else avg

    return result


corpus_vecs = embed_all_segments(content_segs)
print(f"Unique Tokens mit Embedding: {len(corpus_vecs)}")


# ══════════════════════════════════════════════════════════════════════════════
# 3. Classifier trainieren (auf Train-Seed-Embeddings)
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 3. Logistic Regression Classifier ──")

from sklearn.linear_model    import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing   import LabelEncoder

# Für jede Train-Seed-Entity: kontextuellen Vektor aus Korpus holen
# Fallback: Token kommt im Korpus nicht vor → überspringen
X_train, y_train, train_names = [], [], []
n_missing = 0

for e in train_seed:
    typ  = e["typ"]
    norm = e.get("normalform", "").strip()
    if norm in corpus_vecs:
        X_train.append(corpus_vecs[norm])
        y_train.append(typ)
        train_names.append(norm)
    else:
        # Suche Alias im Korpus
        found = False
        for alias in (e.get("aliases") or []):
            alias = alias.strip()
            if alias and alias in corpus_vecs:
                X_train.append(corpus_vecs[alias])
                y_train.append(typ)
                train_names.append(alias)
                found = True
                break
        if not found:
            n_missing += 1

print(f"Train-Embeddings aus Korpus: {len(X_train)} / {len(train_seed)}")
print(f"Nicht im Korpus gefunden:    {n_missing}")

X_train_arr = np.vstack(X_train)
le  = LabelEncoder()
y   = le.fit_transform(y_train)

# 5-fold CV
valid_types = [t for t, n in Counter(y_train).items() if n >= 3]
mask_v = np.array([t in valid_types for t in y_train])
if mask_v.sum() >= 6 and len(valid_types) >= 2:
    n_splits = min(5, min(Counter(t for t, ok in zip(y_train, mask_v) if ok).values()))
    cv   = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_SEED)
    clf  = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs", random_state=RANDOM_SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cv_scores = cross_val_score(clf, X_train_arr[mask_v],
                                    le.transform([t for t, ok in zip(y_train, mask_v) if ok]),
                                    cv=cv, scoring="accuracy")
    print(f"{n_splits}-Fold CV Accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
else:
    print("Zu wenige Samples für CV.")

clf = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs", random_state=RANDOM_SEED)
clf.fit(X_train_arr, y)
print(f"Train-Accuracy: {(clf.predict(X_train_arr) == y).mean():.3f}")
print(f"Klassen: {list(le.classes_)}")


# ══════════════════════════════════════════════════════════════════════════════
# 4. Classifier auf ALLE Korpus-Tokens anwenden
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n── 4. Classifier auf alle {len(corpus_vecs)} Tokens (Schwelle {CONF_THRESHOLD}) ──")

all_words  = list(corpus_vecs.keys())
all_matrix = np.vstack([corpus_vecs[w] for w in all_words])

probas    = clf.predict_proba(all_matrix)
pred_type = le.classes_[np.argmax(probas, axis=1)]
conf      = probas.max(axis=1)

# Kandidaten: Konfidenz > Schwellwert
candidates = [
    (w, pred_type[i], float(conf[i]))
    for i, w in enumerate(all_words)
    if conf[i] >= CONF_THRESHOLD
]
candidates.sort(key=lambda x: -x[2])

print(f"Kandidaten (conf ≥ {CONF_THRESHOLD}): {len(candidates)}")


# ── Klassifizierung: in Train-Seed / Holdout / neu ───────────────────────────
all_seed_lc = _entity_tokens(seed)  # Train + Holdout zusammen

in_train    = [(w, t, c) for w, t, c in candidates if w.lower() in train_lc]
in_holdout  = [(w, t, c) for w, t, c in candidates if w.lower() in holdout_lc
               and w.lower() not in train_lc]
truly_new   = [(w, t, c) for w, t, c in candidates if w.lower() not in all_seed_lc]

print(f"  davon in Train-Seed:   {len(in_train)}")
print(f"  davon in Holdout:      {len(in_holdout)}")
print(f"  davon neu (nicht Seed):{len(truly_new)}")


# ── Holdout-Recall ────────────────────────────────────────────────────────────
print("\n── Holdout-Recall ──")

found_holdout_entities = []
missed_holdout_entities = []

for e in holdout_seed:
    names_lc = {e["normalform"].lower()}
    for a in (e.get("aliases") or []):
        if a:
            names_lc.add(a.lower())
            for w in a.split():
                if len(w) >= MIN_TOKEN_LEN:
                    names_lc.add(w.lower())
    norm_lc = e["normalform"].lower()
    for w in norm_lc.split():
        if len(w) >= MIN_TOKEN_LEN:
            names_lc.add(w)

    found = any(w.lower() in names_lc for w, _, _ in candidates)
    if found:
        found_holdout_entities.append(e)
    else:
        missed_holdout_entities.append(e)

recall = len(found_holdout_entities) / len(holdout_seed) if holdout_seed else 0.0
print(f"Holdout-Entities gefunden: {len(found_holdout_entities)} / {len(holdout_seed)} "
      f"= {recall*100:.1f}%")

# Typ-Recall
print(f"  {'Typ':<14}  {'Gefunden':>9}  {'Total':>6}  {'Recall':>7}")
for typ in ["Person", "Ort", "Organisation", "Konzept"]:
    total = sum(1 for e in holdout_seed if e["typ"] == typ)
    found_n = sum(1 for e in found_holdout_entities if e["typ"] == typ)
    if total:
        print(f"  {typ:<14}  {found_n:>9}  {total:>6}  {found_n/total*100:>6.1f}%")

# Typ-Accuracy auf gefundenen Holdout-Entities
correct_type = 0
for e in found_holdout_entities:
    names_lc = {e["normalform"].lower()}
    for a in (e.get("aliases") or []):
        if a:
            names_lc.add(a.lower())
            for w in a.split():
                if len(w) >= MIN_TOKEN_LEN:
                    names_lc.add(w)
    for w in e["normalform"].lower().split():
        if len(w) >= MIN_TOKEN_LEN:
            names_lc.add(w)

    # Nimm den Classifier-Typ des erstbesten Treffers
    for w, t, c in candidates:
        if w.lower() in names_lc:
            if t == e["typ"]:
                correct_type += 1
            break

print(f"\nTyp-Accuracy auf gefundenen Holdout-Entities: "
      f"{correct_type}/{len(found_holdout_entities)}"
      + (f" = {correct_type/len(found_holdout_entities)*100:.1f}%"
         if found_holdout_entities else ""))

print(f"\nVerpasste Holdout-Entities ({len(missed_holdout_entities)}):")
for e in missed_holdout_entities[:15]:
    print(f"  [{e['typ']:<14}] {e['normalform']}")
if len(missed_holdout_entities) > 15:
    print(f"  … +{len(missed_holdout_entities)-15} weitere")


# ══════════════════════════════════════════════════════════════════════════════
# 5. DBSCAN auf Kandidaten-Embeddings
# ══════════════════════════════════════════════════════════════════════════════

print("\n── 5. DBSCAN auf Kandidaten-Embeddings ──")

from sklearn.cluster import DBSCAN

if len(candidates) >= 4:
    cand_names   = [w for w, _, _ in candidates]
    cand_matrix  = np.vstack([corpus_vecs[w] for w in cand_names])

    print(f"{'eps':>5}  {'Cluster':>7}  {'Noise':>6}  {'Multi-Cluster':>14}")
    for eps in [0.10, 0.15, 0.18, 0.20, 0.25, 0.30]:
        lbls    = DBSCAN(eps=eps, min_samples=2, metric="cosine",
                         n_jobs=-1).fit_predict(cand_matrix)
        n_cl    = len(set(lbls)) - (1 if -1 in lbls else 0)
        n_noise = int((lbls == -1).sum())
        from collections import Counter as _C
        multi   = sum(1 for v in _C(lbls).values() if v > 1 and lbls[0] != -1)
        n_multi = sum(1 for lbl, cnt in _C(lbls).items()
                      if lbl != -1 and cnt > 1)
        marker = " ← aktuell" if abs(eps - 0.18) < 0.001 else ""
        print(f"{eps:>5.2f}  {n_cl:>7}  {n_noise:>6}  {n_multi:>14}{marker}")

    # Cluster bei eps=0.20 anzeigen
    lbls_best = DBSCAN(eps=0.20, min_samples=2, metric="cosine",
                       n_jobs=-1).fit_predict(cand_matrix)
    clusters = defaultdict(list)
    for name, lbl in zip(cand_names, lbls_best):
        clusters[lbl].append(name)
    multi_cl = {lbl: toks for lbl, toks in clusters.items()
                if lbl != -1 and len(toks) > 1}

    print(f"\nMehrfach-Cluster bei eps=0.20: {len(multi_cl)}")
    for lbl, toks in sorted(multi_cl.items(), key=lambda x: -len(x[1]))[:15]:
        tagged = [f"{t}{'*' if t.lower() in all_seed_lc else ''}" for t in sorted(toks)]
        print(f"  [{lbl:>3}] {' | '.join(tagged)}")
    print("  (* = im Seed)")
else:
    print("Zu wenige Kandidaten für DBSCAN.")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Zusammenfassung (Variante 1 – 768 dim)
# ══════════════════════════════════════════════════════════════════════════════

print("\n── Zusammenfassung (Variante 1: 768-dim) ──")
print(f"1. Kandidaten (Classifier conf ≥ {CONF_THRESHOLD}):    {len(candidates)}")
print(f"2. Holdout-Recall:                          "
      f"{len(found_holdout_entities)}/{len(holdout_seed)} = {recall*100:.1f}%")
print(f"3. False Positives (nicht im Seed):         {len(truly_new)}")
print(f"4. DBSCAN-Cluster (eps=0.20):               "
      + (str(len(multi_cl)) if len(candidates) >= 4 else "n/a"))

# Variante-1-Zahlen für den Vergleich am Ende merken
_v1_cands      = len(candidates)
_v1_recall_n   = len(found_holdout_entities)
_v1_recall_d   = len(holdout_seed)
_v1_fp         = len(truly_new)
_v1_dbscan     = len(multi_cl) if len(candidates) >= 4 else 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. Variante 2 – 30 stabile Kerndimensionen (aus mBERT-Raum)
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("VARIANTE 2 – 30 stabile Kerndimensionen (5× 80/20 Stabilitätscheck)")
print("=" * 65)

from sklearn.model_selection import StratifiedShuffleSplit

# ── Schritt 1: Stabile Dimensionen aus Train-Embeddings ermitteln ─────────────
# Gleiche Logik wie Test 13 in test_cluster_quality.py,
# aber im mBERT-768-dim-Raum der kontextuellen Embeddings.

_N_STAB   = 5
_TOP_K    = 50

_sss_stab = StratifiedShuffleSplit(n_splits=_N_STAB, test_size=0.2, random_state=RANDOM_SEED)
_top50_splits: list[set[int]] = []

print(f"\n── Stabilitätscheck auf Train-Embeddings ({len(X_train_arr)} Samples) ──")
print(f"  Split  HoldoutAcc")
for _si, (_tr, _te) in enumerate(
    _sss_stab.split(X_train_arr, y), start=1
):
    _cs = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs",
                              random_state=RANDOM_SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _cs.fit(X_train_arr[_tr], y[_tr])
    _hacc = (_cs.predict(X_train_arr[_te]) == y[_te]).mean()
    _maw  = np.abs(_cs.coef_).max(axis=0)        # (768,)
    _top50_splits.append(set(np.argsort(-_maw)[:_TOP_K].tolist()))
    print(f"  {_si:>5}  {_hacc:.3f}")

# Dimensionen die in allen N Splits auftauchen
_stable_dims = sorted(set.intersection(*_top50_splits))
print(f"\nStabile Kerndimensionen (in allen {_N_STAB} Splits): {len(_stable_dims)}")
print(f"  {_stable_dims}")

if len(_stable_dims) < 2:
    print("  Zu wenige stabile Dimensionen — Variante 2 übersprungen.")
else:
    _sdims = np.array(_stable_dims)

    # ── Schritt 2: Projektion ──────────────────────────────────────────────────
    def _project(mat: np.ndarray, dims: np.ndarray) -> np.ndarray:
        """Projiziere auf Unterraum und L2-normalisiere."""
        sub = mat[:, dims]
        n   = np.linalg.norm(sub, axis=1, keepdims=True)
        n   = np.where(n > 0, n, 1.0)
        return sub / n

    X_tr_sub  = _project(X_train_arr, _sdims)
    all_sub   = _project(all_matrix,  _sdims)

    # ── Schritt 3: Classifier im Unterraum ────────────────────────────────────
    print(f"\n── Classifier im {len(_stable_dims)}-dim Unterraum ──")

    # CV-Accuracy im Unterraum
    if mask_v.sum() >= 6 and len(valid_types) >= 2:
        _clf2_cv  = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs",
                                       random_state=RANDOM_SEED)
        _n_sp2    = min(5, min(Counter(t for t, ok in zip(y_train, mask_v) if ok).values()))
        _cv2      = StratifiedKFold(n_splits=_n_sp2, shuffle=True, random_state=RANDOM_SEED)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _cv2_scores = cross_val_score(
                _clf2_cv,
                X_tr_sub[mask_v],
                le.transform([t for t, ok in zip(y_train, mask_v) if ok]),
                cv=_cv2, scoring="accuracy",
            )
        print(f"{_n_sp2}-Fold CV Accuracy ({len(_stable_dims)} dim): "
              f"{_cv2_scores.mean():.3f} ± {_cv2_scores.std():.3f}  "
              f"(768-dim: {cv_scores.mean():.3f} ± {cv_scores.std():.3f})")

    _clf2 = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs",
                               random_state=RANDOM_SEED)
    _clf2.fit(X_tr_sub, y)
    print(f"Train-Accuracy ({len(_stable_dims)} dim): "
          f"{(_clf2.predict(X_tr_sub) == y).mean():.3f}")

    # ── Schritt 4: Inferenz auf allen Tokens ──────────────────────────────────
    _probas2    = _clf2.predict_proba(all_sub)
    _pred_type2 = le.classes_[np.argmax(_probas2, axis=1)]
    _conf2      = _probas2.max(axis=1)

    _cands2 = [
        (w, _pred_type2[i], float(_conf2[i]))
        for i, w in enumerate(all_words)
        if _conf2[i] >= CONF_THRESHOLD
    ]
    _cands2.sort(key=lambda x: -x[2])

    _in_train2   = [(w, t, c) for w, t, c in _cands2 if w.lower() in train_lc]
    _in_holdout2 = [(w, t, c) for w, t, c in _cands2
                    if w.lower() in holdout_lc and w.lower() not in train_lc]
    _truly_new2  = [(w, t, c) for w, t, c in _cands2 if w.lower() not in all_seed_lc]

    print(f"\nKandidaten (conf ≥ {CONF_THRESHOLD}): {len(_cands2)}")
    print(f"  davon in Train-Seed:    {len(_in_train2)}")
    print(f"  davon in Holdout:       {len(_in_holdout2)}")
    print(f"  davon neu (nicht Seed): {len(_truly_new2)}")

    # ── Schritt 5: Holdout-Recall im Unterraum ────────────────────────────────
    print(f"\n── Holdout-Recall ({len(_stable_dims)}-dim) ──")

    _found2, _missed2 = [], []
    for e in holdout_seed:
        _nlc = {e["normalform"].lower()}
        for a in (e.get("aliases") or []):
            if a:
                _nlc.add(a.lower())
                for w in a.split():
                    if len(w) >= MIN_TOKEN_LEN:
                        _nlc.add(w.lower())
        for w in e["normalform"].lower().split():
            if len(w) >= MIN_TOKEN_LEN:
                _nlc.add(w)
        if any(w.lower() in _nlc for w, _, _ in _cands2):
            _found2.append(e)
        else:
            _missed2.append(e)

    _recall2 = len(_found2) / len(holdout_seed) if holdout_seed else 0.0
    print(f"Holdout-Entities gefunden: {len(_found2)} / {len(holdout_seed)} "
          f"= {_recall2*100:.1f}%")

    print(f"  {'Typ':<14}  {'Gefunden':>9}  {'Total':>6}  {'Recall':>7}")
    for typ in ["Person", "Ort", "Organisation", "Konzept"]:
        _tot  = sum(1 for e in holdout_seed if e["typ"] == typ)
        _fn   = sum(1 for e in _found2 if e["typ"] == typ)
        if _tot:
            print(f"  {typ:<14}  {_fn:>9}  {_tot:>6}  {_fn/_tot*100:>6.1f}%")

    # ── Schritt 6: DBSCAN im Unterraum ────────────────────────────────────────
    print(f"\n── DBSCAN auf {len(_cands2)}-Kandidaten-Embeddings ({len(_stable_dims)}-dim) ──")

    _v2_dbscan = 0
    if len(_cands2) >= 4:
        _cnames2  = [w for w, _, _ in _cands2]
        _cmat2    = all_sub[[all_words.index(w) for w in _cnames2]]

        print(f"{'eps':>5}  {'Cluster':>7}  {'Noise':>6}  {'Multi-Cluster':>14}")
        for _eps in [0.10, 0.15, 0.18, 0.20, 0.25, 0.30]:
            _lbls2  = DBSCAN(eps=_eps, min_samples=2, metric="cosine",
                             n_jobs=-1).fit_predict(_cmat2)
            _nc2    = len(set(_lbls2)) - (1 if -1 in _lbls2 else 0)
            _nn2    = int((_lbls2 == -1).sum())
            _nmulti = sum(1 for lbl, cnt in Counter(_lbls2).items()
                          if lbl != -1 and cnt > 1)
            _mark   = " ← aktuell" if abs(_eps - 0.20) < 0.001 else ""
            print(f"{_eps:>5.2f}  {_nc2:>7}  {_nn2:>6}  {_nmulti:>14}{_mark}")
            if abs(_eps - 0.20) < 0.001:
                _v2_dbscan = _nmulti

        _lbls_best2 = DBSCAN(eps=0.20, min_samples=2, metric="cosine",
                             n_jobs=-1).fit_predict(_cmat2)
        _clusters2  = defaultdict(list)
        for _nm, _lb in zip(_cnames2, _lbls_best2):
            _clusters2[_lb].append(_nm)
        _multi2 = {lb: toks for lb, toks in _clusters2.items()
                   if lb != -1 and len(toks) > 1}
        print(f"\nMehrfach-Cluster bei eps=0.20: {len(_multi2)}")
        for _lb, _toks in sorted(_multi2.items(), key=lambda x: -len(x[1]))[:15]:
            _tagged = [f"{t}{'*' if t.lower() in all_seed_lc else ''}"
                       for t in sorted(_toks)]
            print(f"  [{_lb:>3}] {' | '.join(_tagged)}")
        print("  (* = im Seed)")
    else:
        print("Zu wenige Kandidaten für DBSCAN.")


# ══════════════════════════════════════════════════════════════════════════════
# 8. Direkter Vergleich
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 65)
print("VERGLEICH")
print("=" * 65)
_r1 = f"{_v1_recall_n}/{_v1_recall_d} = {_v1_recall_n/_v1_recall_d*100:.1f}%" \
      if _v1_recall_d else "n/a"
_r2 = (f"{len(_found2)}/{len(holdout_seed)} = {_recall2*100:.1f}%"
       if len(_stable_dims) >= 2 else "n/a")
_n2_cands = len(_cands2)  if len(_stable_dims) >= 2 else "n/a"
_n2_fp    = len(_truly_new2) if len(_stable_dims) >= 2 else "n/a"
_n2_db    = _v2_dbscan    if len(_stable_dims) >= 2 else "n/a"

print(f"  {'':30}  {'768-dim (V1)':>15}  {f'{len(_stable_dims)}-dim (V2)':>15}")
print(f"  {'-'*62}")
print(f"  {'Kandidaten (conf ≥ 0.7)':<30}  {_v1_cands:>15}  {str(_n2_cands):>15}")
print(f"  {'Holdout-Recall':<30}  {_r1:>15}  {_r2:>15}")
print(f"  {'False Positives':<30}  {_v1_fp:>15}  {str(_n2_fp):>15}")
print(f"  {'DBSCAN-Cluster (eps=0.20)':<30}  {_v1_dbscan:>15}  {str(_n2_db):>15}")
print(f"\nTop-20 neue Kandidaten (nicht im Seed), Variante 2:")
print(f"  {'Token':<30}  {'Typ':<14}  {'Conf':>6}")
if len(_stable_dims) >= 2:
    for w, t, c in _truly_new2[:20]:
        print(f"  {w:<30}  {t:<14}  {c:.3f}")
