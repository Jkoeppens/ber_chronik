"""
tests/test_neu_vokabular.py — die Wertevorräte stehen an genau einer Stelle

Zwei Dinge werden geprüft:

  1. Jeder Vorrat ist aus seinem `Literal` abgeleitet, nicht danebengeschrieben.
     Ein Tupel, das man von Hand pflegt, läuft irgendwann auseinander — genau
     das war der Zustand vorher: 'literaturexzerpt' stand in ingest/kern.py, in
     datierung/kern.py und in modelle.py.
  2. Ein erfundenes Quellformat scheitert überall mit derselben Meldung. Vorher
     gab es zwei quellformat_pruefen() und zwei Ausnahmeklassen gleichen
     Namens; welche Meldung ankam, hing davon ab, welches Modul zuerst prüfte.

Ausführen:
  python3 -m pytest tests/test_neu_vokabular.py -v
"""

import re
import sqlite3
import sys
from pathlib import Path
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu import modelle, vokabular                       # noqa: E402
from src.neu.akteure import kern as akteure_kern             # noqa: E402
from src.neu.datierung import kern as datierung_kern         # noqa: E402
from src.neu.datierung import dienst as datierung_dienst     # noqa: E402
from src.neu.ingest import kern as ingest_kern               # noqa: E402
from src.neu.kategorien import kern as kategorien_kern       # noqa: E402
from src.neu.kategorien import dienst as kategorien_dienst   # noqa: E402

ERFUNDEN = "buchnotizen"   # der alte interne Wert, heute unbekannt


# ── 1. Die Laufzeitliste kommt aus dem Literal ────────────────────────────────

PAARE = [
    ("Quellformat", vokabular.Quellformat, vokabular.QUELLFORMATE),
    ("EinheitTyp", vokabular.EinheitTyp, vokabular.EINHEIT_TYPEN),
    ("Praezision", vokabular.Praezision, vokabular.PRAEZISIONEN),
    ("DatierungHerkunft", vokabular.DatierungHerkunft, vokabular.DATIERUNG_HERKUENFTE),
    ("AnkerHerkunft", vokabular.AnkerHerkunft, vokabular.ANKER_HERKUENFTE),
    ("KategorieHerkunft", vokabular.KategorieHerkunft, vokabular.KATEGORIE_HERKUENFTE),
    ("Konfidenz", vokabular.Konfidenz, vokabular.KONFIDENZEN),
    ("VorschlagHerkunft", vokabular.VorschlagHerkunft, vokabular.VORSCHLAG_HERKUENFTE),
    ("AkteurTyp", vokabular.AkteurTyp, vokabular.AKTEUR_TYPEN),
    ("AkteurStatus", vokabular.AkteurStatus, vokabular.AKTEUR_STATUS),
    ("AkteurHerkunft", vokabular.AkteurHerkunft, vokabular.AKTEUR_HERKUENFTE),
    ("KandidatGrund", vokabular.KandidatGrund, vokabular.KANDIDAT_GRUENDE),
    ("LaufStatus", vokabular.LaufStatus, vokabular.LAUF_STATUS),
    ("LaufSchritt", vokabular.LaufSchritt, vokabular.LAUF_SCHRITTE),
    ("Umfang", vokabular.Umfang, vokabular.UMFAENGE),
]


@pytest.mark.parametrize("name,literal,vorrat", PAARE, ids=[p[0] for p in PAARE])
def test_vorrat_ist_aus_dem_literal_abgeleitet(name, literal, vorrat) -> None:
    assert vorrat == get_args(literal)
    assert len(set(vorrat)) == len(vorrat), f"{name} hat Dubletten"
    assert all(isinstance(w, str) and w for w in vorrat)


# ── 2. Die Module tragen keine eigene Zweitfassung mehr ───────────────────────

def test_die_kerne_teilen_denselben_quellformat_vorrat() -> None:
    """Ein Objekt, nicht drei gleich aussehende Tupel."""
    assert ingest_kern.QUELLFORMATE is vokabular.QUELLFORMATE
    assert datierung_kern.QUELLFORMATE is vokabular.QUELLFORMATE
    assert get_args(modelle.Quellformat) == vokabular.QUELLFORMATE


