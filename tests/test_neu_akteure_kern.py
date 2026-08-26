"""
test_neu_akteure_kern.py — der Akteurskern ohne Datenbank und ohne Modell

Der Erkenner und das Embedding kommen als Funktionen herein; hier sind es
Attrappen. Geprüft wird das Verfahren, nicht das Modell.
"""

import numpy as np
import pytest

from src.neu.akteure import kern
from src.neu.akteure.kern import Akteur, Fund


# ── Stückelung ────────────────────────────────────────────────────────────────

def test_kurzer_text_bleibt_ein_stueck():
    assert kern.stuecke("Ein kurzer Satz.") == ["Ein kurzer Satz."]


def test_stueckelung_trennt_an_satzgrenzen():
    satz = "A" * 1500 + ". " + "B" * 900
    teile = kern.stuecke(satz, max_zeichen=2000)
    assert len(teile) == 2
    assert teile[0].endswith(".")
    assert teile[1].startswith("B")


def test_stueckelung_ohne_satzgrenze_schneidet_hart():
    teile = kern.stuecke("X" * 5000, max_zeichen=2000)
    assert [len(t) for t in teile] == [2000, 2000, 1000]


# ── Erkennung ─────────────────────────────────────────────────────────────────

def _vorhersage(treffer_je_stueck):
    """Attrappe: gibt je Aufruf die nächste vorbereitete Trefferliste."""
    reste = list(treffer_je_stueck)

    def vorhersage(stueck, labels, schwelle):
        return reste.pop(0) if reste else []

    return vorhersage


# Der Kern hat keine Vorgabe mehr — die produktive Schwelle steht in
# anbieter.toml. Was hier steht, ist die Zahl dieses Tests.
SCHWELLE = 0.7


def test_labels_werden_auf_vier_typen_abgebildet():
    funde, unbekannt = kern.erkenne(
        ["egal"],
        _vorhersage([[
            {"text": "Kayali", "label": "Person"},
            {"text": "Damaskus", "label": "geographischer Ort"},
            {"text": "Al-Fatat", "label": "politische Bewegung"},
            {"text": "Panislamismus", "label": "religiöse Strömung oder Konzept"},
        ]]),
        schwelle=SCHWELLE,
    )
    assert [(f.normalform, f.typ) for f in funde] == [
        ("Kayali", "Person"),
        ("Damaskus", "Ort"),
        ("Al-Fatat", "Organisation"),
        ("Panislamismus", "Konzept"),
    ]
    assert unbekannt == {}


def test_unbekanntes_label_wird_gemeldet_und_nicht_zu_konzept():
    funde, unbekannt = kern.erkenne(
        ["egal"],
        _vorhersage([[
            {"text": "Kritik der reinen Vernunft", "label": "Werk"},
            {"text": "Anderes Werk", "label": "Werk"},
        ]]),
        schwelle=SCHWELLE,
    )
    # Die Vorlage machte hier still ein 'Konzept' daraus.
    assert [f.typ for f in funde] == [None, None]
    assert unbekannt == {"Werk": 2}


def test_kleinschreib_filter_verwirft_kurze_kleinbuchstaben():
    funde, _ = kern.erkenne(
        ["egal"],
        _vorhersage([[
            {"text": "und", "label": "Person"},       # klein, < 5 → weg
            {"text": "fatat", "label": "Organisation"},  # klein, ≥ 5 → bleibt
            {"text": "Bey", "label": "Person"},       # groß → bleibt
        ]]),
        schwelle=SCHWELLE,
    )
    assert [f.normalform for f in funde] == ["fatat", "Bey"]


def test_landkarte_fuehrt_kurzform_auf_vollnamen_zurueck():
    landkarte = kern.alias_landkarte([
        Akteur(normalform="Ismail Enver", typ="Person", aliase=["Enver"])
    ])
    funde, _ = kern.erkenne(
        ["egal"], _vorhersage([[{"text": "Enver", "label": "Person"}]]),
        landkarte=landkarte, schwelle=SCHWELLE,
    )
    assert funde[0].normalform == "Ismail Enver"


