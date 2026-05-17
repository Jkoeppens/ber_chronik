"""
test_export_exploration.py — Unit-Tests für export_exploration.py

Getestete Funktionen (direkte Importe, kein Subprocess, keine I/O):
  - build_entries(anchors, cls_map)
  - build_meta(config, taxonomy, entities)
  - build_entities_csv(entities)

Abgedeckte Fälle:
  - Buchnotizen: time_from/time_to-Spanne → year, date_precision="year", date_js
  - Buchnotizen: exakter Anker → date_precision="exact", date_js mit Jahres-Fallback
  - Presseartikel/DOCX: date_raw="YYYY-MM-DD" → date_js=date_raw, source_date
  - Presseartikel/Obsidian: url-Feld wird durchgereicht
  - source als Dict → source_name und source_date extrahiert
  - Undatiertes Segment → date_precision="none", date_js=None
  - cls_map-Treffer → event_type, confidence, actors gesetzt
  - Kein cls_map-Treffer → event_type=None, actors=[]
  - build_meta: year_min/year_max nur wenn in config vorhanden
  - build_meta: color_map und node_color_map aus Taxonomie/Entities
  - build_entities_csv: Alias-Zeilen; Duplikate case-insensitiv dedupliziert
"""

import csv
import io
import pytest

from src.generalized.export_exploration import (
    build_entries,
    build_meta,
    build_entities_csv,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def seg(segment_id, *, time_from=None, time_to=None, precision=None,
        date_raw=None, text="dummy", source=None, url="", is_quote=False):
    s = {
        "segment_id": segment_id,
        "time_from": time_from,
        "time_to": time_to,
        "precision": precision,
        "text": text,
        "url": url,
        "is_quote": is_quote,
    }
    if date_raw is not None:
        s["date_raw"] = date_raw
    if source is not None:
        s["source"] = source
    return s


def cls_entry(segment_id, *, category="Klage", confidence="high", actors=None):
    return {
        "segment_id": segment_id,
        "category": category,
        "confidence": confidence,
        "actors": actors or [],
    }


# ── build_entries ─────────────────────────────────────────────────────────────

class TestBuildEntries:
    def test_buchnotizen_interpolated_range(self):
        """Buchnotizen-Segment mit Zeitspanne → year=time_from, date_precision='year'."""
        anchors = [seg("s1", time_from=1990, time_to=2000, precision="interpolated")]
        entries = build_entries(anchors, {})
        e = entries[0]
        assert e["year"] == 1990
        assert e["date_precision"] == "year"
        assert e["date_js"] == "1990-01-01"

    def test_buchnotizen_exact_anchor(self):
        """Exakter Buchnotizen-Anker → date_precision='exact', date_js als Jahr."""
        anchors = [seg("s1", time_from=1995, time_to=1995, precision="exact")]
        entries = build_entries(anchors, {})
        e = entries[0]
        assert e["date_precision"] == "exact"
        assert e["date_js"] == "1995-01-01"

    def test_presseartikel_docx_full_date_raw(self):
        """date_raw='YYYY-MM-DD' → date_js=date_raw, source_date=date_raw."""
        anchors = [seg("s1", time_from=2005, precision="exact", date_raw="2005-03-15")]
        entries = build_entries(anchors, {})
        e = entries[0]
        assert e["date_js"] == "2005-03-15"
        assert e["source_date"] == "2005-03-15"

    def test_presseartikel_obsidian_url_passed_through(self):
        """url-Feld des Segments wird als url im Entry durchgereicht."""
        anchors = [seg("s1", url="https://example.com/article",
                       time_from=2020, precision="exact")]
        entries = build_entries(anchors, {})
        assert entries[0]["url"] == "https://example.com/article"

    def test_source_dict_name_and_date(self):
        """source als Dict → source_name und source_date korrekt extrahiert."""
        src = {"name": "Der Tagesspiegel", "date": "2010-06-01"}
        anchors = [seg("s1", source=src, time_from=2010, precision="exact")]
        entries = build_entries(anchors, {})
        e = entries[0]
        assert e["source_name"] == "Der Tagesspiegel"
        assert e["source_date"] == "2010-06-01"

    def test_undated_segment(self):
        """Undatiertes Segment → date_precision='none', year=None, date_js=None."""
        anchors = [seg("s1")]
        entries = build_entries(anchors, {})
        e = entries[0]
        assert e["year"] is None
        assert e["date_precision"] == "none"
        assert e["date_js"] is None

    def test_cls_map_applied(self):
        """Klassifizierungs-Map-Treffer → event_type, confidence, actors gesetzt."""
        anchors = [seg("s1", time_from=2000, precision="exact")]
        cls_map = {"s1": cls_entry("s1", category="Personalie",
                                   confidence="high", actors=["Mehdorn, Hartmut"])}
        entries = build_entries(anchors, cls_map)
        e = entries[0]
        assert e["event_type"] == "Personalie"
        assert e["actors"] == ["Mehdorn, Hartmut"]

    def test_confidence_medium_abbreviated(self):
        """confidence='medium' wird zu 'med' abgekürzt."""
        anchors = [seg("s1", time_from=2000, precision="exact")]
        cls_map = {"s1": cls_entry("s1", confidence="medium")}
        entries = build_entries(anchors, cls_map)
        assert entries[0]["confidence"] == "med"

    def test_missing_cls_map_gives_none(self):
        """Kein cls_map-Treffer → event_type=None, actors=[]."""
        anchors = [seg("s1", time_from=2000, precision="exact")]
        entries = build_entries(anchors, {})
        assert entries[0]["event_type"] is None
        assert entries[0]["actors"] == []

    def test_id_is_sequential(self):
        """Entries bekommen fortlaufende ids ab 1."""
        anchors = [seg("s1"), seg("s2"), seg("s3")]
        entries = build_entries(anchors, {})
        assert [e["id"] for e in entries] == [1, 2, 3]

    def test_all_required_fields_present(self):
        """Jeder Entry enthält alle 15 Pflichtfelder."""
        required = [
            "id", "doc_anchor", "year", "date_raw", "date_js", "date_precision",
            "text", "event_type", "confidence", "source_name", "source_date",
            "url", "is_quote", "actors", "causal_theme",
        ]
        anchors = [seg("s1", time_from=2000, precision="exact", date_raw="2000-01-01")]
        entries = build_entries(anchors, {})
        for field in required:
            assert field in entries[0], f"Pflichtfeld fehlt: {field}"


# ── build_meta ────────────────────────────────────────────────────────────────

class TestBuildMeta:
    def _taxonomy(self, names):
        return [{"name": n} for n in names]

    def _entities(self, types):
        return [{"normalform": f"Entity{i}", "typ": t} for i, t in enumerate(types)]

    def test_title_and_doc_type_passed_through(self):
        config = {"title": "BER Chronik", "doc_type": "presseartikel"}
        meta = build_meta(config, self._taxonomy(["Klage"]), [])
        assert meta["title"] == "BER Chronik"
        assert meta["doc_type"] == "presseartikel"

    def test_year_min_max_included_when_present(self):
        config = {"year_min": 1989, "year_max": 2017}
        meta = build_meta(config, self._taxonomy(["A"]), [])
        assert meta["year_min"] == 1989
        assert meta["year_max"] == 2017

    def test_year_min_max_absent_when_not_in_config(self):
        config = {}
        meta = build_meta(config, self._taxonomy(["A"]), [])
        assert "year_min" not in meta
        assert "year_max" not in meta

    def test_color_map_from_taxonomy(self):
        taxonomy = self._taxonomy(["Klage", "Personalie"])
        meta = build_meta({}, taxonomy, [])
        assert "Klage" in meta["color_map"]
        assert "Personalie" in meta["color_map"]

    def test_entity_types_sorted(self):
        entities = self._entities(["Person", "Org", "Ort"])
        meta = build_meta({}, self._taxonomy(["A"]), entities)
        assert meta["entity_types"] == sorted(["Person", "Org", "Ort"])

    def test_default_title_when_missing(self):
        meta = build_meta({}, self._taxonomy(["A"]), [])
        assert meta["title"] == "Dokument"


# ── build_entities_csv ────────────────────────────────────────────────────────

class TestBuildEntitiesCsv:
    def _parse_csv(self, text):
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def test_normalform_and_alias_rows(self):
        """Normalform + Alias → je eine Zeile."""
        entities = [{"normalform": "BER", "typ": "Org", "aliases": ["Flughafen BER"]}]
        rows = self._parse_csv(build_entities_csv(entities))
        aliases = [r["alias"] for r in rows]
        assert "BER" in aliases
        assert "Flughafen BER" in aliases

    def test_dedup_case_insensitive(self):
        """Alias = Normalform (case-insensitiv) → nur eine Zeile."""
        entities = [{"normalform": "BER", "typ": "Org", "aliases": ["ber"]}]
        rows = self._parse_csv(build_entities_csv(entities))
        assert len(rows) == 1
        assert rows[0]["alias"] == "BER"

    def test_header_row(self):
        """CSV hat alias, normalform, typ als Header."""
        csv_text = build_entities_csv([])
        first_line = csv_text.splitlines()[0]
        assert first_line == "alias,normalform,typ"

    def test_normalform_column_consistent(self):
        """Alle Alias-Zeilen einer Entity referenzieren dieselbe Normalform."""
        entities = [{"normalform": "Mehdorn", "typ": "Person",
                     "aliases": ["Hartmut Mehdorn"]}]
        rows = self._parse_csv(build_entities_csv(entities))
        for r in rows:
            assert r["normalform"] == "Mehdorn"
