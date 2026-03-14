import argparse
import re
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# Date at start of text: "29. Januar", "Am 3. August", "3. Oktober", "21./22. März"
DATE_START_RE = re.compile(
    r"^(?:Am\s+|Im\s+)?"
    r"(\d{1,2}\.(?:/\d{1,2}\.)?\s*(?:Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember))"
    r"|^(\d{1,2}\.\s*\d{1,2}\.\s*(?:19|20)\d{2})"  # full date at start
)

# Month only (no day): "Im Oktober", "Oktober 1993"
MONTH_ONLY_RE = re.compile(
    r"\b(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\b"
)

# Source citations anywhere in text: "Tsp, 14.10.2000", "(taz, 09.06.1992)", "Mittldt.Ztg, 01.01.2000"
SOURCE_RE = re.compile(
    r"\b([A-Za-zÄÖÜäöüß/.-]{2,20}),\s*(\d{2}\.\d{2}\.\d{2,4})\)?"
)

# Any full date in text: "13. Oktober 2000", "13.10.2000"
FULL_DATE_RE = re.compile(
    r"\b(\d{1,2})\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s*(\d{4})\b"
    r"|\b(\d{2})\.(\d{2})\.(\d{2,4})\b"
)

# Event type keyword mapping (order matters: first match wins)
EVENT_KEYWORDS = [
    ("Klage",      r"\b(Klage|Gericht|OLG|BGH|Urteil|Vergabekammer|klagt|verklagt|Richter|Prozess|Verfahren)\b"),
    ("Kosten",     r"\b(Kosten|Budget|Kredit|Milliarden?|Millionen?|Finanzierung|Nachtragshaushalt|teurer|Mehrkosten|Kostensteigerung)\b"),
    ("Termin",     r"\b(Eröffnung|Fertigstellung|Verzögerung|verschiebt|Verschiebung|Inbetriebnahme|Eröffnungstermin)\b"),
    ("Personalie", r"\b(Rücktritt|tritt zurück|Ernennung|ernannt|Geschäftsführer|Aufsichtsrat|Wechsel|Vorsitz|Chef|Direktor)\b"),
    ("Technik",    r"\b(Brandschutz|Entrauchung|Mängel|Baumängel|Technik|Installation|Anlage|System|Kabel|Sprinkler)\b"),
    ("Vertrag",    r"\b(Vertrag|Generalunternehmer|Auftrag|Letter of Intent|Ausschreibung|Vergabe|unterzeichnet|beauftragt)\b"),
    ("Beschluss",  r"\b(Beschluss|beschlossen|Senat|Kabinett|Bundesregierung|Entscheidung|entschieden|Planfeststellung|Genehmigung)\b"),
    ("Planung",    r"\b(Planung|Standort|Konzept|Gutachten|Studie|Entwurf|Architekt|Bebauungsplan)\b"),
]
EVENT_KEYWORD_RES = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in EVENT_KEYWORDS]


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def extract_source(text: str) -> tuple[str, str]:
    """Return (source_name, source_date) with all matches joined by ';'."""
    matches = SOURCE_RE.findall(text)
    if matches:
        names = ";".join(m[0].strip() for m in matches)
        dates = ";".join(m[1].strip() for m in matches)
        return names, dates
    return "", ""


def extract_date(text: str, year_bucket) -> tuple[str, str]:
    """Return (date_raw, date_precision)."""
    # Full date in text
    m = FULL_DATE_RE.search(text)
    if m:
        if m.group(1):  # "13. Oktober 2000"
            return f"{m.group(1)}. {m.group(2)} {m.group(3)}", "exact"
        else:            # "13.10.2000"
            return f"{m.group(4)}.{m.group(5)}.{m.group(6)}", "exact"

    # Day + month at start (no year)
    m = DATE_START_RE.match(text)
    if m:
        return (m.group(1) or m.group(2)).strip(), "month_day"

    # Month only
    m = MONTH_ONLY_RE.search(text)
    if m:
        return m.group(1), "month"

    # Fall back to year bucket
    if year_bucket is not None and not pd.isna(year_bucket):
        return str(int(year_bucket)), "year"

    return "", "none"


def classify_event_type(text: str) -> str:
    for name, pat in EVENT_KEYWORD_RES:
        if pat.search(text):
            return name
    return "Claim"


def compute_confidence(date_precision: str, source_name: str, event_type: str) -> str:
    score = 0
    if date_precision == "exact":
        score += 2
    elif date_precision == "month_day":
        score += 1
    if source_name:
        score += 1
    if event_type != "Claim":
        score += 1
    if score >= 3:
        return "high"
    if score >= 2:
        return "med"
    return "low"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_features(df: pd.DataFrame) -> pd.DataFrame:
    # Drop year headings – they're structural, not content
    df = df[df["is_year_heading"] == False].copy()

    # Fix year_bucket to int-compatible (nullable Int64)
    df["year_bucket"] = pd.to_numeric(df["year_bucket"], errors="coerce").astype("Int64")

    results = []
    for _, row in df.iterrows():
        text = row["text_span"]

        source_name, source_date = extract_source(text)
        date_raw, date_precision = extract_date(text, row["year_bucket"])
        is_quote = text.startswith("„") or text.startswith('"')
        is_geicke = not source_name and not is_quote
        event_type = classify_event_type(text)
        confidence = compute_confidence(date_precision, source_name, event_type)

        results.append({
            "id":                 row["id"],
            "doc_anchor":         row["doc_anchor"],
            "year_bucket":        row["year_bucket"],
            "year_section_index": row["year_section_index"],
            "text_span":          text,
            "date_raw":           date_raw,
            "date_precision":     date_precision,
            "source_name":        source_name,
            "source_date":        source_date,
            "is_quote":           is_quote,
            "is_geicke":          is_geicke,
            "event_type":         event_type,
            "event_type_manual":  "",
            "causal_theme":       "",
            "confidence":         confidence,
        })

    return pd.DataFrame(results)


def main():
    ap = argparse.ArgumentParser(description="Extract features from paragraphs_raw.csv")
    ap.add_argument("--input",  default="data/interim/paragraphs_raw.csv")
    ap.add_argument("--output", default="data/interim/paragraphs_enriched.csv")
    args = ap.parse_args()

    in_path  = Path(args.input).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(in_path)
    enriched = parse_features(raw)
    enriched.to_csv(out_path, index=False)
    print(f"Wrote {len(enriched):,} rows -> {out_path}")

    # Quick summary
    print("\ndate_precision:")
    print(enriched["date_precision"].value_counts().to_string())
    print("\nevent_type:")
    print(enriched["event_type"].value_counts().to_string())
    print("\nconfidence:")
    print(enriched["confidence"].value_counts().to_string())


if __name__ == "__main__":
    main()
