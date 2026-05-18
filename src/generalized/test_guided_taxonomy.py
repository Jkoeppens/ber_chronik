"""
test_guided_taxonomy.py — Vergleich: LLM vs. KMeans Guided vs. BERTopic Guided

Lädt Segmente aus damaskus_test_2, verarbeitet sie mit drei Systemen,
gibt eine tabellarische Gegenüberstellung inkl. Top-3-Segmente pro Cluster aus.

Keine Schreiboperationen in Projektdateien. Kein git commit.

Aufruf:
    python -m src.generalized.test_guided_taxonomy
"""

import json
import random
import re
import time
from pathlib import Path
from dotenv import load_dotenv

# ── Konfiguration ─────────────────────────────────────────────────────────────
SEGMENTS_PATH = Path("data/projects/damaskus_test_2/documents/b1e1d872/segments.json")
EMB_MODEL     = "paraphrase-multilingual-MiniLM-L12-v2"
MAX_SEGMENTS  = 80
MAX_SEG_CHARS = 1000
MIN_LENGTH    = 80
RANDOM_SEED   = 42
PREVIEW_CHARS = 300   # Textvorschau pro Segment

seed_topic_list = [
    ["ulama", "islam", "religiös", "sunni", "fatwa"],
    ["nationalismus", "arabisch", "wataniyya", "arab"],
    ["osmanisch", "CUP", "jungtürken", "istanbul"],
    ["syrien", "damaskus", "provinz", "verwaltung"],
    ["presse", "zeitung", "journal", "artikel"],
]

N_CLUSTERS = len(seed_topic_list)


# ── Laden ─────────────────────────────────────────────────────────────────────

def load_segments() -> list[str]:
    raw = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    pool = [
        s.get("text", "")[:MAX_SEG_CHARS]
        for s in raw
        if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH
    ]
    random.seed(RANDOM_SEED)
    sample = random.sample(pool, min(MAX_SEGMENTS, len(pool)))
    print(f"Segmente: {len(pool)} verfügbar, {len(sample)} ausgewählt\n")
    return sample


def _seg_id(idx: int) -> str:
    return f"s{idx:04d}"


# ── Ausgabe-Hilfsfunktionen ───────────────────────────────────────────────────

_STOPWORDS = {
    "die","der","das","den","dem","des","ein","eine","einer","einen","einem",
    "und","oder","aber","auch","sich","mit","von","aus","bei","nach","vor",
    "über","unter","für","nicht","ist","war","sind","wird","wurde","werden",
    "hat","haben","hatte","hatten","kann","will","soll","dass","als","wie",
    "auf","an","in","im","am","zum","zur","nur","noch","dann","schon","mehr",
    "wenn","durch","gegen","seit","zwischen","diese","dieser","dieses",
    "ihrer","seine","seiner","seinen","ihrem","ihm","ihn","sie","ihr",
    "the","and","of","to","in","is","was","are","that","this","with","for",
    "not","from","have","had","been","they","their","which","but","also",
    "has","its","it","at","by","an","as","or","be","on",
}


def _tfidf_top_keywords(cluster_docs: list[str], n: int = 5) -> list[str]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    if len(cluster_docs) < 2:
        return []
    try:
        vec = TfidfVectorizer(
            max_features=500, sublinear_tf=True, min_df=1,
            token_pattern=r"(?u)\b[a-zA-ZäöüÄÖÜß\-]{3,}\b",
        )
        X      = vec.fit_transform(cluster_docs)
        scores = X.mean(axis=0).A1
        terms  = vec.get_feature_names_out()
        ranked = sorted(
            ((terms[i], scores[i]) for i in range(len(terms))
             if terms[i].lower() not in _STOPWORDS),
            key=lambda x: -x[1],
        )
        return [w for w, _ in ranked[:n]]
    except Exception:
        return []


def _seed_name(centroid, seed_embeddings) -> str:
    import numpy as np
    c = centroid / (np.linalg.norm(centroid) + 1e-9)
    return seed_topic_list[int((seed_embeddings @ c).argmax())][0].capitalize()


def _print_cluster_details(cat: dict) -> None:
    name     = cat["name"]
    count    = cat.get("count", "?")
    keywords = ", ".join(cat.get("keywords", []))
    segs     = cat.get("top_segments", [])

    print(f"\n── Cluster: {name} ({count} Segmente) " + "─" * max(0, 60 - len(name) - len(str(count)) - 14))
    print(f"Top-Keywords: {keywords}")
    for i, s in enumerate(segs, 1):
        preview = s["text"].replace("\n", " ").strip()
        print(f'\n  Segment {i} [{s["id"]}]:')
        print(f'  "{preview}"')


# ── LLM-Parser ────────────────────────────────────────────────────────────────

