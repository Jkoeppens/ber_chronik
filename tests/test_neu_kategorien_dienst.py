"""
tests/test_neu_kategorien_dienst.py — src/neu/kategorien/dienst.py

Jeder Test baut seine eigene Datenbank aus schema.sql in einem tmp_path.
data/neu.db und data/projects.db werden nicht angefasst.

Die Tests des LLM-Pfads spritzen ein Attrappen-Modell ein und gehen nicht ins
Netz. Die BGE-Abnahme lädt BAAI/bge-m3 lokal (im HF-Cache) — sie ist mit
@pytest.mark.langsam versehen.

Ausführen:
  python3 -m pytest tests/test_neu_kategorien_dienst.py -v
  python3 -m pytest tests/test_neu_kategorien_dienst.py -v -m "not langsam"
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.kategorien import dienst, kern  # noqa: E402
from src.neu.kategorien.dienst import (  # noqa: E402
    KlassifikationFehler,
    klassifizieren,
    zuordnung_setzen,
)

SCHEMA = ROOT / "schema.sql"
BASELINE = ROOT / "data" / "projects" / "baseline_damaskus_docx"
DAMASKUS_DOCX = ROOT / "data" / "raw" / "Damakus Notizen.docx"

TAXONOMIE = [
    ("Politik", "Staatliches Handeln", "Staat,Partei"),
    ("Kosten", "Geld und Budget", "Preis"),
]


def _db(tmp_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(tmp_path / "test.db")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.execute("PRAGMA foreign_keys = ON")
    with con:
        con.execute(
            "INSERT INTO zugang (token, angelegt_am, rolle) VALUES ('t','2026-01-01','nutzer')"
        )
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES ('p','P',1,'2026-01-01')"
        )
        con.execute(
            "INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
            "VALUES ('q','p','literaturexzerpt','2026-01-01')"
        )
    return con


def _kategorien(con: sqlite3.Connection, eintraege=TAXONOMIE) -> list[int]:
    ids = []
    with con:
        for name, beschreibung, schlagworte in eintraege:
            z = con.execute(
                "INSERT INTO kategorie (projekt_id, name, beschreibung, schlagworte, herkunft) "
                "VALUES ('p', ?, ?, ?, 'vorschlag')",
                (name, beschreibung, schlagworte),
            )
            ids.append(z.lastrowid)
    return ids


def _einheiten(con: sqlite3.Connection, texte: list[str], typ: str = "content") -> list[int]:
    ids = []
    with con:
        for i, t in enumerate(texte, start=1):
            z = con.execute(
                "INSERT INTO einheit (quelle_id, position, typ, text) VALUES ('q',?,?,?)",
                (i, typ, t),
            )
            ids.append(z.lastrowid)
    return ids


def _attrappe(antwort: str):
    """Ein Modell, das immer dieselbe Antwort gibt. Kein Netz.

    In der Gestalt von anbieter.llm_funktion(): (frage_modell, Modellname), und
    frage_modell gibt (Text, Eingabe-Token, Ausgabe-Token). Vorher war es die
    Gestalt von generalized.llm.get_provider() — ein Objekt mit .complete().
    """
    def bauen(*_a, **_k):
        return (lambda prompt, system: (antwort, 0, 0)), "attrappe"
    return bauen


@pytest.fixture
def con(tmp_path):
    verbindung = _db(tmp_path)
    yield verbindung
    verbindung.close()


# ── Wiederaufnahme über die Datenbank ─────────────────────────────────────────

def test_lauf_nimmt_nur_offene_einheiten(con, monkeypatch) -> None:
    kat = _kategorien(con)
    ids = _einheiten(con, ["a", "b", "c"])
    with con:  # eine ist schon klassifiziert — also hat sie eine Kategorie
        con.execute(
            "UPDATE einheit SET kategorie_id=?, kategorie_herkunft='automatisch', "
            "konfidenz='high' WHERE id=?",
            (kat[0], ids[0]),
        )

    monkeypatch.setitem(
        dienst.WEGE, "vektoren",
        lambda con, einheiten, tax, melden=None: [kern.Zuordnung("Politik", "high", "automatisch") for _ in einheiten],
    )
    ergebnis = klassifizieren(con, "p", verfahren="vektoren", umfang="offen")
    assert ergebnis.anzahl_einheiten == 2


def test_nicht_content_einheiten_bleiben_unberuehrt(con, monkeypatch) -> None:
    _kategorien(con)
    _einheiten(con, ["inhalt"])
    with con:
        con.execute(
            "INSERT INTO einheit (quelle_id, position, typ, text) "
            "VALUES ('q', 99, 'bibliography', 'Literaturangabe')"
        )
    monkeypatch.setitem(
        dienst.WEGE, "vektoren",
        lambda con, einheiten, tax, melden=None: [kern.Zuordnung("Politik", "high", "automatisch") for _ in einheiten],
    )
    klassifizieren(con, "p")
    offen = con.execute(
        "SELECT count(*) FROM einheit WHERE typ!='content' AND kategorie_herkunft IS NOT NULL"
    ).fetchone()[0]
    assert offen == 0


# ── Handkorrektur ist geschützt ───────────────────────────────────────────────

def test_manuell_bleibt_auch_bei_umfang_alle_unberuehrt(con, monkeypatch) -> None:
    kat = _kategorien(con)
    ids = _einheiten(con, ["a", "b"])
    zuordnung_setzen(con, ids[0], kat[1])          # von Hand auf 'Kosten'

    monkeypatch.setitem(
        dienst.WEGE, "vektoren",
        lambda con, einheiten, tax, melden=None: [kern.Zuordnung("Politik", "high", "automatisch") for _ in einheiten],
    )
    ergebnis = klassifizieren(con, "p", umfang="alle")

    assert ergebnis.anzahl_einheiten == 1          # nur die andere
    zeile = con.execute(
        "SELECT kategorie_id, kategorie_herkunft, konfidenz FROM einheit WHERE id=?",
        (ids[0],),
    ).fetchone()
    assert zeile == (kat[1], "manuell", None)


def test_nur_auch_manuell_ueberschreibt_die_handkorrektur(con, monkeypatch) -> None:
    kat = _kategorien(con)
    ids = _einheiten(con, ["a"])
    zuordnung_setzen(con, ids[0], kat[1])

    monkeypatch.setitem(
        dienst.WEGE, "vektoren",
        lambda con, einheiten, tax, melden=None: [kern.Zuordnung("Politik", "high", "automatisch") for _ in einheiten],
    )
    ergebnis = klassifizieren(con, "p", umfang="auch_manuell")

    assert ergebnis.anzahl_einheiten == 1
    zeile = con.execute(
        "SELECT kategorie_id, kategorie_herkunft FROM einheit WHERE id=?", (ids[0],)
    ).fetchone()
    assert zeile == (kat[0], "automatisch")


def test_handkorrektur_leert_die_konfidenz(con) -> None:
    kat = _kategorien(con)
    ids = _einheiten(con, ["a"])
    with con:
        con.execute(
            "UPDATE einheit SET kategorie_id=?, konfidenz='high', kategorie_herkunft='automatisch', "
            "kategorie_lauf_id=NULL WHERE id=?", (kat[0], ids[0]),
        )

    ergebnis = zuordnung_setzen(con, ids[0], kat[1])
    assert ergebnis["konfidenz"] is None
    assert ergebnis["kategorie_herkunft"] == "manuell"
    zeile = con.execute(
        "SELECT kategorie_id, konfidenz, kategorie_herkunft, kategorie_lauf_id "
        "FROM einheit WHERE id=?", (ids[0],)
    ).fetchone()
    assert zeile == (kat[1], None, "manuell", None)


def test_handkorrektur_auf_keine_kategorie(con) -> None:
    _kategorien(con)
    ids = _einheiten(con, ["a"])
    ergebnis = zuordnung_setzen(con, ids[0], None)
    assert ergebnis["kategorie_id"] is None
    assert ergebnis["kategorie_herkunft"] == "manuell"


def test_fremde_kategorie_wird_abgewiesen(con, tmp_path) -> None:
    _kategorien(con)
    ids = _einheiten(con, ["a"])
    with con:
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES ('fremd','F',1,'2026-01-01')"
        )
        z = con.execute(
            "INSERT INTO kategorie (projekt_id, name, herkunft) VALUES ('fremd','X','manuell')"
        )
    with pytest.raises(KlassifikationFehler) as exc:
        zuordnung_setzen(con, ids[0], z.lastrowid)
    assert exc.value.code == "kategorie_nicht_gefunden"


# ── "(unbekannt)" wird kategorie_id NULL ──────────────────────────────────────

def test_unbekannte_kategorie_wird_null_bei_gesetzter_herkunft(con, monkeypatch) -> None:
    """Die Vorlage schrieb '(unbekannt)' in das Kategoriefeld."""
    _kategorien(con)
    ids = _einheiten(con, ["a"])

    from src.neu import anbieter
    monkeypatch.setattr(
        anbieter, "llm_funktion",
        _attrappe('{"category":"Sport","confidence":"high"}'))

    ergebnis = klassifizieren(con, "p", verfahren="llm")
    assert ergebnis.anzahl_ohne_kategorie == 1

    zeile = con.execute(
        "SELECT kategorie_id, kategorie_herkunft, konfidenz FROM einheit WHERE id=?",
        (ids[0],),
    ).fetchone()
    assert zeile[0] is None          # keine Kategorie
    assert zeile[1] == "automatisch"   # aber zugeordnet worden
    assert zeile[2] == "high"


def test_unlesbare_antwort_ergibt_weder_kategorie_noch_konfidenz(con, monkeypatch) -> None:
    _kategorien(con)
    ids = _einheiten(con, ["a"])
    from src.neu import anbieter
    monkeypatch.setattr(anbieter, "llm_funktion", _attrappe("kein JSON"))

    klassifizieren(con, "p", verfahren="llm")
    zeile = con.execute(
        "SELECT kategorie_id, konfidenz, kategorie_herkunft FROM einheit WHERE id=?",
        (ids[0],),
    ).fetchone()
    assert zeile == (None, None, "automatisch")


# ── lauf ──────────────────────────────────────────────────────────────────────

def test_lauf_wird_festgehalten_und_verknuepft(con, monkeypatch) -> None:
    _kategorien(con)
    ids = _einheiten(con, ["a"])
    monkeypatch.setitem(
        dienst.WEGE, "vektoren",
        lambda con, einheiten, tax, melden=None: [kern.Zuordnung("Politik", "high", "automatisch") for _ in einheiten],
    )
    ergebnis = klassifizieren(con, "p")

    lauf = con.execute(
        "SELECT projekt_id, schritt, begonnen_am, beendet_am, parameter, status "
        "FROM lauf WHERE id=?", (ergebnis.lauf_id,)
    ).fetchone()
    assert lauf[0] == "p"
    assert lauf[1] == "klassifikation"
    assert lauf[2] and lauf[3]
    assert json.loads(lauf[4])["verfahren"] == "vektoren"
    assert lauf[5] == "erfolg"

    verknuepft = con.execute(
        "SELECT kategorie_lauf_id FROM einheit WHERE id=?", (ids[0],)
    ).fetchone()[0]
    assert verknuepft == ergebnis.lauf_id


def test_fehlschlag_rollt_zurueck_und_haelt_den_lauf_fest(con, monkeypatch) -> None:
    _kategorien(con)
    _einheiten(con, ["a"])

    def kaputt(con, einheiten, tax, melden=None):
        raise RuntimeError("Modell nicht erreichbar")

    monkeypatch.setitem(dienst.WEGE, "vektoren", kaputt)
    with pytest.raises(RuntimeError):
        klassifizieren(con, "p")

    assert con.execute(
        "SELECT count(*) FROM einheit WHERE kategorie_herkunft IS NOT NULL"
    ).fetchone()[0] == 0
    lauf = con.execute("SELECT status, beendet_am FROM lauf").fetchall()
    assert len(lauf) == 1 and lauf[0][0] == "fehler" and lauf[0][1]


# ── Prüfungen ─────────────────────────────────────────────────────────────────

def test_unbekanntes_projekt(con) -> None:
    with pytest.raises(KlassifikationFehler) as exc:
        klassifizieren(con, "gibtsnicht")
    assert exc.value.code == "projekt_nicht_gefunden"


def test_ohne_taxonomie_kein_lauf(con) -> None:
    _einheiten(con, ["a"])
    with pytest.raises(KlassifikationFehler) as exc:
        klassifizieren(con, "p")
    assert exc.value.code == "keine_taxonomie"


def test_ohne_offene_einheiten(con, monkeypatch) -> None:
    kat = _kategorien(con)
    ids = _einheiten(con, ["a"])
    with con:
        con.execute("UPDATE einheit SET kategorie_id=?, kategorie_herkunft='automatisch' "
                    "WHERE id=?", (kat[0], ids[0]))
    with pytest.raises(KlassifikationFehler) as exc:
        klassifizieren(con, "p", umfang="offen")
    assert exc.value.code == "keine_einheiten"


def test_unbekanntes_verfahren_und_umfang(con) -> None:
    _kategorien(con)
    _einheiten(con, ["a"])
    with pytest.raises(KlassifikationFehler) as exc:
        klassifizieren(con, "p", verfahren="gliner")
    assert exc.value.code == "verfahren_unbekannt"
    with pytest.raises(KlassifikationFehler) as exc:
        klassifizieren(con, "p", umfang="force")
    assert exc.value.code == "umfang_unbekannt"


# ── Abnahme: BGE auf damaskus ─────────────────────────────────────────────────

@pytest.mark.langsam
@pytest.mark.skipif(
    not DAMASKUS_DOCX.exists() or not (BASELINE / "config.json").exists(),
    reason="DOCX oder Baseline-Taxonomie fehlt",
)
def test_bge_ist_deterministisch_und_die_klempnerei_verzerrt_nichts(tmp_path) -> None:
    """Zweimal derselbe Lauf, und der Weg über die Datenbank ändert nichts.

    Nicht verglichen wird gegen baseline_.../classified.json: diese Datei
    stammt aus einem LLM-Lauf (sie enthält 5 Zeilen '(unbekannt)', einen Wert,
    den der BGE-Pfad strukturell nicht erzeugen kann). Ein Soll-Ist-Vergleich
    gegen sie prüfte zwei verschiedene Verfahren gegeneinander.
    """
    from src.neu.ingest.dienst import einlesen

    con = _db(tmp_path)
    try:
        einlesen(con, "p", DAMASKUS_DOCX, "literaturexzerpt", quelle_id="d")
        with con:
            con.execute("DELETE FROM quelle WHERE id='q'")
        tax = json.loads((BASELINE / "config.json").read_text(encoding="utf-8"))["taxonomy"]
        _kategorien(con, [(c["name"], c.get("description", ""),
                           ",".join(c.get("keywords", []))) for c in tax])

        erst = klassifizieren(con, "p", verfahren="vektoren")
        assert erst.anzahl_einheiten == 672
        assert erst.anzahl_ohne_kategorie == 0      # BGE ordnet immer zu

        aus_db = con.execute(
            "SELECT k.name, e.konfidenz FROM einheit e JOIN kategorie k ON k.id = e.kategorie_id "
            "ORDER BY e.position"
        ).fetchall()

        # Derselbe Lauf ein zweites Mal, direkt über den Kern
        from src.generalized.embeddings import EMB_TASK_CLASSIFY, get_embedding_provider
        texte = [z[0] for z in con.execute(
            "SELECT text FROM einheit WHERE typ='content' ORDER BY position"
        )]
        provider = get_embedding_provider(EMB_TASK_CLASSIFY)
        direkt = kern.zuordnungen_aus_embeddings(
            provider.encode(kern.einheit_texte(texte)),
            provider.encode(kern.taxonomie_texte(tax)),
            [c["name"] for c in tax],
        )

        assert [(z.kategorie, z.konfidenz) for z in direkt] == [tuple(r) for r in aus_db]
        assert all(z.herkunft == "automatisch" for z in direkt)
    finally:
        con.close()