def test_abgelehnte_normalform_wird_uebersprungen():
    funde, _ = kern.erkenne(
        ["egal"],
        _vorhersage([[
            {"text": "Berlin", "label": "geographischer Ort"},
            {"text": "Damaskus", "label": "geographischer Ort"},
        ]]),
        abgelehnt=["berlin"], schwelle=SCHWELLE,
    )
    assert [f.normalform for f in funde] == ["Damaskus"]


def test_abgelehnt_prueft_nur_die_normalform_nicht_die_aliase():
    # Grund aus der Vorlage: ein abgelehntes "Paris" darf "Paris Agreement"
    # nicht mitblocken.
    funde, _ = kern.erkenne(
        ["egal"],
        _vorhersage([[{"text": "Paris Agreement", "label": "Organisation"}]]),
        abgelehnt=["Paris"], schwelle=SCHWELLE,
    )
    assert [f.normalform for f in funde] == ["Paris Agreement"]


# ── Zusammenfassen über Namensmengen ──────────────────────────────────────────

def test_zusammenfassen_ueber_gemeinsamen_alias():
    ergebnis = kern.zusammenfassen([[
        Akteur("Ismail Enver", "Person", ["Enver Pascha"]),
        Akteur("Enver Pascha", "Person", ["Enver Bey"]),
    ]])
    assert len(ergebnis) == 1
    assert ergebnis[0].normalform == "Ismail Enver"
    assert ergebnis[0].aliase == ["Enver Pascha", "Enver Bey"]


def test_zusammenfassen_vergleicht_ohne_ruecksicht_auf_gross_klein():
    ergebnis = kern.zusammenfassen([[
        Akteur("Damaskus", "Ort", []),
        Akteur("damaskus", "Ort", []),
    ]])
    assert len(ergebnis) == 1
    assert ergebnis[0].normalform == "Damaskus"


def test_zusammenfassen_ohne_beruehrung_bleibt_getrennt():
    ergebnis = kern.zusammenfassen([[
        Akteur("Atatürk", "Person", []),
        Akteur("Mustafa Kemal", "Person", []),
    ]])
    assert len(ergebnis) == 2


def test_leere_normalform_faellt_weg():
    assert kern.zusammenfassen([[Akteur("   ", "Person", [])]]) == []


def test_funde_zu_akteuren_nimmt_den_typ_des_ersten_vorkommens():
    # Wie die Vorlage: _merge legt den Typ beim ersten Treffer fest. Abgestimmt
    # wird erst eine Stufe spaeter, zwischen den Namen eines Clusters.
    akteure = kern.funde_zu_akteuren([
        Fund("Enver", "Organisation"),
        Fund("Enver", "Person"),
        Fund("Enver", "Person"),
    ])
    assert len(akteure) == 1
    assert akteure[0].typ == "Organisation"


# ── Union-Find über Ähnlichkeit ───────────────────────────────────────────────

def _einheitsvektoren(gruppen: list[list[int]], anzahl: int) -> np.ndarray:
    """Vektoren, die genau innerhalb der Gruppen Ähnlichkeit 1.0 ergeben."""
    dim = len(gruppen)
    embs = np.zeros((anzahl, dim), dtype=np.float32)
    for g, indizes in enumerate(gruppen):
        for i in indizes:
            embs[i, g] = 1.0
    return embs


def test_gruppierung_fuehrt_ueber_der_schwelle_zusammen():
    akteure = [Akteur("Ataturk", "Person", []), Akteur("Atatürk", "Person", [])]
    embs = _einheitsvektoren([[0, 1]], 2)
    ergebnis = kern.gruppiere(akteure, embs, 0.92)
    assert len(ergebnis) == 1
    assert ergebnis[0].aliase == ["Ataturk"] or ergebnis[0].aliase == ["Atatürk"]


def test_gruppierung_laesst_unter_der_schwelle_getrennt():
    akteure = [Akteur("Atatürk", "Person", []), Akteur("Mustafa Kemal", "Person", [])]
    embs = _einheitsvektoren([[0], [1]], 2)
    assert len(kern.gruppiere(akteure, embs, 0.92)) == 2


