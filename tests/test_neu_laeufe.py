"""
tests/test_neu_laeufe.py — lange Schritte anstoßen und ihren Stand abfragen

Kein echter Schritt: die Arbeit ist eine Attrappe. Geprüft wird das Muster —
Zeile anlegen, Stand melden, Ende festhalten, Fehler festhalten.

Ausführen:
  python3 -m pytest tests/test_neu_laeufe.py -v
"""

import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu import laeufe  # noqa: E402
from src.neu.laeufe import LaufFehler  # noqa: E402
from src.neu.kategorien import verwaltung  # noqa: E402
from src.neu.kategorien.verwaltung import KategorieFehler  # noqa: E402

SCHEMA = ROOT / "schema.sql"


@pytest.fixture
def db(tmp_path, monkeypatch):
    pfad = tmp_path / "test.db"
    con = sqlite3.connect(pfad)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    with con:
        con.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                    "VALUES ('t','2026-01-01','nutzer')")
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p','P',1,'2026-01-01')")
        con.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                    "VALUES ('q','p','literaturexzerpt','2026-01-01')")
        for i in range(1, 4):
            con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                        "VALUES ('q', ?, 'content', ?)", (i, f"Text {i}"))
    con.close()
    monkeypatch.setenv("NEU_DB", str(pfad))
    con = sqlite3.connect(pfad)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    yield con
    con.close()


def _warte(con, lauf_id, sekunden=5.0):
    """Wartet, bis der Lauf nicht mehr 'laeuft' — wie es die Fläche tut."""
    ende = time.time() + sekunden
    while time.time() < ende:
        s = laeufe.stand(con, lauf_id)
        if s["status"] != "laeuft":
            return s
        time.sleep(0.05)
    raise AssertionError(f"Lauf {lauf_id} wurde nicht fertig")


# ── Der Weg ───────────────────────────────────────────────────────────────────

def test_lauf_gibt_sofort_eine_kennung(db):
    los = time.time()

    def arbeit(con, lauf_id):
        time.sleep(0.3)
        with con:
            con.execute("UPDATE lauf SET status='erfolg', beendet_am='x' WHERE id=?",
                        (lauf_id,))

    lauf_id = laeufe.starten("p", "taxonomie", {"phase": "beginnt"}, arbeit)
    # Der Aufruf wartet nicht auf die Arbeit.
    assert time.time() - los < 0.2
    assert laeufe.stand(db, lauf_id)["status"] == "laeuft"
    assert _warte(db, lauf_id)["status"] == "erfolg"


def test_fortschritt_ist_waehrenddessen_abfragbar(db):
    """Der Stand steht in der Zeile, nicht in einer offenen Verbindung."""
    gesehen = []

    def arbeit(con, lauf_id):
        for runde in (1, 2, 3):
            laeufe.fortschritt(con, lauf_id, phase="llm", runde=runde, runden_max=3)
            time.sleep(0.1)
        with con:
            con.execute("UPDATE lauf SET status='erfolg', beendet_am='x' WHERE id=?",
                        (lauf_id,))

    lauf_id = laeufe.starten("p", "taxonomie", {"phase": "beginnt"}, arbeit)
    ende = time.time() + 5
    while time.time() < ende:
        s = laeufe.stand(db, lauf_id)
        if s["parameter"].get("runde"):
            gesehen.append(s["parameter"]["runde"])
        if s["status"] != "laeuft":
            break
        time.sleep(0.03)

    assert gesehen, "kein Zwischenstand gesehen"
    assert max(gesehen) == 3


def test_fortschritt_ergaenzt_statt_zu_ersetzen(db):
    lauf_id = laeufe.anlegen(db, "p", "taxonomie", {"warm_start": False})
    laeufe.fortschritt(db, lauf_id, phase="llm", runde=2)
    p = laeufe.stand(db, lauf_id)["parameter"]
    assert p == {"warm_start": False, "phase": "llm", "runde": 2}