def _parse_keywords(text: str) -> list[str]:
    keywords: list[str] = []
    for line in text.splitlines():
        line = re.sub(r'^[\d]+[.):\s]+', '', line.strip()).strip()
        if not line:
            continue
        for kw in line.split(","):
            kw = kw.strip().strip("–-•·").strip()
            if kw and len(kw) > 1:
                keywords.append(kw)
    return keywords


def _parse_plaintext_taxonomy(text: str) -> list[dict]:
    results: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            if current and current.get("name"):
                results.append(current)
            name = re.sub(r'^\d+\.\s*', '', line.lstrip("#").strip())
            name = re.sub(r'\*+', '', name).strip()
            current = {"name": name, "description": "", "keywords": []}
        elif current is not None:
            if line.lower().startswith("keywords:"):
                kws_raw = line[len("keywords:"):].strip()
                current["keywords"] = [k.strip() for k in kws_raw.split(",") if k.strip()][:3]
                results.append(current)
                current = None
            elif not current["description"]:
                current["description"] = line
    if current and current.get("name"):
        results.append(current)
    return [c for c in results if c.get("name")]


def _top_segs_by_keywords(keywords: list[str], segments: list[str], n: int = 3) -> list[dict]:
    scored = []
    for i, text in enumerate(segments):
        tl = text.lower()
        score = sum(1 for kw in keywords if kw.lower() in tl)
        scored.append((score, i))
    scored.sort(key=lambda x: -x[0])
    return [
        {"id": _seg_id(idx), "text": segments[idx][:PREVIEW_CHARS]}
        for score, idx in scored[:n]
        if score > 0
    ]


# ── System A: LLM ─────────────────────────────────────────────────────────────

KW_SYSTEM   = "Du bist ein Forschungsassistent der Texte analysiert."
KW_TEMPLATE = (
    "Nenne für jeden der folgenden Texte 2-3 Themen oder Konzepte als kurze Stichwörter auf Deutsch.\n"
    "Format: eine Zeile pro Text, Stichwörter kommasepariert. Keine Erklärungen, keine Nummerierung.\n\n"
    "{segments}"
)
CAT_SYSTEM   = "Du bist ein Forschungsassistent der Notizen und Dokumente analysiert."
CAT_TEMPLATE = (
    "Hier sind Stichwörter aus einem Dokument:\n\n{keywords}\n\n"
    "Fasse diese Stichwörter zu 6-8 übergeordneten Themenkategorien zusammen. "
    "Führe ähnliche Begriffe zusammen.\n\n"
    "Für jede Kategorie:\n\n"
    "## Kategoriename\nBeschreibung in einem Satz.\nKeywords: keyword1, keyword2, keyword3\n\n"
    "Regeln:\n"
    "- Namen in PascalCase, max. 2 Wörter\n"
    "- Genau 3 Keywords, kommasepariert\n"
    "- Ausschließlich auf Deutsch, keine englischen Begriffe\n"
    "- Nur die Kategorieblöcke ausgeben, kein Kommentar, kein JSON"
)
KW_BATCH = 4


def run_llm(segments: list[str]) -> tuple[list[dict], float]:
    from src.generalized.llm import get_provider, TASK_ANALYZE

    load_dotenv(Path("data") / ".." / ".env")
    provider = get_provider(task=TASK_ANALYZE)
    print(f"System A (LLM): Modell = {provider.model}")

    t0 = time.perf_counter()

    batches  = [segments[i:i + KW_BATCH] for i in range(0, len(segments), KW_BATCH)]
    all_kws: list[str] = []
    for idx, batch in enumerate(batches, 1):
        texts   = [f"Text {i+1}:\n{t}" for i, t in enumerate(batch)]
        raw     = provider.complete(KW_TEMPLATE.format(segments="\n\n".join(texts)), system=KW_SYSTEM) or ""
        kws     = _parse_keywords(raw)
        all_kws += kws
        print(f"  Keyword-Batch {idx}/{len(batches)}: {len(kws)} Keywords", flush=True)

    seen: set[str] = set()
    unique: list[str] = []
    for kw in all_kws:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique.append(kw)
    print(f"  Gesamt: {len(all_kws)} → {len(unique)} eindeutig", flush=True)

    print("  Stufe 2: Destillation…", flush=True)
    kw_text  = "\n".join(f"- {kw}" for kw in unique)
    taxonomy = _parse_plaintext_taxonomy(
        provider.complete(CAT_TEMPLATE.format(keywords=kw_text), system=CAT_SYSTEM) or ""
    )
    if len(taxonomy) < 4:
        taxonomy = _parse_plaintext_taxonomy(
            provider.complete(CAT_TEMPLATE.format(keywords=kw_text), system=CAT_SYSTEM) or ""
        )

    for cat in taxonomy:
        cat["top_segments"] = _top_segs_by_keywords(cat.get("keywords", []), segments)

    elapsed = time.perf_counter() - t0
    return taxonomy, elapsed