def test_die_kerne_teilen_dieselbe_pruefung() -> None:
    assert ingest_kern.quellformat_pruefen is vokabular.quellformat_pruefen
    assert datierung_kern.quellformat_pruefen is vokabular.quellformat_pruefen


def test_die_alten_ausnahmenamen_sind_dieselbe_klasse() -> None:
    """Wer UnbekanntesQuellformat fängt, fängt weiterhin — es ist ein Alias."""
    assert ingest_kern.UnbekanntesQuellformat is vokabular.UnbekannterWert
    assert datierung_kern.UnbekanntesQuellformat is vokabular.UnbekannterWert
    assert kategorien_kern.UnbekannteHerkunft is vokabular.UnbekannterWert


def test_herkunft_meint_ueberall_das_was_die_spalte_meint() -> None:
    """Derselbe Name hatte in drei Modulen drei Vorräte. Jetzt sind sie benannt."""
    assert datierung_kern.HERKUENFTE is vokabular.DATIERUNG_HERKUENFTE
    assert kategorien_kern.HERKUENFTE is vokabular.KATEGORIE_HERKUENFTE
    assert kategorien_kern.KATEGORIE_HERKUENFTE is vokabular.VORSCHLAG_HERKUENFTE
    assert akteure_kern.HERKUENFTE is vokabular.AKTEUR_HERKUENFTE
    assert len({id(datierung_kern.HERKUENFTE), id(kategorien_kern.HERKUENFTE),
                id(akteure_kern.HERKUENFTE)}) == 3


def test_umfang_ist_in_beiden_diensten_derselbe() -> None:
    assert datierung_dienst.UMFAENGE is vokabular.UMFAENGE
    assert kategorien_dienst.UMFAENGE is vokabular.UMFAENGE
    assert get_args(modelle.Umfang) == vokabular.UMFAENGE
    assert get_args(modelle.DatierungUmfang) == vokabular.UMFAENGE


# ── 3. Ein erfundenes Quellformat scheitert überall gleich ────────────────────

def _meldung(aufruf) -> str:
    with pytest.raises(vokabular.UnbekannterWert) as fehler:
        aufruf()
    return str(fehler.value)


def test_erfundenes_quellformat_scheitert_ueberall_mit_derselben_meldung() -> None:
    meldungen = {
        "vokabular": _meldung(lambda: vokabular.quellformat_pruefen(ERFUNDEN)),
        "ingest.kern": _meldung(lambda: ingest_kern.quellformat_pruefen(ERFUNDEN)),
        "datierung.kern": _meldung(lambda: datierung_kern.quellformat_pruefen(ERFUNDEN)),
    }
    assert len(set(meldungen.values())) == 1, meldungen
    einzige = next(iter(meldungen.values()))
    assert ERFUNDEN in einzige
    for erlaubt in vokabular.QUELLFORMATE:
        assert erlaubt in einzige, "Die Meldung sagt nicht, was stattdessen geht"


def test_die_meldung_traegt_wert_und_vorrat_mit() -> None:
    fehler = vokabular.UnbekannterWert(ERFUNDEN, vokabular.QUELLFORMATE, "Quellformat")
    assert fehler.wert == ERFUNDEN
    assert fehler.vorrat == vokabular.QUELLFORMATE
    assert fehler.was == "Quellformat"


def test_der_ingest_dienst_scheitert_vor_jeder_datei(tmp_path) -> None:
    """Die Prüfung steht vorn: kein halb eingelesenes Projekt.

    Genau das ging vorher schief — ein unbekanntes Quellformat kam bis in die
    Segmentierung und hinterließ Einheiten, die niemand datieren konnte.
    """
    from src.neu.ingest import dienst

    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    quelle = tmp_path / "gibtsnicht.docx"          # wird nie geöffnet

    with pytest.raises(vokabular.UnbekannterWert) as fehler:
        dienst.einlesen(con, "p", quelle, ERFUNDEN)

    assert ERFUNDEN in str(fehler.value)
    assert con.execute("SELECT count(*) FROM einheit").fetchone()[0] == 0
    con.close()


