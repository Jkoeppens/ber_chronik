"""
test_neu_anbieter_stapel.py — dass ein zerlegter Aufruf die Reihenfolge behält

Der Anlass kam aus dem Betrieb:

    The batch size limit is 1000. Your batch size is 1100.

Voyage weist eine zu große Anfrage ab. Das Zerlegen ist die leichte Hälfte; die
schwere ist das Zusammensetzen, und sie geht still kaputt. Ein verrutschter
Vektor sieht aus wie ein Vektor: jeder Akteur bekäme die Ähnlichkeit eines
anderen, die Zahlen blieben plausibel, und kein Lauf würde scheitern.

Deshalb prüfen die Tests hier nicht 'es kommen n Zeilen zurück', sondern 'Zeile
i gehört zu Text i' — an einer Attrappe, deren Vektoren ihren Text verraten.
"""

import numpy as np
import pytest

from src.neu.anbieter import AnbieterFehler, _gestapelt, embedding_stapel


def attrappe(grenze: int, gesehen: list[int] | None = None):
    """Ein Modell, dessen Vektoren sagen, zu welchem Text sie gehören.

    Der Text ist eine Zahl als Zeichenkette; der Vektor trägt sie an erster
    Stelle. Damit ist jede Vertauschung sichtbar — anders als bei echten
    Vektoren, wo eine falsche Zuordnung wie ein Ergebnis aussieht.

    Die Attrappe weist selbst ab, was zu groß ist: ohne das prüften die Tests
    nur, dass das Zerlegen etwas tut, nicht dass es nötig war.
    """
    def embed(texte: list[str]) -> np.ndarray:
        if len(texte) > grenze:
            raise AssertionError(
                f"The batch size limit is {grenze}. Your batch size is {len(texte)}."
            )
        if gesehen is not None:
            gesehen.append(len(texte))
        return np.array([[float(t), 0.5, -0.5] for t in texte], dtype=np.float32)

    return embed


# ── Die Reihenfolge ───────────────────────────────────────────────────────────

def test_ueber_tausend_texte_behalten_ihre_reihenfolge():
    """Der Fall aus der Fehlermeldung, plus die Frage, auf die es ankommt."""
    texte = [str(i) for i in range(1100)]
    embed = _gestapelt(attrappe(1000), 1000)

    ergebnis = embed(texte)

    assert ergebnis.shape == (1100, 3)
    # Zeile i trägt die Zahl aus Text i — Stück für Stück, nicht nur am Rand.
    assert np.array_equal(ergebnis[:, 0], np.arange(1100, dtype=np.float32))


def test_die_grenze_wird_wirklich_eingehalten():
    """Sonst prüfte der Test darüber nur, dass vstack funktioniert."""
    gesehen: list[int] = []
    embed = _gestapelt(attrappe(1000, gesehen), 1000)

    embed([str(i) for i in range(2500)])

    assert gesehen == [1000, 1000, 500]
    assert max(gesehen) <= 1000


@pytest.mark.parametrize("anzahl", [1, 999, 1000, 1001, 2000, 3000, 3001])
def test_jede_menge_kommt_vollstaendig_und_in_ordnung_zurueck(anzahl: int):
    """Die Ränder der Stapelgrenze sind die Stellen, an denen sich verzählt wird."""
    embed = _gestapelt(attrappe(1000), 1000)
    ergebnis = embed([str(i) for i in range(anzahl)])
    assert len(ergebnis) == anzahl
    assert np.array_equal(ergebnis[:, 0], np.arange(anzahl, dtype=np.float32))


def test_die_attrappe_faellt_ohne_zerlegung_wirklich_um():
    """Die Gegenprobe: ohne _gestapelt schlägt genau der Betriebsfehler zu.

    Ohne diesen Test wüsste niemand, ob die Tests darüber überhaupt etwas
    absichern oder nur eine Schleife nachfahren, die es nicht braucht.
    """
    with pytest.raises(AssertionError, match="batch size limit is 1000"):
        attrappe(1000)([str(i) for i in range(1100)])


# ── Was der Aufrufer nicht merken soll ────────────────────────────────────────

def test_unter_der_grenze_wird_nicht_zerlegt():
    """Ein Aufruf bleibt ein Aufruf — sonst kostete jede kleine Anfrage mehr."""
    gesehen: list[int] = []
    embed = _gestapelt(attrappe(1000, gesehen), 1000)
    embed([str(i) for i in range(949)])      # die Größe von 'ber'
    assert gesehen == [949]


def test_leere_eingabe_ruft_nichts_auf():
    """Kein Aufruf über das Netz für nichts, und kein Absturz."""
    gesehen: list[int] = []
    embed = _gestapelt(attrappe(1000, gesehen), 1000)
    ergebnis = embed([])
    assert gesehen == []
    assert len(ergebnis) == 0
    assert ergebnis.ndim == 2


def test_zerlegen_aendert_die_werte_nicht():
    """Die Normalisierung ist zeilenweise, also kennt ein Stapel seine Nachbarn nicht.

    Geprüft an einer Attrappe, die genau so rechnet wie VoyageProvider: jede
    Zeile durch ihre eigene Länge. Wäre irgendwo über den Stapel gemittelt,
    ergäbe ein Stapel von 500 andere Zahlen als einer von 2000.
    """
    def normierend(texte: list[str]) -> np.ndarray:
        roh = np.array([[float(t), 1.0, 2.0] for t in texte], dtype=np.float32)
        return roh / np.linalg.norm(roh, axis=1, keepdims=True)

    texte = [str(i) for i in range(2000)]
    in_einem = normierend(texte)
    in_stapeln = _gestapelt(normierend, 500)(texte)

    assert np.allclose(in_einem, in_stapeln)


def test_ein_zu_kurzer_stapel_wird_gemeldet_statt_verschoben():
    """Käme ein Stapel kürzer zurück, verschöbe sich ab dort jede Zuordnung.

    Eine Behauptung über fremden Code — deshalb geprüft und nicht geglaubt.
    """
    def verschluckt(texte: list[str]) -> np.ndarray:
        gekuerzt = texte[:-1] if len(texte) > 1 else texte
        return np.array([[float(t)] for t in gekuerzt], dtype=np.float32)

    embed = _gestapelt(verschluckt, 1000)
    with pytest.raises(AnbieterFehler) as fehler:
        embed([str(i) for i in range(1500)])
    assert fehler.value.code == "stapel_unvollstaendig"


# ── Die Grenze steht in anbieter.toml ─────────────────────────────────────────

def test_die_grenze_kommt_aus_der_datei_und_nicht_aus_dem_code():
    """Eine Eigenschaft des Anbieters wie das Modell und die Schwelle."""
    assert embedding_stapel("voyage") == 1000
    # Die lokalen Modelle stapeln selbst und kennen keine Grenze je Aufruf.
    assert embedding_stapel("local") is None


def test_die_grenze_steht_nirgends_als_zahl_im_code():
    """Wer sie hebt, soll eine Zeile in anbieter.toml ändern, nicht Code.

    Über den Syntaxbaum und nicht über die Zeichenkette: in der Prosa der
    Docstrings kommt die 1000 als Beispiel vor, und das ist kein Wert, der
    irgendwo wirkt. Geprüft wird, dass keine Zahl-Literale mit ihr existieren.
    """
    import ast
    from pathlib import Path

    baum = ast.parse(Path("src/neu/anbieter.py").read_text(encoding="utf-8"))
    zahlen = [
        k.value for k in ast.walk(baum)
        if isinstance(k, ast.Constant) and isinstance(k.value, int)
        and not isinstance(k.value, bool)
    ]
    assert 1000 not in zahlen