# ── System B: KMeans Guided ───────────────────────────────────────────────────

def run_clustering(segments: list[str]) -> tuple[list[dict], float]:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import normalize

    print(f"System B (KMeans Guided): Embedding-Modell = {EMB_MODEL}, k={N_CLUSTERS}")
    t0 = time.perf_counter()

    print("  Lade Embedding-Modell…", flush=True)
    emb_model = SentenceTransformer(EMB_MODEL)

    print("  Berechne Segment-Embeddings…", flush=True)
    embeddings = emb_model.encode(segments, show_progress_bar=False)
    emb_norm   = normalize(embeddings)

    print("  Berechne Seed-Embeddings…", flush=True)
    seed_texts      = [" ".join(s) for s in seed_topic_list]
    seed_embeddings = normalize(emb_model.encode(seed_texts, show_progress_bar=False))

    print("  KMeans-Clustering…", flush=True)
    km = KMeans(n_clusters=N_CLUSTERS, init=seed_embeddings, n_init=1, random_state=42)
    km.fit(emb_norm)
    labels = km.labels_

    taxonomy: list[dict] = []
    for cid in range(N_CLUSTERS):
        indices      = [i for i, lb in enumerate(labels) if lb == cid]
        cluster_embs = emb_norm[np.array(indices)]
        centroid     = cluster_embs.mean(axis=0)
        # top-3 closest to centroid
        dists   = np.linalg.norm(cluster_embs - centroid, axis=1)
        top3    = [indices[j] for j in dists.argsort()[:3]]
        taxonomy.append({
            "name":         _seed_name(centroid, seed_embeddings),
            "keywords":     _tfidf_top_keywords([segments[i] for i in indices]),
            "count":        len(indices),
            "top_segments": [{"id": _seg_id(i), "text": segments[i][:PREVIEW_CHARS]} for i in top3],
        })

    taxonomy.sort(key=lambda c: -c["count"])
    return taxonomy, time.perf_counter() - t0


# ── System C: BERTopic mit HDBSCAN (macOS-Fix: core_dist_n_jobs=1) ───────────

