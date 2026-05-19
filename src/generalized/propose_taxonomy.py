"""
propose_taxonomy.py — Taxonomie-Vorschlag via LLM oder KMeans+LLM

Zwei Methoden (--method):

  llm    (Standard) — 3-stufige LLM-Architektur:
           1. Keyword-Extraktion: Segmente in Batches à 4
           2. Kategorie-Destillation: ein LLM-Call über alle Keywords
           3. Schreiben nach config.json["taxonomy"]

  kmeans — Embedding-Clustering + pro-Cluster-LLM:
           1. Alle content-Segmente embedden (paraphrase-multilingual-MiniLM-L12-v2)
           2. KMeans mit n_clusters (default 7)
           3. Pro Cluster: Top-5 nächste Segmente → ein LLM-Call zur Benennung
           4. Schreiben nach config.json["taxonomy"]

LLM-Output-Format (beide Methoden):

  ## Kategoriename
  Beschreibung in einem Satz.
  Keywords: keyword1, keyword2, keyword3

Input:  data/projects/{project}/documents/{document}/segments.json
Output: data/projects/{project}/config.json["taxonomy"]  (D-P1)
"""

import argparse
import asyncio
import os
import re
import random
import sys
import json
from dotenv import load_dotenv

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.llm import get_provider, TASK_ANALYZE
from src.generalized.utils import read_json_safe

MAX_SEGMENTS  = 80    # maximale Segmente aus dem Pool
KW_BATCH_SIZE = 4     # Segmente pro Keyword-Batch (Stufe 1)
MAX_SEG_CHARS = 1000  # Zeichen-Limit pro Segment
MIN_LENGTH    = 80    # Mindesttextlänge für Aufnahme in Pool

KW_SYSTEM = "Du bist ein Forschungsassistent der Texte analysiert."

KW_TEMPLATE = """\
Nenne für jeden der folgenden Texte 2-3 Themen oder Konzepte als kurze Stichwörter auf Deutsch.
Format: eine Zeile pro Text, Stichwörter kommasepariert. Keine Erklärungen, keine Nummerierung.

{segments}"""

CAT_SYSTEM = "Du bist ein Forschungsassistent der Notizen und Dokumente analysiert."

CAT_TEMPLATE = """\
Hier sind Stichwörter aus einem Dokument:

{keywords}

Fasse diese Stichwörter zu 6-8 übergeordneten Themenkategorien zusammen. Führe ähnliche Begriffe zusammen.

Für jede Kategorie:

## Kategoriename
Beschreibung in einem Satz.
Keywords: keyword1, keyword2, keyword3

Regeln:
- Namen in PascalCase, max. 2 Wörter
- Genau 3 Keywords, kommasepariert
- Ausschließlich auf Deutsch, keine englischen Begriffe
- Nur die Kategorieblöcke ausgeben, kein Kommentar, kein JSON"""

# ── KMeans-Pfad: Alle-Cluster-Prompt ─────────────────────────────────────────

KMEANS_SEG_CHARS = 500   # kürzer als LLM-Pfad; Prompt fasst alle Cluster

CLUSTER_SYSTEM = "Du analysierst Forschungsnotizen zur osmanischen Geschichte."

ALL_CLUSTERS_HEADER = """\
Hier sind {n} Gruppen von Texten. Benenne jede Gruppe mit einer distincten \
Kategorie die sie von den anderen abgrenzt.

{groups}
Antworte für jede Gruppe:
## Gruppe 1: [Kurzer Name, 2-4 Wörter]
[Ein Satz der diese Gruppe von den anderen abgrenzt]
Keywords: keyword1, keyword2, keyword3

## Gruppe 2: ..."""


def clean_name(raw: str) -> str:
    """Entfernt Nummerierungspräfixe und Markdown-Sternchen aus Kategorienamen."""
    name = re.sub(r'^\d+\.\s*', '', raw)
    name = re.sub(r'\*+', '', name)
    return name.strip()


def _parse_plaintext_taxonomy(text: str) -> list[dict]:
    """Parst das ## Name / Beschreibung / Keywords: … Format."""
    results: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("##"):
            if current and current.get("name"):
                results.append(current)
            current = {"name": clean_name(line.lstrip("#").strip()), "description": "", "keywords": []}
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


def _parse_keywords(text: str) -> list[str]:
    """Parst kommaseparierte Keywords aus Stufe-1-Output (eine Zeile pro Segment)."""
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


# ── KMeans-Pfad ───────────────────────────────────────────────────────────────

def _label_all_clusters(provider, cluster_texts: list[list[str]]) -> list[dict]:
    """Benennt alle Cluster in einem einzigen LLM-Call."""
    n = len(cluster_texts)
    groups = []
    for i, texts in enumerate(cluster_texts, 1):
        body = "\n\n".join(f"Text {j+1}:\n{t}" for j, t in enumerate(texts))
        groups.append(f"=== Gruppe {i} ===\n{body}")
    prompt = ALL_CLUSTERS_HEADER.format(n=n, groups="\n\n".join(groups) + "\n\n")

    print(f"  {n} Cluster → ein LLM-Call…", flush=True)
    raw  = provider.complete(prompt, system=CLUSTER_SYSTEM) or ""
    cats = _parse_plaintext_taxonomy(raw)

    # Strip "Gruppe N: " prefix that the LLM echoes back in the name
    for cat in cats:
        cat["name"] = re.sub(r"^Gruppe\s+\d+:\s*", "", cat["name"]).strip()

    print(f"  → {len(cats)}/{n} Kategorien geparst", flush=True)
    for cat in cats:
        print(f"    {cat['name']}", flush=True)
    return cats


