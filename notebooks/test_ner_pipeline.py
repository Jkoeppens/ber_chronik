"""
test_ner_pipeline.py — Exploration: kontextuelle NER-Pipeline auf osmanischem Material

Vier Schritte:
  1. TF-IDF Kandidaten-Extraktion
  2. Kontextuelle mBERT-Embeddings (Token-im-Satz vs. isoliert)
  3. Logistic Regression auf kontextuellen Embeddings (5-fold CV)
  4. DBSCAN auf kontextuellen Embeddings — Schreibvarianten

Ziel: entscheiden ob kontextuelle Embeddings dem aktuellen Ansatz überlegen sind.

Ausführen:
  .venv/bin/python notebooks/test_ner_pipeline.py
"""

import json
import re
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT    = Path(__file__).resolve().parent.parent
DOC_DIR = ROOT / "data" / "projects" / "osmanisch" / "documents" / "657e2449"

MBERT_MODEL     = "bert-base-multilingual-cased"
MBERT_DIM       = 768
TFIDF_TOP_N     = 50
MIN_TOKEN_LEN   = 3
CAPITAL_RE      = re.compile(r'^[A-ZÄÖÜ]')
# Klassische Stoppwörter die in Forschungsnotizen oft großgeschrieben auftauchen
STOPWORDS = {
    "Der", "Die", "Das", "Den", "Dem", "Des", "Ein", "Eine", "Einen",
    "Im", "In", "Ist", "Mit", "Von", "Vom", "Zum", "Zur", "Bei",
    "Auch", "Aber", "Oder", "Und", "Wie", "Als", "Auf", "An",
    "Für", "Über", "Unter", "Nach", "Vor", "Noch", "Seit",
    "The", "This", "That", "These", "Those", "Their", "They",
    "Also", "While", "When", "Which", "Were", "Have", "Has",
    "Ihrer", "Ihrem", "Ihren", "Seiner", "Seinem", "Seinen",
    "Dabei", "Damit", "Dazu", "Daher", "Doch", "Dann",
    "Ohne", "Gegen", "Zwischen", "Während",
}

# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def sep(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)

def subsep(title: str) -> None:
    print(f"\n  ── {title} ──")

def load_data():
    segs = json.loads((DOC_DIR / "segments.json").read_text(encoding="utf-8"))
    seed = json.loads((DOC_DIR / "entities_seed.json").read_text(encoding="utf-8"))
    content_segs = [s for s in segs if s.get("type") == "content"]
    print(f"  Segmente: {len(segs)} gesamt, {len(content_segs)} content")
    print(f"  Seed:     {len(seed)} Entities  "
          + "  ".join(f"{t}:{n}" for t, n in Counter(e.get('typ') for e in seed).items()))
    return content_segs, seed


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 1 — TF-IDF Kandidaten-Extraktion
# ══════════════════════════════════════════════════════════════════════════════

