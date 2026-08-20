"""
tests/test_neu_akteure_flaeche.py — was die Akteursfläche vom Dienst braucht

Gegen eine echte SQLite-Datei, ohne GLiNER und ohne Embedding: die Akteure
werden von Hand angelegt, die Zuordnung leitet der Dienst aus Normalform und
Aliasen ab. Geprüft wird das, was die alte Fläche nicht konnte — Trefferzahlen
je Name, Herauslösen, eine einzelne Fundstelle, beliebige Akteure verschmelzen.

Ausführen:
  python3 -m pytest tests/test_neu_akteure_flaeche.py -v
"""

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.akteure.dienst import (  # noqa: E402
    AkteurFehler,
    akteur_aendern,
    akteure_verschmelzen,
    alias_herausloesen,
    anlegen,
    fundstelle_loeschen,
    fundstellen_je_einheit,
    liste,
)

SCHEMA = ROOT / "schema.sql"

# Der Klumpen aus damaskus im Kleinen: ein Name, unter dem mehrere Personen und
# gewöhnliche Substantive stecken.
TEXTE = [
    "Mustafa al Hallaq sprach mit den leuten über die Reform.",
    "Die leute kamen, und zahrawi widersprach den leuten deutlich.",
    "zahrawi und die schüler blieben; die leute gingen.",
    "Auch zahrawi war da, dazu einige schüler aus der Stadt.",
]


@pytest.fixture
def con(tmp_path, monkeypatch):
    c = sqlite3.connect(tmp_path / "test.db")
    c.executescript(SCHEMA.read_text(encoding="utf-8"))
    c.execute("PRAGMA foreign_keys = ON")
    with c:
        c.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                  "VALUES ('t','2026-01-01','nutzer')")
        c.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                  "VALUES ('p','P',1,'2026-01-01')")
        c.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                  "VALUES ('q','p','literaturexzerpt','2026-01-01')")
        for n, t in enumerate(TEXTE, start=1):
            c.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                      "VALUES ('q', ?, 'content', ?)", (n, t))
    monkeypatch.setenv("NEU_DB", str(tmp_path / "test.db"))
    yield c
    c.close()


def _klumpen(con) -> dict:
    """Ein Akteur, der nach etwas heißt, das er kaum ist."""
    return anlegen(con, "p", "Mustafa al Hallaq", "Person",
                   ["leute", "schüler", "zahrawi"])


def _finde(con, name: str) -> dict:
    return next(a for a in liste(con, "p")["akteure"] if a["normalform"] == name)


# ── Was die alte Fläche nicht zeigen konnte ──────────────────────────────────

def test_trefferzahlen_je_name(con) -> None:
    """Nicht welche Namen ein Akteur trägt, sondern welcher die Arbeit tut."""
    _klumpen(con)
    a = _finde(con, "Mustafa al Hallaq")
    zahlen = {n["name"]: n["anzahl"] for n in a["namen"]}
    assert zahlen["leute"] == 2          # 'leuten' zählt nicht — Wortgrenze
    assert zahlen["zahrawi"] == 3
    assert zahlen["schüler"] == 2
    assert zahlen["Mustafa al Hallaq"] == 1
    assert a["anzahl_fundstellen"] == 8


def test_namen_stehen_nach_haeufigkeit(con) -> None:
    _klumpen(con)
    a = _finde(con, "Mustafa al Hallaq")
    assert [n["anzahl"] for n in a["namen"]] == sorted(
        (n["anzahl"] for n in a["namen"]), reverse=True)


def test_klumpen_wird_erkannt(con) -> None:
    """Viele Namen UND der eigene trifft fast nie — beides muss zutreffen."""
    with con:
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                    "VALUES ('q', 90, 'content', 'leute leute leute leute leute leute')")
    anlegen(con, "p", "Mustafa al Hallaq", "Person",
            ["leute", "schüler", "zahrawi", "kollegen", "konterrev"])
    a = _finde(con, "Mustafa al Hallaq")
    assert a["ist_klumpen"] is True
    assert a["anteil_normalform"] < 0.1
    assert liste(con, "p")["anzahl_klumpen"] == 1


