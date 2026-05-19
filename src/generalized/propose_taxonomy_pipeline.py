"""
propose_taxonomy_pipeline.py — Taxonomie-Vorschlag: Embedding-Clustering + LLM

Algorithmus:
  1. Segmente embedden via get_embedding_provider(EMB_TASK_CLUSTER)
       EMBEDDING_PROVIDER=local  → MiniLM  (lokal, ~120 MB)
       EMBEDDING_PROVIDER=voyage → Voyage-4 (API, VOYAGE_API_KEY)
  2. KMeans-Clustering (sklearn)
  3. Top-5 Repräsentanten pro Cluster (Zentroid-Abstand)
  4. Ein LLM-Call für alle Cluster via get_provider(TASK_ANALYZE)
  5. Schreiben nach config.json["taxonomy"]  (D-P1)

Kein direkter Modell-Import. Kein bge→kmeans-Redirect.
Provider-Wahl ausschließlich über EMBEDDING_PROVIDER und LLM_PROVIDER.

Input:  data/projects/{project}/documents/{document}/segments.json
Output: data/projects/{project}/config.json["taxonomy"]
"""

import argparse
import json
import os
import re
import sys

import numpy as np
from dotenv import load_dotenv
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.embeddings import EMB_TASK_CLUSTER, get_embedding_provider
from src.generalized.llm import get_provider, TASK_ANALYZE
from src.generalized.utils import read_json_safe

MIN_LENGTH  = 80    # Mindesttextlänge für Aufnahme in Pool
SEG_CHARS   = 500   # Zeichen-Limit beim Embedden
LABEL_CHARS = 300   # Zeichen-Limit für LLM-Labeling-Prompt

SYSTEM = (
    "Du analysierst Texte und vergibst prägnante, unterschiedliche Kategorienamen. "
    "Schreibe ausschließlich auf Deutsch."
)

LABEL_TEMPLATE = """\
Hier sind {n} Gruppen von Texten. Benenne jede Gruppe mit einer prägnanten \
Kategorie die sie klar von den anderen abgrenzt.

{groups}

Antworte für jede Gruppe im Format — kein weiterer Text, kein JSON:

## Kategoriename
Ein Satz der beschreibt was diese Gruppe inhaltlich zusammenhält.
Keywords: keyword1, keyword2, keyword3

Regeln:
- Namen in PascalCase, max. 3 Wörter, auf Deutsch
- Genau 3 Keywords, kommasepariert, auf Deutsch
- Jede Gruppe muss sich klar von den anderen unterscheiden"""


def _parse_taxonomy(text: str) -> list[dict]:
    """Parst ## Name / Beschreibung / Keywords: … Format."""
    results: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("##"):
            if current and current.get("name"):
                results.append(current)
            name = re.sub(r"\*+", "", line.lstrip("#").strip())
            name = re.sub(r"^Gruppe\s+\d+[:\.\-–]\s*", "", name).strip()
            current = {"name": name, "description": "", "keywords": []}
        elif current is not None:
            if line.lower().startswith("keywords:"):
                kws = line[len("keywords:"):].strip()
                current["keywords"] = [k.strip() for k in kws.split(",") if k.strip()][:3]
                results.append(current)
                current = None
            elif not current["description"]:
                current["description"] = line
    if current and current.get("name"):
        results.append(current)
    return [c for c in results if c.get("name")]