def test_das_pydantic_modell_kennt_denselben_vorrat() -> None:
    """Der Rand prüft gegen dasselbe Literal — nur eben als 422."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as fehler:
        modelle.QuelleAnlegen(pfad="Notizen.docx", quellformat=ERFUNDEN)
    text = str(fehler.value)
    for erlaubt in vokabular.QUELLFORMATE:
        assert erlaubt in text


# ── 4. Die Datenbank führt dieselben Vorräte ──────────────────────────────────

def test_schema_und_vokabular_stimmen_ueberein() -> None:
    """Was schema.sql per CHECK erlaubt, ist der Vorrat aus vokabular.py.

    Jede Spalte mit geschlossenem Wertevorrat trägt ihn als CHECK — ein
    Kommentar hält nichts auf. Die einzige Ausnahme ist lauf.schritt, und sie
    ist begründet: siehe test_lauf_schritt_bleibt_absichtlich_ohne_check.
    """
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(":memory:")
    con.executescript(schema)
    ddl = {z[0]: z[1] for z in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'")}
    con.close()

    erwartet = [
        ("zugang", "rolle", vokabular.ROLLEN),
        ("quelle", "quellformat", vokabular.QUELLFORMATE),
        ("einheit", "typ", vokabular.EINHEIT_TYPEN),
        ("einheit", "konfidenz", vokabular.KONFIDENZEN),
        ("lauf", "status", vokabular.LAUF_STATUS),
        ("einheit", "praezision", vokabular.PRAEZISIONEN),
        ("einheit", "datierung_herkunft", vokabular.DATIERUNG_HERKUENFTE),
        ("einheit", "kategorie_herkunft", vokabular.KATEGORIE_HERKUENFTE),
        ("anker", "herkunft", vokabular.ANKER_HERKUENFTE),
        ("kategorie", "herkunft", vokabular.VORSCHLAG_HERKUENFTE),
        ("akteur", "typ", vokabular.AKTEUR_TYPEN),
        ("akteur", "status", vokabular.AKTEUR_STATUS),
        ("akteur", "herkunft", vokabular.AKTEUR_HERKUENFTE),
        ("verschmelzungskandidat", "grund", vokabular.KANDIDAT_GRUENDE),
    ]
    for tabelle, spalte, vorrat in erwartet:
        treffer = re.search(rf"CHECK \({spalte} IN\s*\((.*?)\)\)", ddl[tabelle], re.S)
        assert treffer, f"{tabelle}.{spalte} hat keinen CHECK"
        werte = tuple(w.strip().strip("'") for w in treffer.group(1).split(","))
        assert werte == vorrat, f"{tabelle}.{spalte}: {werte} != {vorrat}"


@pytest.mark.parametrize("sql", [
    "UPDATE einheit SET praezision = 'ungefaehr'",
    "UPDATE einheit SET datierung_herkunft = 'geraten'",
    "UPDATE anker SET herkunft = 'geraten'",
    "UPDATE kategorie SET herkunft = 'geraten'",
    "UPDATE zugang SET rolle = 'chef'",
    "UPDATE quelle SET quellformat = 'buchnotizen'",
    "UPDATE einheit SET typ = 'absatz'",
    "UPDATE einheit SET konfidenz = 'sehr hoch'",
    "UPDATE lauf SET status = 'fertig'",
])
def test_die_datenbank_weist_erfundene_werte_ab(sql: str) -> None:
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    con.executescript("""
        INSERT INTO zugang (id, token, angelegt_am) VALUES (1,'t','2026-01-01');
        INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am)
             VALUES ('p','P',1,'2026-01-01');
        INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am)
             VALUES ('q','p','literaturexzerpt','2026-01-01');
        INSERT INTO einheit (id, quelle_id, position, typ, text)
             VALUES (1,'q',1,'content','Ein Text.');
        INSERT INTO anker (einheit_id, jahr, herkunft) VALUES (1, 1900, 'text');
        INSERT INTO kategorie (projekt_id, name, herkunft)
             VALUES ('p','Eins','vorschlag');
        INSERT INTO lauf (projekt_id, schritt, begonnen_am, status)
             VALUES ('p','ingest','2026-01-01','erfolg');
    """)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        con.execute(sql)
    con.close()


def test_die_einzige_ausnahme_ohne_check_ist_lauf_schritt() -> None:
    """Eine Spalte führt einen geschlossenen Vorrat ohne CHECK — mit Grund.

    Die Liste steht hier ausdrücklich und wird nicht aus dem Schema geraten: ein
    Parser über SQL-Kommentare verrutscht an der ersten mehrzeiligen Klausel und
    gäbe dann falsche Sicherheit. Kommt eine zweite Ausnahme dazu, soll jemand
    sie hier eintragen und dabei begründen müssen.
    """
    ausnahmen = {
        # Ein neuer Verarbeitungsschritt soll nicht zuerst als Datenbankfehler
        # zur Sprache kommen; ein Tippfehler macht nichts kaputt, er taucht nur
        # nicht in der Aufstellung auf.
        ("lauf", "schritt"),
    }
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(":memory:")
    con.executescript(schema)
    ddl = {z[0]: z[1] for z in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table'")}
    con.close()
    for tabelle, spalte in ausnahmen:
        assert f"CHECK ({spalte} IN" not in ddl[tabelle], f"{tabelle}.{spalte} hat doch einen"


def test_lauf_schritt_bleibt_absichtlich_ohne_check() -> None:
    """Geschlossen im Vorrat, offen in der Datenbank — und das ist gewollt.

    Ein neuer Verarbeitungsschritt soll nicht zuerst als Datenbankfehler zur
    Sprache kommen. Ein falsch geschriebener Schritt macht auch nichts kaputt:
    er taucht nur nicht in der Aufstellung auf.
    """
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    lauf = re.search(r"CREATE TABLE lauf \((.*?)\n\);", schema, re.S).group(1)
    assert "CHECK (schritt IN" not in lauf
    # Der Kommentar zählt genau die sechs auf, die vokabular.py kennt.
    for schritt in vokabular.LAUF_SCHRITTE:
        assert schritt in lauf, schritt
    assert "…" not in lauf


def test_rolle_steht_im_vokabular_und_nicht_nur_im_kommentar() -> None:
    assert vokabular.ROLLEN == ("verwalter", "nutzer")
    assert vokabular.pruefen("nutzer", vokabular.ROLLEN, "Rolle") == "nutzer"
    with pytest.raises(vokabular.UnbekannterWert):
        vokabular.pruefen("chef", vokabular.ROLLEN, "Rolle")


def test_ebene_ist_auf_die_drei_stufen_beschraenkt() -> None:
    """1|2|3 sind die Stufen, die ingest/kern.py vergibt — NULL bleibt erlaubt.

    Die Grenze gehört dem heutigen Parser und nicht dem Gegenstand: ein Exzerpt
    könnte tiefer gegliedert sein. Wer den Parser vertieft, hebt hier mit; genau
    dafür meldet sich der CHECK. NULL muss durchgehen, weil jedes Format außer
    literaturexzerpt keine Ebene hat.
    """
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    con.executescript("""
        INSERT INTO zugang (id, token, angelegt_am) VALUES (1,'t','2026-01-01');
        INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am)
             VALUES ('p','P',1,'2026-01-01');
        INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am)
             VALUES ('q','p','literaturexzerpt','2026-01-01');
    """)
    for stufe in (1, 2, 3, None):
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text, ebene) "
                    "VALUES ('q', ?, 'content', 'x', ?)", (stufe or 9, stufe))
    for schlecht in (0, 4, -1):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            con.execute("INSERT INTO einheit (quelle_id, position, typ, text, ebene) "
                        "VALUES ('q', 100, 'content', 'x', ?)", (schlecht,))
    con.close()


def test_der_parser_vergibt_nur_die_erlaubten_stufen() -> None:
    """Gegenprobe am Erzeuger: was ingest/kern.py setzt, passiert den CHECK."""
    import ast

    quelle = (ROOT / "src" / "neu" / "ingest" / "kern.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    gesetzt = {
        k.value.value
        for k in ast.walk(baum)
        if isinstance(k, ast.keyword) and k.arg == "ebene"
        and isinstance(k.value, ast.Constant) and isinstance(k.value.value, int)
    }
    assert gesetzt <= {1, 2, 3}, gesetzt