def test_wenige_aliase_sind_kein_klumpen(con) -> None:
    """Zwei Namen sind normal, auch wenn der zweite öfter trifft."""
    anlegen(con, "p", "Mustafa al Hallaq", "Person", ["leute"])
    assert _finde(con, "Mustafa al Hallaq")["ist_klumpen"] is False


def test_markierungen_kommen_mit_positionen(con) -> None:
    """Gelesen, nicht gesucht: die Stelle, die der Dienst zugeordnet hat."""
    _klumpen(con)
    je_einheit = fundstellen_je_einheit(con, "p")
    erste = con.execute("SELECT id, text FROM einheit WHERE position = 1").fetchone()
    stellen = je_einheit[erste[0]]
    # Die Positionen zeigen auf genau das, was zugeordnet wurde — 'leuten' in
    # derselben Zeile ist keine Fundstelle, weil die Wortgrenze fehlt.
    assert [erste[1][m["start"]:m["ende"]] for m in stellen] == ["Mustafa al Hallaq"]


# ── Alias entfernen nimmt seine Fundstellen mit ──────────────────────────────

def test_alias_entfernen_nimmt_die_fundstellen_mit(con) -> None:
    a = _klumpen(con)
    assert a["anzahl_fundstellen"] == 8
    nachher = akteur_aendern(con, a["id"], aliase=["schüler", "zahrawi"])
    assert nachher["anzahl_fundstellen"] == 6          # die zwei 'leute' sind weg
    assert "leute" not in [n["name"] for n in _finde(con, "Mustafa al Hallaq")["namen"]]


# ── Herauslösen ─────────────────────────────────────────────────────────────

def test_herausloesen_macht_einen_eigenen_akteur(con) -> None:
    a = _klumpen(con)
    e = alias_herausloesen(con, a["id"], "zahrawi")

    assert e["neu"]["normalform"] == "zahrawi"
    assert e["neu"]["typ"] == "Person"            # der Typ des alten
    assert e["neu"]["herkunft"] == "manuell"
    assert e["neu"]["anzahl_fundstellen"] == 3
    assert e["quelle"]["anzahl_fundstellen"] == 5  # 8 − 3
    assert "zahrawi" not in e["quelle"]["aliase"]


def test_herausloesen_verlangt_einen_vorhandenen_alias(con) -> None:
    a = _klumpen(con)
    with pytest.raises(AkteurFehler) as exc:
        alias_herausloesen(con, a["id"], "gibtsnicht")
    assert exc.value.code == "alias_nicht_gefunden"


def test_herausloesen_kollidiert_nicht(con) -> None:
    a = _klumpen(con)
    anlegen(con, "p", "zahrawi", "Person")
    with pytest.raises(AkteurFehler) as exc:
        alias_herausloesen(con, a["id"], "zahrawi")
    assert exc.value.code == "normalform_belegt"


def test_herausloesen_macht_beide_manuell(con) -> None:
    """Ein Mensch hat das getrennt — der nächste Lauf fasst es nicht an."""
    a = _klumpen(con)
    e = alias_herausloesen(con, a["id"], "zahrawi")
    assert e["quelle"]["herkunft"] == "manuell"
    assert e["neu"]["herkunft"] == "manuell"


# ── Eine einzelne Fundstelle ────────────────────────────────────────────────

def test_fundstelle_loeschen_laesst_den_akteur_stehen(con) -> None:
    """Im Annotator heißt Entfernen: nur diese Stelle, nicht der Akteur.

    Die alte Fläche löschte an dieser Stelle den ganzen Akteur — sie hatte
    keine Fundstellen als Gegenstände.
    """
    a = _klumpen(con)
    stelle = con.execute(
        "SELECT id FROM einheit_akteur WHERE akteur_id = ? LIMIT 1", (a["id"],)
    ).fetchone()[0]

    e = fundstelle_loeschen(con, stelle)
    assert e["anzahl_fundstellen"] == 7
    assert e["wortlaut"]
    assert con.execute("SELECT COUNT(*) FROM akteur").fetchone()[0] == 1
    assert "leute" in _finde(con, "Mustafa al Hallaq")["aliase"]


