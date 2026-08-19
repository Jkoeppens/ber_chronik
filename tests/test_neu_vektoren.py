"""
tests/test_neu_vektoren.py — der Zwischenspeicher für Einheiten-Embeddings

Kein Modell: `embed` ist eine Attrappe, die zählt, wie oft sie gerufen wurde und
mit welchen Texten. Geprüft wird genau das, was den Speicher ausmacht — dass er
beim zweiten Mal nicht rechnet, und dass er in den drei Fällen, in denen er
falsch läge, von selbst nicht greift.

Ausführen:
  python3 -m pytest tests/test_neu_vektoren.py -v
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu import vektoren  # noqa: E402

SCHEMA = ROOT / "schema.sql"


class Zaehlend:
    """Ein 'Modell', das aus jedem Text einen Vektor macht und sich merkt, wie oft."""

    def __init__(self, masse: int = 4):
        self.masse = masse
        self.aufrufe = 0
        self.texte: list[str] = []

    def __call__(self, texte: list[str]) -> np.ndarray:
        self.aufrufe += 1
        self.texte.extend(texte)
        # Deterministisch aus dem Text, damit ein Treffer nachweisbar ist.
        return np.array(
            [[float(len(t) + n) for n in range(self.masse)] for t in texte],
            dtype=np.float32,
        )


@pytest.fixture
def con(tmp_path):
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


# ── Der Zweck ─────────────────────────────────────────────────────────────────

def test_zweites_mal_rechnet_nicht(con):
    ids = _einheiten(con, ["alpha", "beta", "gamma"])
    paare = list(zip(ids, ["alpha", "beta", "gamma"]))
    embed = Zaehlend()

    erst = vektoren.hole(con, paare, "modell-a", embed)
    assert embed.aufrufe == 1
    assert len(embed.texte) == 3

    zweit = vektoren.hole(con, paare, "modell-a", embed)
    assert embed.aufrufe == 1, "beim zweiten Mal wurde wieder gerechnet"
    assert np.array_equal(erst, zweit)


def test_reihenfolge_bleibt_die_der_eingabe(con):
    ids = _einheiten(con, ["a", "bb", "ccc"])
    embed = Zaehlend()
    vektoren.hole(con, list(zip(ids, ["a", "bb", "ccc"])), "m", embed)

    # Umgekehrt abfragen: alles aus dem Speicher, trotzdem in dieser Reihenfolge.
    gedreht = vektoren.hole(con, list(zip(reversed(ids), ["ccc", "bb", "a"])), "m", embed)
    assert embed.aufrufe == 1
    assert [v[0] for v in gedreht] == [3.0, 2.0, 1.0]


def test_teilweiser_treffer_rechnet_nur_den_rest(con):
    ids = _einheiten(con, ["a", "bb", "ccc"])
    embed = Zaehlend()
    vektoren.hole(con, [(ids[0], "a")], "m", embed)
    embed.texte.clear()

    ergebnis = vektoren.hole(con, list(zip(ids, ["a", "bb", "ccc"])), "m", embed)
    assert embed.texte == ["bb", "ccc"], "die schon bekannte wurde erneut gerechnet"
    assert ergebnis.shape == (3, 4)


# ── Die drei Fälle, in denen er nicht greifen darf ─────────────────────────────

def test_geaenderter_text_macht_den_wert_ungueltig(con):
    ids = _einheiten(con, ["alt"])
    embed = Zaehlend()
    vektoren.hole(con, [(ids[0], "alt")], "m", embed)

    neu = vektoren.hole(con, [(ids[0], "viel laengerer text")], "m", embed)
    assert embed.aufrufe == 2
    assert neu[0][0] == float(len("viel laengerer text"))
    # Überschrieben, nicht danebengelegt: ein Modell, eine Zeile je Einheit.
    assert con.execute("SELECT COUNT(*) FROM einheit_embedding").fetchone()[0] == 1


def test_anderes_modell_nimmt_keine_alten_werte(con):
    ids = _einheiten(con, ["alpha"])
    a, b = Zaehlend(masse=4), Zaehlend(masse=8)

    vektoren.hole(con, [(ids[0], "alpha")], "minilm", a)
    ergebnis = vektoren.hole(con, [(ids[0], "alpha")], "voyage-4", b)

    assert b.aufrufe == 1, "der Wert des anderen Modells wurde weiterverwendet"
    assert ergebnis.shape == (1, 8)
    # Beide bleiben liegen: ein Zurückwechseln soll sofort wieder greifen.
    assert con.execute("SELECT COUNT(*) FROM einheit_embedding").fetchone()[0] == 2
    zurueck = vektoren.hole(con, [(ids[0], "alpha")], "minilm", a)
    assert a.aufrufe == 1
    assert zurueck.shape == (1, 4)


def test_geloeschte_einheit_nimmt_ihren_vektor_mit(con):
    ids = _einheiten(con, ["alpha"])
    vektoren.hole(con, [(ids[0], "alpha")], "m", Zaehlend())
    with con:
        con.execute("DELETE FROM einheit WHERE id = ?", (ids[0],))
    assert con.execute("SELECT COUNT(*) FROM einheit_embedding").fetchone()[0] == 0


# ── Randfälle ─────────────────────────────────────────────────────────────────

def test_leere_eingabe(con):
    embed = Zaehlend()
    assert vektoren.hole(con, [], "m", embed).shape == (0, 0)
    assert embed.aufrufe == 0


def test_pruefsumme_haengt_am_text_nicht_an_der_einheit(con):
    assert vektoren.pruefsumme("a") == vektoren.pruefsumme("a")
    assert vektoren.pruefsumme("a") != vektoren.pruefsumme("b")


def test_melden_sagt_woher_die_werte_kamen(con):
    ids = _einheiten(con, ["a", "bb", "ccc"])
    paare = list(zip(ids, ["a", "bb", "ccc"]))
    embed = Zaehlend()
    gemeldet: list[tuple[int, int]] = []

    vektoren.hole(con, paare, "m", embed, lambda g, o: gemeldet.append((g, o)))
    assert gemeldet == [(0, 3)]

    vektoren.hole(con, paare, "m", embed, lambda g, o: gemeldet.append((g, o)))
    assert gemeldet[-1] == (3, 0), "auch ohne zu Rechnendes muss gemeldet werden"


def test_lage_zaehlt_was_noch_fehlt(con):
    ids = _einheiten(con, ["a", "bb", "ccc"])
    assert vektoren.lage(con, "p", "m")["zu_rechnen"] == 3

    vektoren.hole(con, [(ids[0], "a")], "m", Zaehlend())
    z = vektoren.lage(con, "p", "m")
    assert (z["einheiten"], z["gespeichert"], z["zu_rechnen"]) == (3, 1, 2)

    # Ein anderes Modell fängt bei null an.
    assert vektoren.lage(con, "p", "anderes")["zu_rechnen"] == 3


def test_nicht_content_einheiten_zaehlen_nicht_mit(con):
    _einheiten(con, ["a"])
    with con:
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                    "VALUES ('q', 99, 'bibliography', 'Literaturangabe')")
    assert vektoren.lage(con, "p", "m")["einheiten"] == 1