def _run_kmeans(pool: list[dict], provider, n_clusters: int) -> list[dict]:
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import normalize
    from src.generalized.embeddings import EMB_TASK_CLUSTER, get_embedding_provider

    texts = [s.get("text", "")[:KMEANS_SEG_CHARS] for s in pool]
    print(f"KMeans: {len(texts)} Segmente, {n_clusters} Cluster", flush=True)

    emb_norm = normalize(get_embedding_provider(EMB_TASK_CLUSTER).encode(texts))
    print(f"  Embeddings: {emb_norm.shape}", flush=True)

    print("  KMeans…", flush=True)
    km     = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = km.fit_predict(emb_norm)

    # Top-5 Segmente pro Cluster (nächste zum Centroid)
    cluster_texts: list[list[str]] = []
    for cid in range(n_clusters):
        indices      = [i for i, lb in enumerate(labels) if lb == cid]
        if not indices:
            cluster_texts.append([])
            continue
        cluster_embs = emb_norm[np.array(indices)]
        centroid     = cluster_embs.mean(axis=0)
        dists        = np.linalg.norm(cluster_embs - centroid, axis=1)
        top5         = [indices[j] for j in dists.argsort()[:5]]
        cluster_texts.append([texts[i] for i in top5])

    # Leere Cluster rausfiltern, aber Index merken für Zuordnung
    non_empty = [(cid, ct) for cid, ct in enumerate(cluster_texts) if ct]
    taxonomy  = _label_all_clusters(provider, [ct for _, ct in non_empty])
    return taxonomy


# ── Stufe 1: Keyword-Extraktion ────────────────────────────────────────────────

def _run_keyword_batch(provider, batch: list[dict], idx: int, total: int) -> list[str]:
    print(f"  Keyword-Batch {idx}/{total}…", flush=True)
    texts = []
    for i, s in enumerate(batch, 1):
        text = s.get("text", "")[:MAX_SEG_CHARS]
        source = s.get("source") or "?"
        texts.append(f"Text {i} [{source}]:\n{text}")
    prompt = KW_TEMPLATE.format(segments="\n\n".join(texts))
    result = provider.complete(prompt, system=KW_SYSTEM)
    keywords = _parse_keywords(result or "")
    print(f"    → {len(keywords)} Keywords", flush=True)
    return keywords


