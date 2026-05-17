"""
test_detect_anchors.py — Unit-Tests für src/generalized/detect_anchors.py

Getestete Funktionen (direkt importiert, kein I/O, kein Subprozess):
  detect_anchors(text)            — Regex-Ankererkennung
  _process_literatur(segments)    — buchnotizen-Pfad
  _process_presseartikel(segments) — presseartikel-Pfad (DOCX + Obsidian)

Drei Quellentypen aus der Spezifikation:
  1. buchnotizen     — Anker aus Fließtext (Regex)
  2. presseartikel/docx  — Heading-Jahres-Kontext + date-Feld
  3. presseartikel/obsidian — date-Feld aus Frontmatter, kein Heading
"""
import pytest
from src.generalized.detect_anchors import (
    detect_anchors,
    _process_literatur,
    _process_presseartikel,
)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def seg(segment_id, text, **kwargs):
    return {"type": "content", "segment_id": segment_id, "text": text, **kwargs}


def heading(text):
    return {"type": "heading", "text": text}


# ── 1. buchnotizen: _process_literatur ───────────────────────────────────────

class TestBuchnotizen:

    def test_year_in_text_exact(self):
        result = _process_literatur([seg("s0001", "Im Jahr 1905 wurde das Gebäude errichtet.")])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 1905
        assert r["time_to"]   == 1905

    def test_year_range_min_max(self):
        # Mehrere Jahreszahlen → time_from=min, time_to=max
        result = _process_literatur([seg("s0001", "Von 1850 bis 1870 dauerte die Reform.")])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 1850
        assert r["time_to"]   == 1870

    def test_decade_phrase(self):
        # "1900er" enthält bare year "1900" → exact schlägt decade.
        # Phrase ohne eingebettete 4-stellige Zahl verwenden:
        result = _process_literatur([seg("s0001", "Im frühen 19. Jahrhundert entstand die Bewegung.")])
        r = result[0]
        assert r["precision"] == "decade"
        assert r["time_from"] is None
        assert r["time_to"]   is None

    def test_named_event_jungtuerken(self):
        result = _process_literatur([seg("s0001", "Die Jungtürkenrevolution veränderte das Reich grundlegend.")])
        r = result[0]
        assert r["precision"] == "event"
        assert r["time_from"] == 1908

    def test_no_anchor_stays_undated(self):
        result = _process_literatur([seg("s0001", "Die Verwaltung funktionierte nach alten Mustern.")])
        r = result[0]
        assert r["precision"] is None
        assert r["time_from"] is None

    def test_heading_filtered_from_output(self):
        # Heading-Segmente landen nicht in der Ausgabe
        segs = [heading("1989"), seg("s0001", "Erster Eintrag ohne eigene Jahreszahl.")]
        result = _process_literatur(segs)
        assert len(result) == 1
        assert result[0]["segment_id"] == "s0001"

    def test_life_dates_in_parens_not_detected(self):
        # (1820–1880) = Lebensdaten → kein Anker
        result = _process_literatur([seg("s0001", "Der Autor (1820–1880) schrieb darüber.")])
        r = result[0]
        # Lebensdaten in Klammern herausgefiltert → kein exact-Anker
        assert r["precision"] is None

    def test_output_preserves_all_input_fields(self):
        # Alle Input-Felder bleiben erhalten
        s = seg("s0001", "Text aus 1900.", source="Quelle A", page=12)
        result = _process_literatur([s])
        r = result[0]
        assert r["source"] == "Quelle A"
        assert r["page"]   == 12


# ── 2. presseartikel/docx: _process_presseartikel ────────────────────────────

