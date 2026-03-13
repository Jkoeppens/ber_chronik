import argparse
import re
from pathlib import Path

import pandas as pd
from docx import Document


YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def ingest_docx(docx_path: Path) -> pd.DataFrame:
    doc = Document(str(docx_path))

    rows = []
    year_bucket = None
    year_section_index = 0
    global_index = 0

    for p in doc.paragraphs:
        text = (p.text or "").strip()
        if not text:
            continue

        # Year heading detection: paragraph that is exactly a year (e.g., "1993")
        if YEAR_RE.match(text):
            year_bucket = int(text)
            year_section_index = 0
            # Still keep the year heading as a row? Usually useful to keep as a marker.
            global_index += 1
            rows.append(
                {
                    "id": global_index,
                    "doc_anchor": f"p{global_index}",
                    "year_bucket": year_bucket,
                    "year_section_index": year_section_index,
                    "text_span": text,
                    "is_year_heading": True,
                }
            )
            continue

        if year_bucket is None:
            # preface before first year heading
            year_bucket = None

        year_section_index += 1
        global_index += 1
        rows.append(
            {
                "id": global_index,
                "doc_anchor": f"p{global_index}",
                "year_bucket": year_bucket,
                "year_section_index": year_section_index,
                "text_span": text,
                "is_year_heading": False,
            }
        )

    df = pd.DataFrame(rows)
    return df


def main():
    ap = argparse.ArgumentParser(description="Ingest BER chronik DOCX -> paragraphs_raw.csv")
    ap.add_argument("--input", required=True, help="Path to .docx file")
    ap.add_argument("--output", default="data/interim/paragraphs_raw.csv", help="Output CSV path")
    args = ap.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = ingest_docx(in_path)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df):,} rows -> {out_path}")


if __name__ == "__main__":
    main()