async def _run_keyword_batch_async(provider, batch, idx, total, sem):
    async with sem:
        return await asyncio.to_thread(_run_keyword_batch, provider, batch, idx, total)


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Taxonomie-Vorschlag per LLM oder KMeans+LLM")
    ap.add_argument("--project",    required=True)
    ap.add_argument("--document",   required=True)
    ap.add_argument("--method",     choices=["llm", "kmeans", "bge"], default="llm",
                    help="llm = bestehender 3-Stufen-Pfad (Standard); kmeans = Embedding-Clustering + LLM; bge = BGE-M3 + TF-IDF-Anchor")
    ap.add_argument("--n-clusters", type=int, default=7,
                    help="Anzahl Cluster für --method kmeans (Standard: 7)")
    args = ap.parse_args()

    doc_dir     = PROJECTS_DIR / args.project / "documents" / args.document
    config_path = PROJECTS_DIR / args.project / "config.json"
    input_path  = doc_dir / "segments.json"

    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_ANALYZE)

    segments = read_json_safe(input_path, default=[])
    pool = [s for s in segments
            if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]

    if not pool:
        print("Keine geeigneten Segmente gefunden.", file=sys.stderr)
        sys.exit(1)

    emb_provider_name = os.environ.get("EMBEDDING_PROVIDER", "local").lower()

    # ── BGE-Pfad ──────────────────────────────────────────────────────────────
    # Bei nicht-lokalem Embedding-Provider (z.B. voyage): kmeans-Pfad nutzen,
    # der intern get_embedding_provider() aufruft.
    if args.method == "bge":
        if emb_provider_name != "local":
            print(f"Methode: BGE → KMeans (EMBEDDING_PROVIDER={emb_provider_name})", flush=True)
            taxonomy = _run_kmeans(pool, provider, args.n_clusters)
            if not taxonomy:
                print("KMeans ergab keine Kategorien.", file=sys.stderr)
                sys.exit(1)
        else:
            import src.generalized.test_tfidf_anchor_taxonomy as _bge

            cache_path = doc_dir / "bge_embeddings.npy"
            texts, _   = _bge.load_segments(input_path)

            cfg_existing = read_json_safe(config_path)
            prev_tax     = cfg_existing.get("taxonomy") or None

            n_clusters = len(prev_tax) if prev_tax else args.n_clusters

            if prev_tax:
                print(f"Warm-Start: {len(prev_tax)} bestehende Kategorien → n_clusters={n_clusters}", flush=True)
            print(f"Methode: BGE  |  Modell: {_bge.MODEL_ANTHROPIC}  |  Cluster: {n_clusters}", flush=True)

            bge      = _bge._load_bge()
            seg_embs = _bge._compute_segment_embeddings(bge, texts, cache_path)
            seg_embs = _bge._neighbor_aggregate(seg_embs, texts)

            result = _bge._run_tfidf_anchor(
                bge, seg_embs, texts,
                n_clusters=n_clusters,
                previous_taxonomy=prev_tax,
            )
            result = _bge._eval(result, seg_embs)

            kw_map      = result["kw_map"]
            logs        = result.get("iteration_logs", [])
            last_parsed = logs[-1].get("parsed", []) if logs else []

            taxonomy = []
            for cid in range(n_clusters):
                if cid < len(last_parsed) and last_parsed[cid] is not None:
                    title, body = last_parsed[cid]
                else:
                    s = result["summaries"][cid]
                    title, body = (s.split(". ", 1) if ". " in s else (s, ""))
                taxonomy.append({
                    "name":        title,
                    "description": body,
                    "keywords":    kw_map.get(cid, [])[:5],
                })

            print(f"\nBGE: {n_clusters} Cluster → {len(taxonomy)} Kategorien  "
                  f"|  Ø Delta {result['avg_delta']:+.4f}  |  ${result['cost_usd']:.4f}", flush=True)

    # ── KMeans-Pfad ───────────────────────────────────────────────────────────
    elif args.method == "kmeans":
        print(f"Methode: KMeans  |  Modell: {provider.model}  |  Cluster: {args.n_clusters}")
        taxonomy = _run_kmeans(pool, provider, args.n_clusters)
        if not taxonomy:
            print("KMeans ergab keine Kategorien.", file=sys.stderr)
            sys.exit(1)

    # ── LLM-Pfad (unverändert) ────────────────────────────────────────────────
    else:
        sample  = random.sample(pool, min(MAX_SEGMENTS, len(pool)))
        batches = [sample[i:i + KW_BATCH_SIZE] for i in range(0, len(sample), KW_BATCH_SIZE)]

        print(f"Modell: {provider.model}  |  "
              f"Stufe 1: {len(batches)} Batches à {KW_BATCH_SIZE} Segmente ({len(sample)} gesamt)")

        # ── Stufe 1: Keyword-Extraktion (parallel / sequenziell) ──────────────
        if provider.max_concurrency > 1:
            sem = asyncio.Semaphore(provider.max_concurrency)

            async def _run_all():
                tasks = [
                    _run_keyword_batch_async(provider, b, i + 1, len(batches), sem)
                    for i, b in enumerate(batches)
                ]
                return await asyncio.gather(*tasks)

            kw_lists = asyncio.run(_run_all())
        else:
            kw_lists = [
                _run_keyword_batch(provider, b, i + 1, len(batches))
                for i, b in enumerate(batches)
            ]

        all_keywords = [kw for kws in kw_lists for kw in kws]
        if not all_keywords:
            print("Stufe 1 ergab keine Keywords.", file=sys.stderr)
            sys.exit(1)

        # Exakte Deduplizierung (case-insensitiv) vor Stufe 2
        seen: set[str] = set()
        unique_keywords: list[str] = []
        for kw in all_keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique_keywords.append(kw)

        print(f"\nStufe 1: {len(all_keywords)} Keywords → {len(unique_keywords)} eindeutig")

        # ── Stufe 2: Kategorie-Destillation (ein LLM-Call) ────────────────────
        print("Stufe 2: Kategorie-Destillation …", flush=True)
        kw_text    = "\n".join(f"- {kw}" for kw in unique_keywords)
        cat_prompt = CAT_TEMPLATE.format(keywords=kw_text)

        taxonomy: list[dict] = []
        for attempt in range(2):
            cat_text = provider.complete(cat_prompt, system=CAT_SYSTEM)
            taxonomy = _parse_plaintext_taxonomy(cat_text or "")
            if len(taxonomy) >= 4:
                break
            if attempt == 0:
                print(f"  Nur {len(taxonomy)} Kategorie(n) — Retry…", flush=True)

        if not taxonomy:
            print("Stufe 2 ergab keine Kategorien.", file=sys.stderr)
            sys.exit(1)

        print(f"Stufe 2: {len(taxonomy)} Kategorien")

    # ── config.json schreiben (D-P1) — beide Pfade ───────────────────────────
    config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = read_json_safe(config_path)
    cfg["taxonomy"] = taxonomy
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n→ {config_path}  ({len(taxonomy)} Kategorien)\n")
    for cat in taxonomy:
        kw = ", ".join(cat.get("keywords", []))
        print(f"  {cat['name']:20s}  {cat.get('description', '')[:60]}")
        print(f"  {'':20s}  Keywords: {kw}")
        print()


if __name__ == "__main__":
    main()