def test_gruppierung_ist_transitiv():
    # A~B und B~C führen A, B und C zusammen, auch wenn A~C darunter liegt.
    embs = np.array([
        [1.0, 0.0],
        [0.7, 0.714],   # zu A und C je ~0.7, zu keinem 1.0
        [0.0, 1.0],
    ], dtype=np.float32)
    embs = embs / np.linalg.norm(embs, axis=1, keepdims=True)
    akteure = [Akteur("A-Name", None, []), Akteur("B-Name", None, []),
               Akteur("C-Name", None, [])]
    assert float(embs[0] @ embs[2]) < 0.7
    ergebnis = kern.gruppiere(akteure, embs, 0.7)
    assert len(ergebnis) == 1


def test_normalformwahl_nimmt_meiste_woerter():
    assert kern.waehle_normalform(["Enver", "Ismail Enver"]) == "Ismail Enver"


def test_normalformwahl_nimmt_bei_gleichstand_den_laengeren():
    assert kern.waehle_normalform(["Abdulhamid", "Abdülhamid II."]) == "Abdülhamid II."


def test_typ_mehrheit_bei_gleichstand_nimmt_den_ersten():
    assert kern.typ_mehrheit(["Ort", "Person"]) == "Ort"


def test_typ_mehrheit_ohne_typen_bleibt_ohne():
    assert kern.typ_mehrheit([]) is None
    assert kern.typ_mehrheit([None, None, "Person"]) is None


def test_gruppierung_setzt_normalform_nicht_in_die_eigene_aliasliste():
    akteure = [Akteur("Mustafa Kemal", "Person", ["Mustafa Kemal", "Kemal"])]
    ergebnis = kern.gruppiere(akteure, _einheitsvektoren([[0]], 1), 0.92)
    assert ergebnis[0].aliase == ["Kemal"]


# ── Verschmelzen von Hand ─────────────────────────────────────────────────────

def test_verschmelzen_behaelt_die_gewaehlte_normalform():
    ergebnis = kern.verschmelzen(
        [Akteur("Atatürk", "Person", ["Ataturk"]),
         Akteur("Mustafa Kemal", "Person", [])],
        behalten="Mustafa Kemal",
    )
    assert ergebnis.normalform == "Mustafa Kemal"
    assert ergebnis.aliase == ["Ataturk", "Atatürk"]


def test_verschmelzen_kennt_die_gewaehlte_normalform_nicht():
    with pytest.raises(ValueError):
        kern.verschmelzen([Akteur("A", None, [])], behalten="B")


# ── Wortgrenz-Regex ───────────────────────────────────────────────────────────

def test_regex_trifft_nur_an_wortgrenzen():
    muster = kern.muster_fuer(Akteur("Enver", "Person", []))
    assert muster.search("Ismail Enver kam an.")
    assert not muster.search("Enverland")
    assert not muster.search("Nachenver")


def test_regex_ist_unabhaengig_von_gross_und_klein():
    muster = kern.muster_fuer(Akteur("Damaskus", "Ort", []))
    assert muster.search("in damaskus")


def test_regex_bevorzugt_die_laengste_alternative():
    muster = kern.muster_fuer(Akteur("Abd al-Hamid al-Zahrawi", "Person", ["Zahrawi"]))
    treffer = muster.search("über Abd al-Hamid al-Zahrawi sprach man")
    assert treffer.group(0) == "Abd al-Hamid al-Zahrawi"


def test_fundstellen_zeigen_auf_den_namen_im_text():
    text = "Im Jahr 1908 sprach Enver in Damaskus."
    muster = kern.muster_fuer(Akteur("Enver", "Person", []))
    stellen = kern.fundstellen([(7, text)], muster)
    assert len(stellen) == 1
    assert text[stellen[0].start:stellen[0].ende] == "Enver"
    assert stellen[0].einheit_id == 7


def test_fundstellen_zaehlen_jedes_vorkommen():
    text = "Fatat und Fatat und nochmals Fatat"
    muster = kern.muster_fuer(Akteur("Fatat", "Organisation", []))
    stellen = kern.fundstellen([(1, text)], muster)
    assert len(stellen) == 3
    assert [text[s.start:s.ende] for s in stellen] == ["Fatat"] * 3


def test_zu_kurzer_alias_wird_nicht_gesucht():
    muster = kern.muster_fuer(Akteur("Al-Fatat", "Organisation", ["A"]))
    assert not muster.search("A kam")
    assert muster.search("Al-Fatat kam")


