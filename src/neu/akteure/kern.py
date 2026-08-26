"""
kern.py — Akteure erkennen, zusammenführen, Einheiten zuordnen

Reine Funktionen: Text und Zahlen rein, Entscheidungen raus. Keine Datenbank,
kein Modell, keine Dateien, kein Netz, kein print. GLiNER und das Embedding
kommen als Funktionen von außen herein, damit auch diese Wege ohne Modell
prüfbar bleiben.

Fachlogik unverändert übernommen aus
    src/generalized/entity_gliner.py:
        _chunk, _LABEL_TO_TYPE, der Kleinschreib-Filter, _build_alias_map,
        _embedding_cluster samt Union-Find, Normalformwahl und Typ-Mehrheit
    src/generalized/entity_utils.py:
        _merge über Namensmengen
    src/generalized/match_entities.py:
        build_patterns — das Wortgrenz-Regex
    src/generalized/templates/entity_editor.html:
        _levenshtein und die Regel „Editierabstand < 3"

Unterschiede im Ergebnis, jeder mit Grund:

- Die Schwelle steht nicht im Code, sondern kommt vom Anbieter. 0,92 galt für
  MiniLM; mit Voyage-4 gehört sie auf 0,78, und die Vorlage rechnete trotzdem
  weiter mit 0,92.
- Ein Label, das die Abbildung nicht kennt, wird gemeldet und der Fund bekommt
  keinen Typ. Die Vorlage machte still ein 'Konzept' daraus.
- Der GLiNER-Score fällt weg: er wurde mitgeführt und nirgends ausgewertet.
- Die Normalform steht nicht mehr in ihrer eigenen Aliasliste.
- Der Zotero-Filter (videoRecording, 20 000 Zeichen) fällt weg. Er prüfte
  item_type, ein Feld aus einer abgelösten Anbindung.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

import numpy as np

# ── Wertevorräte ──────────────────────────────────────────────────────────────

# Aus src/neu/vokabular.py.
from src.neu.vokabular import AKTEUR_STATUS as STATUS  # noqa: E402
from src.neu.vokabular import AKTEUR_TYPEN as TYPEN  # noqa: E402
from src.neu.vokabular import AKTEUR_HERKUENFTE as HERKUENFTE  # noqa: E402
from src.neu.vokabular import KANDIDAT_GRUENDE as GRUENDE  # noqa: E402

__all_vokabular__ = (TYPEN, STATUS, HERKUENFTE, GRUENDE)

# Wie schwer ein Grund wiegt, kleiner ist stärker.
#
# Ein gemeinsamer Alias ist ein Beleg: zwei Zeilen tragen denselben Namen. Eine
# Schreibvariante ist ein starkes Indiz — 'Kayalı' und 'Kayali' sind fast immer
# dieselbe Person. Ähnlichkeit im Vektorraum ist der schwächste Grund; sie
# stellt auch Namen nebeneinander, die nur zum selben Thema gehören.
#
# Das ist Fachwissen über die drei Regeln und stand bis hierher als
# `const RANG` in akteure/+page.svelte — im Browser, wo niemand es beim
# Nachdenken über die Regeln gefunden hätte.
GRUND_RANG: dict[str, int] = {"alias": 0, "schreibweise": 1, "aehnlichkeit": 2}


def kandidat_rang(grund: str) -> int:
    """Der Rang eines Grundes; ein unbekannter sortiert ans Ende."""
    return GRUND_RANG.get(grund, len(GRUND_RANG))

# GLiNER. Modellname und Erkennungsschwelle stehen nicht hier, sondern in
# anbieter.toml unter [gliner] — sie sagen, WOMIT erkannt wird, und das ist
# Anbieterwissen. Was hier bleibt, ist fachlich: die Labels, ihre Abbildung
# auf die vier Typen, und wie lang ein Stück höchstens sein darf.
GLINER_MAX_ZEICHEN = 2000

GLINER_LABELS: tuple[str, ...] = (
    "Person",
    "Organisation",
    "geographischer Ort",
    "politische Bewegung",
    "religiöse Institution",
    "Zeitung oder Publikation",
    "politische Bewegung oder Ideologie",
    "religiöse Strömung oder Konzept",
)

LABEL_ZU_TYP: dict[str, str] = {
    "Person":                             "Person",
    "Organisation":                       "Organisation",
    "geographischer Ort":                 "Ort",
    "politische Bewegung":                "Organisation",
    "religiöse Institution":              "Organisation",
    "Zeitung oder Publikation":           "Organisation",
    "politische Bewegung oder Ideologie": "Konzept",
    "religiöse Strömung oder Konzept":    "Konzept",
}

# Das Vorschlagsband liegt unterhalb der Verschmelzungsschwelle: alles, was
# knapp nicht gereicht hat. Bei MiniLM ergibt das die heutigen 0,80–0,91.
BAND_BREITE = 0.12
BAND_ABSTAND = 0.01

# Editierabstand, unter dem zwei Normalformen als Schreibvarianten gelten.
LEVENSHTEIN_GRENZE = 3
LEVENSHTEIN_MINDESTLAENGE = 3

# Kürzeste Zeichenkette, die als Alias auf eine Einheit zeigen darf.
ALIAS_MINDESTLAENGE = 2


# ── Ergebnisgestalten ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Fund:
    """Ein Treffer aus dem Erkenner, vor jeder Zusammenführung."""

    normalform: str
    typ: str | None


@dataclass
class Akteur:
    """Ein Akteur mit seinen Aliasen. Die Normalform steht nicht darunter."""

    normalform: str
    typ: str | None
    aliase: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Fundstelle:
    """Ein Vorkommen im Text einer Einheit. ende ist ausschließlich."""

    einheit_id: int
    start: int
    ende: int


@dataclass(frozen=True)
class Kandidat:
    """Zwei Akteure, die dasselbe bezeichnen könnten."""

    a: int
    b: int
    grund: str
    mass: float | None


# ── Stückelung ────────────────────────────────────────────────────────────────
# Unverändert aus entity_gliner._chunk.

def stuecke(text: str, max_zeichen: int = GLINER_MAX_ZEICHEN) -> list[str]:
    """Teilt Text an Satzgrenzen in Stücke à max_zeichen."""
    if len(text) <= max_zeichen:
        return [text]
    ergebnis: list[str] = []
    while text:
        if len(text) <= max_zeichen:
            ergebnis.append(text)
            break
        trenn = text.rfind(". ", 0, max_zeichen)
        trenn = (trenn + 1) if trenn != -1 else max_zeichen
        ergebnis.append(text[:trenn].strip())
        text = text[trenn:].strip()
    return [s for s in ergebnis if s]


# ── Erkennung ─────────────────────────────────────────────────────────────────

def alias_landkarte(akteure: Sequence[Akteur]) -> dict[str, str]:
    """Kleingeschriebener Alias → Normalform.

    Führt Kurzformen aus dem Bestand auf den vollen Namen zurück, bevor
    zusammengefasst wird. Unverändert aus entity_gliner._build_alias_map.
    """
    landkarte: dict[str, str] = {}
    for a in akteure:
        if not a.normalform:
            continue
        landkarte[a.normalform.lower()] = a.normalform
        for alias in a.aliase:
            if alias:
                landkarte[alias.lower()] = a.normalform
    return landkarte


def erkenne(
    texte: Sequence[str],
    vorhersage: Callable[[str, list[str], float], list[dict]],
    landkarte: dict[str, str] | None = None,
    abgelehnt: Iterable[str] = (),
    labels: Sequence[str] = GLINER_LABELS,
    *,
    schwelle: float,
) -> tuple[list[Fund], Counter]:
    """Läuft den Erkenner über die Texte und gibt Funde plus unbekannte Labels.

    vorhersage(stueck, labels, schwelle) -> [{"text": …, "label": …}, …].
    Kommt von außen, damit der Kern kein Modell kennt. Die Schwelle ebenso und
    ohne Vorgabe: sie gehört zum Erkenner, nicht zur Fachlogik, und stand
    vorher als zweite Fassung neben der in anbieter.toml.

    Rückgabe: (Funde in Fundreihenfolge, Zähler der Labels ohne Abbildung).
    Ein unbekanntes Label wird gemeldet und der Fund bekommt typ=None — die
    Vorlage machte still 'Konzept' daraus.
    """
    landkarte = landkarte or {}
    abgelehnt_klein = {a.lower() for a in abgelehnt}
    funde: list[Fund] = []
    unbekannte: Counter = Counter()

    for text in texte:
        if not text:
            continue
        for stueck in stuecke(text):
            for treffer in vorhersage(stueck, list(labels), schwelle):
                name = (treffer.get("text") or "").strip()
                if not name:
                    continue
                # Kleinschreib-Filter: rein klein und kürzer als fünf Zeichen
                if name == name.lower() and len(name) < 5:
                    continue
                label = treffer.get("label") or ""
                typ = LABEL_ZU_TYP.get(label)
                if typ is None:
                    unbekannte[label] += 1
                # Kurzform auf den bekannten Vollnamen zurückführen
                voll = landkarte.get(name.lower())
                if voll and voll != name:
                    name = voll
                if name.lower() in abgelehnt_klein:
                    continue
                funde.append(Fund(normalform=name, typ=typ))

    return funde, unbekannte


# ── Zusammenfassen über Namensmengen ──────────────────────────────────────────
# Unverändert aus entity_utils._merge, ohne _source und ohne score: im
# GLiNER-Weg hat jeder Fund dieselbe Herkunft, die Rangfolge lief immer leer.

def _namensmenge(a: Akteur) -> set[str]:
    return {n.lower() for n in [a.normalform, *a.aliase] if n}


def zusammenfassen(gruppen: Sequence[Sequence[Akteur]]) -> list[Akteur]:
    """Führt zusammen, was sich in Normalform oder Alias berührt.

    Exakter Vergleich, kleingeschrieben. Kein Ähnlichkeitsmaß. Der zuerst
    gesehene Name bleibt die Normalform.
    """
    ergebnis: list[Akteur] = []
    for gruppe in gruppen:
        for eintrag in gruppe:
            if not (eintrag.normalform or "").strip():
                continue
            menge = _namensmenge(eintrag)
            treffer = next((e for e in ergebnis if _namensmenge(e) & menge), None)
            if treffer is None:
                ergebnis.append(Akteur(
                    normalform=eintrag.normalform,
                    typ=eintrag.typ,
                    aliase=list(eintrag.aliase),
                ))
                continue
            vorhanden = {a.lower() for a in treffer.aliase}
            vorhanden.add(treffer.normalform.lower())
            for alias in eintrag.aliase:
                if alias and alias.lower() not in vorhanden:
                    treffer.aliase.append(alias)
                    vorhanden.add(alias.lower())
    return ergebnis


def funde_zu_akteuren(funde: Sequence[Fund]) -> list[Akteur]:
    """Fasst gleichnamige Funde zusammen.

    Der Typ ist der des ersten Vorkommens, nicht die Mehrheit über alle. So
    macht es die Vorlage: _merge legt den Typ beim ersten Treffer fest und
    rührt ihn danach nicht mehr an. Abgestimmt wird erst eine Stufe später,
    zwischen den Namen eines Clusters.
    """
    typen: dict[str, str | None] = {}
    for f in funde:
        if f.normalform not in typen:
            typen[f.normalform] = f.typ
    return [Akteur(normalform=n, typ=t) for n, t in typen.items()]


# ── Union-Find über Ähnlichkeit ───────────────────────────────────────────────
# Unverändert aus entity_gliner._embedding_cluster.

def _wurzeln(anzahl: int, paare: Iterable[tuple[int, int]]) -> list[int]:
    eltern = list(range(anzahl))

    def finde(x: int) -> int:
        while eltern[x] != x:
            eltern[x] = eltern[eltern[x]]
            x = eltern[x]
        return x

    for i, j in paare:
        wi, wj = finde(i), finde(j)
        if wi != wj:
            eltern[wi] = wj
    return [finde(i) for i in range(anzahl)]


def waehle_normalform(namen: Sequence[str]) -> str:
    """Die vollständigste: meiste Wörter, bei Gleichstand längster String."""
    return max(namen, key=lambda n: (len(n.split()), len(n)))


def typ_mehrheit(typen: Sequence[str | None]) -> str | None:
    """Häufigster Typ. Bei Gleichstand der zuerst gesehene.

    None zählt mit: kennt die Abbildung die Mehrheit der Labels nicht, bleibt
    der Akteur ohne Typ, statt einen zu erfinden.
    """
    if not typen:
        return None
    return Counter(typen).most_common(1)[0][0]


def gruppiere(
    akteure: Sequence[Akteur], embeddings: np.ndarray, schwelle: float
) -> list[Akteur]:
    """Führt Akteure zusammen, deren Namen sich ähneln.

    Volle N×N-Kosinusmatrix, Union-Find über alle Paare ab der Schwelle. Die
    Beziehung ist transitiv: A~B und B~C führt A, B und C zusammen, auch wenn
    A und C darunter liegen.

    Eingebettet wird der bloße Name, nicht sein Kontext — deshalb trägt das
    Verfahren Schreibvarianten zusammen und keine verschiedenen Namen für
    dieselbe Person.
    """
    if not akteure:
        return []

    aehnlichkeit = embeddings @ embeddings.T
    paare = [
        (i, j)
        for i in range(len(akteure))
        for j in range(i + 1, len(akteure))
        if float(aehnlichkeit[i, j]) >= schwelle
    ]
    wurzeln = _wurzeln(len(akteure), paare)

    gruppen: dict[int, list[int]] = {}
    for i, w in enumerate(wurzeln):
        gruppen.setdefault(w, []).append(i)

    ergebnis: list[Akteur] = []
    for indizes in gruppen.values():
        gruppe = [akteure[i] for i in indizes]
        normalform = waehle_normalform([a.normalform for a in gruppe])
        aliase: set[str] = set()
        for a in gruppe:
            if a.normalform != normalform:
                aliase.add(a.normalform)
            aliase.update(a.aliase)
        aliase.discard(normalform)
        ergebnis.append(Akteur(
            normalform=normalform,
            typ=typ_mehrheit([a.typ for a in gruppe]),
            aliase=sorted(aliase),
        ))
    return ergebnis


def verschmelzen(akteure: Sequence[Akteur], behalten: str) -> Akteur:
    """Führt Akteure zu einem zusammen. Der Aufrufer bestimmt die Normalform.

    Die Vorlage nahm immer den linken Eintrag des Paares, unabhängig davon,
    welcher Name der bessere war.
    """
    gewaehlt = next((a for a in akteure if a.normalform == behalten), None)
    if gewaehlt is None:
        raise ValueError(
            f"'{behalten}' ist keiner der zu verschmelzenden Akteure."
        )
    aliase: set[str] = set()
    for a in akteure:
        if a.normalform != behalten:
            aliase.add(a.normalform)
        aliase.update(a.aliase)
    aliase.discard(behalten)
    return Akteur(
        normalform=behalten,
        typ=gewaehlt.typ if gewaehlt.typ is not None else typ_mehrheit(
            [a.typ for a in akteure]
        ),
        aliase=sorted(aliase),
    )


# ── Zuordnung zu Einheiten ────────────────────────────────────────────────────
# Wortgrenz-Regex unverändert aus match_entities.build_patterns; neu ist nur,
# dass die Fundstellen behalten werden statt bloß der Treffer.

def muster_fuer(akteur: Akteur) -> re.Pattern | None:
    """Ein Regex über Normalform und Aliase, längste Alternative zuerst."""
    begriffe = [akteur.normalform, *akteur.aliase]
    begriffe = list(dict.fromkeys(b.strip() for b in begriffe if b and b.strip()))
    begriffe = [b for b in begriffe if len(b) >= ALIAS_MINDESTLAENGE]
    if not begriffe:
        return None
    alternativen = "|".join(
        re.escape(b) for b in sorted(begriffe, key=len, reverse=True)
    )
    return re.compile(rf"(?<!\w)(?:{alternativen})(?!\w)", re.IGNORECASE)


def fundstellen(
    einheiten: Sequence[tuple[int, str]], muster: re.Pattern
) -> list[Fundstelle]:
    """Alle Vorkommen des Musters, mit Anfang und Ende im Text der Einheit."""
    treffer: list[Fundstelle] = []
    for einheit_id, text in einheiten:
        for m in muster.finditer(text or ""):
            treffer.append(Fundstelle(einheit_id=einheit_id, start=m.start(), ende=m.end()))
    return treffer


# ── Verschmelzungskandidaten ──────────────────────────────────────────────────

def levenshtein(a: str, b: str) -> int:
    """Editierabstand, kleingeschrieben. Aus entity_editor._levenshtein."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    m, n = len(a), len(b)
    vorher = list(range(n + 1))
    for i in range(1, m + 1):
        jetzt = [i] + [0] * n
        for j in range(1, n + 1):
            jetzt[j] = (
                vorher[j - 1] if a[i - 1] == b[j - 1]
                else 1 + min(vorher[j], jetzt[j - 1], vorher[j - 1])
            )
        vorher = jetzt
    return vorher[n]


