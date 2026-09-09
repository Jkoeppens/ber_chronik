"""
tests/test_neu_chat_kern.py — der Kern des Chats

Ohne Datenbank, ohne Netz, ohne Modell. Geprüft werden die drei Entscheidungen,
die der Kern trifft: welche Stichwörter aus einer Frage werden, wie zwei
Ranglisten zu einer werden, und was am Ende als Quelle gilt.

Ausführen:
  python3 -m pytest tests/test_neu_chat_kern.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.chat import kern  # noqa: E402
from src.neu.chat.kern import Einheit  # noqa: E402


def e(einheit_id: int, text: str, jahr: int | None = None) -> Einheit:
    return Einheit(id=einheit_id, anker=f"main-e{einheit_id}", jahr=jahr, text=text)


# ── Stichwörter ───────────────────────────────────────────────────────────────

def test_stichwoerter_wirft_fuellwoerter_weg() -> None:
    assert kern.stichwoerter("Wer ist Mehdorn?") == ["mehdorn"]


def test_stichwoerter_nimmt_jahreszahlen_auf() -> None:
    """Der eine Unterschied zur Vorlage.

    Deren Regex war r"[A-Za-zÄÖÜäöüß]+" und ließ Ziffern liegen. 'Was' und
    'war' sind Füllwörter, '2012' war das einzige verwertbare Wort — und fiel
    heraus. Die Frage ergab null Stichwörter und damit null Treffer.
    """
    assert kern.stichwoerter("Was war 2012?") == ["2012"]


def test_stichwoerter_nimmt_jahr_mit_anhang() -> None:
    assert kern.stichwoerter("Was geschah in den 1990er Jahren?") == [
        "geschah", "1990er", "jahren"]


@pytest.mark.parametrize("frage", ["Wer war das?", "Und dann?", "Wie und wann?"])
def test_frage_ganz_aus_fuellwoertern_gibt_nichts(frage: str) -> None:
    assert kern.stichwoerter(frage) == []


def test_stichwoerter_kuerzt_auf_sechs() -> None:
    frage = "Kosten Termine Klagen Technik Personal Beschluss Vertrag Planung"
    assert len(kern.stichwoerter(frage)) == kern.STICHWOERTER


def test_zu_kurze_woerter_zaehlen_nicht() -> None:
    # 'BER' hat drei Zeichen — wie in der Vorlage zu kurz. Absichtlich
    # unverändert: die Grenze zu senken zöge Rauschen nach sich.
    assert kern.stichwoerter("Wer baute den BER?") == ["baute"]


# ── Stichwortsuche ────────────────────────────────────────────────────────────

def test_stichwort_rangliste_zaehlt_treffer_nicht_fundstellen() -> None:
    einheiten = [
        e(1, "Kosten und Kosten und nochmals Kosten"),   # 1 Wort, 3-mal
        e(2, "Kosten und Termine"),                      # 2 Wörter
    ]
    assert kern.stichwort_rangliste(einheiten, ["kosten", "termine"]) == [2, 1]


def test_stichwort_rangliste_ist_ohne_gross_und_klein() -> None:
    assert kern.stichwort_rangliste([e(7, "MEHDORN trat zurück")], ["mehdorn"]) == [7]


def test_ohne_treffer_steht_nichts_drin() -> None:
    assert kern.stichwort_rangliste([e(1, "Etwas ganz anderes")], ["mehdorn"]) == []


def test_ohne_stichwoerter_ist_die_liste_leer() -> None:
    assert kern.stichwort_rangliste([e(1, "Text")], []) == []


def test_gleichstand_entscheidet_die_kennung() -> None:
    """Wiederholbar statt von der Eingabereihenfolge abhängig.

    Gemessen an ber liegen bei einer typischen Frage 43 von 45 Treffern
    gleichauf. In der Vorlage entschied dort die Position in der Datei.
    """
    einheiten = [e(9, "Kosten"), e(3, "Kosten"), e(5, "Kosten")]
    assert kern.stichwort_rangliste(einheiten, ["kosten"]) == [3, 5, 9]
    gedreht = list(reversed(einheiten))
    assert kern.stichwort_rangliste(gedreht, ["kosten"]) == [3, 5, 9]


# ── Ähnlichkeit ───────────────────────────────────────────────────────────────

def test_aehnlichkeiten_sind_kosinus() -> None:
    frage = np.array([1.0, 0.0], dtype=np.float32)
    einheiten = np.array([[2.0, 0.0], [0.0, 5.0], [-1.0, 0.0]], dtype=np.float32)
    werte = kern.aehnlichkeiten(frage, einheiten)
    assert werte == pytest.approx([1.0, 0.0, -1.0], abs=1e-6)


def test_aehnlichkeit_normiert_selbst() -> None:
    """Ein unnormierter Vektor darf keine Ähnlichkeit über 1 ergeben."""
    frage = np.array([100.0, 0.0], dtype=np.float32)
    werte = kern.aehnlichkeiten(frage, np.array([[7.0, 0.0]], dtype=np.float32))
    assert werte[0] == pytest.approx(1.0, abs=1e-6)


def test_aehnlichkeits_rangliste_ordnet_absteigend() -> None:
    ids = [10, 20, 30]
    werte = np.array([0.1, 0.9, 0.5], dtype=np.float32)
    assert kern.aehnlichkeits_rangliste(ids, werte) == [20, 30, 10]


def test_aehnlichkeits_rangliste_schneidet_ab() -> None:
    ids = [1, 2, 3, 4]
    werte = np.array([0.4, 0.3, 0.2, 0.1], dtype=np.float32)
    assert kern.aehnlichkeits_rangliste(ids, werte, hoechstens=2) == [1, 2]


def test_leere_eingabe_gibt_leere_rangliste() -> None:
    assert kern.aehnlichkeits_rangliste([], np.zeros(0)) == []
    assert kern.aehnlichkeiten(np.zeros(3), np.zeros((0, 3))).size == 0


# ── Zusammenführen ────────────────────────────────────────────────────────────

def test_rrf_rechnet_wie_versprochen() -> None:
    """sum(1 / (60 + rang)), Rang ab 1."""
    zusammen = kern.verschmelzen([[1, 2], [2, 1]])
    assert zusammen == [1, 2]   # beide gleichauf, Kennung entscheidet
    # 7 steht in einer Liste ganz oben, 8 in beiden auf Platz 2.
    zusammen = kern.verschmelzen([[7, 8], [9, 8]])
    assert zusammen[0] == 8


def test_einigkeit_schlaegt_zuversicht() -> None:
    """Wer in beiden Listen mittelmäßig steht, gewinnt gegen einen Erstplatzierten.

    Das ist der Grund für RRF und nicht für eine gewichtete Summe: keiner der
    beiden Wege ist genau genug, dass sein erster Platz allein reichen sollte.
    """
    nach_wort = [1, 2, 3, 4, 5]
    nach_sinn = [9, 8, 3, 7, 6]
    assert kern.verschmelzen([nach_wort, nach_sinn])[0] == 3


def test_ein_leerer_weg_stoert_nicht() -> None:
    assert kern.verschmelzen([[4, 5, 6], []]) == [4, 5, 6]
    assert kern.verschmelzen([[], [4, 5, 6]]) == [4, 5, 6]
    assert kern.verschmelzen([[], []]) == []


def test_rrf_schneidet_auf_zwanzig_ab() -> None:
    viele = list(range(100))
    assert len(kern.verschmelzen([viele])) == kern.ABSAETZE


def test_rrf_ist_von_der_reihenfolge_der_listen_unabhaengig() -> None:
    a, b = [1, 2, 3], [3, 4, 5]
    assert kern.verschmelzen([a, b]) == kern.verschmelzen([b, a])


def test_die_daempfung_ist_das_stellrad_und_60_ist_gesetzt() -> None:
    """Warum 60 und nicht 0 — festgehalten, damit die Zahl nicht wandert.

    Einheit 8 steht in der einen Liste auf Platz 2, in der anderen auf Platz 3.
    Die Einheiten 7 und 1 stehen je einmal auf Platz 1.

      daempfung=0    8 bekommt 1/2 + 1/3 = 0,83, die Erstplatzierten je 1/1 = 1
                     → ein einzelner erster Platz gewinnt
      daempfung=60   8 bekommt 1/62 + 1/63 = 0,0320, die anderen je 1/61 = 0,0164
                     → Einigkeit gewinnt

    Das zweite ist gewollt: keiner der beiden Wege ist gut genug, dass sein
    erster Platz allein den Ausschlag geben sollte.
    """
    nach_wort, nach_sinn = [7, 8, 9], [1, 2, 8]
    assert kern.verschmelzen([nach_wort, nach_sinn], daempfung=0)[0] != 8
    assert kern.verschmelzen([nach_wort, nach_sinn], daempfung=60)[0] == 8
    assert kern.RRF_DAEMPFUNG == 60


# ── Prompt ────────────────────────────────────────────────────────────────────

def test_prompt_traegt_jeden_anker_vor_seinem_absatz() -> None:
    absaetze = [e(1, "Erster Absatz", jahr=1996), e(2, "Zweiter", jahr=None)]
    prompt = kern.benutzer_prompt("Warum?", absaetze)
    assert "Frage: Warum?" in prompt
    assert "Auszüge (2 gesamt):" in prompt
    assert "[main-e1] 1996: Erster Absatz" in prompt
    assert "[main-e2] ?: Zweiter" in prompt


def test_systemprompt_nennt_ein_ankerbeispiel_der_neuen_form() -> None:
    """Die Vorlage nannte [PREFIX-s0012] — eine Form, die es nicht mehr gibt."""
    assert "main-e719" in kern.SYSTEM
    assert "s0012" not in kern.SYSTEM


# ── Was das Modell wirklich belegt hat ────────────────────────────────────────

def test_genannte_quellen_liest_die_anker_aus_dem_text() -> None:
    antwort = "Die Kosten stiegen [main-e12]. Später fiel der Termin [main-e13]."
    assert kern.genannte_quellen(antwort, ["main-e12", "main-e13", "main-e14"]) == [
        "main-e12", "main-e13"]


def test_nicht_angebotene_anker_gelten_nicht() -> None:
    """Ein erfundener Anker fände in viz/ ohnehin keinen Absatz."""
    antwort = "Das steht so da [erfunden-e999] und das auch [main-e12]."
    assert kern.genannte_quellen(antwort, ["main-e12"]) == ["main-e12"]


def test_jede_quelle_nur_einmal_und_in_der_reihenfolge_des_textes() -> None:
    antwort = "[main-e5] ... [main-e3] ... [main-e5] ..."
    assert kern.genannte_quellen(antwort, ["main-e3", "main-e5"]) == ["main-e5", "main-e3"]


@pytest.mark.parametrize("form", ["[main-e7]", "[[main-e7]]", "[source: main-e7]"])
def test_auch_die_formen_die_der_prompt_verbietet(form: str) -> None:
    """Der Systemprompt untersagt sie; das Modell schreibt sie trotzdem.

    viz/search.js klaubt dieselben drei Formen aus dem Fließtext. Was der Server
    zählt, muss deshalb dasselbe sein, was der Browser verlinkt.
    """
    assert kern.genannte_quellen(f"Beleg {form}.", ["main-e7"]) == ["main-e7"]


def test_ohne_beleg_ist_die_liste_leer() -> None:
    """Der Fall, den die Vorlage nie zeigen konnte.

    Dort standen immer die 20 angebotenen Absätze unter 'Verwendete Quellen',
    auch wenn die Antwort keinen einzigen nannte.
    """
    assert kern.genannte_quellen("Eine Antwort ganz ohne Klammern.", ["main-e1"]) == []
