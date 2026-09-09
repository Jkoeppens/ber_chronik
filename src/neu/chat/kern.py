"""
kern.py — Absätze zu einer Frage finden und den Prompt daraus bauen

Reine Funktionen: Zeichenketten und Zahlen rein, Ranglisten und Prompts raus.
Keine Datenbank, kein Netz, keine Dateien. Auch das Einbetten kommt nicht
hierher — der Kern bekommt fertige Vektoren.

Die Fachlogik der Stichwortsuche ist übernommen aus
src/generalized/dev_server.py:
    _CHAT_STOPWORDS, _chat_keywords, _chat_search samt der Grenze von 20
    Absätzen, dazu _CHAT_SYSTEM und _CHAT_USER

Ein Unterschied, und der ist der Grund für die Übernahme: das Regex der
Vorlage war r"[A-Za-zÄÖÜäöüß]+" und nahm damit keine Ziffern auf. In einer
Chronik, die aus Datumsangaben besteht, ergab "Was war 2012?" null Stichwörter
und damit null Treffer — die Frage, die man an ein solches Material zuerst
stellt, war die einzige, die nicht ging.

Zwei Wege, eine Rangfolge. Die Stichwörter finden, was wörtlich dasteht; die
Vektoren finden, was dasselbe meint. Zusammengelegt werden sie mit Reciprocal
Rank Fusion: jede Einheit bekommt sum(1 / (K + rang)) über beide Ranglisten.
Bewusst keine gewichtete Summe der Rohwerte — ein Trefferzähler und ein Kosinus
haben keine gemeinsame Einheit, und jedes Gewicht dazwischen wäre eine Zahl,
die jemand pflegen müsste, ohne je zu wissen, ob sie stimmt. Über Ränge
verglichen fällt beides weg: es zählt nur, wie weit oben etwas steht.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

# ── Maße ──────────────────────────────────────────────────────────────────────

#: So viele Absätze gehen in den Prompt. Aus der Vorlage (top_n=20).
ABSAETZE = 20

#: So viele Stichwörter werden aus einer Frage gezogen. Aus der Vorlage.
STICHWOERTER = 6

#: Kürzer als das zählt nicht als Stichwort. Aus der Vorlage.
MINDESTLAENGE = 4

#: Die Dämpfung in der Reciprocal Rank Fusion. 60 ist der Wert aus der
#: ursprünglichen Arbeit von Cormack u.a. und seither der übliche. Er ist groß
#: genug, dass Platz 1 und Platz 3 nahe beieinander liegen — gewollt, denn
#: keiner der beiden Wege ist genau genug, um seinen ersten Platz zu verteidigen.
RRF_DAEMPFUNG = 60


# ── Wortfindung ───────────────────────────────────────────────────────────────

#: Buchstaben UND Ziffern. Die Ziffern sind der Unterschied zur Vorlage.
_WORT = re.compile(r"[A-Za-zÄÖÜäöüß0-9]+")

#: Wörter, die in jeder Frage vorkommen und deshalb nichts unterscheiden.
#: Wörtlich aus dev_server._CHAT_STOPWORDS. Zahlen stehen hier keine — eine
#: Jahreszahl ist nie ein Füllwort.
STOPPWOERTER = frozenset({
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "als", "am",
    "an", "auch", "auf", "aus", "bei", "beim", "bin", "bis", "bitte", "da",
    "damit", "dann", "dass", "dem", "den", "denn", "der", "des", "die", "dies",
    "dieser", "dieses", "doch", "dort", "durch", "ein", "eine", "einem", "einen",
    "einer", "eines", "er", "es", "etwa", "gibt", "haben", "hatte", "hier",
    "ihm", "ihn", "ihnen", "ihr", "ihre", "im", "immer", "ist", "kann", "kein",
    "keine", "mal", "man", "mehr", "mich", "mir", "mit", "nach", "nicht", "noch",
    "nun", "nur", "oder", "ohne", "sehr", "sein", "sich", "sie", "sind", "soll",
    "sowie", "über", "um", "und", "unter", "uns", "vom", "von", "vor", "war",
    "waren", "warum", "was", "weil", "wenn", "wer", "werden", "wie", "wird",
    "wir", "wann", "worden", "wurde", "wurden", "zu", "zum", "zur", "zwischen",
})


def stichwoerter(frage: str, hoechstens: int = STICHWOERTER) -> list[str]:
    """Die Wörter der Frage, an denen man suchen kann.

    Kleingeschrieben, ohne Füllwörter, ohne alles unter MINDESTLAENGE Zeichen,
    die ersten `hoechstens`. Reihenfolge wie in der Frage.
    """
    gefunden = (w.lower() for w in _WORT.findall(frage))
    behalten = [w for w in gefunden
                if len(w) >= MINDESTLAENGE and w not in STOPPWOERTER]
    return behalten[:hoechstens]


# ── Was durchsucht wird ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class Einheit:
    """Ein Absatz, so wie der Kern ihn sieht."""

    id: int
    anker: str          # die Kennung, unter der viz/ ihn wiederfindet
    jahr: int | None
    text: str


# ── Weg 1: Stichwörter ────────────────────────────────────────────────────────

def stichwort_rangliste(
    einheiten: Sequence[Einheit], gesucht: Sequence[str]
) -> list[int]:
    """Einheiten-Kennungen, absteigend nach Zahl der getroffenen Stichwörter.

    Gezählt wird wie in der Vorlage: ein Punkt je Stichwort, das irgendwo im
    Text vorkommt — nicht je Fundstelle. Wer null trifft, steht nicht drin.

    Bei Gleichstand entscheidet die Kennung und nicht die Reihenfolge der
    Eingabe. Das ist der zweite Unterschied zur Vorlage, und er ist nötig:
    gemessen an ber liegen bei einer typischen Frage 43 von 45 Treffern
    gleichauf, die Auswahl der besten 20 war dort in Wahrheit die Position in
    der Datei. Willkürlich bleibt sie so oder so, aber jetzt ist sie
    wiederholbar und damit prüfbar.
    """
    if not gesucht:
        return []
    bewertet: list[tuple[int, int]] = []
    for e in einheiten:
        gesenkt = e.text.lower()
        punkte = sum(1 for wort in gesucht if wort in gesenkt)
        if punkte:
            bewertet.append((punkte, e.id))
    bewertet.sort(key=lambda p: (-p[0], p[1]))
    return [einheit_id for _, einheit_id in bewertet]


# ── Weg 2: Bedeutung ──────────────────────────────────────────────────────────

def _normiert(m: np.ndarray) -> np.ndarray:
    laenge = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(laenge, 1e-12)


def aehnlichkeiten(frage: np.ndarray, einheiten: np.ndarray) -> np.ndarray:
    """Kosinus zwischen der Frage und jeder Einheit.

    Normiert wird hier, obwohl der Speicher normierte Vektoren verspricht: ein
    Skalarprodukt über einen unnormierten Vektor sieht aus wie eine Ähnlichkeit
    und ist keine. Der Preis ist eine Division, der Gewinn ist, dass die
    Funktion für sich stimmt.
    """
    if einheiten.size == 0:
        return np.zeros(0, dtype=np.float32)
    return _normiert(np.asarray(frage, dtype=np.float32)) @ _normiert(
        np.asarray(einheiten, dtype=np.float32)).T


def aehnlichkeits_rangliste(
    ids: Sequence[int], werte: np.ndarray, hoechstens: int | None = None
) -> list[int]:
    """Einheiten-Kennungen, absteigend nach Ähnlichkeit.

    Ohne Schwellwert: die Rangfolge zählt, nicht die Höhe. Ein Wert, ab dem
    etwas 'ähnlich genug' wäre, hinge am Modell und wäre wieder eine Zahl zum
    Pflegen. Abgeschnitten wird stattdessen nach Platz — was hinten steht,
    trägt in der Zusammenführung ohnehin fast nichts bei.
    """
    if len(ids) == 0 or werte.size == 0:
        return []
    reihe = sorted(range(len(ids)), key=lambda n: (-float(werte[n]), ids[n]))
    if hoechstens is not None:
        reihe = reihe[:hoechstens]
    return [ids[n] for n in reihe]


# ── Zusammenführen ────────────────────────────────────────────────────────────

def verschmelzen(
    ranglisten: Iterable[Sequence[int]],
    daempfung: int = RRF_DAEMPFUNG,
    hoechstens: int = ABSAETZE,
) -> list[int]:
    """Reciprocal Rank Fusion über beliebig viele Ranglisten.

    Jede Einheit bekommt sum(1 / (daempfung + rang)), Rang ab 1 gezählt. Wer in
    beiden Listen vorkommt, steht deshalb fast immer vor dem, der nur in einer
    ganz oben steht — und genau das ist der Zweck: Einigkeit zweier Verfahren
    wiegt schwerer als die Zuversicht eines einzelnen.

    Eine leere Rangliste trägt nichts bei und stört nicht. Fällt ein Weg aus,
    bleibt das Ergebnis das des anderen.
    """
    punkte: dict[int, float] = {}
    for liste in ranglisten:
        for rang, einheit_id in enumerate(liste, start=1):
            punkte[einheit_id] = punkte.get(einheit_id, 0.0) + 1.0 / (daempfung + rang)
    geordnet = sorted(punkte.items(), key=lambda p: (-p[1], p[0]))
    return [einheit_id for einheit_id, _ in geordnet[:hoechstens]]


# ── Der Prompt ────────────────────────────────────────────────────────────────

SYSTEM = """\
Du beantwortest Fragen auf Basis von Auszügen aus historischem Quellmaterial.