def _cluster_and_label(texts: list[str], n_clusters: int, provider) -> list[dict]:
    """Embedden → KMeans → Top-5 Repräsentanten pro Cluster → ein LLM-Call."""
    emb_provider_name = os.environ.get("EMBEDDING_PROVIDER", "local")
    print(f"Embeddings: EMBEDDING_PROVIDER={emb_provider_name}  |  {len(texts)} Segmente…",
          flush=True)

    embs = normalize(get_embedding_provider(EMB_TASK_CLUSTER).encode(texts))
    print(f"  shape={embs.shape}", flush=True)

    print(f"KMeans: {n_clusters} Cluster…", flush=True)
    labels = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto").fit_predict(embs)

    cluster_snippets: list[list[str]] = []
    for cid in range(n_clusters):
        idx = np.where(labels == cid)[0]
        if len(idx) == 0:
            cluster_snippets.append([])
            continue
        centroid = embs[idx].mean(axis=0)
        dists    = np.linalg.norm(embs[idx] - centroid, axis=1)
        top5     = idx[dists.argsort()[:5]]
        cluster_snippets.append([texts[i][:LABEL_CHARS] for i in top5])

    non_empty = [(cid, snips) for cid, snips in enumerate(cluster_snippets) if snips]
    n_empty   = n_clusters - len(non_empty)
    if n_empty:
        print(f"  {n_empty} leere Cluster übersprungen", flush=True)
    print(f"  {len(non_empty)} Cluster → ein LLM-Call…", flush=True)

    groups = []
    for i, (_cid, snips) in enumerate(non_empty, 1):
        body = "\n\n".join(f"[{j+1}] {t}" for j, t in enumerate(snips))
        groups.append(f"=== Gruppe {i} ===\n{body}")

    prompt = LABEL_TEMPLATE.format(n=len(non_empty), groups="\n\n".join(groups))

    cats: list[dict] = []
    for attempt in range(2):
        raw  = provider.complete(prompt, system=SYSTEM) or ""
        cats = _parse_taxonomy(raw)
        if len(cats) >= max(1, len(non_empty) // 2):
            break
        if attempt == 0:
            print(f"  Nur {len(cats)} Kategorien geparst — Retry…", flush=True)

    print(f"  → {len(cats)}/{len(non_empty)} Kategorien geparst", flush=True)
    for cat in cats:
        print(f"    {cat['name']}", flush=True)
    return cats


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Taxonomie-Vorschlag via Embedding-Clustering + LLM"
    )
    ap.add_argument("--project",    required=True, help="Projektname (z.B. ber)")
    ap.add_argument("--document",   required=True, help="Dokument-ID (z.B. main)")
    ap.add_argument("--n-clusters", type=int, default=7, help="Cluster-Anzahl (Default: 7)")
    args = ap.parse_args()

    doc_dir       = PROJECTS_DIR / args.project / "documents" / args.document
    config_path   = PROJECTS_DIR / args.project / "config.json"
    segments_path = doc_dir / "segments.json"

    if not segments_path.exists():
        print(f"Nicht gefunden: {segments_path}", file=sys.stderr)
        sys.exit(1)

    load_dotenv(ROOT / ".env")

    provider = get_provider(task=TASK_ANALYZE)

    segments = read_json_safe(segments_path, default=[])
    pool = [
        s for s in segments
        if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH
    ]
    if not pool:
        print("Keine geeigneten Segmente gefunden.", file=sys.stderr)
        sys.exit(1)

    texts = [s.get("text", "")[:SEG_CHARS] for s in pool]
    n_clusters = min(args.n_clusters, len(texts))

    print(
        f"Pool: {len(texts)} Segmente  |  "
        f"Modell: {provider.model}  |  "
        f"Cluster: {n_clusters}",
        flush=True,
    )

    taxonomy = _cluster_and_label(texts, n_clusters, provider)
    if not taxonomy:
        print("Kein Ergebnis — LLM-Output nicht parsbar.", file=sys.stderr)
        sys.exit(1)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = read_json_safe(config_path)
    cfg["taxonomy"] = taxonomy
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n→ {config_path}  ({len(taxonomy)} Kategorien)\n")
    for cat in taxonomy:
        kw = ", ".join(cat.get("keywords", []))
        print(f"  {cat['name']:20s}  {cat.get('description', '')[:60]}")
        if kw:
            print(f"  {'':20s}  Keywords: {kw}")
        print()


if __name__ == "__main__":
    main()