def test_unbekannte_fundstelle(con) -> None:
    with pytest.raises(AkteurFehler) as exc:
        fundstelle_loeschen(con, 9999)
    assert exc.value.code == "fundstelle_nicht_gefunden"


# ── Beliebige Akteure verschmelzen ──────────────────────────────────────────

def test_zwei_beliebige_verschmelzen(con) -> None:
    """Kein vorgeschlagenes Paar nötig, und der Aufrufer wählt die Normalform."""
    a = anlegen(con, "p", "zahrawi", "Person")
    b = anlegen(con, "p", "Abd al-Hamid al-Zahrawi", "Person")
    e = akteure_verschmelzen(con, [a["id"], b["id"]], behalten_id=b["id"])

    assert e["normalform"] == "Abd al-Hamid al-Zahrawi"
    assert "zahrawi" in e["aliase"]
    assert e["aufgeloeste_akteure"] == [a["id"]]
    assert con.execute("SELECT COUNT(*) FROM akteur").fetchone()[0] == 1


def test_verschmelzen_raeumt_die_kandidaten_weg(con) -> None:
    """Danach zeigt kein Paar mehr ins Leere — die Fläche muss nicht aufgeben.

    Die alte sagte 'Neu laden um aktualisierte Kandidaten zu berechnen', weil
    ihre Paare auf Array-Plätze zeigten und ein splice alle darüber verschob.
    """
    a = anlegen(con, "p", "zahrawi", "Person")
    b = anlegen(con, "p", "Abd al-Hamid al-Zahrawi", "Person")
    c = anlegen(con, "p", "schüler", "Person")
    with con:
        for x, y in ((a["id"], b["id"]), (a["id"], c["id"]), (b["id"], c["id"])):
            con.execute(
                "INSERT INTO verschmelzungskandidat (projekt_id, akteur_a_id, "
                "akteur_b_id, grund, mass, berechnet_am) "
                "VALUES ('p', ?, ?, 'aehnlichkeit', 0.9, '2026-01-01')",
                (min(x, y), max(x, y)))

    akteure_verschmelzen(con, [a["id"], b["id"]], behalten_id=b["id"])

    verwaist = con.execute(
        "SELECT COUNT(*) FROM verschmelzungskandidat k "
        "WHERE NOT EXISTS (SELECT 1 FROM akteur x WHERE x.id = k.akteur_a_id) "
        "   OR NOT EXISTS (SELECT 1 FROM akteur y WHERE y.id = k.akteur_b_id)"
    ).fetchone()[0]
    assert verwaist == 0
    assert con.execute("SELECT COUNT(*) FROM verschmelzungskandidat").fetchone()[0] == 0


def test_verschmelzen_ueber_projektgrenzen_wird_abgewiesen(con) -> None:
    with con:
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p2','P2',1,'2026-01-01')")
    a = anlegen(con, "p", "zahrawi", "Person")
    b = anlegen(con, "p2", "zahrawi", "Person")
    with pytest.raises(AkteurFehler) as exc:
        akteure_verschmelzen(con, [a["id"], b["id"]], behalten_id=a["id"])
    assert exc.value.code == "projekte_verschieden"


# ── Anlegen ─────────────────────────────────────────────────────────────────

def test_anlegen_ordnet_sofort_zu(con) -> None:
    e = anlegen(con, "p", "zahrawi", "Person")
    assert e["anzahl_fundstellen"] == 3
    assert e["herkunft"] == "manuell"


def test_anlegen_kollidiert_nicht(con) -> None:
    anlegen(con, "p", "zahrawi", "Person")
    with pytest.raises(AkteurFehler) as exc:
        anlegen(con, "p", "ZAHRAWI", "Person")
    assert exc.value.code == "normalform_belegt"


def test_abgelehnter_zeigt_auf_nichts(con) -> None:
    a = _klumpen(con)
    akteur_aendern(con, a["id"], status="abgelehnt")
    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 0
    assert _finde(con, "Mustafa al Hallaq")["status"] == "abgelehnt"
    assert liste(con, "p")["anzahl_abgelehnt"] == 1
