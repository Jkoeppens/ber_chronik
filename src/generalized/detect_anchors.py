"""
detect_anchors.py — Zeitanker in content-Segmenten erkennen

Anker-Typen:
  exact   Konkrete Jahreszahl (1600–2029), NICHT in runden Klammern
  decade  Jahrzehnt-Referenz ("1900er", "19. Jahrhundert", "end of 19th century" …)
  event   Benanntes historisches Ereignis mit implizierter Zeitverankerung

BER-Spezialfall (type: heading mit vierstelligem Jahr):
  Heading-Segmente mit reiner Jahreszahl (z.B. "1989") setzen einen Jahres-Kontext.
  Folgende content-Segmente ohne eigene Anker erben dieses Jahr direkt
  (time_from = time_to = Jahr, precision = "exact").
  Heading-Segmente selbst werden nicht in die Ausgabe geschrieben.

Aufruf:
  python3 src/generalized/detect_anchors.py [segments.json]

Output:
  data/interim/generalized/anchors.json   — alle content-Segmente mit
    anchors: [...], time_from, time_to, precision (exact|heading|event|decade|null)

precision-Werte (gesetzt von diesem Skript):
  exact    — konkrete Jahreszahl im Fließtext, oder Datum aus date-Feld (Zotero/Obsidian)
  heading  — presseartikel/DOCX: Jahr vom letzten Jahres-Heading geerbt
  event    — benanntes historisches Ereignis (buchnotizen)
  decade   — Jahrzehnt-Referenz ohne genaues Jahr (buchnotizen)
  null     — kein Anker gefunden; interpolate_anchors.py kann "interpolated" nachliefern
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.utils import is_presseartikel

# ── Konfiguration ──────────────────────────────────────────────────────────────

# ── Lebensdaten-Filter (vor Jahreszahl-Erkennung entfernen) ───────────────────
# (YYYY–YYYY) oder (YYYY?–YYYY): beide Zahlen 1700–2000, Abstand < 120 Jahre
_LIFE_DATE_RE = re.compile(
    r"\(\s*(1[7-9]\d{2})\s*\??\s*[–—\-]+\s*(1[7-9]\d{2})\s*\??\s*\)"
)
# (dYYYY) oder (d.YYYY): Todesjahrangabe
_DEATH_YEAR_RE = re.compile(r"\(\s*[dD]\.?\s*(1[7-9]\d{2})\s*\)")

# Vierstelliges Jahr als alleiniger Inhalt (BER-Heading-Erkennung)
_YEAR_ONLY = re.compile(r"^\s*(1[6-9]\d{2}|20[0-2]\d)\s*$")

# Jahreszahl: 1600–2029
# (?<!\d) / (?!\d) statt \b: erfasst auch "1898bibliothekswesen" und "1860er".
# Einzelnes Jahr in Klammern (Publikationsjahr) wird separat entfernt.
_PAREN_YEAR = re.compile(r"\(\s*(?:1[6-9]\d{2}|20[0-2]\d)\s*\)")
_BARE_YEAR  = re.compile(r"(?<!\d)(1[6-9]\d{2}|20[0-2]\d)(?!\d)")

# Jahrzehnte und Jahrhunderte
_DECADE_RE = [
    re.compile(r"\b1[6-9]\d0er(?:\s+Jahre)?\b"),                # "1900er", "1850er Jahre"
    re.compile(r"\b(frühen?|Mitte|Ende|späten?)\s+1[6-9]\. Jahrhundert\b", re.I),
    re.compile(r"\b(early|mid|late)\s+\d{2}(th|st|nd|rd)\s+century\b", re.I),
    re.compile(r"\b(early|mid|late)\s+nineteenth\s+century\b", re.I),
    re.compile(r"\b(frühen?|Mitte|Ende)\s+des\s+\d{2}\.\s*Jahrhunderts?\b", re.I),
    re.compile(r"\bJahrhundert(?:wende)?\b"),                    # allgemeines Jh-Wort
    re.compile(r"\b\d{2}\.\s*Jh\.\b"),                          # "19. Jh."
]

# Benannte Ereignisse → (label, approximates_year_or_None)
_EVENTS: list[tuple[re.Pattern, str, int | None]] = [
    (re.compile(r"\bTanzimat\b",       re.I), "Tanzimat",                  1839),
    (re.compile(r"\bGülhane\b",        re.I), "Hatt-ı Şerif von Gülhane", 1839),
    (re.compile(r"\bJungtürk",         re.I), "Jungtürkenrevolution",      1908),
    (re.compile(r"\bYoung Turk",       re.I), "Young Turk Revolution",     1908),
    (re.compile(r"\bRevolution 1908\b",re.I), "Revolution 1908",           1908),
    (re.compile(r"\bGegenputsch\b",    re.I), "Gegenputsch 1909",          1909),
    (re.compile(r"\bKonterrev",        re.I), "Konterrevolution 1909",     1909),
    (re.compile(r"\bcounter.?rev",     re.I), "Counter-Revolution 1909",   1909),
    (re.compile(r"\bWK\s*1\b|\bWKI\b",re.I), "Erster Weltkrieg",          1914),
    (re.compile(r"\bErster\s+Weltkrieg\b", re.I), "Erster Weltkrieg",      1914),
    (re.compile(r"\bWorld War\s+I\b",  re.I), "World War I",               1914),
    (re.compile(r"\bpre.?World War\b", re.I), "pre-World War I",           1914),
    (re.compile(r"\bBalkankrieg\b",    re.I), "Balkankrieg",               1912),
    (re.compile(r"\bBalkan War\b",     re.I), "Balkan War",                1912),
    (re.compile(r"\bLibyen(?:krieg)?\b",re.I),"Libyen/Tripolitanien",      1911),
    (re.compile(r"\bTripolit",         re.I), "Tripolit. Krieg",           1911),
]


# ── Anker-Erkennung ────────────────────────────────────────────────────────────

def _strip_non_anchors(text: str) -> str:
    """Entfernt Lebensdaten und Todesjahre bevor Jahreszahlen gesucht werden."""
    # Lebensdaten (YYYY–YYYY): nur wenn beide Jahre 1700–2000 und Abstand < 120
    def remove_life(m: re.Match) -> str:
        y1, y2 = int(m.group(1)), int(m.group(2))
        if 1700 <= y1 <= 2000 and 1700 <= y2 <= 2000 and abs(y2 - y1) < 120:
            return ""
        return m.group(0)   # kein Lebensdatum → unverändert lassen

    text = _LIFE_DATE_RE.sub(remove_life, text)
    text = _DEATH_YEAR_RE.sub("", text)        # (d1827) immer entfernen
    text = _PAREN_YEAR.sub("", text)           # einzelnes (YYYY) = Publikationsjahr
    return text


def detect_anchors(text: str) -> list[dict]:
    """Gibt alle erkannten Anker als Liste von Dicts zurück."""
    anchors: list[dict] = []

    # Lebensdaten, Todesjahre und Publikationsjahre aus dem Text entfernen
    clean = _strip_non_anchors(text)

    # exact
    for m in _BARE_YEAR.finditer(clean):
        anchors.append({"type": "exact", "value": int(m.group(1)), "span": m.group(1)})

    # decade
    for pattern in _DECADE_RE:
        for m in pattern.finditer(text):
            anchors.append({"type": "decade", "value": None, "span": m.group(0)})

    # event
    for pattern, label, approx_year in _EVENTS:
        if pattern.search(text):
            anchors.append({"type": "event", "value": approx_year, "span": label})

    return anchors


# ── Verarbeitungs-Funktionen ───────────────────────────────────────────────────

def _process_presseartikel(segments: list[dict]) -> list[dict]:
    """Geicke-DOCX, Zotero und Obsidian presseartikel — gibt output_rows zurück, druckt Stats."""
    output_rows:         list[dict] = []
    active_heading_year: int | None = None
    heading_count        = 0
    date_field_count     = 0
    without_date         = 0

    for seg in segments:
        if seg.get("type") == "heading":
            m = _YEAR_ONLY.match(seg.get("text", ""))
            if m:
                # DOCX-Stil: reine Jahreszahl im Text → setzt Jahres-Kontext
                active_heading_year = int(m.group(1))
            continue

        if seg.get("type") != "content":
            continue

        if active_heading_year is not None:
            anchors   = [{"type": "exact", "value": active_heading_year,
                           "span": str(active_heading_year), "source": "heading"}]
            time_from = time_to = active_heading_year
            precision = "heading"
            heading_count += 1
        else:
            # Kein Heading-Jahr — date-Feld lesen (Zotero + Obsidian)
            date_str = (seg.get("date") or "").strip()
            year = None
            if re.match(r"^\d{4}-\d{2}", date_str):   # YYYY-MM-DD oder YYYY-MM
                year = int(date_str[:4])
                precision = "exact"
            elif re.match(r"^\d{4}$", date_str):       # nur YYYY
                year = int(date_str)
                precision = "exact"
            else:
                precision = None

            if year is not None:
                anchors   = [{"type": "exact", "value": year,
                              "span": date_str, "source": "date"}]
                time_from = time_to = year
                date_field_count += 1
            else:
                anchors   = []
                time_from = time_to = None
                without_date += 1

        row = {**seg, "anchors": anchors,
               "time_from": time_from, "time_to": time_to,
               "precision": precision}
        if not row.get("date_raw") and row.get("date"):
            row["date_raw"] = row["date"]
        output_rows.append(row)

    total     = len(output_rows)
    n_content = sum(1 for r in output_rows if r.get("type") == "content")
    print(f"Segmente gesamt:                  {total}")
    if n_content:
        print(f"  mit DOCX-Heading-Jahr:          {heading_count}"
              f"  ({heading_count/n_content*100:.1f} %)")
        print(f"  mit date-Feld (Zotero/Obsidian):{date_field_count}"
              f"  ({date_field_count/n_content*100:.1f} %)")
        print(f"  ohne Datum:                     {without_date}"
              f"  ({without_date/n_content*100:.1f} %)")

    return output_rows


def _process_literatur(segments: list[dict]) -> list[dict]:
    """buchnotizen/Forschungsnotizen — gibt output_rows zurück, druckt Stats."""
    output_rows:     list[dict] = []
    with_anchors:    list[dict] = []
    without_anchors: list[dict] = []
    type_counter:    Counter    = Counter()
    year_counter:    Counter    = Counter()
    heading_inherited           = 0

    active_heading_year: int | None = None

    for seg in segments:
        if seg.get("type") == "heading":
            m = _YEAR_ONLY.match(seg.get("text", ""))
            active_heading_year = int(m.group(1)) if m else None
            continue

        if seg.get("type") != "content":
            continue

        anchors = detect_anchors(seg["text"])

        years_exact = [a["value"] for a in anchors if a["type"] == "exact"]
        years_event = [a["value"] for a in anchors
                       if a["type"] == "event" and a["value"] is not None]

        if years_exact:
            time_from, time_to, precision = min(years_exact), max(years_exact), "exact"
        elif years_event:
            time_from, time_to, precision = min(years_event), max(years_event), "event"
        elif any(a["type"] == "decade" for a in anchors):
            time_from, time_to, precision = None, None, "decade"
        elif active_heading_year is not None:
            time_from  = time_to = active_heading_year
            precision  = "exact"
            anchors    = [{"type": "exact", "value": active_heading_year,
                           "span": str(active_heading_year), "source": "heading"}]
            heading_inherited += 1
        else:
            time_from, time_to, precision = None, None, None

        row = {**seg, "anchors": anchors,
               "time_from": time_from, "time_to": time_to, "precision": precision}
        output_rows.append(row)

        if anchors:
            with_anchors.append(seg)
            seen_types: set[str] = set()
            for a in anchors:
                if a["type"] not in seen_types:
                    type_counter[a["type"]] += 1
                    seen_types.add(a["type"])
                if a["type"] == "exact":
                    year_counter[a["value"]] += 1
        else:
            without_anchors.append(seg)

    total = len(output_rows)
    print(f"Segmente (type=content):          {total}")
    print(f"  mit mindestens einem Anker:     {len(with_anchors)}"
          f"  ({len(with_anchors)/total*100:.1f} %)")
    print(f"    davon von Heading geerbt:     {heading_inherited}")
    print(f"  ohne Anker:                     {len(without_anchors)}"
          f"  ({len(without_anchors)/total*100:.1f} %)")
    print()
    print("Verteilung nach Anker-Typ")
    print("  (Segment wird je Typ nur einmal gezählt)")
    for typ in ("exact", "decade", "event"):
        n = type_counter[typ]
        print(f"  {typ:8s}  {n:4d}  ({n/total*100:.1f} %)")
    print()
    print("Top 10 Jahreswerte (exact-Anker, Häufigkeit = Anzahl Segmente):")
    for year, count in year_counter.most_common(10):
        bar = "█" * count
        print(f"  {year}  {count:4d}  {bar}")
    print()
    print("Beispiele ohne Anker (erste 5):")
    for seg in without_anchors[:5]:
        print(f"  [{seg['segment_id']}] {seg['text'][:100]!r}")

    return output_rows


# ── Hauptprogramm ──────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Zeitanker in Segmenten erkennen")
    ap.add_argument("--project",  required=True, help="Projektname (z.B. ber, damaskus)")
    ap.add_argument("--document", required=True, help="Dokument-ID (z.B. main)")
    args = ap.parse_args()

    project_dir = PROJECTS_DIR / args.project
    doc_dir     = project_dir / "documents" / args.document
    input_path  = doc_dir / "segments.json"
    output_path = doc_dir / "anchors.json"

    if not input_path.exists():
        print(f"Datei nicht gefunden: {input_path}", file=sys.stderr)
        sys.exit(1)

    segments: list[dict] = json.loads(input_path.read_text(encoding="utf-8"))

    press = is_presseartikel(doc_dir)
    if press:
        output_rows = _process_presseartikel(segments)
    else:
        output_rows = _process_literatur(segments)

    output_path.write_text(
        json.dumps(output_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    doc_type = "presseartikel" if press else "buchnotizen"
    print(f"\n→ {output_path}  ({len(output_rows)} Segmente, doc_type={doc_type})")


if __name__ == "__main__":
    main()