def step1_tfidf(content_segs: list[dict]) -> list[str]:
    sep("SCHRITT 1 — TF-IDF Kandidaten-Extraktion")

    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [s["text"] for s in content_segs]

    # Tokenizer: nur Wörter ≥3 Zeichen, Großbuchstaben am Anfang, keine Stopwörter
    def token_filter(text: str) -> list[str]:
        tokens = re.findall(r'\b[A-ZÄÖÜa-zäöüß][a-zA-ZÄÖÜäöüß\-]{2,}\b', text)
        return [t for t in tokens
                if CAPITAL_RE.match(t)
                and t not in STOPWORDS
                and len(t) >= MIN_TOKEN_LEN]

    # TF-IDF auf Segment-Ebene (jedes Segment = ein Dokument)
    vectorizer = TfidfVectorizer(
        analyzer=token_filter,
        min_df=2,        # muss in mind. 2 Segmenten vorkommen
        max_df=0.6,      # nicht in >60% aller Segmente (zu generisch)
        sublinear_tf=True,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tfidf_matrix = vectorizer.fit_transform(texts)

    vocab = vectorizer.get_feature_names_out()
    # Maximaler TF-IDF Score über alle Segmente pro Token
    max_scores = np.asarray(tfidf_matrix.max(axis=0)).flatten()
    ranked = sorted(zip(vocab, max_scores), key=lambda x: -x[1])

    # Nur großgeschriebene Tokens, keine Stopwörter
    filtered = [(tok, score) for tok, score in ranked
                if CAPITAL_RE.match(tok) and tok not in STOPWORDS]

    print(f"\n  Vokabular nach TF-IDF-Filter: {len(vocab)} Tokens")
    print(f"  Kandidaten (großgeschrieben, nicht Stopwort): {len(filtered)}")
    print(f"\n  Top-{TFIDF_TOP_N} TF-IDF Kandidaten:")
    print(f"  {'Rang':>4}  {'Token':<30}  {'Score':>6}")
    print(f"  {'-'*4}  {'-'*30}  {'-'*6}")
    for rank, (tok, score) in enumerate(filtered[:TFIDF_TOP_N], 1):
        print(f"  {rank:>4}  {tok:<30}  {score:.4f}")

    candidates = [tok for tok, _ in filtered[:TFIDF_TOP_N]]

    # Plausibilitäts-Check: wie viele landen im Seed?
    seed_norms_lc = set()
    seed = json.loads((DOC_DIR / "entities_seed.json").read_text(encoding="utf-8"))
    for e in seed:
        seed_norms_lc.add(e.get("normalform", "").lower())
        for a in e.get("aliases") or []:
            seed_norms_lc.add(a.lower())

    in_seed = [t for t in candidates if t.lower() in seed_norms_lc]
    print(f"\n  Davon bereits im Seed: {len(in_seed)}/{len(candidates)}")
    print(f"  Beispiele: {in_seed[:10]}")

    return candidates


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 2 — Kontextuelle mBERT-Embeddings
# ══════════════════════════════════════════════════════════════════════════════

def _embed_isolated(names: list[str], tokenizer, model) -> np.ndarray:
    """Namen isoliert einbetten (wie aktueller Produktivcode)."""
    import torch
    vecs = []
    for name in names:
        enc = tokenizer(name, return_tensors="pt", truncation=True, max_length=64)
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state[0]
        token_vecs = hidden[1:-1]
        if token_vecs.shape[0] == 0:
            token_vecs = hidden
        vec = token_vecs.mean(dim=0).cpu().numpy().astype(np.float32)
        n = np.linalg.norm(vec)
        vecs.append(vec / n if n > 0 else vec)
    return np.vstack(vecs) if vecs else np.empty((0, MBERT_DIM), dtype=np.float32)


def _embed_contextual(
    token: str,
    sentences: list[str],
    tokenizer,
    model,
) -> np.ndarray | None:
    """
    Token kontextuell einbetten: für jeden Satz wo das Token vorkommt,
    mBERT-Forward → Durchschnitt der Subtoken-Vektoren des Tokens im Satz.
    Gibt Durchschnitt über alle Vorkommen zurück (L2-normalisiert).
    """
    import torch
    tok_lc = token.lower()
    context_vecs = []

    for sent in sentences:
        words = sent.split()
        # Suche nach dem Token (case-insensitive)
        match_indices = [i for i, w in enumerate(words)
                         if re.sub(r'[^\w]', '', w).lower() == tok_lc]
        if not match_indices:
            continue

        enc = tokenizer(
            words,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            is_split_into_words=True,
        )
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state[0]

        w_ids = enc.word_ids(batch_index=0)

        for wi in match_indices:
            idxs = [j for j, w in enumerate(w_ids) if w == wi]
            if not idxs:
                continue
            vec = hidden[idxs].mean(dim=0).cpu().numpy().astype(np.float32)
            n = np.linalg.norm(vec)
            if n > 0:
                context_vecs.append(vec / n)

    if not context_vecs:
        return None
    avg = np.mean(context_vecs, axis=0).astype(np.float32)
    n = np.linalg.norm(avg)
    return avg / n if n > 0 else avg


def step2_contextual_embeddings(
    candidates: list[str],
    content_segs: list[dict],
    seed: list[dict],
) -> tuple[np.ndarray, list[str], dict]:
    sep("SCHRITT 2 — Kontextuelle mBERT-Embeddings")

    from sklearn.metrics import silhouette_score
    import torch

    print(f"  Lade {MBERT_MODEL} …", flush=True)
    from transformers import AutoTokenizer, AutoModel
    tokenizer = AutoTokenizer.from_pretrained(MBERT_MODEL)
    model     = AutoModel.from_pretrained(MBERT_MODEL)
    model.eval()

    sentences = [s["text"] for s in content_segs]

    # ── Seed-Entities: kontextuell vs. isoliert ──────────────────────────────
    subsep("Seed-Entities: kontextuell vs. isoliert")

    # Nur Typen mit genug Beispielen für Silhouette
    valid_types = ["Person", "Ort", "Organisation"]
    seed_by_type = defaultdict(list)
    for e in seed:
        if e.get("typ") in valid_types:
            seed_by_type[e["typ"]].append(e)

    # Isolierte Embeddings (wie Produktivcode)
    iso_vecs, iso_labels = [], []
    for typ in valid_types:
        for e in seed_by_type[typ]:
            names = [e.get("normalform", "")] + list(e.get("aliases") or [])
            names = [n.strip() for n in names if n.strip()]
            vecs  = _embed_isolated(names[:1], tokenizer, model)  # nur Normalform
            if vecs.shape[0]:
                iso_vecs.append(vecs[0])
                iso_labels.append(typ)

    # Kontextuelle Embeddings
    ctx_vecs, ctx_labels = [], []
    n_no_context = 0
    for typ in valid_types:
        for e in seed_by_type[typ]:
            name = e.get("normalform", "")
            vec  = _embed_contextual(name, sentences, tokenizer, model)
            if vec is not None:
                ctx_vecs.append(vec)
                ctx_labels.append(typ)
            else:
                n_no_context += 1

    iso_arr = np.vstack(iso_vecs)
    ctx_arr = np.vstack(ctx_vecs) if ctx_vecs else np.empty((0, MBERT_DIM))

    print(f"  Isolierte Embeddings: {len(iso_labels)} Seed-Entities")
    print(f"  Kontextuelle Embeddings: {len(ctx_labels)} Seed-Entities "
          f"({n_no_context} ohne Kontext im Korpus)")

    # Silhouette-Scores
    if len(set(iso_labels)) >= 2 and len(iso_labels) >= 4:
        from sklearn.preprocessing import LabelEncoder
        le = LabelEncoder()
        sil_iso = silhouette_score(iso_arr, le.fit_transform(iso_labels), metric="cosine")
        print(f"\n  Silhouette-Score (isoliert):    {sil_iso:.4f}")
    if len(set(ctx_labels)) >= 2 and len(ctx_labels) >= 4 and ctx_arr.shape[0] >= 4:
        from sklearn.preprocessing import LabelEncoder
        le = LabelEncoder()
        sil_ctx = silhouette_score(ctx_arr, le.fit_transform(ctx_labels), metric="cosine")
        print(f"  Silhouette-Score (kontextuell): {sil_ctx:.4f}")
        if len(set(iso_labels)) >= 2 and len(iso_labels) >= 4:
            delta = sil_ctx - sil_iso
            print(f"  Delta: {delta:+.4f}  "
                  + ("kontextuell besser" if delta > 0 else "isoliert besser"))

    # ── Intra-Typ-Kohärenz: mittlere Paarweise Cosine-Ähnlichkeit ─────────────
    subsep("Intra-Typ-Kohärenz (mittlere paarweise Cosine-Ähnlichkeit)")
    print(f"  {'Typ':<14}  {'Isoliert':>9}  {'Kontextuell':>12}  {'n':>4}")
    for typ in valid_types:
        iso_t = np.array([v for v, l in zip(iso_vecs, iso_labels) if l == typ])
        ctx_t = np.array([v for v, l in zip(ctx_vecs, ctx_labels) if l == typ])
        if len(iso_t) >= 2:
            sim_iso = float(np.mean(iso_t @ iso_t.T) - np.mean(np.diag(iso_t @ iso_t.T)))
            # Korrigiert: nur off-diagonal
            n = len(iso_t)
            sim_iso_od = (np.sum(iso_t @ iso_t.T) - np.trace(iso_t @ iso_t.T)) / (n * (n - 1)) if n > 1 else 0.0
        else:
            sim_iso_od = float("nan")
        if len(ctx_t) >= 2:
            n = len(ctx_t)
            sim_ctx_od = (np.sum(ctx_t @ ctx_t.T) - np.trace(ctx_t @ ctx_t.T)) / (n * (n - 1)) if n > 1 else 0.0
        else:
            sim_ctx_od = float("nan")
        n_ctx = len(ctx_t)
        print(f"  {typ:<14}  {sim_iso_od:>9.4f}  {sim_ctx_od:>12.4f}  {n_ctx:>4}")

    # ── Kontextuelle Embeddings für Kandidaten ────────────────────────────────
    subsep(f"Kontextuelle Embeddings für {len(candidates)} TF-IDF-Kandidaten")
    cand_vecs = {}
    n_found   = 0
    for tok in candidates:
        vec = _embed_contextual(tok, sentences, tokenizer, model)
        if vec is not None:
            cand_vecs[tok] = vec
            n_found += 1

    print(f"  {n_found}/{len(candidates)} Kandidaten mit Kontext im Korpus gefunden")
    no_context = [t for t in candidates if t not in cand_vecs]
    if no_context:
        print(f"  Ohne Kontext: {no_context[:10]}")

    return ctx_arr, ctx_labels, cand_vecs, tokenizer, model


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 3 — Classifier auf kontextuellen Embeddings
# ══════════════════════════════════════════════════════════════════════════════

def step3_classifier(
    ctx_arr: np.ndarray,
    ctx_labels: list[str],
    cand_vecs: dict[str, np.ndarray],
    seed: list[dict],
) -> None:
    sep("SCHRITT 3 — Classifier auf kontextuellen Embeddings")

    from sklearn.linear_model   import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    from sklearn.preprocessing  import LabelEncoder

    if ctx_arr.shape[0] < 10:
        print("  Zu wenige kontextuelle Seed-Embeddings für Classifier.")
        return

    le = LabelEncoder()
    y  = le.fit_transform(ctx_labels)
    X  = ctx_arr

    clf = LogisticRegression(max_iter=2000, C=1.0, solver="lbfgs", random_state=42)

    # 5-fold CV
    n_splits = min(5, min(Counter(ctx_labels).values()))
    if n_splits < 2:
        print("  Zu wenige Samples pro Klasse für Cross-Validation.")
        return

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")

    print(f"\n  {n_splits}-fold CV Accuracy:  {scores.mean():.3f} ± {scores.std():.3f}")
    print(f"  Scores: {[f'{s:.3f}' for s in scores]}")

    # Auf vollständigen Daten trainieren
    clf.fit(X, y)
    train_acc = (clf.predict(X) == y).mean()
    print(f"  Train-Accuracy (voll):    {train_acc:.3f}")
    print(f"  Klassen: {list(le.classes_)}")

    # Auf Kandidaten anwenden
    if not cand_vecs:
        print("  Keine Kandidaten-Vektoren vorhanden.")
        return

    subsep("Neue Kandidaten aus TF-IDF + kontextuellem Classifier")

    seed_norms_lc = set()
    for e in seed:
        seed_norms_lc.add(e.get("normalform", "").lower())
        for a in e.get("aliases") or []:
            seed_norms_lc.add(a.lower())

    results = []
    cand_names = list(cand_vecs.keys())
    cand_matrix = np.vstack([cand_vecs[n] for n in cand_names])
    probas = clf.predict_proba(cand_matrix)

    for name, proba in zip(cand_names, probas):
        best_cls  = int(np.argmax(proba))
        conf      = float(proba[best_cls])
        typ       = le.classes_[best_cls]
        in_seed   = name.lower() in seed_norms_lc
        results.append((name, typ, conf, in_seed))

    results.sort(key=lambda x: -x[2])

    # Neue Kandidaten (nicht im Seed), Konfidenz ≥ 0.5
    new_cands = [(n, t, c) for n, t, c, in_s in results if not in_s and c >= 0.5]
    print(f"\n  Neue Kandidaten (nicht im Seed, conf ≥ 0.50): {len(new_cands)}")
    print(f"  {'Token':<30}  {'Typ':<14}  {'Conf':>6}")
    print(f"  {'-'*30}  {'-'*14}  {'-'*6}")
    for name, typ, conf in new_cands[:20]:
        print(f"  {name:<30}  {typ:<14}  {conf:.3f}")

    # Seed-Entities die der Classifier korrekt klassifiziert
    seed_results = [(n, t, c) for n, t, c, in_s in results if in_s]
    if seed_results:
        subsep("Seed-Entities im Kandidaten-Pool (Sanity-Check)")
        # Ist die Typ-Vorhersage korrekt?
        seed_by_norm = {e.get("normalform", "").lower(): e.get("typ") for e in seed}
        correct = sum(1 for n, t, c in seed_results
                      if seed_by_norm.get(n.lower()) == t)
        print(f"  {len(seed_results)} Seed-Entities im Pool, "
              f"{correct} korrekt klassifiziert ({correct/len(seed_results)*100:.0f}%)")
        for n, t, c in seed_results[:10]:
            expected = seed_by_norm.get(n.lower(), "?")
            ok = "✓" if expected == t else "✗"
            print(f"  {ok} {n:<28}  pred={t:<14} exp={expected:<14}  {c:.3f}")


# ══════════════════════════════════════════════════════════════════════════════
# SCHRITT 4 — DBSCAN auf kontextuellen Embeddings
# ══════════════════════════════════════════════════════════════════════════════

def step4_dbscan(cand_vecs: dict[str, np.ndarray]) -> None:
    sep("SCHRITT 4 — DBSCAN auf kontextuellen Embeddings")

    from sklearn.cluster import DBSCAN
    from sklearn.metrics import silhouette_score

    if len(cand_vecs) < 4:
        print("  Zu wenige Kandidaten für DBSCAN.")
        return

    names  = list(cand_vecs.keys())
    matrix = np.vstack([cand_vecs[n] for n in names])

    # Mehrere eps-Werte testen, inkl. aktuellen Produktionswert 0.18
    eps_values = [0.10, 0.15, 0.18, 0.20, 0.25, 0.30]

    subsep("eps-Sweep (min_samples=2, metric=cosine)")
    print(f"  {'eps':>5}  {'Cluster':>7}  {'Noise':>6}  {'Noise%':>7}  {'Silhouette':>11}")
    print(f"  {'-'*5}  {'-'*7}  {'-'*6}  {'-'*7}  {'-'*11}")

    for eps in eps_values:
        labels = DBSCAN(eps=eps, min_samples=2, metric="cosine", n_jobs=-1).fit_predict(matrix)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise    = int((labels == -1).sum())
        noise_pct  = n_noise / len(names) * 100
        if n_clusters >= 2 and n_noise < len(names) - n_clusters:
            try:
                sil = silhouette_score(matrix, labels, metric="cosine")
                sil_str = f"{sil:.4f}"
            except Exception:
                sil_str = "n/a"
        else:
            sil_str = "n/a"
        marker = " ← aktuell" if abs(eps - 0.18) < 0.001 else ""
        print(f"  {eps:>5.2f}  {n_clusters:>7}  {n_noise:>6}  {noise_pct:>6.1f}%  {sil_str:>11}{marker}")

    # Detailansicht mit eps=0.18 (Produktionswert)
    subsep("Cluster-Inhalt bei eps=0.18 (Produktionswert)")
    labels_018 = DBSCAN(eps=0.18, min_samples=2, metric="cosine", n_jobs=-1).fit_predict(matrix)
    clusters = defaultdict(list)
    for name, lbl in zip(names, labels_018):
        clusters[lbl].append(name)

    non_noise = {lbl: toks for lbl, toks in clusters.items() if lbl != -1}
    multi     = {lbl: toks for lbl, toks in non_noise.items() if len(toks) > 1}
    singleton = {lbl: toks for lbl, toks in non_noise.items() if len(toks) == 1}

    print(f"  Cluster gesamt: {len(non_noise)}  "
          f"davon Mehrfach: {len(multi)}  Singleton: {len(singleton)}  "
          f"Noise: {(labels_018 == -1).sum()}")

    if multi:
        print(f"\n  Cluster mit mehreren Tokens (potenzielle Schreibvarianten):")
        for lbl, toks in sorted(multi.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"  [{lbl}] {' | '.join(sorted(toks))}")

    # Vergleich eps=0.18 vs. eps=0.25 für Varianten-Erkennung
    subsep("Vergleich eps=0.18 vs. eps=0.25 — neue Varianten")
    labels_025 = DBSCAN(eps=0.25, min_samples=2, metric="cosine", n_jobs=-1).fit_predict(matrix)
    clusters_025 = defaultdict(list)
    for name, lbl in zip(names, labels_025):
        clusters_025[lbl].append(name)

    new_multi_025 = {lbl: toks for lbl, toks in clusters_025.items()
                     if lbl != -1 and len(toks) > 1}
    print(f"  eps=0.18: {len(multi)} Mehrfach-Cluster")
    print(f"  eps=0.25: {len(new_multi_025)} Mehrfach-Cluster")

    # Neue Cluster die bei 0.25 entstehen aber nicht bei 0.18
    set_018 = {frozenset(toks) for toks in multi.values()}
    new_in_025 = [toks for toks in new_multi_025.values()
                  if frozenset(toks) not in set_018]
    if new_in_025:
        print(f"  Neue Cluster nur bei eps=0.25 ({len(new_in_025)} Stück):")
        for toks in sorted(new_in_025, key=lambda x: -len(x))[:10]:
            print(f"    {' | '.join(sorted(toks))}")
    else:
        print("  Keine neuen Cluster bei eps=0.25 gegenüber 0.18.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("test_ner_pipeline.py — Exploration kontextueller NER-Ansatz")
    print(f"Dokument: osmanisch/657e2449\n")

    content_segs, seed = load_data()

    # Schritt 1
    candidates = step1_tfidf(content_segs)

    # Schritt 2
    result = step2_contextual_embeddings(candidates, content_segs, seed)
    ctx_arr, ctx_labels, cand_vecs, tokenizer, model = result

    # Schritt 3
    step3_classifier(ctx_arr, ctx_labels, cand_vecs, seed)

    # Schritt 4
    step4_dbscan(cand_vecs)

    print(f"\n{'='*70}")
    print("  Fertig.")
    print('='*70)


if __name__ == "__main__":
    main()