def band(schwelle: float) -> tuple[float, float]:
    """Der Streifen unterhalb der Verschmelzungsschwelle: was knapp nicht reichte.

    Fest verdrahtet waren 0,80–0,91 — richtig für MiniLM (0,92), zu hoch für
    jeden Anbieter mit anderer Skalierung.
    """
    oben = schwelle - BAND_ABSTAND
    return round(oben - BAND_BREITE, 10), round(oben, 10)


def kandidaten(
    akteure: Sequence[Akteur],
    embeddings: np.ndarray | None,
    schwelle: float,
) -> list[Kandidat]:
    """Alle Paare, die eine der drei Regeln anschlagen lässt.

    Rangfolge, wenn mehrere Regeln dasselbe Paar treffen:
    alias vor schreibweise vor aehnlichkeit — vom härteren zum weicheren Beleg.
    Ein Paar erscheint genau einmal.

    Die Indizes beziehen sich auf akteure. Die Vorlage ließ je Akteur höchstens
    ein Paar zu, weil ein Verschmelzen im Browser die Listenplätze der übrigen
    verschob; mit Kennungen in der Datenbank ist das gegenstandslos.
    """
    gefunden: dict[tuple[int, int], Kandidat] = {}

    def merke(i: int, j: int, grund: str, mass: float | None) -> None:
        schluessel = (min(i, j), max(i, j))
        if schluessel in gefunden:
            return
        gefunden[schluessel] = Kandidat(
            a=schluessel[0], b=schluessel[1], grund=grund, mass=mass
        )

    mengen = [_namensmenge(a) for a in akteure]

    for i in range(len(akteure)):
        for j in range(i + 1, len(akteure)):
            gemeinsam = {
                n for n in mengen[i] & mengen[j] if len(n) >= ALIAS_MINDESTLAENGE
            }
            if gemeinsam:
                merke(i, j, "alias", None)
                continue
            ni, nj = akteure[i].normalform.strip(), akteure[j].normalform.strip()
            if (len(ni) >= LEVENSHTEIN_MINDESTLAENGE
                    and len(nj) >= LEVENSHTEIN_MINDESTLAENGE):
                abstand = levenshtein(ni, nj)
                if abstand < LEVENSHTEIN_GRENZE:
                    merke(i, j, "schreibweise", float(abstand))

    if embeddings is not None and len(akteure) > 1:
        unten, oben = band(schwelle)
        aehnlichkeit = embeddings @ embeddings.T
        for i in range(len(akteure)):
            for j in range(i + 1, len(akteure)):
                s = float(aehnlichkeit[i, j])
                if unten <= s <= oben:
                    merke(i, j, "aehnlichkeit", round(s, 3))

    return [gefunden[s] for s in sorted(gefunden)]