def test_ein_fehler_landet_in_der_zeile(db):
    def arbeit(con, lauf_id):
        raise RuntimeError("Modell weg")

    lauf_id = laeufe.starten("p", "taxonomie", {}, arbeit)
    s = _warte(db, lauf_id)
    assert s["status"] == "fehler"
    assert "Modell weg" in s["fehler"]
    assert s["parameter"]["fehlerart"] == "RuntimeError"
    assert s["beendet_am"] is not None


def test_zwei_gleiche_schritte_zugleich_werden_abgewiesen(db):
    def arbeit(con, lauf_id):
        time.sleep(0.4)
        with con:
            con.execute("UPDATE lauf SET status='erfolg', beendet_am='x' WHERE id=?",
                        (lauf_id,))

    erster = laeufe.starten("p", "taxonomie", {}, arbeit)
    with pytest.raises(LaufFehler) as exc:
        laeufe.starten("p", "taxonomie", {}, arbeit)
    assert exc.value.code == "lauf_schon_unterwegs"
    assert str(erster) in str(exc.value)
    _warte(db, erster)


def test_verschiedene_schritte_duerfen_gleichzeitig(db):
    def arbeit(con, lauf_id):
        time.sleep(0.2)
        with con:
            con.execute("UPDATE lauf SET status='erfolg', beendet_am='x' WHERE id=?",
                        (lauf_id,))

    a = laeufe.starten("p", "taxonomie", {}, arbeit)
    b = laeufe.starten("p", "klassifikation", {}, arbeit)
    assert a != b
    _warte(db, a)
    _warte(db, b)


def test_unbekannter_lauf(db):
    with pytest.raises(LaufFehler) as exc:
        laeufe.stand(db, 999)
    assert exc.value.code == "lauf_nicht_gefunden"


# ── Kategorien pflegen ────────────────────────────────────────────────────────

def test_angelegte_kategorie_ist_manuell(db):
    k = verwaltung.anlegen(db, "p", "Kosten", "Geld und Budget", ["preis", "euro"])
    assert k["herkunft"] == "manuell"
    assert k["schlagworte"] == ["preis", "euro"]


def test_aendern_macht_eine_vorschlagskategorie_manuell(db):
    with db:
        db.execute("INSERT INTO kategorie (projekt_id, name, beschreibung, schlagworte, "
                   "herkunft) VALUES ('p','Alt','B','x','vorschlag')")
    kid = db.execute("SELECT id FROM kategorie").fetchone()[0]
    k = verwaltung.aendern(db, kid, name="Neu")
    assert (k["name"], k["herkunft"]) == ("Neu", "manuell")


def test_doppelter_name_wird_abgewiesen(db):
    verwaltung.anlegen(db, "p", "Kosten")
    with pytest.raises(KategorieFehler) as exc:
        verwaltung.anlegen(db, "p", "Kosten")
    assert exc.value.code == "kategorie_gibt_es_schon"


def test_loeschen_laesst_die_einheiten_stehen(db):
    k = verwaltung.anlegen(db, "p", "Kosten")
    with db:
        db.execute("UPDATE einheit SET kategorie_id = ?, kategorie_herkunft='bge'", (k["id"],))
    ergebnis = verwaltung.loeschen(db, k["id"])

    assert ergebnis["einheiten_ohne_kategorie"] == 3
    assert db.execute("SELECT COUNT(*) FROM einheit").fetchone()[0] == 3
    assert db.execute(
        "SELECT COUNT(*) FROM einheit WHERE kategorie_id IS NULL").fetchone()[0] == 3
    # Die Herkunft bleibt stehen: die Einheit gilt weiter als behandelt.
    assert db.execute(
        "SELECT kategorie_herkunft FROM einheit LIMIT 1").fetchone()[0] == "bge"


def test_liste_zaehlt_handkorrekturen(db):
    k = verwaltung.anlegen(db, "p", "Kosten")
    with db:
        db.execute("UPDATE einheit SET kategorie_id = ?, kategorie_herkunft='manuell' "
                   "WHERE position = 1", (k["id"],))
    stand = verwaltung.liste(db, "p")
    assert stand["anzahl_manuell_zugeordnet"] == 1
    assert stand["anzahl_ohne_kategorie"] == 2
    assert stand["kategorien"][0]["anzahl_einheiten"] == 1
