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
        gliner_schwelle=kwargs.pop("gliner_schwelle", 0.7),
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
                 embed=_embed_getrennt, schwelle=0.92, gliner_schwelle=0.7)
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


# ── Zusammenfassungen ─────────────────────────────────────────────────────────
# Kein Modell und kein Netz: frage_modell ist eine Attrappe. Geprüft wird, wen
# der Dienst auswählt, was er schreibt und was er beim zweiten Mal unterlässt.

def _mit_akteuren(tmp_path: Path, nennungen: dict[str, int]) -> sqlite3.Connection:
    """Ein Projekt, in dem jeder Name in so vielen Einheiten vorkommt."""
    con = _db(tmp_path, [])
    with con:
        con.execute("INSERT INTO kategorie (id, projekt_id, name, herkunft) "
                    "VALUES (1,'p','Klage','vorschlag'), (2,'p','Kosten','vorschlag')")
        pos = 0
        for akteur_nr, (name, anzahl) in enumerate(nennungen.items(), 1):
            con.execute("INSERT INTO akteur (id, projekt_id, normalform, typ, status, "
                        "herkunft) VALUES (?,'p',?,'Person','aktiv','gliner')",
                        (akteur_nr, name))
            for _ in range(anzahl):
                pos += 1
                con.execute(
                    "INSERT INTO einheit (id, quelle_id, position, typ, text, jahr_von, "
                    "kategorie_id) VALUES (?,'q',?,'content',?,?,?)",
                    (pos, pos, f"Absatz {pos} über {name}.", 1900 + pos,
                     1 if pos % 2 else 2))
                con.execute("INSERT INTO einheit_akteur (einheit_id, akteur_id, start, "
                            "ende) VALUES (?,?,0,4)", (pos, akteur_nr))
    return con


def _modell(antwort: str = "Wer.\n\nRolle.\n\nKonflikte.", protokoll: list | None = None):
    def frage(prompt: str, system: str) -> tuple[str, int, int]:
        if protokoll is not None:
            protokoll.append(prompt)
        return antwort, 100, 50
    return frage


def test_nur_akteure_mit_genug_nennungen(tmp_path):
    """Unter drei Nennungen steht zu wenig da, um etwas über eine Rolle zu sagen."""
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen, zusammenfassungen_stand

    con = _mit_akteuren(tmp_path, {"Enver": 5, "Talaat": 3, "Randfigur": 2})

    stand = zusammenfassungen_stand(con, "p")
    assert stand["anzahl_kandidaten"] == 2      # Randfigur fällt raus
    assert stand["anzahl_offen"] == 2
    assert stand["mindest_nennungen"] == 3

    e = zusammenfassungen_erzeugen(con, "p", frage_modell=_modell(), llm_modell="attrappe")
    assert e.anzahl_kandidaten == 2
    assert e.anzahl_geschrieben == 2

    geschrieben = dict(con.execute(
        "SELECT normalform, zusammenfassung IS NOT NULL FROM akteur"))
    assert geschrieben == {"Enver": 1, "Talaat": 1, "Randfigur": 0}
    con.close()


def test_zweiter_lauf_zahlt_nicht_noch_einmal(tmp_path):
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen, zusammenfassungen_stand

    con = _mit_akteuren(tmp_path, {"Enver": 5})
    aufrufe: list = []
    zusammenfassungen_erzeugen(con, "p", frage_modell=_modell(protokoll=aufrufe),
                               llm_modell="attrappe")
    assert len(aufrufe) == 1

    zweiter = zusammenfassungen_erzeugen(
        con, "p", frage_modell=_modell(protokoll=aufrufe), llm_modell="attrappe")
    assert len(aufrufe) == 1, "Der zweite Lauf hat das Modell noch einmal gefragt"
    assert zweiter.anzahl_geschrieben == 0
    assert zweiter.anzahl_uebersprungen == 1
    assert zusammenfassungen_stand(con, "p")["anzahl_offen"] == 0

    # alle=True schreibt bewusst neu.
    dritter = zusammenfassungen_erzeugen(
        con, "p", frage_modell=_modell("Neu.", protokoll=aufrufe), llm_modell="attrappe",
        alle=True)
    assert dritter.anzahl_geschrieben == 1
    assert con.execute("SELECT zusammenfassung FROM akteur").fetchone()[0] == "Neu."
    con.close()


def test_der_prompt_traegt_die_auszuege(tmp_path):
    from src.neu.akteure.dienst import MAX_ABSAETZE, zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 4})
    prompts: list = []
    zusammenfassungen_erzeugen(con, "p", frage_modell=_modell(protokoll=prompts),
                               llm_modell="attrappe")

    prompt = prompts[0]
    assert "Person/Organisation: Enver" in prompt
    assert "(4 gesamt, 4 gezeigt)" in prompt
    assert "Absatz 1 über Enver." in prompt
    assert "[1, 1901]" in prompt          # Einheit und Jahr als Beleg
    assert MAX_ABSAETZE == 30
    con.close()


