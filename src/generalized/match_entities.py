"""
match_entities.py — Entity-Matching via Dictionary + Regex

Input:  data/interim/generalized/entities_seed.json
        data/interim/generalized/segments.json
        data/interim/generalized/classified.json  (wird in-place ergänzt)
Output: data/interim/generalized/classified.json  (actors-Feld hinzugefügt)

Für jedes content-Segment: alle Aliases aller Entities per Wortgrenz-Regex
suchen und als actors-Liste speichern.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def build_patterns(entities: list[dict]) -> list[tuple[str, re.Pattern]]:
    """Gibt Liste von (normalform, compiled_regex) zurück."""
    patterns = []
    for ent in entities:
        normalform = ent.get("normalform") or ent.get("text", "")
        terms = [normalform] + list(ent.get("aliases", []))
        # Deduplizieren, leere Strings raus
        terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
        if not terms:
            continue
        # Wortgrenz-Pattern, case-insensitive
        alt = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
        pat = re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)
        patterns.append((normalform, pat))
    return patterns


def main() -> None:
    ap = argparse.ArgumentParser(description="Entity-Matching per Wortgrenz-Regex")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    args = ap.parse_args()

    project_dir     = ROOT / "data" / "projects" / args.project
    doc_dir         = project_dir / "documents" / args.document
    SEGMENTS_PATH   = doc_dir / "segments.json"
    CLASSIFIED_PATH = doc_dir / "classified.json"

    for path in (SEGMENTS_PATH, CLASSIFIED_PATH):
        if not path.exists():
            print(f"Datei nicht gefunden: {path}", file=sys.stderr)
            sys.exit(1)

    # Entities von Projektebene (project_dir/config.json) lesen
    project_cfg_path = project_dir / "config.json"
    entities = []
    if project_cfg_path.exists():
        entities = json.loads(project_cfg_path.read_text(encoding="utf-8")).get("entities", [])
    # Fallback: per-doc entities_seed.json
    if not entities:
        fallback = doc_dir / "entities_seed.json"
        if fallback.exists():
            entities = json.loads(fallback.read_text(encoding="utf-8"))
    if not entities:
        print("Warnung: Keine Entities definiert – actors-Felder bleiben leer.", file=sys.stderr)
    segments   = json.loads(SEGMENTS_PATH.read_text(encoding="utf-8"))
    classified = json.loads(CLASSIFIED_PATH.read_text(encoding="utf-8"))

    # segment_id → classified entry (in-place update)
    cls_map = {r["segment_id"]: r for r in classified}

    patterns = build_patterns(entities)
    print(f"Entities:   {len(entities)}")
    print(f"Patterns:   {len(patterns)}")
    print(f"Segmente:   {len(segments)} gesamt, {sum(1 for s in segments if s.get('type')=='content')} content")

    matched = 0
    for seg in segments:
        if seg.get("type") != "content":
            continue
        text    = seg.get("text", "")
        seg_id  = seg["segment_id"]
        hits    = [nf for nf, pat in patterns if pat.search(text)]
        if seg_id in cls_map:
            cls_map[seg_id]["actors"] = hits
            if hits:
                matched += 1
        # Segmente ohne classified-Eintrag überspringen

    CLASSIFIED_PATH.write_text(
        json.dumps(classified, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n→ {CLASSIFIED_PATH}")
    print(f"  Segmente mit ≥1 Entity: {matched}")
    if len(segments):
        content_n = sum(1 for s in segments if s.get("type") == "content")
        print(f"  Abdeckung:              {matched}/{content_n} ({matched/content_n*100:.1f} %)" if content_n else "")


if __name__ == "__main__":
    main()
