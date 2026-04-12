"""
classify_segments.py — Segmente per Claude Haiku klassifizieren

Input:  data/interim/generalized/segments.json
        data/interim/generalized/taxonomy_proposal.json
Output: data/interim/generalized/classified.json

Technisch:
  - CONCURRENCY gleichzeitige Requests pro Batch via asyncio.gather
  - BATCH_PAUSE Sekunden zwischen Batches (Rate-Limit-Schutz)
  - Resume-fähig: bereits klassifizierte Segmente überspringen
  - Bei ungültigem JSON: einmal retry, dann category=null, confidence=low
  - Fortschrittsanzeige mit tqdm
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.generalized.llm import get_provider, TASK_CLASSIFY
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent.parent

BATCH_PAUSE    = 12.0   # Sekunden nach jedem Batch (10 req / 12s ≈ 50 RPM); 0 bei max_concurrency==1
SAVE_INTERVAL  = 2      # nach je N Batches zwischenspeichern

SYSTEM_PROMPT  = "Du klassifizierst Forschungsnotizen nach vorgegebenen Kategorien. Antworte ausschließlich als JSON."

USER_TEMPLATE  = """\
Kategorien:
{categories}

Klassifiziere diese Notiz in genau eine Kategorie.
Antworte NUR mit diesem JSON-Objekt, kein Markdown, keine Erklärungen:
{{"category": "<Name>", "confidence": "<high|medium|low>"}}

