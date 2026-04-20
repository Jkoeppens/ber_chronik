"""
propose_taxonomy.py — Taxonomie-Vorschlag via LLM

5 Batches à 10 Segmente → je ein LLM-Call → Zwischenlisten.
Danach Code-Merge: Duplikate nach Name zusammenlegen, nach Häufigkeit
sortieren, auf 6-8 kürzen. Kein zweiter LLM-Call für den Merge (D-E1).

Anthropic: Batches parallel (max_concurrency=10).
Ollama:    Batches sequenziell.

LLM-Output-Format (Plaintext, kein JSON):

  ## Kategoriename
  Beschreibung in einem Satz.
  Keywords: keyword1, keyword2, keyword3

Input:  data/projects/{project}/documents/{document}/segments.json
Output: data/projects/{project}/config.json["taxonomy"]  (D-P1)
"""

import argparse
import asyncio
import re
import random
import sys
from collections import Counter
import json
from dotenv import load_dotenv

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.llm import get_provider, TASK_ANALYZE

N_BATCHES  = 5
BATCH_SIZE = 10
MIN_LENGTH = 80

SYSTEM_PROMPT = "Du bist ein Forschungsassistent der Notizen und Dokumente analysiert."

BATCH_TEMPLATE = """\
Analysiere diese Notizen. Erkenne selbst um welches Thema und welchen historischen Kontext es geht.
Schlage 4–6 Kategorien vor, die für eine systematische Klassifizierung dieses spezifischen Materials sinnvoll sind.

Für jede Kategorie:

## Kategoriename
Beschreibung in einem Satz.
Keywords: keyword1, keyword2, keyword3

Regeln:
- Namen in PascalCase, max. 2 Wörter
- Genau 3 Keywords, kommasepariert
- Ausschließlich auf Deutsch, keine englischen Begriffe
- Nur die Kategorieblöcke ausgeben, kein Kommentar, kein JSON

Notizen:
---
{segments}"""


def clean_name(raw: str) -> str:
    """Entfernt Nummerierungspräfixe und Markdown-Sternchen aus Kategorienamen."""
    name = re.sub(r'^\d+\.\s*', '', raw)   # "1. " am Anfang
    name = re.sub(r'\*+', '', name)         # ** oder *
    return name.strip()


def format_segment(s: dict) -> str:
    source = s.get("source") or "?"
    page   = f", S. {s['page']}" if s.get("page") else ""
    return f"[{source}{page}]\n{s['text']}"


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


def _merge_taxonomy(partial_lists: list[list[dict]]) -> list[dict]:
    """Code-Merge: Duplikate nach Name zusammenlegen, nach Häufigkeit sortieren, top 8."""
    name_count: Counter = Counter()
    first_seen: dict[str, dict] = {}

    for cats in partial_lists:
        seen_this_batch: set[str] = set()
        for cat in cats:
            key = (cat.get("name") or "").strip().lower()
            if not key:
                continue
            if key not in first_seen:
                first_seen[key] = dict(cat)
            if key not in seen_this_batch:
                name_count[key] += 1
                seen_this_batch.add(key)

    sorted_keys = sorted(first_seen, key=lambda k: -name_count[k])
    result = [first_seen[k] for k in sorted_keys[:8]]

    total = sum(name_count.values())
    print(f"Merge: {len(first_seen)} eindeutige Kategorien aus {total} Batch-Einträgen "
          f"→ {len(result)} übernommen", flush=True)
    return result


def _run_batch(provider, batch: list[dict], idx: int, total: int) -> list[dict]:
    print(f"Batch {idx}/{total}…", flush=True)
    segments_text = "\n\n".join(format_segment(s) for s in batch)
    prompt = BATCH_TEMPLATE.format(segments=segments_text)
    for attempt in range(2):
        text = provider.complete(prompt, system=SYSTEM_PROMPT)
        result = _parse_plaintext_taxonomy(text or "")
        if len(result) >= 2:
            print(f"  Batch {idx}: {len(result)} Kategorien", flush=True)
            return result
        if attempt == 0:
            print(f"  Batch {idx}: nur {len(result)} Kategorie(n) — Retry…", flush=True)
    print(f"  Batch {idx}: {len(result)} Kategorie(n) nach Retry — übernommen", flush=True)
    return result


async def _run_batch_async(provider, batch: list[dict], idx: int, total: int,
                           sem: asyncio.Semaphore) -> list[dict]:
    async with sem:
        return await asyncio.to_thread(_run_batch, provider, batch, idx, total)


def main() -> None:
    ap = argparse.ArgumentParser(description="Taxonomie-Vorschlag per LLM")
    ap.add_argument("--project",  required=True)
    ap.add_argument("--document", required=True)
    args = ap.parse_args()

    doc_dir     = PROJECTS_DIR / args.project / "documents" / args.document
    config_path = PROJECTS_DIR / args.project / "config.json"
    input_path  = doc_dir / "segments.json"

    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_ANALYZE)

    segments = json.loads(input_path.read_text(encoding="utf-8"))
    pool = [s for s in segments if s.get("type") == "content" and len(s.get("text", "")) >= MIN_LENGTH]

    n_total = N_BATCHES * BATCH_SIZE
    if len(pool) < n_total:
        print(f"Warnung: nur {len(pool)} geeignete Segmente (< {n_total})", file=sys.stderr)

    sample  = random.sample(pool, min(n_total, len(pool)))
    batches = [sample[i:i + BATCH_SIZE] for i in range(0, len(sample), BATCH_SIZE)]
    batches = batches[:N_BATCHES]

    print(f"Modell: {provider.model}  |  {len(batches)} Batches à {BATCH_SIZE} Segmente")

    # ── Batch-Phase ────────────────────────────────────────────────────────────
    if provider.max_concurrency > 1:
        sem = asyncio.Semaphore(provider.max_concurrency)

        async def run_all():
            tasks = [
                _run_batch_async(provider, batch, i + 1, len(batches), sem)
                for i, batch in enumerate(batches)
            ]
            return await asyncio.gather(*tasks)

        partial_lists = asyncio.run(run_all())
    else:
        partial_lists = [
            _run_batch(provider, batch, i + 1, len(batches))
            for i, batch in enumerate(batches)
        ]

    partial_lists = [p for p in partial_lists if p]
    if not partial_lists:
        print("Keine gültigen Batch-Ergebnisse", file=sys.stderr)
        sys.exit(1)

    # ── Merge-Phase (Code, kein LLM) ──────────────────────────────────────────
    taxonomy = _merge_taxonomy(partial_lists)

    if not taxonomy:
        print("Merge ergab keine Kategorien", file=sys.stderr)
        sys.exit(1)

    # D-P1: direkt in config.json["taxonomy"] schreiben — kein taxonomy_proposal.json mehr
    config_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    cfg["taxonomy"] = taxonomy
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"→ {config_path}  ({len(taxonomy)} Kategorien)\n")
    for cat in taxonomy:
        kw = ", ".join(cat.get("keywords", []))
        print(f"  {cat['name']:20s}  {cat.get('description','')[:60]}…")
        print(f"  {'':20s}  Keywords: {kw}")
        print()


if __name__ == "__main__":
    main()
