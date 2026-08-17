"""
tests/test_neu_kern.py — src/neu/ingest/kern.py

Ohne Datenbank, ohne Dateien, ohne Server: der Kern bekommt Rohtexte als
Objekte und gibt Einheiten zurück.

Ausführen:
  python3 -m pytest tests/test_neu_kern.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.ingest.kern import (  # noqa: E402
    QUELLFORMATE,
    RohAbsatz,
    RohDatei,
    UnbekanntesQuellformat,
    aus_absaetzen,
    aus_dateien,
    datum_lesen,
    frontmatter_lesen,
    ist_bibliographie,
    obsidian_links_saeubern,
    quellformat_pruefen,
    seite_abtrennen,
)


# ── Wertevorrat ───────────────────────────────────────────────────────────────

def test_quellformat_wird_geprueft_nicht_durchgereicht() -> None:
    for wert in QUELLFORMATE:
        assert quellformat_pruefen(wert) == wert
    with pytest.raises(UnbekanntesQuellformat, match="buchnotizen"):
        quellformat_pruefen("buchnotizen")      # alter interner Wert
    with pytest.raises(UnbekanntesQuellformat):
        quellformat_pruefen("Forschungsnotizen")  # Wert aus den Altdaten


# ── Bausteine literaturexzerpt ────────────────────────────────────────────────

def test_seite_wird_vom_zeilenende_abgetrennt() -> None:
    assert seite_abtrennen("Ein Satz über Damaskus 127") == (127, "Ein Satz über Damaskus")
    assert seite_abtrennen("Ein Satz) 43") == (43, "Ein Satz")
    assert seite_abtrennen("Ohne Seitenzahl") == (None, "Ohne Seitenzahl")
    # vierstellig ist keine Seitenzahl mehr — sonst würden Jahreszahlen abgeschnitten
    assert seite_abtrennen("Text 1908")[0] is None
    # Ziffern müssen am Zeilenende stehen; "(43)" endet auf der Klammer
    assert seite_abtrennen("Ein Satz (43)") == (None, "Ein Satz (43)")


def test_bibliographie_signale() -> None:
    assert ist_bibliographie("Khoury : Urban Notables")
    assert ist_bibliographie('"Ein Zitat als Titel"')
    assert ist_bibliographie("Irgendetwas (1984)")
    assert ist_bibliographie("4: Re 4618")
    assert ist_bibliographie("Buch, gelesen")
    assert not ist_bibliographie("Die Azms hatten die meisten Posten")


# ── literaturexzerpt ──────────────────────────────────────────────────────────

def _absaetze() -> list[RohAbsatz]:
    return [
        RohAbsatz("Notizen", "Heading 1"),               # Organizer → meta, ebene 1
        RohAbsatz("Khoury : Urban Notables", "Normal"),  # darunter → ebene 2
        RohAbsatz("Kayali - Arabs and Young Turks", "Heading 1"),  # Buchquelle
        RohAbsatz("Die Azms stellten die meisten Posten 88", "Normal"),
        RohAbsatz("", "Normal"),                          # leer → verschwindet
        RohAbsatz("Commins: Islamic Reform", "Heading 2"),
        RohAbsatz("Ein weiterer Gedanke", "Normal"),
    ]


def test_absaetze_ergeben_einheiten_mit_ebene_und_quelle() -> None:
    e = aus_absaetzen(_absaetze())
    assert len(e) == 4

    assert (e[0].typ, e[0].ebene, e[0].text) == ("meta", 1, "Notizen")
    assert e[0].publikation is None

    assert (e[1].typ, e[1].ebene) == ("bibliography", 2)

    assert (e[2].typ, e[2].ebene, e[2].seite) == ("content", 3, 88)
    assert e[2].text == "Die Azms stellten die meisten Posten"
    assert e[2].publikation == "Kayali - Arabs and Young Turks"

    # Heading 2 wechselt die Quelle, erzeugt aber keine Einheit
    assert e[3].publikation == "Commins: Islamic Reform"


def test_position_ist_lueckenlos_und_ueberspringt_leere_absaetze() -> None:
    e = aus_absaetzen(_absaetze())
    assert [x.position for x in e] == [1, 2, 3, 4]


def test_chronologie_gruppe_ist_das_werk() -> None:
    e = aus_absaetzen(_absaetze())
    for einheit in e[1:]:
        assert einheit.chronologie_gruppe == einheit.publikation


def test_leere_eingabe_ergibt_leere_liste() -> None:
    assert aus_absaetzen([]) == []


# ── Bausteine pressesammlung ──────────────────────────────────────────────────

def test_frontmatter_wird_vom_rumpf_getrennt() -> None:
    meta, rumpf = frontmatter_lesen("---\ntitle: Ein Titel\npublished: 2025-11-03\n---\nDer Text.\n")
    assert meta["title"] == "Ein Titel"
    assert rumpf.strip() == "Der Text."


def test_ohne_frontmatter_bleibt_alles_rumpf() -> None:
    meta, rumpf = frontmatter_lesen("Nur Text.\n")
    assert meta == {}
    assert rumpf == "Nur Text.\n"


def test_kaputtes_yaml_wirft_nicht() -> None:
    meta, rumpf = frontmatter_lesen("---\n: : :\n---\nText\n")
    assert meta == {}
    assert rumpf.strip() == "Text"


def test_datum_published_vor_created() -> None:
    assert datum_lesen({"published": "2025-11-03", "created": "2024-01-01"}) == "2025-11-03"
    assert datum_lesen({"created": "2024-01-01"}) == "2024-01-01"
    assert datum_lesen({"published": "2025"}) == "2025"
    assert datum_lesen({"published": "gestern"}) is None
    assert datum_lesen({}) is None


def test_obsidian_links_werden_gesaeubert() -> None:
    assert obsidian_links_saeubern("[[Anna Meier]]") == "Anna Meier"
    assert obsidian_links_saeubern("[[a/b|Anzeige]]") == "a/b"
    assert obsidian_links_saeubern("ohne Link") == "ohne Link"


# ── pressesammlung ────────────────────────────────────────────────────────────

def test_dateien_ergeben_je_eine_einheit() -> None:
    e = aus_dateien([
        RohDatei("a.md", "---\ntitle: Erster\npublished: 2025-11-03\nsource: https://x/1\n"
                         "author: '[[Anna Meier]]'\ndescription: Kurz\n---\nRumpf eins.\n"),
        RohDatei("b.md", "---\ntitle: Zweiter\n---\nRumpf zwei.\n"),
    ])
    assert len(e) == 2
    assert e[0].typ == "content"
    assert e[0].publikation == "Erster"
    assert e[0].datum == "2025-11-03"
    assert e[0].url == "https://x/1"
    assert e[0].autor == "Anna Meier"
    assert e[0].kurzfassung == "Kurz"
    assert e[0].quellpfad == "a.md"
    assert e[0].text == "Rumpf eins."
    assert e[1].datum is None


def test_leere_dateien_verbrauchen_keine_position() -> None:
    e = aus_dateien([
        RohDatei("leer.md", "   \n"),
        RohDatei("nur_frontmatter.md", "---\ntitle: X\n---\n\n"),
        RohDatei("echt.md", "---\ntitle: Y\n---\nInhalt.\n"),
    ])
    assert len(e) == 1
    assert e[0].position == 1
    assert e[0].publikation == "Y"


def test_titel_faellt_auf_dateinamen_zurueck() -> None:
    e = aus_dateien([RohDatei("ordner/mein_artikel.md", "Ohne Frontmatter.\n")])
    assert e[0].publikation == "mein_artikel"


def test_sammlung_hat_keine_chronologie_gruppe() -> None:
    e = aus_dateien([RohDatei("a.md", "---\ntitle: X\n---\nText.\n")])
    assert e[0].chronologie_gruppe is None


# ── Der Kern fasst nichts an ──────────────────────────────────────────────────

def test_kern_kennt_weder_datenbank_noch_ausgabe() -> None:
    import ast

    quelle = (ROOT / "src" / "neu" / "ingest" / "kern.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Call):
            name = ast.unparse(knoten.func)
            assert name != "print", f"print in kern.py, Zeile {knoten.lineno}"
            assert "sqlite3" not in name, f"Datenbank in kern.py, Zeile {knoten.lineno}"
            assert "open" != name, f"Dateizugriff in kern.py, Zeile {knoten.lineno}"
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.Import, ast.ImportFrom)):
            modul = getattr(knoten, "module", None) or ""
            namen = [a.name for a in knoten.names]
            assert "sqlite3" not in modul and "sqlite3" not in namen
