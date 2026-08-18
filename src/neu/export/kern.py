"""
kern.py — die Dateien bauen, die viz/ liest

Reine Funktionen: Zeilen rein, fertige Gebilde raus. Keine Datenbank, keine
Dateien, kein Netz, kein print. viz/ wird nicht angefasst — was hier entsteht,
muss die bestehende Visualisierung ohne eine geänderte Zeile laden können.

Fachlogik übernommen aus src/generalized/export_exploration.py:
    build_entries samt date_js-Regeln, build_entities_csv, build_meta,
    CAT_PALETTE und NODE_PALETTE, die Farbzuweisung nach Listenplatz
und aus src/generalized/precompute_network.js:
    Knoten- und Kantenbildung, LINK_MIN_COUNT = 2, die Leinwand 1100×600

Die Kategorienormalisierung kommt aus src.neu.kategorien.kern — dieselbe
Funktion, die schon der Klassifikationsschritt benutzt.

Was wegfällt und warum:

- group_by_article. Im neuen Modell ist eine Obsidian-Datei bereits eine
  Einheit; das Zusammenfassen nach (source_name, url) würde bei einer
  Pressesammlung nichts tun und bei einer Chronik die tagesgenauen Daten
  wieder auf ein Datum je Artikel einebnen.
- causal_theme, date_precision, confidence, is_quote, doc_type, entity_types.
  Keine Zeile in viz/ liest sie. date_precision war die einzige Verwendung
  von PREC_MAP: eine Abbildung von sechs Stufen auf drei, deren Ergebnis
  niemand ansieht.

Was anders gerechnet wird:

- year_min/year_max sind MIN(jahr_von) und MAX(jahr_bis) über die Einheiten.
  Bisher stand dort eine gespeicherte Angabe, bei Literaturexzerpten von
  einem Sprachmodell geschätzt — und d3.bin() verwarf im Browser alles
  außerhalb.
- Das Netzwerklayout rechnet networkx.spring_layout statt d3-force. Beides
  ist Fruchterman-Reingold; mit festem seed ist das Ergebnis wiederholbar,
  was der Node-Unterprozess nicht war.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from io import StringIO
from typing import Sequence

from src.neu.kategorien.kern import normalisiere_kategorie

# ── Farbpaletten ──────────────────────────────────────────────────────────────
# Unverändert aus export_exploration.py.

CAT_PALETTE = [
    "#3b82f6", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444",
    "#06b6d4", "#f97316", "#6366f1", "#14b8a6", "#a855f7",
]
NODE_PALETTE = [
    "#60a5fa", "#fbbf24", "#34d399", "#c084fc", "#f87171", "#6ee7b7",
]

# ── Netzwerk ──────────────────────────────────────────────────────────────────
# Muss mit viz/boot.js übereinstimmen.

LINK_MIN_COUNT = 2
LEINWAND_BREITE = 1100
LEINWAND_HOEHE = 600
LAYOUT_SEED = 42

_DATUM_VOLL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATUM_JAHR = re.compile(r"^\d{4}$")


# ── Eingabegestalten ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Einheit:
    """Eine Einheit, so wie der Export sie braucht."""

    id: int
    quelle_id: str
    text: str
    datum: str | None = None
    jahr_von: int | None = None
    jahr_bis: int | None = None
    kategorie: str | None = None
    publikation: str | None = None
    publikationsdatum: str | None = None
    url: str | None = None
    akteure: tuple[str, ...] = ()


@dataclass(frozen=True)
class Akteur:
    normalform: str
    typ: str | None
    aliase: tuple[str, ...] = ()
    zusammenfassung: str | None = None


@dataclass(frozen=True)
class Periode:
    id: int
    name: str
    jahr_von: int | None
    jahr_bis: int | None


@dataclass
class Zaehlung:
    """Was hineinging und was davon wo ankommt."""

    einheiten: int = 0
    mit_datum: int = 0
    ohne_datum: int = 0
    ohne_kategorie: int = 0
    mit_akteur: int = 0
    akteure: int = 0
    knoten: int = 0
    kanten: int = 0
    je_kategorie: dict[str, int] = field(default_factory=dict)


# ── data.json ─────────────────────────────────────────────────────────────────

def _datum_js(datum: str | None, jahr: int | None) -> str | None:
    """ISO-Tagesstring für die Zeitachse. Unverändert aus build_entries."""
    if datum and _DATUM_VOLL.match(datum):
        return datum
    if datum and _DATUM_JAHR.match(datum):
        return datum + "-01-01"
    if jahr is not None:
        return f"{jahr}-01-01"
    return None


def anker(einheit: Einheit) -> str:
    """Die Kennung, unter der viz/ eine Einheit wiederfindet.

    Bisher {doc_id}-{segment_id}, wobei segment_id nur die Position kodierte.
    Jetzt die stabile Kennung der Einheit.
    """
    return f"{einheit.quelle_id}-e{einheit.id}"


def eintraege(
    einheiten: Sequence[Einheit], kategorienamen: Sequence[str] = ()
) -> list[dict]:
    """Baut die entries-Liste von data.json.

    Keine Einheit fällt weg — auch undatierte nicht. Wer nicht auf der
    Zeitachse erscheint, steht trotzdem in der Datei und ist über Suche,
    Netzwerk und Panel erreichbar.
    """
    gueltige = list(kategorienamen)
    liste: list[dict] = []
    for i, e in enumerate(einheiten, start=1):
        datum_roh = e.datum or (str(e.jahr_von) if e.jahr_von is not None else None)
        kategorie = e.kategorie
        if kategorie is not None and gueltige:
            kategorie = normalisiere_kategorie(kategorie, gueltige)
        liste.append({
            "id": i,
            "doc_anchor": anker(e),
            "year": e.jahr_von,
            "date_raw": datum_roh,
            "date_js": _datum_js(e.datum, e.jahr_von),
            "text": e.text,
            "event_type": kategorie,
            "source_name": e.publikation or None,
            "source_date": e.publikationsdatum or datum_roh,
            "url": e.url or "",
            "actors": list(e.akteure),
        })
    return liste


# ── entities_seed.csv ─────────────────────────────────────────────────────────

def alias_tabelle(akteure: Sequence[Akteur]) -> str:
    """alias,normalform,typ — eine Zeile je Name, die Normalform zuerst.

    Unverändert aus build_entities_csv. Fehlt der Typ, steht dort 'Org' wie
    in der Vorlage: viz/ schlägt damit in NODE_COLOR nach.
    """
    puffer = StringIO()
    schreiber = csv.writer(puffer, lineterminator="\n")
    schreiber.writerow(["alias", "normalform", "typ"])
    for a in akteure:
        nf = a.normalform
        typ = a.typ or "Org"
        gesehen: set[str] = set()
        for name in [nf, *a.aliase]:
            n = (name or "").strip()
            if n and n.lower() not in gesehen:
                gesehen.add(n.lower())
                schreiber.writerow([n, nf, typ])
    return puffer.getvalue()


# ── project_meta.json ─────────────────────────────────────────────────────────

def spanne(einheiten: Sequence[Einheit]) -> tuple[int | None, int | None]:
    """MIN(jahr_von) bis MAX(jahr_bis) — abgeleitet, nicht abgelegt.

    jahr_bis fällt auf jahr_von zurück, wo keine Spanne steht. Gibt es keine
    datierte Einheit, ist beides None und viz/ nimmt den Wertebereich der
    Daten selbst.
    """
    von = [e.jahr_von for e in einheiten if e.jahr_von is not None]
    bis = [e.jahr_bis if e.jahr_bis is not None else e.jahr_von
           for e in einheiten if e.jahr_von is not None]
    if not von:
        return None, None
    return min(von), max(bis)


def farbzuordnung(namen: Sequence[str], palette: Sequence[str]) -> dict[str, str]:
    """Name → Farbe nach Listenplatz.

    Übernommen wie sie ist, samt ihrer Schwäche: wer eine Kategorie löscht
    oder umsortiert, verschiebt alle nachfolgenden Farben. Ab dem elften
    Eintrag wiederholt sich die Palette.
    """
    return {name: palette[i % len(palette)] for i, name in enumerate(namen)}


def metadaten(
    titel: str,
    taxonomie: Sequence[dict],
    akteure: Sequence[Akteur],
    einheiten: Sequence[Einheit],
    perioden: Sequence[Periode] = (),
) -> dict:
    """project_meta.json — Titel, Taxonomie, Farben, Zeitraum, Perioden."""
    namen = [c["name"] for c in taxonomie if c.get("name")]
    typen = sorted({a.typ for a in akteure if a.typ})
    jahr_min, jahr_max = spanne(einheiten)

    meta: dict = {
        "title": titel,
        "taxonomy": list(taxonomie),
        "color_map": farbzuordnung(namen, CAT_PALETTE),
        "node_color_map": farbzuordnung(typen, NODE_PALETTE),
        # Perioden hatten bisher keinen Verbraucher: das Sprachmodell erzeugte
        # sie in Schritt 1, der Wizard zeigte sie, der Export ließ sie liegen.
        "events": [
            {"id": p.id, "name": p.name,
             "year_from": p.jahr_von, "year_to": p.jahr_bis}
            for p in perioden
        ],
    }
    if jahr_min is not None:
        meta["year_min"] = jahr_min
        meta["year_max"] = jahr_max
    return meta


# ── network_layout.json ───────────────────────────────────────────────────────

def netz(eintraege_: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """Knoten und Kanten aus den actors-Feldern.

    Ein Knoten je Akteur mit der Zahl seiner Einheiten, eine Kante je Paar,
    das mindestens LINK_MIN_COUNT-mal gemeinsam vorkommt. Identisch zu
    precompute_network.js und zu dem, was viz/boot.js selbst rechnet.
    """
    knoten_zahl: dict[str, int] = {}
    kanten_zahl: dict[tuple[str, str], int] = {}

    for eintrag in eintraege_:
        akteure = list(eintrag.get("actors") or [])
        for a in akteure:
            knoten_zahl[a] = knoten_zahl.get(a, 0) + 1
        for i in range(len(akteure)):
            for j in range(i + 1, len(akteure)):
                paar = tuple(sorted((akteure[i], akteure[j])))
                kanten_zahl[paar] = kanten_zahl.get(paar, 0) + 1

    knoten = [{"id": name, "count": n} for name, n in knoten_zahl.items()]
    kanten = [{"source": a, "target": b, "count": n}
              for (a, b), n in kanten_zahl.items() if n >= LINK_MIN_COUNT]
    return knoten, kanten


def layout(
    knoten: Sequence[dict],
    kanten: Sequence[dict],
    breite: int = LEINWAND_BREITE,
    hoehe: int = LEINWAND_HOEHE,
    seed: int = LAYOUT_SEED,
) -> dict:
    """Vorberechnetes Netzwerklayout, Format wie precompute_network.js.

    networkx.spring_layout ist Fruchterman-Reingold, derselbe Algorithmus wie
    d3-force. Mit festem seed ist der Lauf wiederholbar — der Node-Weg war es
    nicht, weil d3-force die Startpositionen aus einem Phyllotaxis-Muster
    zieht und die Simulation über die Tick-Zahl driftet.

    Die Ausgabe ist auf die Leinwand skaliert; viz/network.js rechnet sie über
    width/height auf die tatsächliche Bildgröße um.
    """
    import networkx as nx

    ergebnis = {"width": breite, "height": hoehe, "nodes": []}
    if not knoten:
        return ergebnis

    g = nx.Graph()
    # Sortiert einfügen: networkx' Knotenreihenfolge geht in die Startlage ein.
    for k in sorted(knoten, key=lambda k: k["id"]):
        g.add_node(k["id"])
    for kante in sorted(kanten, key=lambda k: (k["source"], k["target"])):
        g.add_edge(kante["source"], kante["target"], weight=kante["count"])

    lage = nx.spring_layout(g, seed=seed, iterations=300)

    # spring_layout liefert Werte in [-1, 1]; auf die Leinwand legen.
    ergebnis["nodes"] = [
        {"id": name,
         "x": round((float(x) + 1) / 2 * breite, 2),
         "y": round((float(y) + 1) / 2 * hoehe, 2)}
        for name, (x, y) in sorted(lage.items())
    ]
    return ergebnis


# ── Zählung ───────────────────────────────────────────────────────────────────

def zaehlung(eintraege_: Sequence[dict], knoten: Sequence[dict],
             kanten: Sequence[dict], akteure: Sequence[Akteur]) -> Zaehlung:
    """Was hineinging und was davon wo ankommt.

    Undatierte Einheiten dürfen auf der Zeitachse fehlen — die Zahl muss
    auffindbar sein und nicht erst durch Nachzählen im Browser entstehen.
    """
    z = Zaehlung(einheiten=len(eintraege_), akteure=len(akteure),
                 knoten=len(knoten), kanten=len(kanten))
    for e in eintraege_:
        if e.get("date_js"):
            z.mit_datum += 1
        else:
            z.ohne_datum += 1
        kategorie = e.get("event_type")
        if kategorie is None:
            z.ohne_kategorie += 1
        else:
            z.je_kategorie[kategorie] = z.je_kategorie.get(kategorie, 0) + 1
        if e.get("actors"):
            z.mit_akteur += 1
    return z
