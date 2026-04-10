"""
interpolate_anchors.py — undatierte Segmente durch Intra-Quellen-Interpolation datieren

Regeln (innerhalb derselben source):
  1. Segment mit eigenem Anker → behalten (time_from/time_to/precision unverändert)
  2. Segment ohne Anker zwischen zwei datierten Segmenten
       → time_from = Jahr des letzten Ankers davor
          time_to   = Jahr des nächsten Ankers danach
          precision = "interpolated"
  3. Segment vor dem ersten Anker der Quelle (kein Vorgänger-Anker in derselben Quelle)
       → bleibt undatiert. Kein Rückwärts-Erben; kein Anker aus anderen Quellen.
  4. Segment nach dem letzten Anker der Quelle
       → erbt den letzten Anker vorwärts:
          time_from = time_to = Jahr des letzten Ankers
          precision = "interpolated"
  5. Quelle ohne einen einzigen datierten Anker
       → Segment bleibt undatiert (precision = null)

Overrides (overrides.json):
  action: "set_anchor"  → setzt time_from/time_to/precision="manual" mit höchster Priorität;
                           das Segment dient als Anker-Punkt in der Interpolation.
  action: "undatable"   → Segment bleibt dauerhaft undatiert und wird in der Interpolation
                           nicht als Anker behandelt (aber auch nicht als Barriere).

"Datiert" im Sinne dieser Datei: precision in {exact, event, manual} mit nicht-null Jahren,
also Segmente mit einem konkreten Jahreswert. Decade-Anker (kein Jahreswert) zählen
für die Interpolationsanker nicht.

Input:  data/interim/generalized/anchors.json
        data/interim/generalized/overrides.json  (optional)
Output: data/interim/generalized/anchors_interpolated.json
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _source_key(seg: dict) -> str:
    """Normalisiert source zu einem hashbaren String-Schlüssel.
    Unterstützt source als String oder {"name": ..., "date": ...}."""
    src = seg.get("source", "")
    if isinstance(src, dict):
        return src.get("name") or ""
    return src or ""


def _representative_year(seg: dict) -> int | None:
    """Einzelnes repräsentatives Jahr eines datierten Segments (Mittelpunkt)."""
    tf, tt = seg.get("time_from"), seg.get("time_to")
    if tf is not None and tt is not None:
        return (tf + tt) // 2
    if tf is not None:
        return tf
    if tt is not None:
        return tt
    return None


def _has_year(seg: dict) -> bool:
    return _representative_year(seg) is not None


def apply_overrides(segments: list[dict], overrides: list[dict]) -> list[dict]:
    """
    Wendet Overrides auf eine Kopie der Segmente an, bevor die Interpolation läuft.
    Setzt _undatable=True für undatable-Overrides (internes Flag, wird am Ende entfernt).
    """
    ov_map: dict[str, dict] = {o["segment_id"]: o for o in overrides}
    result = [dict(s) for s in segments]

    for seg in result:
        ov = ov_map.get(seg["segment_id"])
        if ov is None:
            continue
        if ov["action"] == "set_anchor":
            seg["time_from"]  = ov.get("time_from")
            seg["time_to"]    = ov.get("time_to")
            seg["precision"]  = "manual"
            if "text" in ov and ov["text"] is not None:
                seg["text"] = ov["text"]
        elif ov["action"] == "undatable":
            seg["time_from"]  = None
            seg["time_to"]    = None
            seg["precision"]  = None
            seg["_undatable"] = True   # skip in interpolation

    return result


def interpolate(segments: list[dict]) -> list[dict]:
    """
    Erwartet eine nach source gruppierte, reihenfolge-treue Liste von Segmenten.
    Gibt eine neue Liste mit ausgefüllten time_from/time_to/precision zurück.
    Respektiert _undatable-Flag: diese Segmente werden nicht datiert und dienen
    nicht als Anker-Punkte.
    """
    from collections import defaultdict
    by_source: dict[str, list[int]] = defaultdict(list)
    for i, seg in enumerate(segments):
        by_source[_source_key(seg)].append(i)

    result = [dict(s) for s in segments]   # shallow copy

    for source, indices in by_source.items():
        # Positionen mit konkretem Jahreswert (kein undatable-Flag)
        dated_positions = [
            i for i in indices
            if _has_year(result[i]) and not result[i].get("_undatable")
        ]

        if not dated_positions:
            # Regel 5: keine datierten Anker in dieser Quelle → alles bleibt undatiert
            continue

        for pos in indices:
            seg = result[pos]

            # Undatable-Segmente nie datieren
            if seg.get("_undatable"):
                continue

            if _has_year(seg):
                continue   # schon datiert

            prev_dated = [i for i in dated_positions if i < pos]
            next_dated = [i for i in dated_positions if i > pos]

            prev_year = _representative_year(result[prev_dated[-1]]) if prev_dated else None
            next_year = _representative_year(result[next_dated[0]])  if next_dated else None

            if prev_year is None and next_year is None:
                continue   # sollte nicht erreicht werden

            if prev_year is None:
                # Regel 3: kein Vorgänger-Anker in dieser Quelle → undatiert lassen
                continue
            elif next_year is None:
                # Regel 4: nach dem letzten Anker → vorwärts erben
                time_from = time_to = prev_year
            else:
                # Regel 2: zwischen zwei Ankern → Zeitspanne aufspannen
                time_from, time_to = prev_year, next_year

            result[pos]["time_from"]  = time_from
            result[pos]["time_to"]    = time_to
            result[pos]["precision"]  = "interpolated"

    # Internes Flag entfernen
    for seg in result:
        seg.pop("_undatable", None)

    return result


def stats(original: list[dict], interpolated: list[dict], n_overrides: int) -> None:
    total = len(original)

    def count_dated(segs: list[dict]) -> int:
        return sum(1 for s in segs if s.get("precision") in ("exact", "event", "interpolated", "manual")
                   and s.get("time_from") is not None)

    def count_undated(segs: list[dict]) -> int:
        return sum(1 for s in segs if s.get("time_from") is None)

    orig_dated     = count_dated(original)
    interp_dated   = count_dated(interpolated)
    interp_undated = count_undated(interpolated)

    from collections import defaultdict
    source_has_anchor: dict[str, bool] = defaultdict(bool)
    for seg in interpolated:
        if _has_year(seg):
            source_has_anchor[_source_key(seg)] = True

    undated_no_source_anchor = sum(
        1 for s in interpolated
        if s.get("time_from") is None
        and not source_has_anchor[_source_key(s)]
    )

    gained = interp_dated - orig_dated

    print(f"Input:   {total} Segmente  (Overrides: {n_overrides})")
    print()
    print(f"Datiert vor Interpolation:   {orig_dated:4d}  ({orig_dated/total*100:.1f} %)")
    print(f"  davon exact:               "
          f"{sum(1 for s in original if s.get('precision')=='exact'):4d}")
    print(f"  davon event:               "
          f"{sum(1 for s in original if s.get('precision')=='event'):4d}")
    print(f"  davon manual (override):   "
          f"{sum(1 for s in original if s.get('precision')=='manual'):4d}")
    print()
    print(f"Neu datiert durch Interpolation: +{gained}  Segmente")
    print(f"Datiert nach Interpolation:  {interp_dated:4d}  ({interp_dated/total*100:.1f} %)")
    print(f"Undatiert nach Interpolation:{interp_undated:4d}  ({interp_undated/total*100:.1f} %)")
    print()
    print(f"  davon ohne datierten Anker in ihrer Quelle: {undated_no_source_anchor}")
    print(f"  davon Quelle hat Anker, aber Segment isoliert: "
          f"{interp_undated - undated_no_source_anchor}")
    print()

    sources_total  = len(source_has_anchor)
    sources_no_anc = sum(1 for v in source_has_anchor.values() if not v)
    print(f"Quellen gesamt:              {sources_total}")
    print(f"  ohne datierten Anker:      {sources_no_anc}")
    print(f"  mit datierten Ankern:      {sources_total - sources_no_anc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Undatierte Segmente interpolieren")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    args = ap.parse_args()

    project_dir    = ROOT / "data" / "projects" / args.project
    doc_dir        = project_dir / "documents" / args.document
    input_path     = doc_dir / "anchors.json"
    output_path    = doc_dir / "anchors_interpolated.json"
    overrides_path = doc_dir / "overrides.json"

    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    segments_raw: list[dict] = json.loads(input_path.read_text(encoding="utf-8"))

    # doc_type aus doc config.json lesen
    doc_cfg_path = doc_dir / "config.json"
    if doc_cfg_path.exists():
        doc_type = json.loads(doc_cfg_path.read_text(encoding="utf-8")).get("doc_type", "buchnotizen")
    else:
        doc_type = next((s.get("doc_type") for s in segments_raw if s.get("doc_type")), "buchnotizen")
    if doc_type == "presseartikel":
        # Presseartikel haben bereits ihr Jahr aus der Heading-Erkennung – keine Interpolation
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(segments_raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"→ {output_path}  (presseartikel – Interpolation übersprungen, {len(segments_raw)} Segmente)")
        return

    override_list: list[dict] = []
    if overrides_path.exists():
        override_list = json.loads(overrides_path.read_text(encoding="utf-8"))
        print(f"← {overrides_path}  ({len(override_list)} Overrides)")

    segments_with_ov = apply_overrides(segments_raw, override_list)
    result           = interpolate(segments_with_ov)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"→ {output_path}\n")

    stats(segments_with_ov, result, len(override_list))


if __name__ == "__main__":
    main()
