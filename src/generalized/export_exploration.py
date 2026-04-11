"""
export_exploration.py — Alle Dokumente eines Projekts → exploration/data.json

Input (pro Dokument unter documents/{doc_id}/):
  anchors_interpolated.json  — Zeit + Text
  classified.json            — Kategorie + Entities

Input (Projektebene):
  config.json                — taxonomy, entities, title, year_min/max

Output → data/projects/{project}/exploration/:
  data.json            — Hauptdatendatei für viz/index.html
  entities_seed.csv    — Alias-Tabelle für Entity-Highlighting (boot.js)
  project_meta.json    — Projekt-Metadaten mit Farbzuweisungen

Mapping precision → date_precision:
  exact / heading / manual  → "exact"
  interpolated / decade / event → "year"
  None                       → "none"
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Farbpaletten ───────────────────────────────────────────────────────────────
CAT_PALETTE = [
    "#3b82f6", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444",
    "#06b6d4", "#f97316", "#6366f1", "#14b8a6", "#a855f7",
]
NODE_PALETTE = [
    "#60a5fa", "#fbbf24", "#34d399", "#c084fc", "#f87171", "#6ee7b7",
]

# ── precision → date_precision ─────────────────────────────────────────────────
PREC_MAP = {
    "exact":        "exact",
    "heading":      "exact",
    "manual":       "exact",
    "interpolated": "year",
    "decade":       "year",
    "event":        "year",
    None:           "none",
}

# ── confidence: "medium" → "med" ───────────────────────────────────────────────
def _conf(val: str | None) -> str | None:
    if val == "medium":
        return "med"
    return val


def _source_name(src) -> str | None:
    if src is None:
        return None
    if isinstance(src, dict):
        return src.get("name") or None
    return src or None


def _source_date(src) -> str | None:
    if isinstance(src, dict):
        return src.get("date") or None
    return None


# ── Hauptkonvertierung ─────────────────────────────────────────────────────────

def build_entries(anchors: list[dict], cls_map: dict[str, dict]) -> list[dict]:
    entries = []
    for i, seg in enumerate(anchors, start=1):
        sid       = seg.get("segment_id", f"s{i:04d}")
        cls       = cls_map.get(sid, {})
        tf        = seg.get("time_from")
        prec      = seg.get("precision")
        date_raw  = seg.get("date_raw") or (str(tf) if tf is not None else None)
        src       = seg.get("source")

        entries.append({
            "id":             i,
            "doc_anchor":     sid,
            "year":           tf,
            "date_raw":       date_raw,
            "date_precision": PREC_MAP.get(prec, "none"),
            "text":           seg.get("text", ""),
            "event_type":     cls.get("category"),
            "confidence":     _conf(cls.get("confidence")),
            "source_name":    _source_name(src),
            "source_date":    _source_date(src),
            "is_quote":       bool(seg.get("is_quote", False)),
            "is_geicke":      bool(seg.get("is_geicke", False)),
            "actors":         list(cls.get("actors") or []),
            "causal_theme":   [],
        })
    return entries


# ── entities_seed.csv ──────────────────────────────────────────────────────────

def build_entities_csv(entities: list[dict]) -> str:
    buf = StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["alias", "normalform", "typ"])
    for ent in entities:
        nf  = ent.get("normalform") or ent.get("text", "")
        typ = ent.get("typ", "Org")
        terms = [nf] + list(ent.get("aliases", []))
        seen: set[str] = set()
        for term in terms:
            t = term.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                writer.writerow([t, nf, typ])
    return buf.getvalue()


# ── project_meta.json ─────────────────────────────────────────────────────────

def build_meta(config: dict, taxonomy: list[dict], entities: list[dict]) -> dict:
    title    = config.get("title") or config.get("input_file") or "Dokument"
    doc_type = config.get("doc_type", "buchnotizen")

    ordered_cats = [c["name"] for c in taxonomy if c.get("name")]
    color_map = {
        cat: CAT_PALETTE[i % len(CAT_PALETTE)]
        for i, cat in enumerate(ordered_cats)
    }

    entity_types = sorted({e.get("typ") for e in entities if e.get("typ")})
    node_color_map = {
        typ: NODE_PALETTE[i % len(NODE_PALETTE)]
        for i, typ in enumerate(entity_types)
    }

    meta: dict = {
        "title":          title,
        "doc_type":       doc_type,
        "taxonomy":       taxonomy,
        "entity_types":   entity_types,
        "color_map":      color_map,
        "node_color_map": node_color_map,
    }
    if config.get("year_min") is not None:
        meta["year_min"] = config["year_min"]
    if config.get("year_max") is not None:
        meta["year_max"] = config["year_max"]
    return meta


# ── Validierung + Statistik ────────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "id", "doc_anchor", "year", "date_raw", "date_precision",
    "text", "event_type", "confidence", "source_name", "source_date",
    "is_quote", "is_geicke", "actors", "causal_theme",
]

def validate_and_stats(entries: list[dict]) -> None:
    total = len(entries)
    print(f"\nValidierung: {total} Einträge\n")

    # Pflichtfelder
    missing: Counter = Counter()
    for e in entries:
        for f in REQUIRED_FIELDS:
            if f not in e:
                missing[f] += 1
    if missing:
        print("⚠ Fehlende Pflichtfelder:")
        for f, n in missing.most_common():
            print(f"  {f:20s}  {n:4d} mal")
    else:
        print("✓ Alle 14 Pflichtfelder in jedem Eintrag vorhanden")

    # Verteilung event_type
    et_counter: Counter = Counter(e.get("event_type") for e in entries)
    print("\nVerteilung event_type:")
    for et, n in et_counter.most_common():
        bar = "█" * min(n, 40)
        label = et or "(null)"
        print(f"  {label:25s}  {n:4d}  ({n/total*100:.1f} %)  {bar}")

    # date_precision
    dp_counter: Counter = Counter(e.get("date_precision") for e in entries)
    print("\nVerteilung date_precision:")
    for dp, n in dp_counter.most_common():
        print(f"  {str(dp):15s}  {n:4d}  ({n/total*100:.1f} %)")

    # Actors
    with_actors = sum(1 for e in entries if e.get("actors"))
    print(f"\nMit actors:   {with_actors:4d}  ({with_actors/total*100:.1f} %)")

    # date_raw
    with_date_raw = sum(1 for e in entries if e.get("date_raw"))
    print(f"Mit date_raw: {with_date_raw:4d}  ({with_date_raw/total*100:.1f} %)")

    # source_name
    with_src = sum(1 for e in entries if e.get("source_name"))
    print(f"Mit source:   {with_src:4d}  ({with_src/total*100:.1f} %)")
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Alle Dokumente eines Projekts → exploration/")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", default=None,  help="Nur dieses Dokument exportieren (optional)")
    args = ap.parse_args()

    project_dir     = ROOT / "data" / "projects" / args.project
    exploration_dir = project_dir / "exploration"
    data_out  = exploration_dir / "data.json"
    csv_out   = exploration_dir / "entities_seed.csv"
    meta_out  = exploration_dir / "project_meta.json"

    # ── Projekt-Config (Taxonomie + Entities) ──────────────────────────────────
    config_path = project_dir / "config.json"
    config      = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    taxonomy    = config.get("taxonomy") or []
    entities    = config.get("entities") or []

    _taxonomy_is_fallback = not taxonomy

    # ── Dokumente auflisten ────────────────────────────────────────────────────
    docs_dir = project_dir / "documents"
    if not docs_dir.exists():
        print(f"Kein documents/-Verzeichnis: {docs_dir}", file=sys.stderr)
        sys.exit(1)

    if args.document:
        doc_ids = [args.document]
    else:
        doc_ids = sorted(d.name for d in docs_dir.iterdir() if d.is_dir())

    if not doc_ids:
        print("Keine Dokumente gefunden.", file=sys.stderr)
        sys.exit(1)

    # ── Alle Dokumente einlesen + mergen ───────────────────────────────────────
    all_anchors: list[dict]  = []
    all_cls_map: dict[str, dict] = {}

    for doc_id in doc_ids:
        doc_dir         = docs_dir / doc_id
        anchors_path    = doc_dir / "anchors_interpolated.json"
        classified_path = doc_dir / "classified.json"

        if not anchors_path.exists():
            print(f"  [{doc_id}] anchors_interpolated.json fehlt – übersprungen", file=sys.stderr)
            continue
        if not classified_path.exists():
            print(f"  [{doc_id}] classified.json fehlt – übersprungen", file=sys.stderr)
            continue

        anchors    = json.loads(anchors_path.read_text(encoding="utf-8"))
        classified = json.loads(classified_path.read_text(encoding="utf-8"))

        # segment_id mit doc_id-Präfix versehen (Kollisionsvermeidung)
        for seg in anchors:
            if "segment_id" in seg:
                seg["segment_id"] = f"{doc_id}-{seg['segment_id']}"
        for row in classified:
            if "segment_id" in row:
                row["segment_id"] = f"{doc_id}-{row['segment_id']}"

        cls_map = {r["segment_id"]: r for r in classified if r.get("segment_id")}

        print(f"  [{doc_id}]  {len(anchors):4d} Segmente,  {len(cls_map):4d} klassifiziert")
        all_anchors.extend(anchors)
        all_cls_map.update(cls_map)

    if not all_anchors:
        print("Keine Daten gefunden.", file=sys.stderr)
        sys.exit(1)

    # ── data.json ──────────────────────────────────────────────────────────────
    entries = build_entries(all_anchors, all_cls_map)

    # Taxonomy-Fallback: event_type-Werte aus den Einträgen ableiten
    if _taxonomy_is_fallback:
        seen_types = sorted({e["event_type"] for e in entries if e.get("event_type")})
        taxonomy = [{"name": t, "description": "", "keywords": []} for t in seen_types]
        if taxonomy:
            print(f"⚠ taxonomy in config.json leer — Fallback: {len(taxonomy)} event_type-Werte aus klassifizierten Segmenten")

    data_obj = {
        "generated": str(date.today()),
        "count":     len(entries),
        "entries":   entries,
    }
    exploration_dir.mkdir(parents=True, exist_ok=True)
    data_out.write_text(json.dumps(data_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {data_out}  ({len(entries)} Einträge, {data_out.stat().st_size:,} Bytes)")

    # ── entities_seed.csv ──────────────────────────────────────────────────────
    if entities:
        csv_text = build_entities_csv(entities)
        csv_out.write_text(csv_text, encoding="utf-8")
        n_rows = csv_text.count("\n") - 1
        print(f"→ {csv_out}  ({n_rows} Alias-Zeilen)")

    # ── project_meta.json ──────────────────────────────────────────────────────
    meta = build_meta(config, taxonomy, entities)
    meta_out.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {meta_out}")

    # ── Validierung ────────────────────────────────────────────────────────────
    validate_and_stats(entries)


if __name__ == "__main__":
    main()
