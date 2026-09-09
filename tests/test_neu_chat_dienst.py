"""
tests/test_neu_chat_dienst.py — src/neu/chat/dienst.py

Jeder Test baut seine eigene Datenbank aus schema.sql in einem tmp_path.
data/neu.db wird nicht angefasst.

Sprachmodell und Embedding sind Attrappen: kein Ollama, kein Anthropic, kein
sentence-transformers, kein Netz.

Ausführen:
  python3 -m pytest tests/test_neu_chat_dienst.py -v
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.anbieter import AnbieterFehler  # noqa: E402
from src.neu.chat import dienst  # noqa: E402
from src.neu.chat.dienst import Abbruch, Fertig, Stueck  # noqa: E402

SCHEMA = ROOT / "schema.sql"


def _db(tmp_path: Path, texte: list[str], jahre: list[int | None] | None = None
        ) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    jahre = jahre or [None] * len(texte)
    with con:
        con.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                    "VALUES ('t','2026-01-01','nutzer')")
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p','P',1,'2026-01-01')")
        con.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                    "VALUES ('main','p','presseexzerpt','2026-01-01')")
        for i, (text, jahr) in enumerate(zip(texte, jahre)):
            con.execute(
                "INSERT INTO einheit (quelle_id, position, typ, text, jahr_von) "
                "VALUES ('main', ?, 'content', ?, ?)", (i, text, jahr))
        # Eine heading-Einheit, die nie in einer Antwort auftauchen darf.
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                    "VALUES ('main', 999, 'heading', 'Kosten Kosten Kosten')")
    return con


def _ohne_embedding(monkeypatch) -> None:
    """Kein Embedding-Anbieter — nur die Stichwörter bleiben."""
    def platzt(_aufgabe, name=None):
        raise AnbieterFehler("kein Anbieter", "embedding_anbieter_fehlt")
    monkeypatch.setattr(dienst, "embedding_funktion", platzt)


def _strom(stuecke: list[str], modell: str = "attrappe"):
    """Attrappe für llm_strom_funktion: gibt die Stücke der Reihe nach aus."""
    def bauen():
        def laufen(prompt, system):
            laufen.prompt = prompt
            laufen.system = system
            yield from stuecke
        bauen.laufen = laufen
        return laufen, modell
    return bauen


def _sammeln(ereignisse) -> tuple[str, list]:
    liste = list(ereignisse)
    text = "".join(e.text for e in liste if isinstance(e, Stueck))
    return text, liste


# ── Lesen ─────────────────────────────────────────────────────────────────────

def test_nur_content_einheiten_werden_durchsucht(tmp_path, monkeypatch) -> None:
    """Eine Überschrift ist kein Absatz, den man zitieren könnte."""
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Ein Absatz über Kosten"])
    fund = dienst.suchen(con, "p", "Welche Kosten?")
    assert [e.text for e in fund.absaetze] == ["Ein Absatz über Kosten"]


def test_anker_hat_die_form_des_exports(tmp_path, monkeypatch) -> None:
    """Derselbe Anker wie in data.json — sonst findet viz/ den Absatz nicht."""
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten und Termine"])
    fund = dienst.suchen(con, "p", "Kosten?")
    einheit_id = con.execute(
        "SELECT id FROM einheit WHERE typ='content'").fetchone()[0]
    assert fund.absaetze[0].anker == f"main-e{einheit_id}"


def test_jahr_kommt_aus_jahr_von_sonst_aus_datum(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten A", "Kosten B"], jahre=[1996, None])
    with con:
        con.execute("UPDATE einheit SET datum='2012-05-08' WHERE position=1")
    fund = dienst.suchen(con, "p", "Kosten?")
    assert {e.jahr for e in fund.absaetze} == {1996, 2012}


# ── Suchen ────────────────────────────────────────────────────────────────────

def test_jahreszahl_findet_absaetze(tmp_path, monkeypatch) -> None:
    """Der Fall, an dem die Vorlage scheiterte."""
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Im Jahr 2012 wurde verschoben.", "Etwas ganz anderes."])
    fund = dienst.suchen(con, "p", "Was war 2012?")
    assert fund.stichwoerter == ["2012"]
    assert len(fund.absaetze) == 1
    assert "2012" in fund.absaetze[0].text


def test_ohne_embedding_bleibt_nur_ein_weg(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten und Termine"])
    assert dienst.suchen(con, "p", "Kosten?").wege == ["stichwoerter"]


def test_bedeutung_findet_ohne_stichworttreffer(tmp_path, monkeypatch) -> None:
    """Der Grund für den zweiten Weg.

    Die Frage trifft kein Wort im Text. Über die Vektoren wird der Absatz
    trotzdem gefunden.
    """
    con = _db(tmp_path, ["Flughafenbetrieb wurde untersagt", "Kaninchenzucht"])
    ids = [z[0] for z in con.execute(
        "SELECT id FROM einheit WHERE typ='content' ORDER BY position")]

    # Attrappe: die Frage zeigt auf Achse 0, der erste Absatz auch.
    def einbetten_attrappe(_aufgabe, name=None):
        def einbetten(texte):
            return np.array([[1.0, 0.0]] * len(texte), dtype=np.float32)
        return einbetten, "attrappe-modell"
    monkeypatch.setattr(dienst, "embedding_funktion", einbetten_attrappe)
    monkeypatch.setattr(dienst.vektoren, "vorhandene", lambda *_: {
        ids[0]: np.array([1.0, 0.0], dtype=np.float32),
        ids[1]: np.array([0.0, 1.0], dtype=np.float32),
    })

    fund = dienst.suchen(con, "p", "Durfte dort geflogen werden?")
    assert fund.stichwoerter                      # es gibt Stichwörter …
    assert dienst.kern.stichwort_rangliste(
        dienst.einheiten_lesen(con, "p"), fund.stichwoerter) == []   # … die nichts treffen
    assert fund.wege == ["bedeutung"]
    assert fund.absaetze[0].text == "Flughafenbetrieb wurde untersagt"


def test_ohne_abgelegte_vektoren_faellt_der_weg_still_aus(tmp_path, monkeypatch) -> None:
    """Kein Themenlauf gelaufen: der Chat antwortet trotzdem, nur einwegig."""
    con = _db(tmp_path, ["Kosten und Termine"])
    monkeypatch.setattr(dienst, "embedding_funktion",
                        lambda *_a, **_k: ((lambda t: np.zeros((len(t), 2), np.float32)),
                                           "attrappe-modell"))
    monkeypatch.setattr(dienst.vektoren, "vorhandene", lambda *_: {})
    fund = dienst.suchen(con, "p", "Kosten?")
    assert fund.wege == ["stichwoerter"]
    assert len(fund.absaetze) == 1


def test_der_chat_rechnet_niemals_embeddings(tmp_path, monkeypatch) -> None:
    """vektoren.hole() schriebe und dauerte Minuten — auf eine Frage hin falsch."""
    con = _db(tmp_path, ["Kosten"])
    _ohne_embedding(monkeypatch)

    def darf_nicht(*_a, **_k):
        raise AssertionError("hole() rechnet und schreibt — im Chat verboten")
    monkeypatch.setattr(dienst.vektoren, "hole", darf_nicht)
    dienst.suchen(con, "p", "Kosten?")


# ── Antworten ─────────────────────────────────────────────────────────────────

def test_der_text_kommt_stueckweise(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten stiegen"])
    ereignisse = list(dienst.antworten(con, "p", "Kosten?",
                                       strom_funktion=_strom(["Die ", "Kosten ", "stiegen."])))
    stuecke = [e for e in ereignisse if isinstance(e, Stueck)]
    assert [s.text for s in stuecke] == ["Die ", "Kosten ", "stiegen."]
    assert isinstance(ereignisse[-1], Fertig)


def test_fertig_nennt_nur_die_wirklich_belegten_quellen(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten A", "Kosten B", "Kosten C"])
    anker = [e.anker for e in dienst.suchen(con, "p", "Kosten?").absaetze]
    assert len(anker) == 3

    antwort = f"Nur der erste zählt [{anker[0]}]."
    _, ereignisse = _sammeln(dienst.antworten(
        con, "p", "Kosten?", strom_funktion=_strom([antwort])))
    fertig = ereignisse[-1]
    assert fertig.quellen == [anker[0]]
    assert fertig.absaetze == 3          # angeboten waren drei …
    assert len(fertig.quellen) == 1      # … belegt ist einer


def test_ohne_treffer_wird_das_modell_nicht_gefragt(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Etwas ganz anderes"])

    def darf_nicht():
        raise AssertionError("ohne Auszüge darf nicht gefragt werden")
    text, ereignisse = _sammeln(dienst.antworten(
        con, "p", "Mehdorn?", strom_funktion=darf_nicht))
    assert text == dienst.OHNE_TREFFER
    assert ereignisse[-1].quellen == []
    assert ereignisse[-1].absaetze == 0


def test_leere_frage_bricht_ab(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten"])
    ereignisse = list(dienst.antworten(con, "p", "   "))
    assert len(ereignisse) == 1
    assert isinstance(ereignisse[0], Abbruch)
    assert ereignisse[0].code == "frage_leer"


def test_fehlender_anbieter_wird_zum_abbruch(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten"])

    def platzt():
        raise AnbieterFehler("kein Schlüssel", "llm_schluessel_fehlt")
    ereignisse = list(dienst.antworten(con, "p", "Kosten?", strom_funktion=platzt))
    assert isinstance(ereignisse[0], Abbruch)
    assert ereignisse[0].code == "llm_schluessel_fehlt"


def test_ein_fehler_mitten_im_strom_beendet_ihn_als_abbruch(tmp_path, monkeypatch) -> None:
    """Ab dem ersten Stück ist die Antwort unterwegs — 500 geht nicht mehr."""
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten"])

    def bauen():
        def laufen(prompt, system):
            yield "Der Anfang"
            raise AnbieterFehler("still geworden", "ollama_zeitueberschreitung")
        return laufen, "attrappe"

    ereignisse = list(dienst.antworten(con, "p", "Kosten?", strom_funktion=bauen))
    assert isinstance(ereignisse[0], Stueck)
    assert isinstance(ereignisse[-1], Abbruch)
    assert ereignisse[-1].code == "ollama_zeitueberschreitung"
    assert not any(isinstance(e, Fertig) for e in ereignisse)


def test_der_prompt_traegt_die_absaetze_mit_ankern(tmp_path, monkeypatch) -> None:
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten stiegen 1996"], jahre=[1996])
    bauen = _strom(["ok"])
    list(dienst.antworten(con, "p", "Kosten?", strom_funktion=bauen))
    assert "Frage: Kosten?" in bauen.laufen.prompt
    assert "1996: Kosten stiegen 1996" in bauen.laufen.prompt
    assert bauen.laufen.system == dienst.kern.SYSTEM


def test_unbekanntes_projekt_findet_nichts(tmp_path, monkeypatch) -> None:
    """Kein Absturz, keine Datei — nur keine Absätze.

    Den 404 setzt der Server davor; der Dienst kennt keine Projekte, nur
    Einheiten. Der alte Endpunkt reichte die Kennung ungeprüft in einen Pfad.
    """
    _ohne_embedding(monkeypatch)
    con = _db(tmp_path, ["Kosten"])
    assert dienst.suchen(con, "gibtsnicht", "Kosten?").absaetze == []