def test_akteur_ohne_brauchbaren_namen_bekommt_kein_muster():
    assert kern.muster_fuer(Akteur("A", None, [])) is None


# ── Levenshtein und Band ──────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,erwartet", [
    ("Enver", "Enver", 0),
    ("Enver", "enver", 0),
    ("Abdülhamid", "Abdulhamid", 1),
    ("Kayali", "Kayalis", 1),
    ("Atatürk", "Mustafa Kemal", 10),
])
def test_levenshtein(a, b, erwartet):
    assert kern.levenshtein(a, b) == erwartet


def test_band_haengt_an_der_schwelle():
    # MiniLM: die heutigen 0,80–0,91
    assert kern.band(0.92) == (0.79, 0.91)
    # Voyage: verschoben, nicht dieselbe Zahl
    assert kern.band(0.78) == (0.65, 0.77)


# ── Verschmelzungskandidaten ──────────────────────────────────────────────────

def test_kandidat_wegen_gemeinsamem_alias():
    akteure = [Akteur("Ismail Enver", "Person", ["Enver"]),
               Akteur("Enver Pascha", "Person", ["Enver"])]
    ergebnis = kern.kandidaten(akteure, None, 0.92)
    assert [(k.a, k.b, k.grund) for k in ergebnis] == [(0, 1, "alias")]


def test_kandidat_wegen_schreibweise():
    akteure = [Akteur("Abdülhamid", "Person", []), Akteur("Abdulhamid", "Person", [])]
    ergebnis = kern.kandidaten(akteure, None, 0.92)
    assert ergebnis[0].grund == "schreibweise"
    assert ergebnis[0].mass == 1.0


def test_kandidat_wegen_aehnlichkeit_im_band():
    akteure = [Akteur("Al-Fatat", None, []), Akteur("Al-Ahd", None, [])]
    # Ähnlichkeit 0,85: im Band unterhalb von 0,92, aber nicht verschmolzen
    embs = np.array([[1.0, 0.0], [0.85, np.sqrt(1 - 0.85**2)]], dtype=np.float32)
    ergebnis = kern.kandidaten(akteure, embs, 0.92)
    assert ergebnis[0].grund == "aehnlichkeit"
    assert ergebnis[0].mass == pytest.approx(0.85, abs=0.001)


def test_aehnlichkeit_oberhalb_der_schwelle_ist_kein_kandidat():
    # Was verschmolzen wurde, wird nicht noch einmal vorgeschlagen. Namen ohne
    # Schreibweisen-Naehe, damit wirklich nur das Band geprueft wird.
    akteure = [Akteur("Al-Fatat", None, []), Akteur("Damaskus", None, [])]
    embs = np.array([[1.0, 0.0], [0.99, np.sqrt(1 - 0.99**2)]], dtype=np.float32)
    assert kern.kandidaten(akteure, embs, 0.92) == []


def test_jedes_paar_erscheint_nur_einmal_mit_dem_haerteren_grund():
    # Alias-Überschneidung UND kleiner Editierabstand: alias gewinnt.
    akteure = [Akteur("Abdülhamid", "Person", ["Hamid"]),
               Akteur("Abdulhamid", "Person", ["Hamid"])]
    ergebnis = kern.kandidaten(akteure, None, 0.92)
    assert len(ergebnis) == 1
    assert ergebnis[0].grund == "alias"


def test_ohne_embeddings_bleiben_die_beiden_textregeln():
    akteure = [Akteur("Damaskus", "Ort", []), Akteur("Beirut", "Ort", [])]
    assert kern.kandidaten(akteure, None, 0.92) == []


def test_kandidaten_beschraenken_nicht_auf_ein_paar_je_akteur():
    # Die Vorlage ließ je Entity höchstens ein Paar zu — eine Krücke der
    # Oberfläche, weil ein Verschmelzen dort die Listenplätze verschob.
    akteure = [Akteur("Abdülhamid", "Person", []),
               Akteur("Abdulhamid", "Person", []),
               Akteur("Abdulhamit", "Person", [])]
    ergebnis = kern.kandidaten(akteure, None, 0.92)
    assert len(ergebnis) == 3
