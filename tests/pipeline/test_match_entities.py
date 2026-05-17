"""
test_match_entities.py — Unit-Tests für match_entities.py

Getestete Funktion (direkter Import, kein Subprocess, keine I/O):
  - build_patterns(entities)

Matching-Logik (inline im main()-Loop) wird über build_patterns + pat.search()
getestet, um keine I/O-Abhängigkeit zu erzeugen.

Abgedeckte Fälle:
  - Alias-Match: Alias im Text → Normalform zurückgegeben
  - Normalform-Match: Normalform direkt im Text
  - Kein Treffer: Entity nicht im Text → leer
  - Kein Entities → build_patterns([]) → keine Patterns → actors=[]
  - Mehrere Entities im selben Text → alle Normalformen zurückgegeben
  - Case-insensitiv: Groß-/Kleinschreibung irrelevant
  - Wortgrenze: Teilstring-Overlap wird nicht gematcht (BER ≠ BERLIN)
  - Längster Alias wird zuerst versucht (Disambiguierung)
  - Duplikate im terms-Array werden dedupliziert
"""

import pytest
from src.generalized.match_entities import build_patterns


# ── Helfer ────────────────────────────────────────────────────────────────────

def match(text: str, patterns) -> list[str]:
    """Simuliert den Match-Loop aus match_entities.main()."""
    return [nf for nf, pat in patterns if pat.search(text)]


def ent(normalform, *, typ="Org", aliases=None):
    return {"normalform": normalform, "typ": typ, "aliases": aliases or []}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBuildPatterns:
    def test_normalform_matched_in_text(self):
        patterns = build_patterns([ent("BER")])
        assert match("Der Flughafen BER öffnet.", patterns) == ["BER"]

    def test_alias_matched_normalform_returned(self):
        """Alias trifft → Normalform wird zurückgegeben, nicht der Alias."""
        patterns = build_patterns([ent("BER", aliases=["Flughafen BER", "Berlin Brandenburg"])])
        assert match("Der Flughafen BER ist fertig.", patterns) == ["BER"]

    def test_no_match_returns_empty(self):
        patterns = build_patterns([ent("Mehdorn")])
        assert match("Der Flughafen öffnet endlich.", patterns) == []

    def test_no_entities_returns_empty_patterns(self):
        patterns = build_patterns([])
        assert patterns == []
        assert match("Irgendein Text.", patterns) == []

    def test_multiple_entities_in_text(self):
        """Zwei Entities im Text → beide Normalformen zurückgegeben."""
        patterns = build_patterns([
            ent("Mehdorn"),
            ent("BER"),
        ])
        hits = match("Mehdorn sprach am Flughafen BER.", patterns)
        assert "Mehdorn" in hits
        assert "BER" in hits

    def test_case_insensitive_match(self):
        """Groß-/Kleinschreibung spielt keine Rolle."""
        patterns = build_patterns([ent("Mehdorn")])
        assert match("mehdorn war anwesend.", patterns) == ["Mehdorn"]

    def test_word_boundary_no_partial_match(self):
        """'BER' darf nicht in 'BERLIN' matchen (Wortgrenze)."""
        patterns = build_patterns([ent("BER")])
        assert match("Das ist Berlin.", patterns) == []

    def test_word_boundary_matches_at_end_of_sentence(self):
        """'BER' am Satzende (vor Punkt) wird erkannt."""
        patterns = build_patterns([ent("BER")])
        assert match("Wir landen am BER.", patterns) == ["BER"]

    def test_duplicate_alias_deduplicated(self):
        """Normalform = Alias → nur eine Zeile im Pattern, kein doppelter Treffer."""
        patterns = build_patterns([ent("BER", aliases=["BER"])])
        assert len(patterns) == 1
        hits = match("Flughafen BER.", patterns)
        assert hits == ["BER"]

    def test_longer_alias_takes_priority(self):
        """Längster Alias steht im Regex zuerst; kein falscher Teilmatch."""
        patterns = build_patterns([ent("SPD", aliases=["SPD-Fraktion"])])
        # "SPD-Fraktion" im Text → sollte trotzdem nur "SPD" als Normalform liefern
        hits = match("Die SPD-Fraktion stimmte zu.", patterns)
        assert hits == ["SPD"]

    def test_entity_without_normalform_skipped(self):
        """Entity ohne normalform und ohne text wird übersprungen."""
        patterns = build_patterns([{"typ": "Org", "aliases": []}])
        assert patterns == []
