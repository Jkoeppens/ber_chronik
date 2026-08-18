"""
tests/test_neu_akteure_dienst.py — src/neu/akteure/dienst.py

Jeder Test baut seine eigene Datenbank aus schema.sql in einem tmp_path.
data/neu.db und data/projects.db werden nicht angefasst.

Erkenner und Embedding sind Attrappen: kein GLiNER, kein sentence-transformers,
kein Netz. Geprüft wird, was der Dienst mit dem Ergebnis macht.

Ausführen:
  python3 -m pytest tests/test_neu_akteure_dienst.py -v
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.akteure.dienst import (  # noqa: E402
    AkteurFehler,
    akteur_aendern,
    akteure_verschmelzen,
    duplikatskandidaten,
    erkennen,
)

SCHEMA = ROOT / "schema.sql"


def _db(tmp_path: Path, texte: list[str]) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        con.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                    "VALUES ('t','2026-01-01','nutzer')")
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p','P',1,'2026-01-01')")
        con.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                    "VALUES ('q','p','literaturexzerpt','2026-01-01')")
        for i, text in enumerate(texte):
            con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                        "VALUES ('q', ?, 'content', ?)", (i, text))
    return con


def _erkenner(namen_je_label: dict[str, str]):
    """Attrappe: meldet jeden Namen, der im Textstück vorkommt."""
    def vorhersage(stueck, labels, schwelle):
        return [{"text": name, "label": label}
                for name, label in namen_je_label.items() if name in stueck]
    return vorhersage


def _embed_getrennt(texte):
    """Attrappe: jeder Name bekommt eine eigene Achse — nichts wird ähnlich."""
    embs = np.zeros((len(texte), max(len(texte), 1)), dtype=np.float32)
    for i in range(len(texte)):
        embs[i, i] = 1.0
    return embs


def _lauf(con, **kwargs):
    return erkennen(
        con, "p",
        vorhersage=kwargs.pop("vorhersage", _erkenner({"Enver": "Person"})),
        embed=kwargs.pop("embed", _embed_getrennt),
        schwelle=kwargs.pop("schwelle", 0.92),
        embedding_modell="attrappe", gliner_modell="attrappe",
        **kwargs,
    )


# ── Der Lauf ──────────────────────────────────────────────────────────────────

def test_erkennen_legt_akteure_und_fundstellen_an(tmp_path):
    con = _db(tmp_path, ["Enver kam 1908 an.", "Später sprach Enver in Damaskus."])
    ergebnis = _lauf(con, vorhersage=_erkenner(
        {"Enver": "Person", "Damaskus": "geographischer Ort"}
    ))

    assert ergebnis.status == "erfolg"
    assert ergebnis.anzahl_neu == 2
    assert ergebnis.anzahl_zuordnungen == 3   # Enver zweimal, Damaskus einmal
    assert ergebnis.anzahl_einheiten_mit_akteur == 2
    assert ergebnis.anzahl_je_typ == {"Person": 1, "Ort": 1}

    zeilen = con.execute(
        "SELECT normalform, typ, status, herkunft FROM akteur ORDER BY normalform"
    ).fetchall()
    assert zeilen == [("Damaskus", "Ort", "aktiv", "gliner"),
                      ("Enver", "Person", "aktiv", "gliner")]


def test_fundstellen_zeigen_auf_den_namen(tmp_path):
    text = "Im Jahr 1908 sprach Enver in Damaskus."
    con = _db(tmp_path, [text])
    _lauf(con)
    start, ende = con.execute(
        "SELECT start, ende FROM einheit_akteur"
    ).fetchone()
    assert text[start:ende] == "Enver"


def test_lauf_zeile_wird_geschrieben(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    ergebnis = _lauf(con)
    zeile = con.execute(
        "SELECT schritt, status, beendet_am IS NOT NULL FROM lauf WHERE id = ?",
        (ergebnis.lauf_id,),
    ).fetchone()
    assert zeile == ("akteure", "erfolg", 1)


def test_zweiter_lauf_ergibt_dasselbe(tmp_path):
    con = _db(tmp_path, ["Enver kam an.", "Enver ging."])

    def zustand():
        return (
            con.execute("SELECT normalform, typ, status, herkunft FROM akteur "
                        "ORDER BY normalform").fetchall(),
            con.execute("SELECT e.position, a.normalform, ea.start, ea.ende "
                        "FROM einheit_akteur ea "
                        "JOIN akteur a ON a.id = ea.akteur_id "
                        "JOIN einheit e ON e.id = ea.einheit_id "
                        "ORDER BY e.position, a.normalform, ea.start").fetchall(),
        )

    _lauf(con)
    erster = zustand()
    _lauf(con)
    assert zustand() == erster


def test_unbekanntes_label_wird_gemeldet(tmp_path):
    con = _db(tmp_path, ["Die Kritik erschien."])
    ergebnis = _lauf(con, vorhersage=_erkenner({"Kritik": "Werk"}))
    assert ergebnis.unbekannte_labels == {"Werk": 1}
    assert con.execute("SELECT typ FROM akteur").fetchone()[0] is None


def test_projekt_ohne_einheiten(tmp_path):
    con = _db(tmp_path, [])
    with pytest.raises(AkteurFehler) as exc:
        _lauf(con)
    assert exc.value.code == "keine_einheiten"


def test_unbekanntes_projekt(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    with pytest.raises(AkteurFehler) as exc:
        erkennen(con, "gibt-es-nicht", vorhersage=_erkenner({}),
                 embed=_embed_getrennt, schwelle=0.92)
    assert exc.value.code == "projekt_nicht_gefunden"


def test_fehlgeschlagener_lauf_hinterlaesst_eine_fehlerzeile(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])

    def kaputt(stueck, labels, schwelle):
        raise RuntimeError("Modell weg")

    with pytest.raises(RuntimeError):
        _lauf(con, vorhersage=kaputt)
    assert con.execute("SELECT status FROM lauf").fetchall() == [("fehler",)]


# ── Handkorrekturen überleben ─────────────────────────────────────────────────

def test_von_hand_angelegter_akteur_ueberlebt_den_neulauf(tmp_path):
    con = _db(tmp_path, ["Enver traf Talat in Damaskus."])
    with con:
        con.execute("INSERT INTO akteur (projekt_id, normalform, typ, status, herkunft) "
                    "VALUES ('p','Talat Pascha','Person','aktiv','manuell')")
        con.execute("INSERT INTO akteur_alias (akteur_id, alias) VALUES (1,'Talat')")

    ergebnis = _lauf(con)

    zeile = con.execute(
        "SELECT normalform, typ, status, herkunft FROM akteur WHERE id = 1"
    ).fetchone()
    assert zeile == ("Talat Pascha", "Person", "aktiv", "manuell")
    assert [z[0] for z in con.execute(
        "SELECT alias FROM akteur_alias WHERE akteur_id = 1")] == ["Talat"]
    assert ergebnis.anzahl_manuell == 1
    # Und er ist zugeordnet: sein Alias steht im Text.
    assert con.execute(
        "SELECT COUNT(*) FROM einheit_akteur WHERE akteur_id = 1"
    ).fetchone()[0] == 1


def test_abgelehnter_akteur_wird_beim_neulauf_uebersprungen(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    with con:
        con.execute("INSERT INTO akteur (projekt_id, normalform, typ, status, herkunft) "
                    "VALUES ('p','Enver','Person','abgelehnt','manuell')")

    ergebnis = _lauf(con)

    assert ergebnis.anzahl_neu == 0
    assert ergebnis.anzahl_abgelehnt == 1
    # Die abgelehnte Zeile bleibt und zeigt auf nichts.
    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 0


def test_ablehnung_loest_auch_alte_zuordnungen(tmp_path):
    """Ein abgelehnter Akteur zeigt auf nichts — auch nicht aus einem Vorlauf."""
    con = _db(tmp_path, ["Enver kam an."])
    _lauf(con)
    akteur_id = con.execute("SELECT id FROM akteur").fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 1

    # Ablehnung an der Datenbank, wie sie aus einem früheren Bestand käme
    with con:
        con.execute("UPDATE akteur SET status='abgelehnt', herkunft='manuell' "
                    "WHERE id = ?", (akteur_id,))
    _lauf(con)

    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 0


def test_fund_auf_einem_handnamen_wird_nicht_geschrieben(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    with con:
        con.execute("INSERT INTO akteur (projekt_id, normalform, typ, status, herkunft) "
                    "VALUES ('p','Enver','Organisation','aktiv','manuell')")

    ergebnis = _lauf(con)

    assert ergebnis.verdraengt_von_manuell == ["Enver"]
    # Der von Hand gesetzte Typ bleibt stehen.
    assert con.execute("SELECT typ, herkunft FROM akteur").fetchall() == [
        ("Organisation", "manuell")
    ]


# ── PATCH ─────────────────────────────────────────────────────────────────────

def test_patch_macht_den_akteur_manuell(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    _lauf(con)
    akteur_id = con.execute("SELECT id FROM akteur").fetchone()[0]

    ergebnis = akteur_aendern(con, akteur_id, typ="Organisation")

    assert ergebnis["herkunft"] == "manuell"
    assert ergebnis["typ"] == "Organisation"


def test_neuer_alias_zieht_die_zuordnung_sofort_nach(tmp_path):
    con = _db(tmp_path, ["Enver kam an.", "Der Pascha ging."])
    _lauf(con)
    akteur_id = con.execute("SELECT id FROM akteur").fetchone()[0]
    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 1

    ergebnis = akteur_aendern(con, akteur_id, aliase=["Pascha"])

    # Heute läuft match_entities nach dem Editor nicht — hier schon.
    assert ergebnis["anzahl_fundstellen"] == 2


def test_patch_auf_abgelehnt_loest_die_zuordnung(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    _lauf(con)
    akteur_id = con.execute("SELECT id FROM akteur").fetchone()[0]

    akteur_aendern(con, akteur_id, status="abgelehnt")

    assert con.execute("SELECT COUNT(*) FROM einheit_akteur").fetchone()[0] == 0


def test_patch_auf_einen_belegten_namen_wird_abgewiesen(tmp_path):
    con = _db(tmp_path, ["Enver traf Talat."])
    _lauf(con, vorhersage=_erkenner({"Enver": "Person", "Talat": "Person"}))
    a, b = [z[0] for z in con.execute("SELECT id FROM akteur ORDER BY id")]

    with pytest.raises(AkteurFehler) as exc:
        akteur_aendern(con, a, normalform=con.execute(
            "SELECT normalform FROM akteur WHERE id = ?", (b,)).fetchone()[0])
    assert exc.value.code == "normalform_belegt"


def test_patch_auf_unbekannten_akteur(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    with pytest.raises(AkteurFehler) as exc:
        akteur_aendern(con, 999, typ="Person")
    assert exc.value.code == "akteur_nicht_gefunden"


# ── Verschmelzen ──────────────────────────────────────────────────────────────

def test_verschmelzen_beliebiger_akteure(tmp_path):
    con = _db(tmp_path, ["Atatürk sprach.", "Mustafa Kemal schwieg."])
    _lauf(con, vorhersage=_erkenner(
        {"Atatürk": "Person", "Mustafa Kemal": "Person"}
    ))
    a, b = [z[0] for z in con.execute("SELECT id FROM akteur ORDER BY normalform")]

    # Kein vorgeschlagenes Paar — die beiden Namen haben nichts gemeinsam.
    assert duplikatskandidaten(con, "p") == []

    ergebnis = akteure_verschmelzen(con, [a, b], behalten_id=b)

    assert ergebnis["normalform"] == "Mustafa Kemal"
    assert ergebnis["aliase"] == ["Atatürk"]
    assert ergebnis["herkunft"] == "manuell"
    assert ergebnis["aufgeloeste_akteure"] == [a]
    # Beide Vorkommen hängen jetzt an einem Akteur.
    assert ergebnis["anzahl_fundstellen"] == 2
    assert con.execute("SELECT COUNT(*) FROM akteur").fetchone()[0] == 1


def test_der_aufrufer_bestimmt_welche_normalform_bleibt(tmp_path):
    con = _db(tmp_path, ["Atatürk sprach.", "Mustafa Kemal schwieg."])
    _lauf(con, vorhersage=_erkenner(
        {"Atatürk": "Person", "Mustafa Kemal": "Person"}
    ))
    a, b = [z[0] for z in con.execute("SELECT id FROM akteur ORDER BY normalform")]

    # Die Vorlage nahm immer den linken Eintrag; hier gewinnt der genannte.
    ergebnis = akteure_verschmelzen(con, [a, b], behalten_id=a)
    assert ergebnis["normalform"] == "Atatürk"


def test_verschmelzen_braucht_zwei_verschiedene(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    _lauf(con)
    a = con.execute("SELECT id FROM akteur").fetchone()[0]
    with pytest.raises(AkteurFehler) as exc:
        akteure_verschmelzen(con, [a, a], behalten_id=a)
    assert exc.value.code == "zu_wenige_akteure"


def test_behalten_id_muss_in_ids_stehen(tmp_path):
    con = _db(tmp_path, ["Enver traf Talat."])
    _lauf(con, vorhersage=_erkenner({"Enver": "Person", "Talat": "Person"}))
    a, b = [z[0] for z in con.execute("SELECT id FROM akteur ORDER BY id")]
    with pytest.raises(AkteurFehler) as exc:
        akteure_verschmelzen(con, [a, b], behalten_id=999)
    assert exc.value.code == "behalten_nicht_in_ids"


# ── Verschmelzungskandidaten ──────────────────────────────────────────────────

def test_kandidaten_kommen_aus_einer_quelle(tmp_path):
    con = _db(tmp_path, ["Abdülhamid und Abdulhamid und Damaskus."])
    _lauf(con, vorhersage=_erkenner({
        "Abdülhamid": "Person", "Abdulhamid": "Person",
        "Damaskus": "geographischer Ort",
    }))

    kandidaten = duplikatskandidaten(con, "p")
    assert len(kandidaten) == 1
    assert kandidaten[0]["grund"] == "schreibweise"
    assert {kandidaten[0]["akteur_a"], kandidaten[0]["akteur_b"]} == {
        "Abdülhamid", "Abdulhamid"
    }


def test_kandidaten_verschwinden_beim_verschmelzen(tmp_path):
    con = _db(tmp_path, ["Abdülhamid und Abdulhamid."])
    _lauf(con, vorhersage=_erkenner(
        {"Abdülhamid": "Person", "Abdulhamid": "Person"}
    ))
    assert len(duplikatskandidaten(con, "p")) == 1

    a, b = [z[0] for z in con.execute("SELECT id FROM akteur ORDER BY id")]
    akteure_verschmelzen(con, [a, b], behalten_id=a)

    assert duplikatskandidaten(con, "p") == []


def test_kandidaten_eines_unbekannten_projekts(tmp_path):
    con = _db(tmp_path, ["Enver kam an."])
    with pytest.raises(AkteurFehler) as exc:
        duplikatskandidaten(con, "gibt-es-nicht")
    assert exc.value.code == "projekt_nicht_gefunden"
