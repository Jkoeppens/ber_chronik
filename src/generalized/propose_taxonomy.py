"""
propose_taxonomy.py — Taxonomie-Vorschlag via LLM

5 Batches à 10 Segmente → je ein LLM-Call → Zwischenlisten.
Danach ein Merge-Call der alle Zwischenlisten zu 6-8 finalen Kategorien zusammenführt.

Anthropic: Batches parallel (max_concurrency=10).
Ollama:    Batches sequenziell.

Input:  data/projects/{project}/documents/{document}/segments.json
Output: data/projects/{project}/documents/{document}/taxonomy_proposal.json
"""

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.generalized.llm import get_provider, TASK_ANALYZE

ROOT = Path(__file__).resolve().parent.parent.parent

N_BATCHES  = 5
BATCH_SIZE = 10
MIN_LENGTH = 80

SYSTEM_PROMPT = "Du bist ein Forschungsassistent der Notizen und Dokumente analysiert."

BATCH_TEMPLATE = """\
Analysiere diese Notizen. Erkenne selbst um welches Thema und welchen historischen Kontext es geht.
Schlage 4–6 Kategorien vor, die für eine systematische Klassifizierung dieses spezifischen Materials sinnvoll sind.

Für jede Kategorie:
- name: kurzer Bezeichner (PascalCase, max. 2 Wörter)
- description: ein Satz, der beschreibt welche Inhalte diese Kategorie umfasst
- keywords: genau 3 Schlüsselwörter, nicht mehr, nicht weniger

Wichtig:
- Antworte ausschließlich auf Deutsch. Keine englischen Begriffe.
- Antworte ausschließlich als JSON-Array, ohne Erklärungen, ohne Markdown-Codeblöcke.

Format: [{{"name": "...", "description": "...", "keywords": ["...", "...", "..."]}}]

Notizen:
---
{segments}"""

MERGE_TEMPLATE = """\
Du hast {n} Teilanalysen desselben historischen Quellmaterials erhalten.
Jede enthält Kategorie-Vorschläge. Führe sie zu 6–8 finalen Kategorien zusammen.

Regeln:
- Ähnliche oder überlappende Kategorien zusammenführen
- Kategorien die das Material nicht gut abdecken weglassen
- Namen in PascalCase, max. 2 Wörter
- Jede Kategorie hat genau 3 Keywords, nicht mehr, nicht weniger

Wichtig:
- Antworte ausschließlich auf Deutsch. Keine englischen Begriffe.
- Antworte ausschließlich als JSON-Array, ohne Erklärungen, ohne Markdown-Codeblöcke.

Format: [{{"name": "...", "description": "...", "keywords": ["...", "...", "..."]}}]

Teilanalysen:
---
{partial}"""


def format_segment(s: dict) -> str:
    source = s.get("source") or "?"
    page   = f", S. {s['page']}" if s.get("page") else ""
    return f"[{source}{page}]\n{s['text']}"


def _normalize(raw) -> list[dict]:
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [c for c in raw if isinstance(c, dict) and c.get("name")]


def _run_batch(provider, batch: list[dict], idx: int, total: int) -> list[dict]:
    print(f"Batch {idx}/{total}…", flush=True)
    segments_text = "\n\n".join(format_segment(s) for s in batch)
    prompt = BATCH_TEMPLATE.format(segments=segments_text)
    for attempt in range(2):
        try:
            raw = provider.complete_json(prompt, system=SYSTEM_PROMPT)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Batch {idx}: JSON-Fehler ({e})" + (" — Retry…" if attempt == 0 else " — übersprungen"), file=sys.stderr)
            continue
        result = _normalize(raw)
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


def _merge(provider, partial_lists: list[list[dict]]) -> list[dict]:
    print("Merge-Call…", flush=True)
    parts = []
    for i, cats in enumerate(partial_lists, 1):
        block = json.dumps(cats, ensure_ascii=False)
        parts.append(f"Teilanalyse {i}:\n{block}")
    prompt = MERGE_TEMPLATE.format(n=len(partial_lists), partial="\n\n".join(parts))
    try:
        raw = provider.complete_json(prompt, system=SYSTEM_PROMPT)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Merge JSON-Fehler: {e}", file=sys.stderr)
        # Fallback: alle Zwischenlisten flach zusammenführen, Duplikate nach Name entfernen
        seen: set[str] = set()
        fallback = []
        for cats in partial_lists:
            for c in cats:
                key = c.get("name", "").lower()
                if key and key not in seen:
                    seen.add(key)
                    fallback.append(c)
        return fallback[:8]
    return _normalize(raw)


def main() -> None:
    ap = argparse.ArgumentParser(description="Taxonomie-Vorschlag per LLM")
    ap.add_argument("--project",  required=True)
    ap.add_argument("--document", required=True)
    args = ap.parse_args()

    doc_dir     = ROOT / "data" / "projects" / args.project / "documents" / args.document
    input_path  = doc_dir / "segments.json"
    output_path = doc_dir / "taxonomy_proposal.json"

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

    sample = random.sample(pool, min(n_total, len(pool)))
    batches = [sample[i:i + BATCH_SIZE] for i in range(0, len(sample), BATCH_SIZE)]
    # Trim to N_BATCHES in case sample < n_total produced fewer chunks
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

    # ── Merge-Phase ────────────────────────────────────────────────────────────
    taxonomy = _merge(provider, partial_lists)

    if not taxonomy:
        print("Merge ergab keine Kategorien", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"→ {output_path}  ({len(taxonomy)} Kategorien)\n")
    for cat in taxonomy:
        kw = ", ".join(cat.get("keywords", []))
        print(f"  {cat['name']:20s}  {cat.get('description','')[:60]}…")
        print(f"  {'':20s}  Keywords: {kw}")
        print()


if __name__ == "__main__":
    main()
