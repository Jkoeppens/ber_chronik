"""
tests/test_neu_taxonomie_dienst.py — src/neu/taxonomie/dienst.py

Der Lauf gegen eine echte SQLite-Datei, aber ohne Modell: Embedding und
Sprachmodell werden über anbieter.* ersetzt. Geprüft wird, was der Dienst mit
der Datenbank macht — und das ist seit dem Abgleich das Entscheidende: die
Kennungen bleiben, die Handarbeit bleibt, gelöscht wird nichts mehr.

Ausführen:
  python3 -m pytest tests/test_neu_taxonomie_dienst.py -v
"""

import sqlite3
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.taxonomie import anbieter, dienst  # noqa: E402
from src.neu.taxonomie.dienst import TaxonomieFehler, vorschlagen  # noqa: E402
from src.neu.taxonomie.kern import UnlesbareAntwort  # noqa: E402

SCHEMA = ROOT / "schema.sql"


def _embed(texte):
    """Gleicher Text, gleicher Vektor — crc32 statt hash(), das ist gesalzen."""
    out = []
    for t in texte:
        rng = np.random.default_rng(zlib.crc32(t.encode("utf-8")))
        v = rng.normal(size=8).astype(np.float32)
        out.append(v / np.linalg.norm(v))
    return np.array(out, dtype=np.float32)


def _antwort(titel: list[str]) -> str:
    return "\n\n".join(f"## Gruppe {i+1}\n{t}\nBeschreibung zu {t}."
                       for i, t in enumerate(titel))


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
        for i in range(1, 41):
            thema = ("Flughafen Termin Eröffnung Bericht über den Bau"
                     if i <= 20 else "Gericht Klage Urteil Verfahren vor der Kammer")
            c.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                      "VALUES ('q', ?, 'content', ?)", (i, f"{thema} Nummer {i}"))
    monkeypatch.setenv("NEU_DB", str(pfad))
    monkeypatch.setattr(anbieter, "embedding_funktion",
                        lambda *a, **k: (_embed, "test-modell"))
    yield c
    c.close()


def _modell(monkeypatch, antwort: str):
    monkeypatch.setattr(
        anbieter, "llm_funktion",
        lambda *a, **k: ((lambda p, s: (antwort, 10, 5)), "test-llm"),
    )


def _kategorien(con) -> list[tuple]:
    return con.execute(
        "SELECT id, name, beschreibung, herkunft FROM kategorie "
        "WHERE projekt_id='p' ORDER BY id"
    ).fetchall()


# ── Kalt: anlegen ─────────────────────────────────────────────────────────────

def test_kalt_legt_an(con, monkeypatch) -> None:
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    e = vorschlagen(con, "p", warm_start=False, n_clusters=2)
    assert e.n_clusters == 2
    assert [z[1] for z in _kategorien(con)] == ["Bau", "Klagen"]
    assert all(z[3] == "vorschlag" for z in _kategorien(con))
    assert e.anzahl_zugeordnet == 40


def test_kalt_bei_vorhandenen_wird_abgewiesen(con, monkeypatch) -> None:
    """Kalt heißt bei null anfangen — und das geht nur, wenn null ist.

    Vorher hat der Lauf an dieser Stelle stillschweigend alles gelöscht.
    """
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)
    with pytest.raises(TaxonomieFehler) as exc:
        vorschlagen(con, "p", warm_start=False, n_clusters=2)
    assert exc.value.code == "kalt_bei_vorhandenen"
    assert len(_kategorien(con)) == 2, "die vorhandenen wurden angetastet"


# ── Warm: abgleichen statt ersetzen ───────────────────────────────────────────

def test_verfeinern_behaelt_die_kennungen(con, monkeypatch) -> None:
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)
    vorher = [z[0] for z in _kategorien(con)]

    _modell(monkeypatch, _antwort(["Bauverzug", "Gerichtsverfahren"]))
    vorschlagen(con, "p", warm_start=True)
    nachher = _kategorien(con)

    assert [z[0] for z in nachher] == vorher, "die Kennungen wurden neu vergeben"
    assert [z[1] for z in nachher] == ["Bauverzug", "Gerichtsverfahren"]


def test_verfeinern_loescht_nichts(con, monkeypatch) -> None:
    """Kein DELETE über das Projekt mehr — die Einheiten verlieren ihre Kategorie nicht."""
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)

    _modell(monkeypatch, _antwort(["Bauverzug", "Gerichtsverfahren"]))
    vorschlagen(con, "p", warm_start=True)

    ohne = con.execute(
        "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id=e.quelle_id "
        "WHERE q.projekt_id='p' AND e.kategorie_id IS NULL").fetchone()[0]
    assert ohne == 0


