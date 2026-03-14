import argparse
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"
MAX_PARAGRAPHS = 30  # cap per entity before sampling

SUMMARY_PROMPT = """\
You are summarizing the role of a person or organization in the history of \
Berlin Brandenburg Airport (BER), based on excerpts from a German chronology \
covering 1989–2017.

Entity: {name}

Relevant excerpts ({count} total, showing {shown}):
{paragraphs}

Write a concise summary in German (3–5 sentences) describing:
- Who or what this entity is
- Their role and significance in the BER project
- Key events or decisions they were involved in

Reply with plain text only, no JSON, no headings.\
"""


def to_int(val):
    try:
        v = float(val)
        return None if math.isnan(v) else int(v)
    except (TypeError, ValueError):
        return None


def to_str(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    s = str(val).strip()
    return s if s else None


def to_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, float) and math.isnan(val):
        return None
    return bool(val)


def to_array(val):
    """Split ';'-joined string into list, return [] if empty/null."""
    s = to_str(val)
    if not s:
        return []
    return [item.strip() for item in s.split(";") if item.strip()]


def build_entry(row: pd.Series) -> dict:
    # event_type_manual overrides event_type if set
    event_type = to_str(row.get("event_type_manual")) or to_str(row.get("event_type"))

    return {
        "id":             to_int(row["id"]),
        "doc_anchor":     to_str(row["doc_anchor"]),
        "year":           to_int(row["year_bucket"]),
        "date_raw":       to_str(row["date_raw"]),
        "date_precision": to_str(row["date_precision"]),
        "text":           to_str(row["text_span"]),
        "event_type":     event_type,
        "confidence":     to_str(row["confidence"]),
        "source_name":    to_str(row["source_name"]),
        "source_date":    to_str(row["source_date"]),
        "is_quote":       to_bool(row["is_quote"]),
        "is_geicke":      to_bool(row["is_geicke"]),
        "actors":         to_array(row.get("actors")),
        "causal_theme":   to_array(row.get("causal_theme")),
    }


def sample_paragraphs(rows: list[dict], max_n: int) -> list[dict]:
    """Sample up to max_n rows, spread across event_types for diversity."""
    if len(rows) <= max_n:
        return rows
    # Group by event_type, round-robin sample
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r.get("event_type") or "?"].append(r)
    result, buckets = [], list(by_type.values())
    i = 0
    while len(result) < max_n:
        bucket = buckets[i % len(buckets)]
        if bucket:
            result.append(bucket.pop(0))
        i += 1
        if all(not b for b in buckets):
            break
    # Sort back by id to preserve chronological order
    result.sort(key=lambda r: r.get("id", 0))
    return result


def call_ollama(prompt: str) -> str | None:
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip() or None
    except requests.RequestException:
        return None


def build_summaries(entries: list[dict], out_path: Path, min_mentions: int = 3) -> None:
    # Load existing summaries to allow resuming interrupted runs
    existing: dict = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Collect paragraphs per actor
    actor_paragraphs: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        for actor in e.get("actors", []):
            actor_paragraphs[actor].append(e)

    # Filter by min_mentions, sort by mention count descending
    actors_sorted = sorted(
        [(name, paras) for name, paras in actor_paragraphs.items() if len(paras) >= min_mentions],
        key=lambda x: -len(x[1]),
    )
    print(f"  {len(actors_sorted)} actors with >= {min_mentions} mentions to summarise")

    results = dict(existing)

    for name, paragraphs in tqdm(actors_sorted, desc="Summarising entities"):
        if name in results:
            continue  # already done

        shown = sample_paragraphs(paragraphs, MAX_PARAGRAPHS)
        para_block = "\n\n".join(
            f"[{p['doc_anchor']}, {p['year']}] {p['text']}" for p in shown
        )
        prompt = SUMMARY_PROMPT.format(
            name=name,
            count=len(paragraphs),
            shown=len(shown),
            paragraphs=para_block,
        )

        summary = call_ollama(prompt)
        if summary is None:
            summary = call_ollama(prompt)  # one retry

        results[name] = {
            "summary":       summary,
            "paragraph_ids": [p["doc_anchor"] for p in paragraphs],
            "count":         len(paragraphs),
        }

        # Write after every entity so a crash doesn't lose progress
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    done    = sum(1 for v in results.values() if v["summary"])
    missing = sum(1 for v in results.values() if not v["summary"])
    print(f"  Summaries written: {done}  |  Failed (None): {missing}")


def main():
    ap = argparse.ArgumentParser(description="Export paragraphs_enriched.csv → viz/data.json")
    ap.add_argument("--input",     default="data/interim/paragraphs_enriched.csv")
    ap.add_argument("--output",    default="viz/data.json")
    ap.add_argument("--summaries", action="store_true",
                    help="Generate viz/entities_summary.json via Ollama instead of data.json")
    ap.add_argument("--summaries-output", default="viz/entities_summary.json")
    ap.add_argument("--min-mentions", type=int, default=3,
                    help="Minimum paragraph mentions for an entity to get a summary")
    args = ap.parse_args()

    in_path  = Path(args.input).expanduser().resolve()
    df = pd.read_csv(in_path)
    entries = [build_entry(row) for _, row in df.iterrows()]

    if args.summaries:
        print(f"Loaded {len(entries):,} entries. Building entity summaries …")
        build_summaries(entries, Path(args.summaries_output).expanduser().resolve(),
                        min_mentions=args.min_mentions)
        return

    out_path = Path(args.output).expanduser().resolve()
    payload = {
        "generated": date.today().isoformat(),
        "count":     len(entries),
        "entries":   entries,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(entries):,} entries → {out_path}")
    with_actors = sum(1 for e in entries if e["actors"])
    with_et     = sum(1 for e in entries if e["event_type"])
    with_date   = sum(1 for e in entries if e["date_raw"])
    print(f"  Mit actors:     {with_actors}/{len(entries)}")
    print(f"  Mit event_type: {with_et}/{len(entries)}")
    print(f"  Mit date_raw:   {with_date}/{len(entries)}")


if __name__ == "__main__":
    main()