Antworte auf Deutsch. Gliedere deine Antwort nach relevanten thematischen Kategorien \
die sich aus den Auszügen ergeben. Nenne konkrete Daten, Personen und Beschlüsse. \
Halte dich strikt an die Auszüge, erfinde keine Fakten. \
Falls die Auszüge nicht genug Information enthalten, sage das kurz.

Zitierregeln (strikt einzuhalten):
- Jeder Auszug beginnt mit einer ID in eckigen Klammern, z.B. [main-e719]. Nutze exakt diese ID als Quellenangabe — kopiere sie Zeichen für Zeichen, kürze sie nicht ab.
- Schreibe niemals "doc_anchor" oder Platzhalter — nur echte IDs aus den Auszügen.
- Kein "source:", keine doppelten Klammern [[...]], kein Zusatztext in den Klammern.
- Setze die Quellenangabe DIREKT nach der Aussage, die du damit belegst — niemals alle Quellen am Ende sammeln.
- Mehrere Quellen für eine Aussage: direkt hintereinander ohne Komma, z.B. [ID1][ID2].

Antworte mit Fließtext und kurzen Überschriften (##), keine JSON-Ausgabe.\
"""

_BENUTZER = """\
Frage: {frage}

Auszüge ({anzahl} gesamt):
{absaetze}\
"""


def benutzer_prompt(frage: str, absaetze: Sequence[Einheit]) -> str:
    """Die Frage und die gefundenen Absätze, jeder mit seinem Anker davor."""
    block = "\n\n".join(
        f"[{e.anker}] {e.jahr if e.jahr is not None else '?'}: {e.text}"
        for e in absaetze
    )
    return _BENUTZER.format(frage=frage, anzahl=len(absaetze), absaetze=block)


# ── Was das Modell wirklich belegt hat ────────────────────────────────────────

#: Dieselben Formen, die viz/search.js aus dem Fließtext klaubt: [anker],
#: [[anker]] und [source: anker]. Der Systemprompt verbietet die letzten beiden;
#: dass beide Seiten sie trotzdem kennen, sagt genug darüber, wie verlässlich
#: ein Prompt eine Form erzwingt.
_ANKER_IM_TEXT = re.compile(r"\[(?:source:\s*)?\[?([A-Za-z0-9][\w\-]*)\]?\]")


def genannte_quellen(antwort: str, angeboten: Iterable[str]) -> list[str]:
    """Die Anker, die im Antworttext tatsächlich stehen — in ihrer Reihenfolge.

    Der alte Weg meldete die 20 angebotenen Absätze als 'Verwendete Quellen'
    und fragte das Modell nie, welche es benutzt hat. Das war keine Ungenauigkeit,
    sondern eine falsche Auskunft: die Überschrift behauptete etwas, das niemand
    geprüft hatte.

    Gegen `angeboten` abgeglichen, weil ein Modell Anker erfindet. Was nicht im
    Prompt stand, kann es nicht gelesen haben — und ein erfundener Anker fände
    in viz/ ohnehin keinen Absatz.
    """
    erlaubt = set(angeboten)
    gesehen: list[str] = []
    for treffer in _ANKER_IM_TEXT.findall(antwort):
        if treffer in erlaubt and treffer not in gesehen:
            gesehen.append(treffer)
    return gesehen
