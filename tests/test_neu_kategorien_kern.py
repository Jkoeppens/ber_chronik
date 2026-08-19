"""
tests/test_neu_kategorien_kern.py — src/neu/kategorien/kern.py

Ohne Datenbank, ohne Netz, ohne Modell: der LLM-Aufruf wird als Funktion
hereingegeben, die Embeddings sind von Hand gesetzte Zahlen.

Ausführen:
  python3 -m pytest tests/test_neu_kategorien_kern.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.kategorien.kern import (  # noqa: E402
    HERKUENFTE,
    SCHWELLE_HIGH,
    SCHWELLE_MEDIUM,
    SEG_CHARS,
    UnbekannteHerkunft,
    Zuordnung,
    baue_kategorienblock,
    baue_prompt,
    einheit_texte,
    herkunft_pruefen,
    klassifiziere_eine,
    konfidenz_aus_aehnlichkeit,
    normalisiere_kategorie,
    parse_taxonomie,
    taxonomie_texte,
    zuordnung_aus_antwort,
    zuordnungen_aus_embeddings,
)

TAXONOMIE = [
    {"name": "Politik", "description": "Staatliches Handeln", "keywords": ["Staat", "Partei"]},
    {"name": "Außenpolitik", "description": "Zwischenstaatliches", "keywords": ["Vertrag"]},
    {"name": "Kosten", "description": "Geld und Budget", "keywords": []},
]
NAMEN = [c["name"] for c in TAXONOMIE]


# ── Wertevorrat ───────────────────────────────────────────────────────────────

def test_herkunft_wird_geprueft() -> None:
    for wert in HERKUENFTE:
        assert herkunft_pruefen(wert) == wert
    with pytest.raises(UnbekannteHerkunft):
        herkunft_pruefen("vorschlag")   # das ist eine kategorie-Herkunft
    with pytest.raises(UnbekannteHerkunft):
        herkunft_pruefen("")


# ── Taxonomie parsen ──────────────────────────────────────────────────────────

def test_taxonomie_wird_geparst() -> None:
    text = (
        "## Politische Instabilität\n"
        "Ein Satz über den Zusammenhang.\n"
        "Keywords: Staat, Partei, Wahl\n"
        "## Kosten\n"
        "Geld und Budget.\n"
        "Keywords: Preis, Budget\n"
    )
    tax = parse_taxonomie(text)
    assert [c["name"] for c in tax] == ["Politische Instabilität", "Kosten"]
    assert tax[0]["description"] == "Ein Satz über den Zusammenhang."
    assert tax[0]["keywords"] == ["Staat", "Partei", "Wahl"]


def test_gruppenpraefix_und_sterne_fallen_weg() -> None:
    tax = parse_taxonomie("## **Gruppe 3: Kosten**\nBeschreibung.\nKeywords: a\n")
    assert tax[0]["name"] == "Kosten"


def test_keywords_werden_auf_drei_gekuerzt() -> None:
    tax = parse_taxonomie("## X\nY.\nKeywords: a, b, c, d, e\n")
    assert tax[0]["keywords"] == ["a", "b", "c"]


def test_kategorie_ohne_keywords_zeile_wird_am_ende_uebernommen() -> None:
    tax = parse_taxonomie("## X\nNur eine Beschreibung.\n")
    assert len(tax) == 1
    assert tax[0]["keywords"] == []


def test_leerer_text_ergibt_leere_taxonomie() -> None:
    assert parse_taxonomie("") == []


# ── Namen normalisieren ───────────────────────────────────────────────────────

def test_exakter_name_gewinnt() -> None:
    assert normalisiere_kategorie("Kosten", NAMEN) == "Kosten"


def test_laengster_teilstring_gewinnt() -> None:
    """Außenpolitik vor Politik — wörtlich die Regel der Vorlage."""
    assert normalisiere_kategorie("Kategorie: Außenpolitik", NAMEN) == "Außenpolitik"


def test_ohne_treffer_wird_none() -> None:
    """In der Vorlage war das die Zeichenkette '(unbekannt)'."""
    assert normalisiere_kategorie("Sport", NAMEN) is None
    assert normalisiere_kategorie(None, NAMEN) is None
    assert normalisiere_kategorie(42, NAMEN) is None


# ── Prompt ────────────────────────────────────────────────────────────────────

def test_kategorienblock_hat_eine_zeile_je_kategorie() -> None:
    block = baue_kategorienblock(TAXONOMIE)
    assert block.splitlines() == [
        "- Politik – Staatliches Handeln",
        "- Außenpolitik – Zwischenstaatliches",
        "- Kosten – Geld und Budget",
    ]


def test_prompt_enthaelt_kategorien_und_text() -> None:
    prompt = baue_prompt(baue_kategorienblock(TAXONOMIE), "Ein Absatz.")
    assert "- Kosten – Geld und Budget" in prompt
    assert prompt.rstrip().endswith("Ein Absatz.")
    assert '{"category": "<Name>", "confidence": "<high|medium|low>"}' in prompt


# ── LLM-Antwort auswerten ─────────────────────────────────────────────────────

def test_antwort_wird_ausgewertet() -> None:
    z = zuordnung_aus_antwort('{"category": "Kosten", "confidence": "high"}', NAMEN)
    assert z == Zuordnung(kategorie="Kosten", konfidenz="high", herkunft="automatisch")


def test_markdown_zaun_wird_entfernt() -> None:
    roh = '```json\n{"category": "Politik", "confidence": "medium"}\n```'
    z = zuordnung_aus_antwort(roh, NAMEN)
    assert z.kategorie == "Politik"
    assert z.konfidenz == "medium"


def test_fehlende_konfidenz_wird_low() -> None:
    z = zuordnung_aus_antwort('{"category": "Kosten"}', NAMEN)
    assert z.konfidenz == "low"


def test_unlesbare_antwort_gibt_none() -> None:
    assert zuordnung_aus_antwort("kein JSON", NAMEN) is None


# ── LLM-Pfad mit Wiederholung ─────────────────────────────────────────────────

def test_erste_antwort_wird_genommen() -> None:
    aufrufe = []

    def modell(prompt: str, system: str) -> str:
        aufrufe.append(prompt)
        return '{"category": "Kosten", "confidence": "high"}'

    z = klassifiziere_eine("Text", baue_kategorienblock(TAXONOMIE), NAMEN, modell)
    assert z.kategorie == "Kosten"
    assert len(aufrufe) == 1


def test_bei_muell_wird_genau_einmal_wiederholt() -> None:
    antworten = iter(["Müll", '{"category": "Politik", "confidence": "low"}'])

    def modell(prompt: str, system: str) -> str:
        return next(antworten)

    z = klassifiziere_eine("Text", "", NAMEN, modell)
    assert z.kategorie == "Politik"


def test_zweimal_muell_ergibt_keine_kategorie_und_keine_konfidenz() -> None:
    def modell(prompt: str, system: str) -> str:
        return "immer noch Müll"

    z = klassifiziere_eine("Text", "", NAMEN, modell)
    assert z == Zuordnung(kategorie=None, konfidenz=None, herkunft="automatisch")


# ── BGE-Pfad ──────────────────────────────────────────────────────────────────

def test_schwellwerte() -> None:
    assert konfidenz_aus_aehnlichkeit(0.9) == "high"
    assert konfidenz_aus_aehnlichkeit(0.4) == "medium"
    assert konfidenz_aus_aehnlichkeit(0.1) == "low"
    # Die Grenzen selbst gehören zur jeweils schwächeren Stufe (>, nicht >=)
    assert konfidenz_aus_aehnlichkeit(SCHWELLE_HIGH) == "medium"
    assert konfidenz_aus_aehnlichkeit(SCHWELLE_MEDIUM) == "low"


def test_argmax_waehlt_die_aehnlichste_kategorie() -> None:
    einheiten = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    tax = np.array([[0.9, 0.0], [0.0, 0.3]], dtype=np.float32)
    z = zuordnungen_aus_embeddings(einheiten, tax, ["A", "B"])
    assert [x.kategorie for x in z] == ["A", "B", "A"]
    # 1.0·0.9 = 0.90 → high | 1.0·0.3 = 0.30 → low | 0.5·0.9 = 0.45 → medium
    assert [x.konfidenz for x in z] == ["high", "low", "medium"]
    assert {x.herkunft for x in z} == {"automatisch"}


def test_bge_ordnet_immer_zu() -> None:
    """Kein '(unbekannt)': schwache Ähnlichkeit heißt low, nicht leer."""
    einheiten = np.array([[0.01, 0.0]], dtype=np.float32)
    tax = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    z = zuordnungen_aus_embeddings(einheiten, tax, ["A", "B"])
    assert z[0].kategorie == "A"
    assert z[0].konfidenz == "low"


def test_taxonomie_text_setzt_name_beschreibung_keywords_zusammen() -> None:
    assert taxonomie_texte(TAXONOMIE)[0] == "Politik. Staatliches Handeln. Staat Partei"
    assert taxonomie_texte(TAXONOMIE)[2] == "Kosten. Geld und Budget. "


def test_einheit_texte_werden_gekuerzt() -> None:
    lang = "x" * 900
    assert einheit_texte([lang])[0] == "x" * SEG_CHARS


# ── Der Kern fasst nichts an ──────────────────────────────────────────────────

def test_kern_kennt_weder_datenbank_noch_netz_noch_ausgabe() -> None:
    import ast

    quelle = (ROOT / "src" / "neu" / "kategorien" / "kern.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Call):
            name = ast.unparse(knoten.func)
            assert name != "print", f"print in kern.py, Zeile {knoten.lineno}"
            assert name != "open", f"Dateizugriff in kern.py, Zeile {knoten.lineno}"
        if isinstance(knoten, (ast.Import, ast.ImportFrom)):
            modul = getattr(knoten, "module", None) or ""
            namen = [a.name for a in knoten.names]
            for verboten in ("sqlite3", "requests", "anthropic", "httpx"):
                assert verboten not in modul and verboten not in namen, verboten
