"""
tests/test_neu_export_kern.py — der Exportkern ohne Datenbank

Geprüft wird, was viz/ zu sehen bekommt: die Gestalt der Einträge, die
Farbzuordnung, die abgeleitete Spanne, die Alias-Tabelle und das Netz.

Ausführen:
  python3 -m pytest tests/test_neu_export_kern.py -v
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.export import kern  # noqa: E402
from src.neu.export.kern import Akteur, Einheit  # noqa: E402


def _e(**kw) -> Einheit:
    grund = dict(id=1, quelle_id="q", text="Text")
    grund.update(kw)
    return Einheit(**grund)


# ── eintraege ─────────────────────────────────────────────────────────────────

def test_jede_einheit_wird_ein_eintrag_auch_ohne_datum():
    """Undatierte fehlen auf der Achse, aber nicht in der Datei."""
    liste = kern.eintraege([_e(id=1, jahr_von=1908), _e(id=2), _e(id=3, jahr_von=1911)])
    assert len(liste) == 3
    assert [x["year"] for x in liste] == [1908, None, 1911]
    assert liste[1]["date_js"] is None


def test_date_js_aus_vollem_datum():
    liste = kern.eintraege([_e(datum="1989-06-15", jahr_von=1989)])
    assert liste[0]["date_js"] == "1989-06-15"
    assert liste[0]["date_raw"] == "1989-06-15"


def test_date_js_aus_jahr():
    liste = kern.eintraege([_e(datum="1908", jahr_von=1908)])
    assert liste[0]["date_js"] == "1908-01-01"


def test_date_js_aus_jahr_von_ohne_datumsfeld():
    liste = kern.eintraege([_e(jahr_von=1908)])
    assert liste[0]["date_js"] == "1908-01-01"
    assert liste[0]["date_raw"] == "1908"


def test_monatsdatum_faellt_auf_das_jahr_zurueck():
    # "1989-06" trifft weder das Voll- noch das Jahresmuster.
    liste = kern.eintraege([_e(datum="1989-06", jahr_von=1989)])
    assert liste[0]["date_js"] == "1989-01-01"
    assert liste[0]["date_raw"] == "1989-06"


def test_tote_felder_fehlen():
    """causal_theme, date_precision, confidence, is_quote liest viz/ nicht."""
    eintrag = kern.eintraege([_e(jahr_von=1908)])[0]
    assert set(eintrag) == {
        "id", "doc_anchor", "year", "date_raw", "date_js", "text",
        "event_type", "source_name", "source_date", "url", "actors",
    }


def test_anker_ist_quelle_und_einheit():
    assert kern.anker(_e(id=42, quelle_id="56da8203")) == "56da8203-e42"


def test_kategorie_wird_gegen_die_taxonomie_normalisiert():
    liste = kern.eintraege(
        [_e(kategorie="Kategorie: Kosten")], kategorienamen=["Kosten", "Termin"]
    )
    assert liste[0]["event_type"] == "Kosten"


def test_unbekannte_kategorie_wird_null():
    liste = kern.eintraege([_e(kategorie="Wetter")], kategorienamen=["Kosten"])
    assert liste[0]["event_type"] is None


def test_ohne_taxonomie_bleibt_die_kategorie_stehen():
    liste = kern.eintraege([_e(kategorie="Kosten")])
    assert liste[0]["event_type"] == "Kosten"


def test_source_date_faellt_auf_das_datum_zurueck():
    ohne = kern.eintraege([_e(datum="1908", jahr_von=1908)])[0]
    assert ohne["source_date"] == "1908"
    mit = kern.eintraege([_e(datum="1908", jahr_von=1908,
                             publikationsdatum="01.01.1908")])[0]
    assert mit["source_date"] == "01.01.1908"


def test_url_ist_leer_statt_null():
    # viz/panel.js prüft auf Wahrheitswert; die Vorlage schrieb "".
    assert kern.eintraege([_e()])[0]["url"] == ""


# ── Spanne ────────────────────────────────────────────────────────────────────

def test_spanne_ist_min_jahr_von_bis_max_jahr_bis():
    einheiten = [_e(id=1, jahr_von=1908), _e(id=2, jahr_von=1780),
                 _e(id=3, jahr_von=1900, jahr_bis=1995)]
    assert kern.spanne(einheiten) == (1780, 1995)


def test_spanne_ignoriert_undatierte():
    assert kern.spanne([_e(id=1), _e(id=2, jahr_von=1908)]) == (1908, 1908)


def test_spanne_ohne_datierte_einheit_ist_leer():
    assert kern.spanne([_e(id=1), _e(id=2)]) == (None, None)


def test_spanne_kommt_nicht_aus_einer_gespeicherten_angabe():
    """Der Zeitraum ist eine Ableitung — kein Feld kann ihn verengen."""
    einheiten = [_e(id=1, jahr_von=1780), _e(id=2, jahr_von=1995)]
    meta = kern.metadaten("T", [], einheiten)
    assert (meta["year_min"], meta["year_max"]) == (1780, 1995)


# ── Keine Farben ──────────────────────────────────────────────────────────────
# Bis September 2026 rechnete kern.farbzuordnung() aus CAT_PALETTE und
# NODE_PALETTE die Felder color_map und node_color_map. Hier standen vier
# Tests darauf, einer davon hielt ausdrücklich fest, dass sich beim Löschen in
# der Mitte alle nachfolgenden Farben verschieben. Beides ist weg: eine Farbe
# ist Darstellung und gehört nicht in den Export. Vergeben wird sie in
# viz/highlight.js, aus dem Namen statt aus dem Listenplatz.

def test_der_export_vergibt_keine_farben():
    """Die Gegenprobe zur Entscheidung — kein Farbfeld, keine Palette."""
    taxonomie = [{"name": "Kosten", "description": "Geld", "keywords": []}]
    meta = kern.metadaten("T", taxonomie, [_e(jahr_von=1900)])
    assert "color_map" not in meta
    assert "node_color_map" not in meta
    assert not hasattr(kern, "farbzuordnung")
    assert not hasattr(kern, "CAT_PALETTE")
    assert not hasattr(kern, "NODE_PALETTE")


def test_kein_feld_der_ausgabe_traegt_eine_farbe():
    """Breiter gefasst: nirgends im project_meta.json steht ein Farbwert."""
    import re
    taxonomie = [{"name": "Kosten", "description": "Geld", "keywords": []}]
    meta = kern.metadaten("Damaskus", taxonomie, [_e(jahr_von=1908)])
    als_text = json.dumps(meta, ensure_ascii=False)
    assert not re.search(r"#[0-9a-fA-F]{6}", als_text), als_text


# ── metadaten ─────────────────────────────────────────────────────────────────

def test_metadaten_gestalt():
    taxonomie = [{"name": "Kosten", "description": "Geld", "keywords": []}]
    meta = kern.metadaten("Damaskus", taxonomie, [_e(jahr_von=1908)])
    assert meta["title"] == "Damaskus"
    assert meta["taxonomy"] == taxonomie
    # Die toten Felder der Vorlage
    assert "doc_type" not in meta
    assert "entity_types" not in meta


def test_metadaten_kennt_die_akteure_nicht_mehr():
    """Der Parameter ist weg, weil er nur node_color_map gespeist hat.

    Er stand noch da, nachdem die Farben gefallen waren — ein Argument, das
    niemand mehr liest, ist eine Zusage, die niemand mehr hält.
    """
    import inspect
    assert list(inspect.signature(kern.metadaten).parameters) == [
        "titel", "taxonomie", "einheiten"]


# ── entities_seed.csv ─────────────────────────────────────────────────────────

def test_alias_tabelle_fuehrt_die_normalform_zuerst():
    csv = kern.alias_tabelle([Akteur("Ismail Enver", "Person", ("Enver", "Enver Bey"))])
    assert csv.splitlines() == [
        "alias,normalform,typ",
        "Ismail Enver,Ismail Enver,Person",
        "Enver,Ismail Enver,Person",
        "Enver Bey,Ismail Enver,Person",
    ]


def test_alias_tabelle_entdoppelt_ohne_ruecksicht_auf_gross_klein():
    csv = kern.alias_tabelle([Akteur("Enver", "Person", ("enver", "Enver"))])
    assert len(csv.splitlines()) == 2


def test_alias_tabelle_ohne_typ_schreibt_org():
    # Wie die Vorlage: viz/ schlägt damit in NODE_COLOR nach.
    csv = kern.alias_tabelle([Akteur("X", None)])
    assert csv.splitlines()[1] == "X,X,Org"


def test_alias_mit_komma_wird_gequotet():
    csv = kern.alias_tabelle([Akteur("Khoury, Philip", "Person")])
    assert '"Khoury, Philip"' in csv


# ── Netz ──────────────────────────────────────────────────────────────────────

def _mit_akteuren(*gruppen) -> list[dict]:
    return [{"actors": list(g)} for g in gruppen]


def test_knoten_zaehlen_die_einheiten():
    knoten, _ = kern.netz(_mit_akteuren(["A"], ["A", "B"], ["B"]))
    assert {k["id"]: k["count"] for k in knoten} == {"A": 2, "B": 2}


def test_kante_erst_ab_zwei_gemeinsamen_einheiten():
    _, kanten = kern.netz(_mit_akteuren(["A", "B"]))
    assert kanten == []
    _, kanten = kern.netz(_mit_akteuren(["A", "B"], ["B", "A"]))
    assert kanten == [{"source": "A", "target": "B", "count": 2}]


def test_kantenrichtung_ist_alphabetisch():
    _, kanten = kern.netz(_mit_akteuren(["B", "A"], ["B", "A"]))
    assert (kanten[0]["source"], kanten[0]["target"]) == ("A", "B")


def test_leeres_netz_ergibt_leeres_layout():
    ergebnis = kern.layout([], [])
    assert ergebnis == {"width": 1100, "height": 600, "nodes": []}


@pytest.mark.parametrize("lauf", [1, 2])
def test_layout_ist_wiederholbar(lauf):
    eintraege = _mit_akteuren(["A", "B"], ["A", "B"], ["B", "C"], ["B", "C"], ["A"])
    knoten, kanten = kern.netz(eintraege)
    erst = kern.layout(knoten, kanten)
    zweit = kern.layout(knoten, kanten)
    assert erst == zweit
    assert {n["id"] for n in erst["nodes"]} == {"A", "B", "C"}


def test_layout_liegt_auf_der_leinwand():
    knoten, kanten = kern.netz(_mit_akteuren(["A", "B"], ["A", "B"], ["C"]))
    ergebnis = kern.layout(knoten, kanten)
    for n in ergebnis["nodes"]:
        assert 0 <= n["x"] <= 1100
        assert 0 <= n["y"] <= 600


# ── Zählung ───────────────────────────────────────────────────────────────────

def test_zaehlung_findet_den_verlust():
    liste = kern.eintraege(
        [_e(id=1, jahr_von=1908, kategorie="Kosten", akteure=("A",)),
         _e(id=2, kategorie="Kosten"),
         _e(id=3, jahr_von=1911)],
        kategorienamen=["Kosten"],
    )
    knoten, kanten = kern.netz(liste)
    z = kern.zaehlung(liste, knoten, kanten, [Akteur("A", "Person")])
    assert z.einheiten == 3
    assert z.mit_datum == 2
    assert z.ohne_datum == 1
    assert z.ohne_kategorie == 1
    assert z.mit_akteur == 1
    assert z.je_kategorie == {"Kosten": 2}
