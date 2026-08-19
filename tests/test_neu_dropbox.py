"""
tests/test_neu_dropbox.py — Pfad-Vereinheitlichung, Anmeldezustand, Riegel

Kein Netz und kein Dropbox-SDK: der Fluss und der Client sind Attrappen.
Geprüft wird, was das System daraus macht.

Ausführen:
  python3 -m pytest tests/test_neu_dropbox.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.ingest import anmeldung as anmelde_dienst  # noqa: E402
from src.neu.ingest import dropbox_anbindung as db  # noqa: E402
from src.neu.ingest.anmeldung import AnmeldungFehler  # noqa: E402
from src.neu.ingest.dienst import IngestFehler, einlesen  # noqa: E402
from src.neu.ingest.kern import RohDatei  # noqa: E402

SCHEMA = ROOT / "schema.sql"


def _db(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        con.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                    "VALUES ('t','2026-01-01','nutzer')")
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p','P',1,'2026-01-01')")
    return con


def _md(name: str, text: str = "Ein Artikel.") -> RohDatei:
    return RohDatei(
        pfad=name,
        inhalt=f"---\ntitle: {Path(name).stem}\npublished: 2026-05-12\n---\n\n{text}\n",
    )


# ── Eine Form für den Pfad ────────────────────────────────────────────────────

@pytest.mark.parametrize("voll,ordner,erwartet", [
    ("/Dropbox_test1/x.md", "/Dropbox_test1", "x.md"),
    ("/Dropbox_test1/unter/x.md", "/Dropbox_test1", "unter/x.md"),
    ("x.md", "/Dropbox_test1", "x.md"),                    # lokaler Weg
    ("unter/x.md", "/Dropbox_test1", "unter/x.md"),
    ("/Dropbox_test1/x.md", "Dropbox_test1", "x.md"),      # ohne führendes /
    ("/Dropbox_test1/x.md", "/dropbox_test1", "x.md"),     # Groß/Klein egal
    ("/Dropbox_test1/x.md", "/Dropbox_test1/", "x.md"),    # abschließendes /
    ("/Anderer/x.md", "/Dropbox_test1", "Anderer/x.md"),   # fremdes Präfix bleibt
])
def test_relativer_pfad(voll, ordner, erwartet):
    assert db.relativer_pfad(voll, ordner) == erwartet


def test_beide_wege_ergeben_denselben_pfad():
    """Der Kern der Sache: lokal und über Dropbox muss dasselbe herauskommen."""
    ueber_dropbox = db.relativer_pfad("/Dropbox_test1/China und die KI.md", "/Dropbox_test1")
    lokal = db.relativer_pfad("China und die KI.md", "/Dropbox_test1")
    assert ueber_dropbox == lokal == "China und die KI.md"


def test_gleichnamige_dateien_in_unterordnern_bleiben_verschieden():
    """Die Krücke der Vorlage — Vergleich nur über den Dateinamen — bricht hier."""
    a = db.relativer_pfad("/O/2025/bericht.md", "/O")
    b = db.relativer_pfad("/O/2026/bericht.md", "/O")
    assert a != b
    assert Path(a).name == Path(b).name       # genau deshalb reicht der Name nicht


@pytest.mark.parametrize("roh,erwartet", [
    ("Dropbox_test1", "/Dropbox_test1"),
    ("/Dropbox_test1", "/Dropbox_test1"),
    ("/Dropbox_test1/", "/Dropbox_test1"),
    ("  /A/B  ", "/A/B"),
    ("", ""),
])
def test_ordner_normalisieren(roh, erwartet):
    assert db.ordner_normalisieren(roh) == erwartet


# ── Anmeldezustand in der Datenbank ───────────────────────────────────────────

def _fluss_attrappe(monkeypatch, refresh="rt-neu"):
    monkeypatch.setattr(db, "anmeldung_beginnen",
                        lambda: ("https://dropbox/auth?state=csrf1", "csrf1", {"s": 1}))
    monkeypatch.setattr(db, "anmeldung_beenden",
                        lambda sitzung, code, state: refresh)


def test_anmeldung_ueberlebt_einen_neustart(tmp_path, monkeypatch):
    """Der Vorgang steht in der Datenbank, nicht im Arbeitsspeicher."""
    _fluss_attrappe(monkeypatch)
    con = _db(tmp_path)
    anmelde_dienst.beginnen(con, "p")
    con.close()

    # Neustart: neue Verbindung, nichts im Speicher
    con = sqlite3.connect(tmp_path / "test.db")
    con.execute("PRAGMA foreign_keys = ON")
    ergebnis = anmelde_dienst.beenden(con, code="c", state="csrf1")

    assert ergebnis == {"projekt_id": "p", "verbunden": True}
    assert con.execute("SELECT dropbox_token FROM projekt WHERE id='p'").fetchone()[0] == "rt-neu"
    # Der Vorgang ist verbraucht.
    assert con.execute("SELECT COUNT(*) FROM anmeldung").fetchone()[0] == 0


def test_token_wird_sofort_geschrieben_nicht_erst_beim_formular(tmp_path, monkeypatch):
    _fluss_attrappe(monkeypatch)
    con = _db(tmp_path)
    anmelde_dienst.beginnen(con, "p")
    anmelde_dienst.beenden(con, code="c", state="csrf1")
    # Kein zweiter Schritt nötig: der Stand steht schon.
    assert anmelde_dienst.verbindung(con, "p")["verbunden"] is True


def test_unbekannte_rueckleitung_meldet_klar(tmp_path, monkeypatch):
    _fluss_attrappe(monkeypatch)
    con = _db(tmp_path)
    with pytest.raises(AnmeldungFehler) as exc:
        anmelde_dienst.beenden(con, code="c", state="gibtsnicht")
    assert exc.value.code == "anmeldung_unbekannt"
    assert "neu beginnen" in str(exc.value)


def test_gescheiterter_tausch_verbraucht_den_vorgang_nicht(tmp_path, monkeypatch):
    """Ein Netzfehler soll keinen zweiten Versuch verhindern."""
    _fluss_attrappe(monkeypatch)
    con = _db(tmp_path)
    anmelde_dienst.beginnen(con, "p")

    def wirft(sitzung, code, state):
        raise RuntimeError("Netz weg")

    monkeypatch.setattr(db, "anmeldung_beenden", wirft)
    with pytest.raises(RuntimeError):
        anmelde_dienst.beenden(con, code="c", state="csrf1")
    assert con.execute("SELECT COUNT(*) FROM anmeldung").fetchone()[0] == 1

    _fluss_attrappe(monkeypatch)
    anmelde_dienst.beenden(con, code="c", state="csrf1")
    assert anmelde_dienst.verbindung(con, "p")["verbunden"] is True


def test_abgelaufene_vorgaenge_werden_aufgeraeumt(tmp_path, monkeypatch):
    _fluss_attrappe(monkeypatch)
    con = _db(tmp_path)
    with con:
        con.execute("INSERT INTO anmeldung (csrf, projekt_id, sitzung, begonnen_am) "
                    "VALUES ('alt','p','{}','2020-01-01T00:00:00+00:00')")
    anmelde_dienst.beginnen(con, "p")
    verbleibend = [z[0] for z in con.execute("SELECT csrf FROM anmeldung")]
    assert verbleibend == ["csrf1"]


def test_verbindung_kommt_aus_der_spalte_nicht_aus_einer_datei(tmp_path):
    con = _db(tmp_path)
    assert anmelde_dienst.verbindung(con, "p")["verbunden"] is False
    with con:
        con.execute("UPDATE projekt SET dropbox_token='rt' WHERE id='p'")
    assert anmelde_dienst.verbindung(con, "p")["verbunden"] is True


def test_ordner_wird_normalisiert_gespeichert(tmp_path):
    con = _db(tmp_path)
    stand = anmelde_dienst.ordner_setzen(con, "p", "Dropbox_test1/")
    assert stand["ordner"] == "/Dropbox_test1"
    assert con.execute(
        "SELECT dropbox_ordner FROM projekt WHERE id='p'").fetchone()[0] == "/Dropbox_test1"


# ── Der Riegel ────────────────────────────────────────────────────────────────

def test_zweiter_lauf_legt_keine_zweite_quelle_an(tmp_path):
    con = _db(tmp_path)
    dateien = [_md("a.md"), _md("b.md")]

    erst = einlesen(con, "p", "/O", "pressesammlung", dateien=dateien)
    assert erst.fortgesetzt is False
    assert erst.anzahl_neu == 2

    zweit = einlesen(con, "p", "/O", "pressesammlung", dateien=dateien)
    assert zweit.fortgesetzt is True
    assert zweit.anzahl_neu == 0
    assert zweit.anzahl_uebersprungen == 2
    assert zweit.quelle_id == erst.quelle_id

    assert con.execute("SELECT COUNT(*) FROM quelle").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM einheit").fetchone()[0] == 2


def test_neue_dateien_werden_angehaengt(tmp_path):
    con = _db(tmp_path)
    einlesen(con, "p", "/O", "pressesammlung", dateien=[_md("a.md"), _md("b.md")])
    zweit = einlesen(con, "p", "/O", "pressesammlung",
                     dateien=[_md("a.md"), _md("b.md"), _md("c.md")])

    assert (zweit.anzahl_neu, zweit.anzahl_uebersprungen) == (1, 2)
    positionen = [z[0] for z in con.execute(
        "SELECT position FROM einheit ORDER BY position")]
    assert positionen == [1, 2, 3]      # lückenlos weitergezählt
    assert con.execute(
        "SELECT quellpfad FROM einheit WHERE position=3").fetchone()[0] == "c.md"


def test_geaenderte_datei_wird_gemeldet_nicht_geraten(tmp_path):
    con = _db(tmp_path)
    einlesen(con, "p", "/O", "pressesammlung", dateien=[_md("a.md", "Alt.")])
    zweit = einlesen(con, "p", "/O", "pressesammlung", dateien=[_md("a.md", "Neu.")])

    assert zweit.geaenderte_dateien == ["a.md"]
    assert zweit.anzahl_neu == 0
    # Der Bestand bleibt unangetastet, solange nicht entschieden ist, was gilt.
    assert "Alt." in con.execute("SELECT text FROM einheit").fetchone()[0]


def test_lokal_und_dropbox_ergeben_keine_doubletten(tmp_path):
    """Derselbe Ordner, zwei Wege, ein Bestand."""
    con = _db(tmp_path)
    lokal = einlesen(con, "p", "/Users/jk/Dropbox/Apps/ber-chronik/Dropbox_test1",
                     "pressesammlung", dateien=[_md("a.md"), _md("b.md")])
    ueber_dropbox = einlesen(con, "p", "/Dropbox_test1", "pressesammlung",
                             dateien=[_md("a.md"), _md("b.md")])

    assert ueber_dropbox.quelle_id == lokal.quelle_id
    assert ueber_dropbox.fortgesetzt is True
    assert ueber_dropbox.anzahl_uebersprungen == 2
    assert con.execute("SELECT COUNT(*) FROM quelle").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM einheit").fetchone()[0] == 2
    assert ueber_dropbox.hinweise and "fortgeführt" in ueber_dropbox.hinweise[0]
    # Der zuletzt benutzte Weg steht an der Quelle.
    assert con.execute("SELECT pfad FROM quelle").fetchone()[0] == "/Dropbox_test1"


def test_riegel_steht_auch_im_schema(tmp_path):
    con = _db(tmp_path)
    einlesen(con, "p", "/O", "pressesammlung", dateien=[_md("a.md")])
    quelle = con.execute("SELECT id FROM quelle").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute(
                "INSERT INTO einheit (quelle_id, position, typ, text, quellpfad) "
                "VALUES (?, 99, 'content', 'x', 'a.md')", (quelle,))


def test_docx_wird_nicht_fortgefuehrt(tmp_path):
    """Ohne Dateibezug lässt sich nichts überspringen — also melden."""
    con = _db(tmp_path)
    with con:
        con.execute("INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
                    "VALUES ('q','p','literaturexzerpt','/a.docx','2026-01-01')")
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                    "VALUES ('q', 1, 'content', 'Text')")
    with pytest.raises(IngestFehler) as exc:
        einlesen(con, "p", "/a.docx", "literaturexzerpt",
                 dateien=[_md("a.md")])
    assert exc.value.code == "quelle_gibt_es_schon"


def test_verschiedene_projekte_teilen_keine_quelle(tmp_path):
    con = _db(tmp_path)
    with con:
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('q2','Q',1,'2026-01-01')")
    einlesen(con, "p", "/O", "pressesammlung", dateien=[_md("a.md")])
    zweit = einlesen(con, "q2", "/O", "pressesammlung", dateien=[_md("a.md")])
    assert zweit.fortgesetzt is False
    assert con.execute("SELECT COUNT(*) FROM quelle").fetchone()[0] == 2