def test_handarbeit_ueberlebt_den_lauf(con, monkeypatch) -> None:
    """Die Zusage aus dem Docstring von kategorien/verwaltung.py, jetzt gedeckt."""
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)
    with con:
        eigene = con.execute(
            "INSERT INTO kategorie (projekt_id, name, beschreibung, schlagworte, "
            "herkunft) VALUES ('p','Von Hand','Meine Beschreibung','x','manuell')"
        ).lastrowid

    _modell(monkeypatch, _antwort(["A", "B", "C"]))
    e = vorschlagen(con, "p", warm_start=True)

    zeile = con.execute(
        "SELECT name, beschreibung, schlagworte, herkunft FROM kategorie WHERE id=?",
        (eigene,)).fetchone()
    assert zeile == ("Von Hand", "Meine Beschreibung", "x", "manuell")
    assert e.n_clusters == 3, "die Handarbeit zählt als eigener Cluster mit"
    assert e.anzahl_unangetastet == 1


def test_nur_handarbeit_fragt_das_modell_nicht(con, monkeypatch) -> None:
    aufrufe = {"n": 0}

    def llm(*a, **k):
        def frage(p, s):
            aufrufe["n"] += 1
            return _antwort(["X", "Y"]), 10, 5
        return frage, "test-llm"

    monkeypatch.setattr(anbieter, "llm_funktion", llm)
    with con:
        for name in ("Eins", "Zwei"):
            con.execute("INSERT INTO kategorie (projekt_id, name, beschreibung, "
                        "schlagworte, herkunft) VALUES ('p',?,?,'','manuell')",
                        (name, f"Beschreibung {name}."))
    e = vorschlagen(con, "p", warm_start=True)

    assert aufrufe["n"] == 0
    assert e.llm_runden == 0
    assert [z[1] for z in _kategorien(con)] == ["Eins", "Zwei"]
    assert e.anzahl_zugeordnet == 40, "zugeordnet wird trotzdem"


def test_doppelte_titel_kollidieren_nicht(con, monkeypatch) -> None:
    """UNIQUE (projekt_id, name) — zwei gleiche Titel dürfen den Lauf nicht sprengen."""
    _modell(monkeypatch, _antwort(["Gleich", "Gleich"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)
    namen = [z[1] for z in _kategorien(con)]
    assert namen == ["Gleich", "Gleich (2)"]


def test_namenstausch_verstoesst_nicht_gegen_unique(con, monkeypatch) -> None:
    """Zwei Kategorien tauschen die Namen — im Zwischenschritt wäre es doppelt."""
    _modell(monkeypatch, _antwort(["Bau", "Klagen"]))
    vorschlagen(con, "p", warm_start=False, n_clusters=2)
    ids = [z[0] for z in _kategorien(con)]

    _modell(monkeypatch, _antwort(["Klagen", "Bau"]))
    vorschlagen(con, "p", warm_start=True)
    assert _kategorien(con)[0][:2] == (ids[0], "Klagen")
    assert _kategorien(con)[1][:2] == (ids[1], "Bau")


# ── Der Lauf scheitert sichtbar ───────────────────────────────────────────────

def test_unlesbare_antwort_laesst_den_lauf_scheitern(con, monkeypatch) -> None:
    _modell(monkeypatch, "Ich bin ein Sprachmodell und helfe Ihnen gern weiter.")
    with pytest.raises(UnlesbareAntwort):
        vorschlagen(con, "p", warm_start=False, n_clusters=2)

    assert _kategorien(con) == [], "trotz unlesbarer Antwort wurde etwas angelegt"
    lauf = con.execute("SELECT schritt, status FROM lauf").fetchone()
    assert lauf == ("taxonomie", "fehler")


def test_teilweise_gelesen_landet_in_der_lauf_zeile(con, monkeypatch) -> None:
    import json
    _modell(monkeypatch, "## Gruppe 1\nNur eine\nBeschreibung dazu.")
    e = vorschlagen(con, "p", warm_start=False, n_clusters=2)
    assert e.warnungen and "1 von 2" in e.warnungen[0]
    p = json.loads(con.execute("SELECT parameter FROM lauf").fetchone()[0])
    assert p["warnungen"] == e.warnungen
