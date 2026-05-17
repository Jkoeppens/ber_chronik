"""
test_interpolate_anchors.py — Unit-Tests für interpolate_anchors.py

Getestete Funktionen (direkte Importe, kein Subprocess, keine I/O):
  - interpolate(segments)
  - apply_overrides(segments, overrides)
  - _representative_year(seg)

Abgedeckte Fälle:
  - Buchnotizen: Segment zwischen zwei Ankern → Zeitspanne aufspannen
  - Buchnotizen: Segment vor erstem Anker → undatiert (kein Rückwärts-Erben)
  - Buchnotizen: Segment nach letztem Anker → erbt letzten Anker vorwärts
  - Buchnotizen: Quelle ohne Anker → alles bleibt undatiert
  - Mehrere undatierte Segmente zwischen zwei Ankern → alle interpoliert
  - Dekaden-Anker (kein time_from/time_to) zählen nicht als Ankerpunkt
  - Mehrere Quellen: Interpolation bleibt quellspezifisch
  - Overrides: set_anchor setzt precision="manual" und dient als Ankerpunkt
  - Overrides: undatable verhindert Datierung und wirkt nicht als Anker
"""

import pytest
from src.generalized.interpolate_anchors import (
    interpolate,
    apply_overrides,
    _representative_year,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def seg(segment_id, *, source="src1", time_from=None, time_to=None, precision=None):
    return {
        "segment_id": segment_id,
        "source": source,
        "time_from": time_from,
        "time_to": time_to,
        "precision": precision,
        "text": "dummy",
    }


def anchored(segment_id, year, *, source="src1", precision="exact"):
    return seg(segment_id, source=source, time_from=year, time_to=year, precision=precision)


# ── _representative_year ─────────────────────────────────────────────────────

class TestRepresentativeYear:
    def test_both_from_and_to(self):
        assert _representative_year({"time_from": 1990, "time_to": 2000}) == 1995

    def test_only_from(self):
        assert _representative_year({"time_from": 1995, "time_to": None}) == 1995

    def test_only_to(self):
        assert _representative_year({"time_from": None, "time_to": 2005}) == 2005

    def test_neither(self):
        assert _representative_year({"time_from": None, "time_to": None}) is None


# ── interpolate() ─────────────────────────────────────────────────────────────

class TestInterpolate:
    def test_between_two_anchors(self):
        """Undatiertes Segment zwischen zwei Ankern → Zeitspanne aufspannen."""
        segs = [
            anchored("s1", 1990),
            seg("s2"),
            anchored("s3", 2000),
        ]
        result = interpolate(segs)
        s2 = result[1]
        assert s2["precision"] == "interpolated"
        assert s2["time_from"] == 1990
        assert s2["time_to"] == 2000

    def test_before_first_anchor_stays_undated(self):
        """Segment vor dem ersten Anker bleibt undatiert (kein Rückwärts-Erben)."""
        segs = [
            seg("s1"),
            anchored("s2", 1990),
        ]
        result = interpolate(segs)
        assert result[0]["time_from"] is None
        assert result[0]["precision"] is None

    def test_after_last_anchor_inherits_forward(self):
        """Segment nach letztem Anker erbt den letzten Anker vorwärts."""
        segs = [
            anchored("s1", 2000),
            seg("s2"),
        ]
        result = interpolate(segs)
        s2 = result[1]
        assert s2["precision"] == "interpolated"
        assert s2["time_from"] == 2000
        assert s2["time_to"] == 2000

    def test_no_anchors_all_remain_undated(self):
        """Quelle ohne Anker → alle Segmente bleiben undatiert."""
        segs = [seg("s1"), seg("s2"), seg("s3")]
        result = interpolate(segs)
        for r in result:
            assert r["time_from"] is None
            assert r["precision"] is None

    def test_already_dated_unchanged(self):
        """Segment mit eigenem Anker wird nicht überschrieben."""
        segs = [
            anchored("s1", 1990),
            anchored("s2", 1995),
            anchored("s3", 2000),
        ]
        result = interpolate(segs)
        assert result[1]["time_from"] == 1995
        assert result[1]["precision"] == "exact"

    def test_multiple_undated_between_anchors(self):
        """Mehrere undatierte Segmente zwischen zwei Ankern → alle interpoliert."""
        segs = [
            anchored("s1", 1980),
            seg("s2"),
            seg("s3"),
            seg("s4"),
            anchored("s5", 2000),
        ]
        result = interpolate(segs)
        for r in result[1:4]:
            assert r["precision"] == "interpolated"
            assert r["time_from"] == 1980
            assert r["time_to"] == 2000

    def test_multi_source_independence(self):
        """Anker aus src1 dürfen nicht auf undatiertes Segment in src2 übertragen werden."""
        segs = [
            anchored("s1", 1990, source="src1"),
            seg("s2", source="src2"),
            anchored("s3", 2000, source="src1"),
        ]
        result = interpolate(segs)
        assert result[1]["time_from"] is None

    def test_decade_anchor_not_used_for_interpolation(self):
        """Dekaden-Anker (kein time_from/time_to) zählen nicht als Ankerpunkt."""
        segs = [
            # precision="decade" aber kein time_from/time_to → zählt nicht
            {"segment_id": "s1", "source": "src1",
             "time_from": None, "time_to": None, "precision": "decade", "text": "dummy"},
            seg("s2"),
            anchored("s3", 2000),
        ]
        result = interpolate(segs)
        # s2 liegt vor dem ersten echten Anker s3 → kein prev_year → undatiert
        assert result[1]["time_from"] is None


# ── apply_overrides() ─────────────────────────────────────────────────────────

class TestApplyOverrides:
    def test_set_anchor_sets_manual_precision(self):
        """set_anchor-Override setzt precision='manual' mit eigenen Jahreswerten."""
        segs = [seg("s1")]
        overrides = [{"segment_id": "s1", "action": "set_anchor",
                      "time_from": 1995, "time_to": 1995}]
        result = apply_overrides(segs, overrides)
        assert result[0]["precision"] == "manual"
        assert result[0]["time_from"] == 1995
        assert result[0]["time_to"] == 1995

    def test_set_anchor_serves_as_interpolation_anchor(self):
        """set_anchor-Override macht undatiertes Segment zum Ankerpunkt für Nachfolger."""
        segs = [
            seg("s1"),
            seg("s2"),
        ]
        overrides = [{"segment_id": "s1", "action": "set_anchor",
                      "time_from": 2005, "time_to": 2005}]
        with_ov = apply_overrides(segs, overrides)
        result = interpolate(with_ov)
        assert result[1]["precision"] == "interpolated"
        assert result[1]["time_from"] == 2005

    def test_undatable_stays_undated_despite_surrounding_anchors(self):
        """undatable-Override: Segment wird auch zwischen zwei Ankern nicht datiert."""
        segs = [
            anchored("s1", 1990),
            seg("s2"),
            anchored("s3", 2000),
        ]
        overrides = [{"segment_id": "s2", "action": "undatable"}]
        with_ov = apply_overrides(segs, overrides)
        result = interpolate(with_ov)
        s2 = result[1]
        assert s2["time_from"] is None
        assert "_undatable" not in s2

    def test_undatable_not_used_as_anchor(self):
        """undatable-Segment wirkt nicht als Ankerpunkt; Nachfolger erbt den letzten echten Anker."""
        segs = [
            anchored("s1", 1990),
            seg("s2"),
            seg("s3"),
        ]
        overrides = [{"segment_id": "s2", "action": "undatable"}]
        with_ov = apply_overrides(segs, overrides)
        result = interpolate(with_ov)
        # s3 erbt von s1 (letzter echter Anker, da s2 undatable)
        assert result[2]["time_from"] == 1990
        assert result[2]["precision"] == "interpolated"

    def test_no_overrides_leaves_segments_unchanged(self):
        """Leere Override-Liste verändert keine Segmente."""
        segs = [anchored("s1", 2000), seg("s2")]
        result = apply_overrides(segs, [])
        assert result[0]["precision"] == "exact"
        assert result[1]["time_from"] is None
