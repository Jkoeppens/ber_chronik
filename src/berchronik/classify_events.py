import argparse
import json
import re
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"

VALID_TYPES = {
    "Beschluss", "Vertrag", "Klage", "Personalie",
    "Kosten", "Termin", "Technik", "Planung", "Claim",
}

PROMPT_TEMPLATE = """\
Classify the following excerpt from a German chronology of Berlin Brandenburg Airport (BER, 1989–2017).

Assign exactly one category:
- Beschluss  – political or administrative decision, approval, resolution
- Vertrag    – contract signed, tender awarded, letter of intent
- Klage      – court proceedings, ruling, procurement tribunal
- Personalie – resignation, appointment, personnel change
- Kosten     – cost overrun, budget, credit, financing
- Termin     – opening date, delay, postponement
- Technik    – fire protection, construction defects, technical systems
- Planung    – tendering process, site selection, concept, expert report
- Claim      – opinion, assessment, quote without a concrete event

Reply with JSON only, no explanation:
{{"event_type": "<category>", "confidence": "<high|med|low>"}}

confidence rules:
- high: category is unambiguous
- med:  category fits but the excerpt touches multiple themes
- low:  category is a guess; excerpt is unclear or very short

Excerpt:
\"\"\"
{text_span}
\"\"\"\
"""


def call_ollama(text: str) -> dict | None:
    payload = {
        "model": MODEL,
        "prompt": PROMPT_TEMPLATE.format(text_span=text),
        "stream": False,
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


def parse_response(raw: dict | None) -> tuple[str | None, str]:
    if raw is None:
        return None, "low"
    response_text = raw.get("response", "")
    # Extract JSON object from response (handles extra text around it)
    match = re.search(r"\{[^}]+\}", response_text)
    if not match:
        return None, "low"
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None, "low"
    event_type = data.get("event_type")
    confidence = data.get("confidence", "low")
    if event_type not in VALID_TYPES:
        event_type = None
    if confidence not in {"high", "med", "low"}:
        confidence = "low"
    return event_type, confidence


def classify(text: str) -> tuple[str | None, str]:
    raw = call_ollama(text)
    event_type, confidence = parse_response(raw)
    if event_type is None:
        # one retry
        raw = call_ollama(text)
        event_type, confidence = parse_response(raw)
    return event_type, confidence


def main():
    ap = argparse.ArgumentParser(description="Classify BER chronik paragraphs via Ollama/Mistral")
    ap.add_argument("--input",   default="data/interim/paragraphs_raw.csv")
    ap.add_argument("--output",  default="data/interim/paragraphs_enriched.csv")
    ap.add_argument("--dry-run", action="store_true", help="Classify first 5 rows only")
    args = ap.parse_args()

    in_path  = Path(args.input).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()

    raw = pd.read_csv(in_path)
    df = raw[raw["is_year_heading"] == False].copy()

    if args.dry_run:
        df = df.head(5)

    results = []
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Classifying"):
        event_type, confidence = classify(row["text_span"])
        results.append({
            "id":         row["id"],
            "event_type": event_type,
            "confidence": confidence,
        })

    results_df = pd.DataFrame(results).set_index("id")

    # Merge into existing enriched CSV if present, otherwise start from raw
    if out_path.exists():
        enriched = pd.read_csv(out_path)
    else:
        enriched = df.copy()

    enriched = enriched.set_index("id")
    enriched["event_type"] = results_df["event_type"]
    enriched["confidence"] = results_df["confidence"]
    enriched = enriched.reset_index()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(out_path, index=False)
    print(f"\nWrote {len(results):,} classifications -> {out_path}")

    # Summary
    print("\nevent_type:")
    print(enriched["event_type"].value_counts(dropna=False).to_string())
    print("\nconfidence:")
    print(enriched["confidence"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