Notiz:
{text}"""


def build_categories_block(taxonomy: list[dict]) -> str:
    return "\n".join(f"- {cat['name']} – {cat['description']}" for cat in taxonomy)


def normalize_category(raw: str | None, valid_names: list[str]) -> str | None:
    """Normalisiert die LLM-Kategorie gegen die gültige Taxonomie-Liste.

    1. Exakter Match → nehmen
    2. Kein exakter Match → längsten gültigen Namen der als Substring vorkommt nehmen
    3. Kein Substring-Match → "(unbekannt)"
    """
    if raw is None:
        return None
    # 1. Exakt
    if raw in valid_names:
        return raw
    # 2. Substring — längsten Match bevorzugen (z.B. "Außenpolitik" vor "Politik")
    raw_lower = raw.lower()
    matches = [n for n in valid_names if n.lower() in raw_lower]
    if matches:
        return max(matches, key=len)
    return "(unbekannt)"


async def classify_one(
    provider,
    segment: dict,
    categories_block: str,
    valid_names: list[str],
) -> dict:
    """Klassifiziert ein einzelnes Segment. Bei JSON-Fehler: einmal retry."""
    user_prompt = USER_TEMPLATE.format(
        categories=categories_block,
        text=segment["text"],
    )

    async def call_api() -> str:
        if provider.max_concurrency == 1:
            # Sequenzieller Modus: direkt synchron aufrufen, kein Thread-Pool
            return provider.complete(user_prompt, SYSTEM_PROMPT)
        return await asyncio.to_thread(
            provider.complete, user_prompt, SYSTEM_PROMPT
        )

    for attempt in range(2):
        raw = await call_api()
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
            return {
                **segment,
                "category":   normalize_category(parsed.get("category"), valid_names),
                "confidence": parsed.get("confidence", "low"),
            }
        except json.JSONDecodeError:
            if attempt == 0:
                continue
            return {**segment, "category": None, "confidence": "low"}


def print_stats(results: list[dict], taxonomy: list[dict]) -> None:
    valid_names = {cat["name"] for cat in taxonomy}
    total       = len(results)
    if not total:
        return

    from collections import Counter
    cat_counter  = Counter(r.get("category") for r in results)
    conf_counter = Counter(r.get("confidence") for r in results)

    print(f"\nKlassifiziert: {total} Segmente\n")

    print("Verteilung nach Kategorie:")
    for cat in taxonomy:
        n = cat_counter.get(cat["name"], 0)
        bar = "█" * min(n, 40)
        print(f"  {cat['name']:25s}  {n:4d}  {bar}")
    for name, n in cat_counter.most_common():
        if name not in valid_names:
            print(f"  {'(unbekannt) ' + str(name):25s}  {n:4d}")

    print(f"\nVerteilung nach Konfidenz:")
    for level in ("high", "medium", "low", None):
        n = conf_counter.get(level, 0)
        label = level or "null"
        print(f"  {label:8s}  {n:4d}  ({n/total*100:.1f} %)")


async def main_async() -> None:
    ap = argparse.ArgumentParser(description="Segmente per LLM klassifizieren")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    ap.add_argument("--force", action="store_true", help="Cache ignorieren, alle Segmente neu klassifizieren")
    args = ap.parse_args()

    project_dir   = ROOT / "data" / "projects" / args.project
    doc_dir       = project_dir / "documents" / args.document
    SEGMENTS_PATH = doc_dir / "segments.json"
    OUTPUT_PATH   = doc_dir / "classified.json"

    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_CLASSIFY)

    if not SEGMENTS_PATH.exists():
        print(f"Nicht gefunden: {SEGMENTS_PATH}", file=sys.stderr)
        sys.exit(1)

    segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))

    # Taxonomie von Projektebene (project_dir/config.json) lesen
    project_cfg_path = project_dir / "config.json"
    taxonomy = []
    if project_cfg_path.exists():
        taxonomy = json.loads(project_cfg_path.read_text(encoding="utf-8")).get("taxonomy", [])
    # Fallback: per-doc taxonomy_proposal.json
    if not taxonomy:
        fallback = doc_dir / "taxonomy_proposal.json"
        if fallback.exists():
            taxonomy = json.loads(fallback.read_text(encoding="utf-8"))
    if not taxonomy:
        print("Keine Taxonomie gefunden (weder project config noch taxonomy_proposal.json)", file=sys.stderr)
        sys.exit(1)
    # Normalisieren: einzelnes Dict → Liste; Strings/ungültige Einträge verwerfen
    if isinstance(taxonomy, dict):
        taxonomy = [taxonomy]
    taxonomy = [c for c in taxonomy if isinstance(c, dict) and c.get("name")]
    if not taxonomy:
        print("Taxonomie enthält keine gültigen Kategorien (erwartet: Liste von {name, description})", file=sys.stderr)
        sys.exit(1)

    content_segments = [s for s in segments if s.get("type") == "content"]
    categories_block = build_categories_block(taxonomy)
    valid_names      = [cat["name"] for cat in taxonomy]

    # ── Resume: bereits klassifizierte laden (überspringen bei --force) ──────
    existing: dict[str, dict] = {}
    if not args.force and OUTPUT_PATH.exists():
        for r in json.loads(OUTPUT_PATH.read_text(encoding="utf-8")):
            if r.get("category") is not None or r.get("confidence") is not None:
                existing[r["segment_id"]] = r

    to_classify = [s for s in content_segments if s["segment_id"] not in existing]
    print(f"Segmente gesamt:        {len(content_segments)}")
    print(f"Bereits klassifiziert:  {len(existing)}")
    print(f"Zu klassifizieren:      {len(to_classify)}")
    if not to_classify:
        print_stats(list(existing.values()), taxonomy)
        return

    concurrency = provider.max_concurrency
    batch_pause = 0.0 if concurrency == 1 else BATCH_PAUSE
    batches = [to_classify[i:i+concurrency] for i in range(0, len(to_classify), concurrency)]
    print(f"Batches: {len(batches)} × {concurrency}  (pause {batch_pause}s)\n")

    all_results = dict(existing)  # segment_id → result

    def save_checkpoint() -> None:
        out = [all_results[s["segment_id"]] for s in content_segments
               if s["segment_id"] in all_results]
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    with tqdm(total=len(to_classify), unit="seg") as bar:
        for batch_idx, batch in enumerate(batches):
            if concurrency == 1:
                # Sequenziell: direkt awaiten, kein gather
                results = []
                for seg in batch:
                    results.append(await classify_one(provider, seg, categories_block, valid_names))
            else:
                results = await asyncio.gather(*[
                    classify_one(provider, seg, categories_block, valid_names)
                    for seg in batch
                ])
            for r in results:
                all_results[r["segment_id"]] = r
            bar.update(len(batch))

            if (batch_idx + 1) % SAVE_INTERVAL == 0:
                save_checkpoint()
                print(f"Fortschritt: {len(all_results)}/{len(content_segments)}", flush=True)

            if batch_pause > 0 and batch_idx < len(batches) - 1:
                await asyncio.sleep(batch_pause)

    save_checkpoint()

    results_list = [all_results[s["segment_id"]] for s in content_segments
                    if s["segment_id"] in all_results]
    print(f"\n→ {OUTPUT_PATH}  ({len(results_list)} Segmente)")
    print_stats(results_list, taxonomy)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
