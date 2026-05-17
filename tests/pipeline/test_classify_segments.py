"""
test_classify_segments.py — Unit-Tests für classify_segments.py

Getestete Funktionen (direkte Importe, kein Subprocess, keine I/O):
  - normalize_category(raw, valid_names)
  - build_categories_block(taxonomy)
  - classify_one(provider, segment, categories_block, valid_names)

Abgedeckte Fälle:
  - normalize_category: exakter Match
  - normalize_category: Substring-Match (längster gewinnt)
  - normalize_category: kein Match → "(unbekannt)"
  - normalize_category: Nicht-String-Input → "(unbekannt)"
  - build_categories_block: Format "- Name – Description" pro Kategorie
  - classify_one: gültiger JSON-Response → Kategorie normalisiert, Konfidenz gesetzt
  - classify_one: Markdown-Code-Fence wird entfernt
  - classify_one: ungültiger JSON nach beiden Versuchen → category=None, confidence=None
"""

import asyncio
import pytest

from src.generalized.classify_segments import (
    normalize_category,
    build_categories_block,
    classify_one,
)


# ── Mock-Provider ─────────────────────────────────────────────────────────────

class _Provider:
    """Minimaler synchroner Mock — gibt responses der Reihe nach zurück."""
    max_concurrency = 1

    def __init__(self, *responses):
        self._queue = list(responses)

    def complete(self, user_prompt, system_prompt):
        if self._queue:
            return self._queue.pop(0)
        return '{"category": "Fallback", "confidence": "low"}'


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def seg(segment_id="s1", text="Dummy-Text"):
    return {"segment_id": segment_id, "text": text}


# ── normalize_category ────────────────────────────────────────────────────────

class TestNormalizeCategory:
    def test_exact_match(self):
        assert normalize_category("Klage", ["Klage", "Personalie"]) == "Klage"

    def test_substring_match_longest_wins(self):
        # "Außenpolitik" enthält "Politik" — längster Match gewinnt
        result = normalize_category(
            "Außenpolitik-Entscheidung",
            ["Politik", "Außenpolitik"],
        )
        assert result == "Außenpolitik"

    def test_no_match_returns_unbekannt(self):
        assert normalize_category("Sonstiges", ["Klage", "Personalie"]) == "(unbekannt)"

    def test_non_string_input_returns_unbekannt(self):
        assert normalize_category(None, ["Klage"]) == "(unbekannt)"
        assert normalize_category(42, ["Klage"]) == "(unbekannt)"

    def test_case_insensitive_substring(self):
        # "klage" im Output → trifft "Klage" in valid_names per lower()-Vergleich
        result = normalize_category("klage", ["Klage", "Personalie"])
        assert result == "Klage"

    def test_empty_valid_names(self):
        assert normalize_category("Klage", []) == "(unbekannt)"


# ── build_categories_block ────────────────────────────────────────────────────

class TestBuildCategoriesBlock:
    def test_single_category_format(self):
        taxonomy = [{"name": "Klage", "description": "Gerichtliche Verfahren"}]
        block = build_categories_block(taxonomy)
        assert block == "- Klage – Gerichtliche Verfahren"

    def test_multiple_categories_one_per_line(self):
        taxonomy = [
            {"name": "Klage",     "description": "Gerichtliche Verfahren"},
            {"name": "Personalie", "description": "Personalentscheidungen"},
        ]
        lines = build_categories_block(taxonomy).splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("- Klage")
        assert lines[1].startswith("- Personalie")


# ── classify_one ─────────────────────────────────────────────────────────────

VALID_NAMES = ["Klage", "Personalie", "Kosten"]


class TestClassifyOne:
    def test_happy_path_json_response(self):
        """Gültiger JSON-Response → Kategorie normalisiert, Konfidenz gesetzt."""
        provider = _Provider('{"category": "Klage", "confidence": "high"}')
        result = run(classify_one(provider, seg(), "- Klage – ...", VALID_NAMES))
        assert result["category"] == "Klage"
        assert result["confidence"] == "high"

    def test_markdown_fence_stripped(self):
        """```json … ``` wird entfernt bevor JSON geparst wird."""
        response = '```json\n{"category": "Personalie", "confidence": "medium"}\n```'
        provider = _Provider(response)
        result = run(classify_one(provider, seg(), "- Personalie – ...", VALID_NAMES))
        assert result["category"] == "Personalie"
        assert result["confidence"] == "medium"

    def test_category_normalized_via_substring(self):
        """Kategorie aus LLM trifft per Substring auf gültigen Namen."""
        provider = _Provider('{"category": "Eine Klage wurde eingereicht", "confidence": "low"}')
        result = run(classify_one(provider, seg(), "- Klage – ...", VALID_NAMES))
        assert result["category"] == "Klage"

    def test_invalid_json_both_attempts_gives_null(self):
        """Kein gültiges JSON nach beiden Versuchen → category=None, confidence=None."""
        provider = _Provider("kein json", "auch kein json")
        result = run(classify_one(provider, seg(), "- Klage – ...", VALID_NAMES))
        assert result["category"] is None
        assert result["confidence"] is None

    def test_retry_succeeds_on_second_attempt(self):
        """Erster Versuch ungültig, zweiter Versuch gültig → korrekte Klassifizierung."""
        provider = _Provider("kein json", '{"category": "Kosten", "confidence": "medium"}')
        result = run(classify_one(provider, seg(), "- Kosten – ...", VALID_NAMES))
        assert result["category"] == "Kosten"

    def test_segment_fields_preserved(self):
        """Alle Felder des Input-Segments bleiben im Ergebnis erhalten."""
        provider = _Provider('{"category": "Klage", "confidence": "high"}')
        s = {"segment_id": "s42", "text": "Test", "time_from": 2000}
        result = run(classify_one(provider, s, "- Klage – ...", VALID_NAMES))
        assert result["segment_id"] == "s42"
        assert result["time_from"] == 2000
