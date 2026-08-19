"""
tests/test_neu_datierung_dienst.py — src/neu/datierung/dienst.py

Gegen eine echte SQLite-Datei, ohne Modell: Datieren ist reine Regexarbeit.
Geprüft wird, was bei einer Handkorrektur und bei einer Textänderung mit der
Datenbank geschieht — und was dabei ausdrücklich nicht stehen bleibt.

Ausführen:
  python3 -m pytest tests/test_neu_datierung_dienst.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.datierung.dienst import (  # noqa: E402
    DatierungFehler,
    ausreisser,
    datieren,
    datierung_setzen,
    text_setzen,
    verteilung,
)

SCHEMA = ROOT / "schema.sql"


@pytest.fixture
def con(tmp_path, monkeypatch):
    pfad = tmp_path / "test.db"
    c = sqlite3.connect(pfad)
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    c.execute("PRAGMA foreign_keys = ON")
    with c:
        c.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                  "VALUES ('t','2026-01-01','nutzer')")
        c.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                  "VALUES ('p','P',1,'2026-01-01')")
        c.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                  "VALUES ('q','p','literaturexzerpt','2026-01-01')")
    monkeypatch.setenv("NEU_DB", str(pfad))
    yield c
    c.close()


def _einheiten(con, texte: list[str]) -> list[int]:
    ids = []
    with con:
        for n, t in enumerate(texte, start=1):
            ids.append(con.execute(
                "INSERT INTO einheit (quelle_id, position, typ, text) "
                "VALUES ('q', ?, 'content', ?)", (n, t)).lastrowid)
    return ids


def _zeile(con, einheit_id: int) -> tuple:
    return con.execute(
        "SELECT datum, jahr_von, jahr_bis, praezision, datierung_herkunft "
        "FROM einheit WHERE id = ?", (einheit_id,)).fetchone()


# ── Handkorrektur mit freier Genauigkeit ─────────────────────────────────────

def test_tagesgenaue_korrektur(con) -> None:
    ids = _einheiten(con, ["Ein Absatz ohne jede Jahreszahl darin."])
    e = datierung_setzen(con, ids[0], "2012-07-30")
    assert e["praezision"] == "tag" and e["datum"] == "2012-07-30"
    assert _zeile(con, ids[0]) == ("2012-07-30", 2012, 2012, "tag", "manuell")


def test_begruendung_landet_in_der_fundstelle(con) -> None:
    """Keine eigene Spalte: der Anker beantwortet ohnehin die Frage 'woher'."""
    ids = _einheiten(con, ["Ein Absatz."])
    datierung_setzen(con, ids[0], "2012", begruendung="Zifferndreher, stand 3012")
    a = con.execute("SELECT jahr, herkunft, fundstelle FROM anker "
                    "WHERE einheit_id = ?", (ids[0],)).fetchone()
    assert a == (2012, "manuell", "Zifferndreher, stand 3012")


def test_undatierbar(con) -> None:
    ids = _einheiten(con, ["Ein Absatz von 1908 mit Jahreszahl."])
    datieren(con, "p", umfang="alle")
    e = datierung_setzen(con, ids[0], None, begruendung="lässt sich nicht datieren")
    assert e["jahr_von"] is None and e["praezision"] == "keine"
    a = con.execute("SELECT jahr, fundstelle FROM anker WHERE einheit_id = ?",
                    (ids[0],)).fetchone()
    assert a == (None, "lässt sich nicht datieren")


def test_unlesbares_datum_wird_abgewiesen(con) -> None:
    ids = _einheiten(con, ["Ein Absatz."])
    with pytest.raises(DatierungFehler) as exc:
        datierung_setzen(con, ids[0], "30.07.2012")
    assert exc.value.code == "datum_unlesbar"


# ── Der Neulauf lässt Handkorrekturen unverändert ────────────────────────────

def test_neulauf_laesst_die_korrektur_stehen(con) -> None:
    ids = _einheiten(con, [
        "Der erste Absatz nennt 1900 als Jahr.",
        "Ein Absatz ganz ohne Datum, der interpoliert wird.",
        "Der dritte Absatz nennt 1920 als Jahr.",
    ])
    datieren(con, "p", umfang="alle")
    datierung_setzen(con, ids[1], "1911-05-04", begruendung="aus der Fußnote")
    vorher = _zeile(con, ids[1])

    datieren(con, "p", umfang="alle")

    assert _zeile(con, ids[1]) == vorher, "die Korrektur wurde vom Neulauf verändert"
    assert _zeile(con, ids[1])[3] == "tag", "die Genauigkeit ging verloren"
    a = con.execute("SELECT fundstelle FROM anker WHERE einheit_id = ? "
                    "AND herkunft = 'manuell'", (ids[1],)).fetchone()
    assert a[0] == "aus der Fußnote", "die Begründung ging verloren"


def test_auch_manuell_ueberschreibt_sie_doch(con) -> None:
    ids = _einheiten(con, ["Der Absatz nennt 1900.", "Ein Absatz ohne Datum darin."])
    datieren(con, "p", umfang="alle")
    datierung_setzen(con, ids[1], "1911")
    datieren(con, "p", umfang="auch_manuell")
    assert _zeile(con, ids[1])[4] != "manuell"


def test_eine_korrektur_verschiebt_die_nachbarn(con) -> None:
    """Interpolierte Nachbarn hängen an den Ankern um sie herum."""
    ids = _einheiten(con, [
        "Der erste Absatz nennt 1900 als Jahr.",
        "Ein Absatz ohne Datum, der dazwischenliegt.",
        "Noch einer ohne Datum, auch dazwischen.",
        "Der vierte Absatz nennt 1920 als Jahr.",
    ])
    datieren(con, "p", umfang="alle")
    vorher = {i: _zeile(con, i)[:3] for i in ids}

    datierung_setzen(con, ids[1], "1905")
    datieren(con, "p", umfang="alle")

    nachher = {i: _zeile(con, i)[:3] for i in ids}
    gewechselt = [i for i in ids if vorher[i] != nachher[i]]
    assert ids[2] in gewechselt, "der Nachbar wurde nicht neu interpoliert"


# ── Textänderung ─────────────────────────────────────────────────────────────

def test_textaenderung_loescht_die_fundstellen(con) -> None:
    """Veraltete Zeichenpositionen markieren still die falschen Wörter."""
    ids = _einheiten(con, ["Talaat Pascha sprach 1908 in Saloniki über die Reform."])
    with con:
        akteur = con.execute(
            "INSERT INTO akteur (projekt_id, normalform, typ, status, herkunft) "
            "VALUES ('p','Talaat Pascha','Person','aktiv','gliner')").lastrowid
        con.execute("INSERT INTO einheit_akteur (einheit_id, akteur_id, start, ende) "
                    "VALUES (?, ?, 0, 13)", (ids[0], akteur))

    e = text_setzen(con, ids[0], "Ein völlig anderer Satz über das Jahr 1912.")

    assert e["geaendert"] is True
    assert e["fundstellen_geloescht"] == 1
    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM akteur").fetchone()[0] == 1, \
        "der Akteur selbst darf bleiben — nur seine Fundstelle hier ist hinfällig"


def test_textaenderung_leitet_die_anker_neu_ab(con) -> None:
    ids = _einheiten(con, ["Der Absatz nennt 1908 als Jahr."])
    datieren(con, "p", umfang="alle")
    assert _zeile(con, ids[0])[1] == 1908

    text_setzen(con, ids[0], "Der Absatz nennt jetzt 1912 als Jahr.")
    assert _zeile(con, ids[0])[1] == 1912
    a = con.execute("SELECT jahr, herkunft FROM anker WHERE einheit_id = ?",
                    (ids[0],)).fetchall()
    assert (1912, "text") in [tuple(x) for x in a]
    assert 1908 not in [x[0] for x in a]


def test_textaenderung_zaehlt_die_betroffenen_nachbarn(con) -> None:
    ids = _einheiten(con, [
        "Der erste Absatz nennt 1900 als Jahr.",
        "Ein Absatz ohne Datum dazwischen, der interpoliert wird.",
        "Der dritte Absatz nennt 1920 als Jahr.",
    ])
    datieren(con, "p", umfang="alle")
    e = text_setzen(con, ids[2], "Der dritte Absatz nennt jetzt 1960 als Jahr.")
    assert e["datierung_neu"] >= 2, "der interpolierte Nachbar hätte mitziehen müssen"


def test_gleicher_text_aendert_nichts(con) -> None:
    ids = _einheiten(con, ["Ein Absatz von 1908."])
    e = text_setzen(con, ids[0], "Ein Absatz von 1908.")
    assert e["geaendert"] is False and e["datierung_neu"] == 0


def test_leerer_text_wird_abgewiesen(con) -> None:
    ids = _einheiten(con, ["Ein Absatz."])
    with pytest.raises(DatierungFehler) as exc:
        text_setzen(con, ids[0], "   ")
    assert exc.value.code == "text_leer"


def test_textaenderung_laesst_die_handkorrektur_stehen(con) -> None:
    ids = _einheiten(con, ["Der Absatz nennt 1908.", "Ein Absatz ohne Datum."])
    datieren(con, "p", umfang="alle")
    datierung_setzen(con, ids[1], "1911-05-04", begruendung="aus der Fußnote")
    text_setzen(con, ids[0], "Der Absatz nennt jetzt 1912.")
    assert _zeile(con, ids[1]) == ("1911-05-04", 1911, 1911, "tag", "manuell")


# ── Ausreißer und Verteilung ─────────────────────────────────────────────────

def test_ausreisser_findet_die_zifferndreher(con) -> None:
    """Wie in ber: die Ausreißer kommen nicht aus dem Fließtext.

    anker_im_text nimmt nur plausible Jahreszahlen an — 3012 und 1201 sind
    dort chancenlos. In ber stammen sie aus der Quellennotation
    ('30.07.3012'), die keine Bereichsprüfung kennt. Hier wird derselbe
    Zustand über eine Handkorrektur hergestellt.
    """
    texte = [f"Der Absatz nennt {1990 + i % 20} als Jahr." for i in range(30)]
    texte += ["Ein Absatz mit falschem Erscheinungsdatum.",
              "Und noch einer mit falschem Erscheinungsdatum."]
    ids = _einheiten(con, texte)
    datieren(con, "p", umfang="alle")
    datierung_setzen(con, ids[30], "3012-07-30")
    datierung_setzen(con, ids[31], "1201-11-21")

    a = ausreisser(con, "p")
    assert set(a["einheiten"]) == {ids[30], ids[31]}
    assert a["unten"] == 1400


def test_ohne_ausreisser_bleibt_die_liste_leer(con) -> None:
    _einheiten(con, [f"Der Absatz nennt {1990 + i % 20} als Jahr." for i in range(30)])
    datieren(con, "p", umfang="alle")
    assert ausreisser(con, "p")["einheiten"] == []


def test_breite_streuung_ist_kein_ausreisser(con) -> None:
    """Ein Werk über zwei Jahrhunderte streut breit — das ist kein Fehler.

    Der Quartilsabstand hat genau hier danebengegriffen: er meldete bei
    damaskus 62 und bei osmanisch 40 Einheiten, die alle in Ordnung sind.
    """
    _einheiten(con, [f"Der Absatz nennt {1780 + i * 8} als Jahr." for i in range(28)])
    datieren(con, "p", umfang="alle")
    assert ausreisser(con, "p")["einheiten"] == []


def test_zukunft_ist_auch_ein_ausreisser(con) -> None:
    ids = _einheiten(con, ["Ein Absatz."] * 3)
    datierung_setzen(con, ids[1], "2199")
    assert ausreisser(con, "p")["einheiten"] == [ids[1]]


def test_verteilung_zeigt_das_geratene(con) -> None:
    _einheiten(con, [
        "Der erste Absatz nennt 1900 als Jahr.",
        "Ein Absatz ohne Datum, der interpoliert wird.",
        "Der dritte Absatz nennt 1920 als Jahr.",
    ])
    datieren(con, "p", umfang="alle")
    v = verteilung(con, "p")
    assert v["anzahl"] == 3
    assert v["je_herkunft"]["text"] == 2
    assert v["anzahl_interpoliert"] == 1
    assert v["je_praezision"]["spanne"] == 1