class TestPresseartikeldocx:

    def test_heading_year_propagates(self):
        # Heading mit reiner Jahreszahl → Folgesegment bekommt precision=heading
        segs = [heading("1989"), seg("s0001", "Erster Spatenstich.")]
        result = _process_presseartikel(segs)
        assert len(result) == 1
        r = result[0]
        assert r["precision"] == "heading"
        assert r["time_from"] == 1989
        assert r["time_to"]   == 1989

    def test_new_heading_resets_context(self):
        segs = [
            heading("1989"), seg("s0001", "Spatenstich."),
            heading("1995"), seg("s0002", "Richtfest."),
        ]
        result = _process_presseartikel(segs)
        assert len(result) == 2
        assert result[0]["time_from"] == 1989
        assert result[1]["time_from"] == 1995

    def test_date_field_used_when_no_heading(self):
        # Kein aktives Heading → date-Feld des Segments bestimmt Datierung
        result = _process_presseartikel([seg("s0001", "Artikel.", date="2005-03-15")])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 2005

    def test_date_year_only(self):
        # date-Feld nur als YYYY
        result = _process_presseartikel([seg("s0001", "Artikel.", date="2005")])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 2005

    def test_heading_takes_priority_over_date_field(self):
        # Aktives Heading-Jahr schlägt das date-Feld am Segment
        segs = [heading("1989"), seg("s0001", "Artikel.", date="2005-03-15")]
        result = _process_presseartikel(segs)
        r = result[0]
        assert r["precision"] == "heading"
        assert r["time_from"] == 1989   # nicht 2005

    def test_no_heading_no_date(self):
        result = _process_presseartikel([seg("s0001", "Segment ohne Datierung.")])
        r = result[0]
        assert r["precision"] is None
        assert r["time_from"] is None

    def test_heading_filtered_from_output(self):
        segs = [heading("1989"), seg("s0001", "Inhalt.")]
        result = _process_presseartikel(segs)
        assert len(result) == 1

    def test_non_year_heading_does_not_propagate(self):
        # Heading mit normalem Text setzt keinen Jahres-Kontext
        segs = [heading("Kapitel 1"), seg("s0001", "Inhalt ohne Datum.")]
        result = _process_presseartikel(segs)
        r = result[0]
        assert r["time_from"] is None


# ── 3. presseartikel/obsidian: gleicher Pfad, kein Heading-Kontext ──────────

class TestPresseartikeldObsidian:
    """
    Obsidian-Segmente laufen durch _process_presseartikel.
    ingest_obsidian.py erzeugt ausschließlich content-Segmente (keine headings),
    daher ist active_heading_year immer None — Datierung kommt aus date-Feld.
    """

    def test_iso_date_full(self):
        result = _process_presseartikel([
            seg("s0001", "Artikeltext.", ingest_source="obsidian", date="2024-11-07")
        ])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 2024

    def test_iso_date_year_month(self):
        result = _process_presseartikel([
            seg("s0001", "Artikeltext.", ingest_source="obsidian", date="2024-11")
        ])
        r = result[0]
        assert r["precision"] == "exact"
        assert r["time_from"] == 2024

    def test_no_date_field_undated(self):
        result = _process_presseartikel([
            seg("s0001", "Artikeltext ohne Datum.", ingest_source="obsidian")
        ])
        r = result[0]
        assert r["precision"] is None
        assert r["time_from"] is None

    def test_year_in_body_not_detected(self):
        # Im presseartikel-Pfad läuft kein Regex auf den Text —
        # Jahr im Fließtext wird ignoriert
        result = _process_presseartikel([
            seg("s0001", "Im Jahr 2020 geschah etwas.", ingest_source="obsidian")
        ])
        r = result[0]
        assert r["precision"] is None
        assert r["time_from"] is None

    def test_url_and_author_preserved(self):
        result = _process_presseartikel([
            seg("s0001", "Text.", ingest_source="obsidian", date="2024-01-01",
                url="https://example.com", author="Max Mustermann")
        ])
        r = result[0]
        assert r["url"]    == "https://example.com"
        assert r["author"] == "Max Mustermann"


# ── detect_anchors() direkt ───────────────────────────────────────────────────

class TestDetectAnchors:
    """Direkte Tests der Regex-Funktion — unabhängig vom Quellenpfad."""

    def test_bare_year_found(self):
        anchors = detect_anchors("Das Jahr 1912 war entscheidend.")
        years = [a["value"] for a in anchors if a["type"] == "exact"]
        assert 1912 in years

    def test_paren_year_ignored(self):
        # (YYYY) = Publikationsjahr → nicht als Anker
        anchors = detect_anchors("Vgl. Müller (1923) zu diesem Thema.")
        years = [a["value"] for a in anchors if a["type"] == "exact"]
        assert 1923 not in years

    def test_event_balkan_war(self):
        anchors = detect_anchors("Der Balkankrieg zog weite Kreise.")
        events = [a for a in anchors if a["type"] == "event"]
        assert any(a["value"] == 1912 for a in events)