def run_bertopic(segments: list[str]) -> tuple[list[dict], float]:
    import hdbscan as hdbscan_module
    from sentence_transformers import SentenceTransformer
    from bertopic import BERTopic

    print(f"System C (BERTopic Guided): Embedding-Modell = {EMB_MODEL}")
    t0 = time.perf_counter()

    print("  Lade Embedding-Modell…", flush=True)
    emb_model = SentenceTransformer(EMB_MODEL)

    print("  Berechne Embeddings…", flush=True)
    embeddings = emb_model.encode(segments, show_progress_bar=False)

    print("  Trainiere BERTopic (PCA + HDBSCAN, core_dist_n_jobs=1)…", flush=True)
    from sklearn.decomposition import PCA
    hdbscan_model = hdbscan_module.HDBSCAN(
        min_cluster_size=3,   # kleiner für 80-Dokument-Datensatz
        min_samples=1,        # weniger streng; reduziert Outlier-Anteil
        core_dist_n_jobs=1,   # verhindert OpenMP-Segfault auf macOS
    )
    topic_model = BERTopic(
        umap_model=PCA(n_components=5),  # UMAP hängt auf macOS; PCA stabil
        hdbscan_model=hdbscan_model,
        embedding_model=emb_model,
        seed_topic_list=seed_topic_list,
        language="multilingual",
        verbose=False,
    )
    topics, _ = topic_model.fit_transform(segments, embeddings)

    topic_info = topic_model.get_topic_info()
    topic_info = topic_info[topic_info["Topic"] != -1]

    # Text → index lookup für top_segments
    seg_index = {text: i for i, text in enumerate(segments)}

    taxonomy: list[dict] = []
    for _, row in topic_info.iterrows():
        tid       = row["Topic"]
        name      = row.get("Name") or f"Thema {tid}"
        top_words = topic_model.get_topic(tid)
        keywords  = [w for w, _ in top_words[:5]] if top_words else []
        count     = int(row.get("Count", 0))

        rep_docs  = topic_model.get_representative_docs(tid) or []
        top_segs  = [
            {"id": _seg_id(seg_index.get(doc, -1)), "text": doc[:PREVIEW_CHARS]}
            for doc in rep_docs[:3]
        ]
        taxonomy.append({"name": name, "keywords": keywords, "count": count,
                         "top_segments": top_segs})

    taxonomy.sort(key=lambda c: -c["count"])
    return taxonomy, time.perf_counter() - t0


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def print_report(
    llm_tax: list[dict], llm_t: float,
    cl_tax:  list[dict], cl_t:  float,
    bt_tax:  list[dict] | None, bt_t: float,
    n_segs:  int,
) -> None:
    W = 80
    print("\n" + "=" * W)
    print("  TAXONOMIE-VERGLEICH: LLM vs. KMeans Guided vs. BERTopic Guided")
    print(f"  Segmente: {n_segs}  |  Seed-Topics: {len(seed_topic_list)}")
    print("=" * W)

    # ── System A: LLM ─────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SYSTEM A — LLM  ({llm_t:.1f}s)  [{len(llm_tax)} Kategorien]")
    print(f"{'─'*W}")
    for cat in llm_tax:
        kws = ", ".join(cat.get("keywords", []))
        print(f"\n  {cat['name']:25s}  Keywords: {kws}")
        if cat.get("description"):
            print(f"  {'':25s}  {cat['description'][:65]}")
        for i, s in enumerate(cat.get("top_segments", []), 1):
            preview = s["text"].replace("\n", " ").strip()
            print(f'\n    Segment {i} [{s["id"]}]:')
            print(f'    "{preview}"')

    # ── System B: KMeans ──────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SYSTEM B — KMeans Guided  ({cl_t:.1f}s)  [{len(cl_tax)} Cluster]")
    print(f"{'─'*W}")
    for cat in cl_tax:
        _print_cluster_details(cat)

    # ── System C: BERTopic ────────────────────────────────────────────────────
    if bt_tax is not None:
        print(f"\n{'─'*W}")
        print(f"  SYSTEM C — BERTopic Guided  ({bt_t:.1f}s)  [{len(bt_tax)} Themen]")
        print(f"{'─'*W}")
        for cat in bt_tax:
            _print_cluster_details(cat)
    else:
        print(f"\n  SYSTEM C — BERTopic: nicht verfügbar (Import-Fehler oder Crash)")

    # ── Zusammenfassung ───────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print("  ZUSAMMENFASSUNG")
    print(f"{'─'*W}")
    print(f"  LLM-Kategorien:    {len(llm_tax):2d}  ({llm_t:.1f}s)")
    print(f"  KMeans-Cluster:    {len(cl_tax):2d}  ({cl_t:.1f}s)")
    if bt_tax is not None:
        print(f"  BERTopic-Themen:   {len(bt_tax):2d}  ({bt_t:.1f}s)")

    def _kw_overlap(tax_a: list[dict], tax_b: list[dict]) -> float:
        set_a = {kw.lower() for c in tax_a for kw in c.get("keywords", [])}
        set_b = {kw.lower() for c in tax_b for kw in c.get("keywords", [])}
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    print(f"\n  Keyword-Jaccard LLM∩KMeans:    {_kw_overlap(llm_tax, cl_tax):.2f}")
    if bt_tax:
        print(f"  Keyword-Jaccard LLM∩BERTopic:  {_kw_overlap(llm_tax, bt_tax):.2f}")
        print(f"  Keyword-Jaccard KMeans∩BERTopic:{_kw_overlap(cl_tax, bt_tax):.2f}")

    print(f"\n  Seed-Topic-Abdeckung (KMeans):")
    cl_kws = {w.lower() for c in cl_tax for w in c.get("keywords", [])}
    for seeds in seed_topic_list:
        hits = [s for s in seeds if s.lower() in cl_kws]
        print(f"    {seeds[0]:20s}  {len(hits)}/{len(seeds)}: {hits}")

    if bt_tax:
        print(f"\n  Seed-Topic-Abdeckung (BERTopic):")
        bt_kws = {w.lower() for c in bt_tax for w in c.get("keywords", [])}
        for seeds in seed_topic_list:
            hits = [s for s in seeds if s.lower() in bt_kws]
            print(f"    {seeds[0]:20s}  {len(hits)}/{len(seeds)}: {hits}")

    print("\n" + "=" * W)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not SEGMENTS_PATH.exists():
        raise FileNotFoundError(f"Segmentdatei nicht gefunden: {SEGMENTS_PATH}")

    segments = load_segments()

    print("─" * 60)
    llm_taxonomy, llm_time = run_llm(segments)

    print()
    print("─" * 60)
    cl_taxonomy, cl_time = run_clustering(segments)

    print()
    print("─" * 60)
    bt_taxonomy, bt_time = None, 0.0
    try:
        bt_taxonomy, bt_time = run_bertopic(segments)
    except Exception as e:
        print(f"  BERTopic fehlgeschlagen: {e}")

    print_report(llm_taxonomy, llm_time, cl_taxonomy, cl_time, bt_taxonomy, bt_time, len(segments))


if __name__ == "__main__":
    main()