def test_mehr_als_dreissig_absaetze_werden_ausgeduennt(tmp_path):
    """Reihum über die Kategorien, damit die Auswahl nicht einseitig wird."""
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 40})
    prompts: list = []
    zusammenfassungen_erzeugen(con, "p", frage_modell=_modell(protokoll=prompts),
                               llm_modell="attrappe")

    assert "(40 gesamt, 30 gezeigt)" in prompts[0]
    gezeigt = [z for z in prompts[0].split("\n") if z.startswith("[")]
    assert len(gezeigt) == 30
    # Beide Kategorien kommen vor, keine ist verdrängt.
    nummern = [int(z[1:z.index(",")]) for z in gezeigt]
    assert any(n % 2 for n in nummern) and any(not n % 2 for n in nummern)
    assert nummern == sorted(nummern), "Die Auszüge stehen nicht in Dokumentreihenfolge"
    con.close()


def test_ein_gescheiterter_akteur_beendet_den_lauf_nicht(tmp_path):
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 5, "Talaat": 4})

    def launisch(prompt, system):
        if "Talaat" in prompt:
            raise RuntimeError("Modell weg")
        return "Wer.\n\nRolle.\n\nKonflikte.", 10, 5

    e = zusammenfassungen_erzeugen(con, "p", frage_modell=launisch, llm_modell="attrappe")
    assert e.anzahl_geschrieben == 1 and e.anzahl_gescheitert == 1
    assert con.execute(
        "SELECT zusammenfassung FROM akteur WHERE normalform='Enver'").fetchone()[0]
    con.close()


def test_ein_lauf_ohne_ein_einziges_ergebnis_scheitert(tmp_path):
    """Erfolg mit null Ergebnissen wäre eine Lüge in der lauf-Zeile."""
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 5})

    def kaputt(prompt, system):
        raise RuntimeError("Modell weg")

    with pytest.raises(AkteurFehler) as fehler:
        zusammenfassungen_erzeugen(con, "p", frage_modell=kaputt, llm_modell="attrappe")
    assert fehler.value.code == "zusammenfassungen_gescheitert"
    con.close()


def test_leere_antwort_zaehlt_als_gescheitert(tmp_path):
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 5, "Talaat": 4})
    antworten = iter(["", "Wer.\n\nRolle.\n\nKonflikte."])
    e = zusammenfassungen_erzeugen(
        con, "p", frage_modell=lambda p, s: (next(antworten), 10, 5),
        llm_modell="attrappe")
    assert e.anzahl_geschrieben == 1 and e.anzahl_gescheitert == 1
    con.close()


def test_die_kosten_kommen_aus_der_anbieterdatei(tmp_path):
    from src.neu.akteure.dienst import zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 5})
    e = zusammenfassungen_erzeugen(
        con, "p", frage_modell=lambda p, s: ("Text.", 1_000_000, 0),
        llm_modell="claude-haiku-4-5-20251001")
    assert e.in_tokens == 1_000_000
    assert e.kosten_usd == pytest.approx(0.80)   # [llm.anthropic.preise]
    con.close()


def test_die_liste_nennt_den_stand_und_den_text(tmp_path):
    """Die Zahl am Knopf und die Zusammenfassung auf der Karte."""
    from src.neu.akteure.dienst import liste, zusammenfassungen_erzeugen

    con = _mit_akteuren(tmp_path, {"Enver": 5, "Randfigur": 2})
    vorher = liste(con, "p")
    assert vorher["anzahl_kandidaten"] == 1 and vorher["anzahl_offen"] == 1
    assert all(a["zusammenfassung"] is None for a in vorher["akteure"])

    zusammenfassungen_erzeugen(con, "p", frage_modell=_modell(), llm_modell="attrappe")
    nachher = liste(con, "p")
    assert nachher["anzahl_offen"] == 0 and nachher["anzahl_mit_zusammenfassung"] == 1
    enver = next(a for a in nachher["akteure"] if a["normalform"] == "Enver")
    assert enver["zusammenfassung"].startswith("Wer.")
    con.close()


def test_kandidaten_stehen_nach_staerke_des_grundes(tmp_path):
    """Die Rangfolge ist Fachwissen und stand bis dahin im Browser."""
    from src.neu.akteure.kern import kandidat_rang

    con = _db(tmp_path, ["Enver kam an.", "Kayali auch."])
    with con:
        con.execute("INSERT INTO akteur (id, projekt_id, normalform, typ, status, "
                    "herkunft) VALUES (1,'p','A','Person','aktiv','gliner'),"
                    "(2,'p','B','Person','aktiv','gliner'),"
                    "(3,'p','C','Person','aktiv','gliner')")
        con.execute(
            "INSERT INTO verschmelzungskandidat (projekt_id, akteur_a_id, akteur_b_id, "
            "grund, mass, berechnet_am) VALUES "
            "('p',1,2,'aehnlichkeit',0.99,'2026-01-01'),"
            "('p',2,3,'schreibweise',2,'2026-01-01'),"
            "('p',1,3,'alias',NULL,'2026-01-01')")

    gruende = [k["grund"] for k in duplikatskandidaten(con, "p")]
    assert gruende == ["alias", "schreibweise", "aehnlichkeit"]
    assert kandidat_rang("alias") < kandidat_rang("aehnlichkeit")
    assert kandidat_rang("erfunden") == 3
    con.close()
