"""
tests/test_neu_datierung_kern.py — src/neu/datierung/kern.py

Ohne Datenbank, ohne Datei: Einheiten kommen als Objekte herein.

Ausführen:
  python3 -m pytest tests/test_neu_datierung_kern.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.datierung.kern import (  # noqa: E402
    HERKUENFTE,
    PRAEZISIONEN,
    QUELLFORMATE,
    Einheit,
    Override,
    UnbekanntesQuellformat,
    UnlesbaresDatum,
    datum_teile,
    handdatierung,
    anker_erkennen,
    anker_im_text,
    datieren,
    frontmatter_datum_lesen,
    interpolieren,
    jahr_aus_ueberschrift,
    ohne_nicht_anker,
    overrides_anwenden,
    quellendatum_lesen,
    quellformat_pruefen,
)


def _e(id, text="", typ="content", gruppe="Werk", publdatum=None, fm=None):
    return Einheit(id=id, position=id, typ=typ, text=text,
                   chronologie_gruppe=gruppe, publikationsdatum=publdatum,
                   datum_frontmatter=fm)


# ── Wertevorrat ───────────────────────────────────────────────────────────────

def test_quellformat_wird_geprueft() -> None:
    for w in QUELLFORMATE:
        assert quellformat_pruefen(w) == w
    with pytest.raises(UnbekanntesQuellformat):
        quellformat_pruefen("presseartikel")   # der alte interne Wert


def test_vokabular_ist_deutsch() -> None:
    for w in PRAEZISIONEN + HERKUENFTE:
        assert w == w.lower()
    assert set(PRAEZISIONEN) == {"tag", "monat", "jahr", "spanne", "keine"}
    for englisch in ("exact", "heading", "event", "decade", "interpolated", "manual"):
        assert englisch not in HERKUENFTE and englisch not in PRAEZISIONEN


# ── Text zerlegen ─────────────────────────────────────────────────────────────

def test_lebensdaten_und_klammerjahre_fallen_weg() -> None:
    """Unverändert aus _strip_non_anchors."""
    assert "1870" not in ohne_nicht_anker("Ahmad Pascha (1870–1935) regierte")
    assert "1827" not in ohne_nicht_anker("Der Gelehrte (d.1827) schrieb")
    assert "1984" not in ohne_nicht_anker("Khoury, Urban Notables (1984)")
    # Ein Abstand über 120 Jahre ist kein Lebensdatum → bleibt stehen
    assert "1750" in ohne_nicht_anker("Der Zeitraum (1750–1950) umfasst")


def test_jahreszahlen_werden_gefunden() -> None:
    a = anker_im_text("1908 kam es zur Revolution, 1912 zum Krieg", 1)
    assert sorted(x.jahr for x in a if x.herkunft == "text") == [1908, 1912]


def test_jahr_auch_ohne_wortgrenze() -> None:
    """(?<!\\d) statt \\b — erfasst '1860er' und '1898bibliothekswesen'."""
    assert any(x.jahr == 1860 for x in anker_im_text("in den 1860er Jahren", 1))


def test_ereignisse_werden_erkannt() -> None:
    a = anker_im_text("Die Jungtürkenrevolution veränderte alles", 1)
    e = [x for x in a if x.herkunft == "ereignis"]
    assert e and e[0].jahr == 1908
    assert e[0].fundstelle == "Jungtürkenrevolution"


def test_jahrzehnt_ohne_jahr() -> None:
    a = anker_im_text("Um die Jahrhundertwende geschah es", 1)
    j = [x for x in a if x.herkunft == "jahrzehnt"]
    assert j and j[0].jahr is None


def test_ueberschriftsjahr() -> None:
    assert jahr_aus_ueberschrift("1989") == 1989
    assert jahr_aus_ueberschrift("1989 und 1990") is None
    assert jahr_aus_ueberschrift("Kapitel 3") is None


# ── Quellennotation ───────────────────────────────────────────────────────────

def test_quellendatum_wird_gelesen() -> None:
    assert quellendatum_lesen("01.01.1989") == ("1989-01-01", 1989)
    assert quellendatum_lesen("3.12.89") == ("1989-12-03", 1989)
    assert quellendatum_lesen("5.6.17") == ("2017-06-05", 2017)


def test_mehrfachtreffer_erster_gewinnt() -> None:
    """Die Vorlage verkettet mehrere Treffer mit ';'."""
    assert quellendatum_lesen("3.12.89;4.12.89") == ("1989-12-03", 1989)


def test_unlesbares_quellendatum() -> None:
    assert quellendatum_lesen(None) is None
    assert quellendatum_lesen("") is None
    assert quellendatum_lesen("Tsp") is None
    assert quellendatum_lesen("32.13.1989") is None      # unmöglicher Tag/Monat


def test_frontmatter_traegt_die_granularitaet() -> None:
    assert frontmatter_datum_lesen("2026-05-12") == ("2026-05-12", 2026, "tag")
    assert frontmatter_datum_lesen("2026-05") == ("2026-05", 2026, "monat")
    assert frontmatter_datum_lesen("2026") == ("2026", 2026, "jahr")
    assert frontmatter_datum_lesen("gestern") is None


# ── Rangfolge Literaturexzerpt ────────────────────────────────────────────────

def test_rangfolge_jahreszahl_vor_ereignis() -> None:
    d = anker_erkennen([_e(1, "1908 zur Zeit der Jungtürkenrevolution")],
                       "literaturexzerpt")[0]
    assert d.herkunft == "text" and d.jahr_von == 1908


def test_rangfolge_ereignis_vor_jahrzehnt() -> None:
    d = anker_erkennen([_e(1, "Die Jungtürkenrevolution um die Jahrhundertwende")],
                       "literaturexzerpt")[0]
    assert d.herkunft == "ereignis" and d.jahr_von == 1908


def test_rangfolge_jahrzehnt_vor_ueberschrift() -> None:
    """Ein Jahrzehnt schlägt die Überschrift — und bleibt trotzdem undatiert."""
    d = anker_erkennen([_e(1, "1920", typ="heading"),
                        _e(2, "Um die Jahrhundertwende geschah es")],
                       "literaturexzerpt")[0]
    assert d.herkunft is None and d.jahr_von is None and d.praezision == "keine"
    assert any(a.herkunft == "jahrzehnt" for a in d.anker)


def test_ueberschrift_als_letzte_stufe() -> None:
    d = anker_erkennen([_e(1, "1920", typ="heading"),
                        _e(2, "Ein Absatz ohne jede Jahreszahl")],
                       "literaturexzerpt")[0]
    assert d.jahr_von == 1920
    # Der behobene Defekt: herkunft ist 'ueberschrift', nicht 'text'
    assert d.herkunft == "ueberschrift"
    assert d.anker[0].herkunft == "ueberschrift"


def test_mehrere_jahre_spannen_auf() -> None:
    d = anker_erkennen([_e(1, "Zwischen 1908 und 1912 geschah es")],
                       "literaturexzerpt")[0]
    assert (d.jahr_von, d.jahr_bis, d.praezision) == (1908, 1912, "spanne")


# ── Rangfolge Presseexzerpt ───────────────────────────────────────────────────

def test_erscheinungsdatum_schlaegt_ueberschrift() -> None:
    """Die beschlossene Änderung: die Quellennotation ist genauer."""
    d = anker_erkennen([_e(1, "1989", typ="heading"),
                        _e(2, "Meldung. Tsp, 14.03.1989", publdatum="14.03.1989")],
                       "presseexzerpt")[0]
    assert d.herkunft == "quellennotation"
    assert d.datum == "1989-03-14"
    assert d.praezision == "tag"


def test_ohne_erscheinungsdatum_gilt_die_ueberschrift() -> None:
    d = anker_erkennen([_e(1, "1989", typ="heading"),
                        _e(2, "Meldung ohne Quellenangabe")],
                       "presseexzerpt")[0]
    assert d.herkunft == "ueberschrift"
    assert d.praezision == "jahr"
    assert d.datum == "1989"


def test_weder_noch_bleibt_leer() -> None:
    d = anker_erkennen([_e(1, "Vorspann ohne alles")], "presseexzerpt")[0]
    assert d.herkunft is None and d.praezision == "keine"


# ── Pressesammlung ────────────────────────────────────────────────────────────

def test_frontmatter_datiert_tagesgenau() -> None:
    d = anker_erkennen([_e(1, "Artikeltext", fm="2026-05-12")], "pressesammlung")[0]
    assert (d.datum, d.jahr_von, d.praezision, d.herkunft) == \
           ("2026-05-12", 2026, "tag", "frontmatter")


# ── Interpolation ─────────────────────────────────────────────────────────────

def _leer(id):
    from src.neu.datierung.kern import Datierung
    return Datierung(id, None, None, None, "keine", None, [])


def _fest(id, jahr):
    from src.neu.datierung.kern import Datierung
    return Datierung(id, str(jahr), jahr, jahr, "jahr", "text", [])


def test_zwischen_zwei_ankern_wird_aufgespannt() -> None:
    """Nicht verteilt: alle dazwischen bekommen dieselbe Spanne."""
    d = interpolieren([_fest(1, 1908), _leer(2), _leer(3), _fest(4, 1912)],
                      {i: "W" for i in range(1, 5)})
    for x in (d[1], d[2]):
        assert (x.jahr_von, x.jahr_bis) == (1908, 1912)
        assert x.praezision == "spanne" and x.herkunft == "interpoliert"


def test_nach_dem_letzten_anker_wird_vorwaerts_geerbt() -> None:
    d = interpolieren([_fest(1, 1908), _leer(2), _leer(3)],
                      {i: "W" for i in range(1, 4)})
    for x in (d[1], d[2]):
        assert (x.jahr_von, x.jahr_bis) == (1908, 1908)
        assert x.praezision == "jahr" and x.herkunft == "interpoliert"


def test_vor_dem_ersten_anker_kein_rueckwaertserben() -> None:
    d = interpolieren([_leer(1), _leer(2), _fest(3, 1908)],
                      {i: "W" for i in range(1, 4)})
    assert d[0].jahr_von is None and d[0].herkunft is None
    assert d[1].jahr_von is None


def test_gruppe_ohne_anker_bleibt_ganz_undatiert() -> None:
    d = interpolieren([_fest(1, 1908), _leer(2)], {1: "A", 2: "B"})
    assert d[1].jahr_von is None


def test_ueber_gruppengrenzen_wird_nicht_interpoliert() -> None:
    d = interpolieren([_fest(1, 1908), _leer(2), _fest(3, 1912)],
                      {1: "A", 2: "B", 3: "A"})
    assert d[1].jahr_von is None


# ── Rücksprung: der eine Fall, den die Vorlage nicht kannte ──────────────────

def test_rueckwaerts_wird_nicht_aufgespannt() -> None:
    """A > B: kein 1914–1860, sondern 1914 als Zeitpunkt.

    Ein Exzerpt ist nach Thema geordnet, nicht nach Jahr. Springt es von 1914
    zurück auf 1860, ist 'jahr_bis < jahr_von' keine ungewöhnliche Spanne,
    sondern keine.
    """
    d = interpolieren([_fest(1, 1914), _leer(2), _leer(3), _fest(4, 1860)],
                      {i: "W" for i in range(1, 5)})
    for x in (d[1], d[2]):
        assert (x.jahr_von, x.jahr_bis) == (1914, 1914)
        assert x.praezision == "jahr" and x.herkunft == "interpoliert"


def test_gleiche_jahre_bleiben_ein_zeitpunkt() -> None:
    """A == B ist kein Rücksprung — die Grenze liegt bei 'kleiner gleich'."""
    d = interpolieren([_fest(1, 1908), _leer(2), _fest(3, 1908)],
                      {i: "W" for i in range(1, 4)})
    assert (d[1].jahr_von, d[1].jahr_bis) == (1908, 1908)
    assert d[1].praezision == "jahr"


def test_vorwaerts_spannt_weiterhin_auf() -> None:
    """Der Normalfall bleibt unberührt — nur eine Bedingung kommt hinzu."""
    d = interpolieren([_fest(1, 1908), _leer(2), _fest(3, 1912)],
                      {i: "W" for i in range(1, 4)})
    assert (d[1].jahr_von, d[1].jahr_bis) == (1908, 1912)
    assert d[1].praezision == "spanne"


def test_nach_dem_ruecksprung_wird_wieder_aufgespannt() -> None:
    """Der Rücksprung betrifft die eine Lücke, nicht den Rest der Gruppe."""
    d = interpolieren(
        [_fest(1, 1914), _leer(2), _fest(3, 1860), _leer(4), _fest(5, 1880)],
        {i: "W" for i in range(1, 6)})
    assert (d[1].jahr_von, d[1].jahr_bis) == (1914, 1914)   # Rücksprung
    assert (d[3].jahr_von, d[3].jahr_bis) == (1860, 1880)   # wieder vorwärts


def test_textspanne_bleibt_unangetastet() -> None:
    """Nennt ein Absatz selbst '1830–1870', ist das keine Interpolation."""
    from src.neu.datierung.kern import Datierung
    eigene = Datierung(2, "1830", 1830, 1870, "spanne", "text", [])
    d = interpolieren([_fest(1, 1914), eigene, _fest(3, 1860)],
                      {i: "W" for i in range(1, 4)})
    assert (d[1].jahr_von, d[1].jahr_bis) == (1830, 1870)
    assert d[1].herkunft == "text"


def test_handkorrektur_beginnt_einen_abschnitt_wie_jeder_anker() -> None:
    from src.neu.datierung.kern import Datierung
    hand = Datierung(3, "1890", 1890, 1890, "jahr", "manuell", [])
    d = interpolieren([_fest(1, 1914), _leer(2), hand, _leer(4), _fest(5, 1900)],
                      {i: "W" for i in range(1, 6)})
    assert (d[1].jahr_von, d[1].jahr_bis) == (1914, 1914)   # 1914 > 1890
    assert (d[3].jahr_von, d[3].jahr_bis) == (1890, 1900)   # 1890 < 1900


def test_spanne_wird_ueber_den_mittelpunkt_weitergereicht() -> None:
    from src.neu.datierung.kern import Datierung
    d = interpolieren([Datierung(1, "1900", 1900, 1910, "spanne", "text", []), _leer(2)],
                      {1: "W", 2: "W"})
    assert d[1].jahr_von == 1905      # (1900+1910)//2


# ── Overrides ─────────────────────────────────────────────────────────────────

def test_handkorrektur_wird_ein_anker() -> None:
    """Der behobene Defekt: heute setzt sie nur precision."""
    d, undat, leer = overrides_anwenden(
        [_leer(1)], [Override(1, "anker_setzen", 1911)])
    assert d[0].herkunft == "manuell" and d[0].jahr_von == 1911
    assert len(d[0].anker) == 1
    assert d[0].anker[0].herkunft == "manuell" and d[0].anker[0].jahr == 1911
    assert undat == set() and leer == []


def test_undatierbar_bleibt_undatiert_und_ist_kein_anker() -> None:
    d, undat, _ = overrides_anwenden([_fest(1, 1908)], [Override(1, "undatierbar")])
    assert d[0].jahr_von is None and d[0].herkunft == "manuell"
    assert d[0].anker == []
    assert undat == {1}


def test_undatierbare_werden_nicht_interpoliert() -> None:
    d, undat, _ = overrides_anwenden(
        [_fest(1, 1908), _leer(2), _fest(3, 1912)], [Override(2, "undatierbar")])
    e = interpolieren(d, {i: "W" for i in (1, 2, 3)}, undat)
    assert e[1].jahr_von is None


def test_override_ins_leere_wird_gemeldet() -> None:
    """Der Fall aus ber: s0026 gibt es im Zielbestand nicht."""
    d, _, leer = overrides_anwenden([_leer(1)], [Override(999, "anker_setzen", 1911)])
    assert leer == [999]
    assert len(d) == 1


# ── Alles zusammen ────────────────────────────────────────────────────────────

def test_overrides_gelten_auch_fuer_presseexzerpt() -> None:
    """Der entfallene Bypass: die Vorlage übersprang das ganz."""
    e = datieren(
        [_e(1, "1989", typ="heading"),
         _e(2, "Meldung", publdatum="14.03.1989"),
         _e(3, "Zweite Meldung", publdatum="15.03.1989")],
        "presseexzerpt",
        [Override(2, "anker_setzen", 1990)],
    )
    nach_id = {d.einheit_id: d for d in e.datierungen}
    assert nach_id[2].herkunft == "manuell" and nach_id[2].jahr_von == 1990
    assert nach_id[3].herkunft == "quellennotation"


def test_heading_einheiten_erscheinen_nicht_im_ergebnis() -> None:
    e = datieren([_e(1, "1989", typ="heading"), _e(2, "Text")], "presseexzerpt")
    assert [d.einheit_id for d in e.datierungen] == [2]


# ── Kein Netz, keine Datei ────────────────────────────────────────────────────

def test_kern_kennt_weder_datenbank_noch_datei_noch_ausgabe() -> None:
    import ast

    quelle = (ROOT / "src" / "neu" / "datierung" / "kern.py").read_text(encoding="utf-8")
    baum = ast.parse(quelle)
    for k in ast.walk(baum):
        if isinstance(k, ast.Call):
            name = ast.unparse(k.func)
            assert name != "print", f"print in kern.py, Zeile {k.lineno}"
            assert name != "open", f"Dateizugriff in kern.py, Zeile {k.lineno}"
        if isinstance(k, (ast.Import, ast.ImportFrom)):
            modul = getattr(k, "module", None) or ""
            namen = [a.name for a in k.names]
            for verboten in ("sqlite3", "requests", "anthropic"):
                assert verboten not in modul and verboten not in namen


# ── Datum von Hand: ein Feld, drei Genauigkeiten ──────────────────────────────

@pytest.mark.parametrize("roh,erwartet", [
    ("2012",       ("2012", 2012, "jahr")),
    ("2012-07",    ("2012-07", 2012, "monat")),
    ("2012-07-30", ("2012-07-30", 2012, "tag")),
    ("  2012-07-30  ", ("2012-07-30", 2012, "tag")),
])
def test_datum_teile(roh, erwartet) -> None:
    assert datum_teile(roh) == erwartet


@pytest.mark.parametrize("roh", ["", "30.07.2012", "2012-13", "2012-02-30", "zwölf"])
def test_unlesbares_datum_wirft(roh) -> None:
    with pytest.raises(UnlesbaresDatum):
        datum_teile(roh)


def test_zeitpunkt_erbt_die_genauigkeit_des_feldes() -> None:
    assert handdatierung("2012-07-30") == ("2012-07-30", 2012, 2012, "tag")
    assert handdatierung("2012-07") == ("2012-07", 2012, 2012, "monat")
    assert handdatierung("2012") == ("2012", 2012, 2012, "jahr")


def test_leeres_von_heisst_undatierbar() -> None:
    assert handdatierung(None) == (None, None, None, "keine")
    assert handdatierung("  ") == (None, None, None, "keine")


def test_zwei_jahre_bleiben_zwei_jahre() -> None:
    assert handdatierung("1989", "2017") == ("1989", 1989, 2017, "spanne")


def test_feine_spanne_behaelt_beide_enden() -> None:
    """Sonst wäre das Ende auf das Jahr eingedampft, ohne dass es jemand merkt."""
    assert handdatierung("2012-07-30", "2013-02-01") == (
        "2012-07-30/2013-02-01", 2012, 2013, "spanne")


def test_gleiches_bis_ist_ein_zeitpunkt() -> None:
    assert handdatierung("2012-07", "2012-07") == ("2012-07", 2012, 2012, "monat")


def test_verkehrte_spanne_wird_abgewiesen() -> None:
    with pytest.raises(UnlesbaresDatum):
        handdatierung("2013", "2012")
    with pytest.raises(UnlesbaresDatum):
        handdatierung("2012-07-30", "2012-07-01")


# ── Eine Handkorrektur übersteht den Neulauf unverändert ─────────────────────

def test_handkorrektur_behaelt_genauigkeit_und_begruendung() -> None:
    """Ohne das käme aus '2012-07-30' beim Wiederanwenden '2012'."""
    d, _, _ = overrides_anwenden([_leer(1)], [Override(
        1, "anker_setzen", 2012, 2012,
        datum="2012-07-30", praezision="tag", fundstelle="Zifferndreher, war 3012")])
    assert d[0].datum == "2012-07-30"
    assert d[0].praezision == "tag"
    assert d[0].anker[0].fundstelle == "Zifferndreher, war 3012"


def test_undatierbar_haelt_seine_begruendung_fest() -> None:
    d, undat, _ = overrides_anwenden(
        [_fest(1, 1908)], [Override(1, "undatierbar", fundstelle="kein Datum im Text")])
    assert d[0].jahr_von is None and undat == {1}
    assert len(d[0].anker) == 1
    assert d[0].anker[0].jahr is None
    assert d[0].anker[0].fundstelle == "kein Datum im Text"


def test_undatierbar_ohne_begruendung_bleibt_ohne_anker() -> None:
    d, _, _ = overrides_anwenden([_fest(1, 1908)], [Override(1, "undatierbar")])
    assert d[0].anker == []
