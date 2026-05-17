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
from dotenv import load_dotenv

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.llm import get_provider, TASK_CLASSIFY
from src.generalized.utils import write_atomic
from tqdm import tqdm

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
    if not isinstance(raw, str):
        return "(unbekannt)"
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
            return {**segment, "category": None, "confidence": None}


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


def _classify_bge(
    doc_dir,
    taxonomy: list[dict],
    content_segments: list[dict],
    output_path,
) -> None:
    """Klassifiziert Segmente per BGE-M3 cosine similarity — kein LLM-Call."""
    import numpy as np
    from src.generalized.embeddings import EMB_TASK_CLASSIFY, get_embedding_provider

    SEG_CHARS  = 500
    cache_path = doc_dir / "bge_embeddings.npy"
    texts      = [s.get("text", "")[:SEG_CHARS] for s in content_segments]
    n          = len(content_segments)

    print(f"BGE: {n} Segmente", flush=True)
    provider = get_embedding_provider(EMB_TASK_CLASSIFY)

    if cache_path.exists():
        cached = np.load(cache_path)
        if cached.shape[0] == n:
            print(f"  Embeddings aus Cache ({cached.shape})", flush=True)
            seg_embs = cached
        else:
            print(f"  Cache: neu berechnen (shape mismatch: {cached.shape[0]} != {n})", flush=True)
            seg_embs = provider.encode(texts)
            np.save(cache_path, seg_embs)
    else:
        seg_embs = provider.encode(texts)
        np.save(cache_path, seg_embs)

    tax_texts = [
        f"{c['name']}. {c.get('description', '')}. {' '.join(c.get('keywords', []))}"
        for c in taxonomy
    ]
    print(f"BGE: {len(tax_texts)} Taxonomie-Kategorien embedden…", flush=True)
    tax_embs    = provider.encode(tax_texts)
    valid_names = [c["name"] for c in taxonomy]

    results = []
    for i, seg in enumerate(content_segments):
        sims       = seg_embs[i] @ tax_embs.T
        best_idx   = int(sims.argmax())
        best_sim   = float(sims[best_idx])
        confidence = "high" if best_sim > 0.5 else ("medium" if best_sim > 0.35 else "low")
        results.append({**seg, "category": valid_names[best_idx], "confidence": confidence})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(output_path, json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n→ {output_path}  ({len(results)} Segmente)")
    print_stats(results, taxonomy)


async def main_async() -> None:
    ap = argparse.ArgumentParser(description="Segmente per LLM oder BGE klassifizieren")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    ap.add_argument("--force",  action="store_true", help="Cache ignorieren, alle Segmente neu klassifizieren")
    ap.add_argument("--method", choices=["llm", "bge"], default="llm",
                    help="llm = LLM-Klassifikation (Standard); bge = BGE-M3 cosine similarity")
    args = ap.parse_args()

    project_dir   = PROJECTS_DIR / args.project
    doc_dir       = project_dir / "documents" / args.document
    SEGMENTS_PATH = doc_dir / "segments.json"
    OUTPUT_PATH   = doc_dir / "classified.json"

    load_dotenv(ROOT / ".env")

    if not SEGMENTS_PATH.exists():
        print(f"Nicht gefunden: {SEGMENTS_PATH}", file=sys.stderr)
        sys.exit(1)

    segments = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))

    # Taxonomie ausschließlich von Projektebene — D-P1: kein Fallback
    project_cfg_path = project_dir / "config.json"
    if not project_cfg_path.exists():
        print(f"Fehler: config.json nicht gefunden: {project_cfg_path}", file=sys.stderr)
        sys.exit(1)
    taxonomy = json.loads(project_cfg_path.read_text(encoding="utf-8")).get("taxonomy", [])
    if not taxonomy:
        print(
            f"Fehler: Keine Taxonomie in {project_cfg_path}\n"
            "Bitte zuerst taxonomy/save ausführen bevor classify läuft.",
            file=sys.stderr,
        )
        sys.exit(1)
    # Normalisieren: einzelnes Dict → Liste; Strings/ungültige Einträge verwerfen
    if isinstance(taxonomy, dict):
        taxonomy = [taxonomy]
    taxonomy = [c for c in taxonomy if isinstance(c, dict) and c.get("name")]
    if not taxonomy:
        print("Taxonomie enthält keine gültigen Kategorien (erwartet: Liste von {name, description})", file=sys.stderr)
        sys.exit(1)

    content_segments = [s for s in segments if s.get("type") == "content"]

    # ── BGE-Pfad ──────────────────────────────────────────────────────────────
    if args.method == "bge":
        _classify_bge(doc_dir, taxonomy, content_segments, OUTPUT_PATH)
        return

    # ── LLM-Pfad ─────────────────────────────────────────────────────────────
    provider         = get_provider(task=TASK_CLASSIFY)
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
        write_atomic(OUTPUT_PATH, json.dumps(out, ensure_ascii=False, indent=2))

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
