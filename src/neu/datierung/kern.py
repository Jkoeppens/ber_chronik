"""
kern.py — Zeitanker erkennen und undatierte Einheiten interpolieren

Nimmt Einheiten als Objekte und gibt Datierungen zurück. Keine Datenbank,
keine Dateien, kein print. Das Quellformat kommt als Parameter — die Vorlage
las dafür mitten in der Verzweigung eine Doc-Config von der Platte.

Fachlogik unverändert übernommen aus src/generalized/detect_anchors.py
(_strip_non_anchors, detect_anchors, die Regexe, die 16 _EVENTS-Muster, die
Rangfolge in _process_literatur) und src/generalized/interpolate_anchors.py
(apply_overrides, interpolate — Aufspannen zwischen zwei Ankern, Vorwärtserben
nach dem letzten, kein Rückwärtserben vor dem ersten).

Zwei beschlossene Verhaltensänderungen gegenüber der Vorlage:

  1. Die Quellennotation wird gelesen. publikationsdatum trägt bei
     presseexzerpt das Erscheinungsdatum als Text ("01.01.1989") und blieb
     bisher unbenutzt. Es schlägt die Jahresüberschrift, weil es genauer ist.
  2. Kein Bypass. Overrides gelten für alle drei Quellformate; die Vorlage
     gab für presseartikel vorzeitig zurück.

Drei behobene Defekte:

  - Eine Handkorrektur wird eine echte anker-Zeile mit herkunft='manuell'.
  - Ein geerbtes Überschriftsjahr bekommt herkunft='ueberschrift', nicht
    'text' — die Vorlage schrieb dort precision='exact', obwohl der Anker
    selbst 'heading' trug.
  - Das Quellformat ist ein Parameter.

Vokabular durchgehend deutsch:
  praezision            tag | monat | jahr | spanne | keine
  datierung_herkunft    text | ueberschrift | frontmatter | quellennotation
                        | ereignis | interpoliert | manuell
  anker.herkunft        dieselben plus jahrzehnt
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

# ── Wertevorräte ──────────────────────────────────────────────────────────────

QUELLFORMATE = ("literaturexzerpt", "presseexzerpt", "pressesammlung")

PRAEZISIONEN = ("tag", "monat", "jahr", "spanne", "keine")

HERKUENFTE = ("text", "ueberschrift", "frontmatter", "quellennotation",
              "ereignis", "interpoliert", "manuell")

# jahrzehnt gibt es nur am Anker, nie als Datierungsherkunft: der Wert wird
# erkannt, trägt aber kein Jahr.
ANKER_HERKUENFTE = HERKUENFTE + ("jahrzehnt",)


class UnbekanntesQuellformat(ValueError):
    pass


def quellformat_pruefen(wert: str) -> str:
    if wert not in QUELLFORMATE:
        raise UnbekanntesQuellformat(
            f"Unbekanntes Quellformat '{wert}'. Erlaubt: {' | '.join(QUELLFORMATE)}"
        )
    return wert


# ── Regexe, unverändert aus der Vorlage ───────────────────────────────────────

# Lebensdaten (YYYY–YYYY) bzw. (YYYY?–YYYY): beide Zahlen 1700–2000
_LEBENSDATEN = re.compile(
    r"\(\s*(1[7-9]\d{2})\s*\??\s*[–—\-]+\s*(1[7-9]\d{2})\s*\??\s*\)"
)
# (dYYYY) oder (d.YYYY): Todesjahrangabe
_TODESJAHR = re.compile(r"\(\s*[dD]\.?\s*(1[7-9]\d{2})\s*\)")

# Vierstelliges Jahr als alleiniger Inhalt (Jahres-Überschrift)
_NUR_JAHR = re.compile(r"^\s*(1[6-9]\d{2}|20[0-2]\d)\s*$")

# Jahreszahl 1600–2029. (?<!\d)/(?!\d) statt \b: erfasst auch
# "1898bibliothekswesen" und "1860er". Klammerjahre werden vorher entfernt.
_KLAMMERJAHR = re.compile(r"\(\s*(?:1[6-9]\d{2}|20[0-2]\d)\s*\)")
_NACKTES_JAHR = re.compile(r"(?<!\d)(1[6-9]\d{2}|20[0-2]\d)(?!\d)")

_JAHRZEHNT = [
    re.compile(r"\b1[6-9]\d0er(?:\s+Jahre)?\b"),
    re.compile(r"\b(frühen?|Mitte|Ende|späten?)\s+1[6-9]\. Jahrhundert\b", re.I),
    re.compile(r"\b(early|mid|late)\s+\d{2}(th|st|nd|rd)\s+century\b", re.I),
    re.compile(r"\b(early|mid|late)\s+nineteenth\s+century\b", re.I),
    re.compile(r"\b(frühen?|Mitte|Ende)\s+des\s+\d{2}\.\s*Jahrhunderts?\b", re.I),
    re.compile(r"\bJahrhundert(?:wende)?\b"),
    re.compile(r"\b\d{2}\.\s*Jh\.\b"),
]

# Benannte Ereignisse → (Muster, Bezeichnung, ungefähres Jahr)
EREIGNISSE: list[tuple[re.Pattern, str, int | None]] = [
    (re.compile(r"\bTanzimat\b", re.I), "Tanzimat", 1839),
    (re.compile(r"\bGülhane\b", re.I), "Hatt-ı Şerif von Gülhane", 1839),
    (re.compile(r"\bJungtürk", re.I), "Jungtürkenrevolution", 1908),
    (re.compile(r"\bYoung Turk", re.I), "Young Turk Revolution", 1908),
    (re.compile(r"\bRevolution 1908\b", re.I), "Revolution 1908", 1908),
    (re.compile(r"\bGegenputsch\b", re.I), "Gegenputsch 1909", 1909),
    (re.compile(r"\bKonterrev", re.I), "Konterrevolution 1909", 1909),
    (re.compile(r"\bcounter.?rev", re.I), "Counter-Revolution 1909", 1909),
    (re.compile(r"\bWK\s*1\b|\bWKI\b", re.I), "Erster Weltkrieg", 1914),
    (re.compile(r"\bErster\s+Weltkrieg\b", re.I), "Erster Weltkrieg", 1914),
    (re.compile(r"\bWorld War\s+I\b", re.I), "World War I", 1914),
    (re.compile(r"\bpre.?World War\b", re.I), "pre-World War I", 1914),
    (re.compile(r"\bBalkankrieg\b", re.I), "Balkankrieg", 1912),
    (re.compile(r"\bBalkan War\b", re.I), "Balkan War", 1912),
    (re.compile(r"\bLibyen(?:krieg)?\b", re.I), "Libyen/Tripolitanien", 1911),
    (re.compile(r"\bTripolit", re.I), "Tripolit. Krieg", 1911),
]

# Erscheinungsdatum in der Quellennotation: "01.01.1989", "3.12.89"
_QUELLENDATUM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{2,4})$")

# Frontmatter-Datum
_ISO_TAG = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_ISO_MONAT = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_JAHR = re.compile(r"^(\d{4})$")


# ── Ein- und Ausgabe ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Einheit:
    """Was der Kern von einer Einheit wissen muss."""

    id: int
    position: int
    typ: str
    text: str
    chronologie_gruppe: str | None = None
    publikationsdatum: str | None = None   # Rohform "01.01.1989"
    datum_frontmatter: str | None = None   # ISO aus dem Frontmatter


@dataclass(frozen=True)
class Anker:
    einheit_id: int
    jahr: int | None
    herkunft: str
    fundstelle: str = ""


@dataclass
class Datierung:
    einheit_id: int
    datum: str | None = None
    jahr_von: int | None = None
    jahr_bis: int | None = None
    praezision: str = "keine"
    herkunft: str | None = None
    anker: list[Anker] = field(default_factory=list)


@dataclass
class Override:
    """Eine Handkorrektur, vollständig genug, um sie wiederherzustellen.

    datum, praezision und fundstelle kommen mit, weil ein Neulauf sonst
    gröber zurückkäme als die Korrektur war: aus '2012-07-30' würde beim
    Wiederanwenden '2012', und die Begründung wäre weg. Eine Handkorrektur,
    die einen Neulauf nicht unverändert übersteht, ist keine.
    """

    einheit_id: int
    aktion: str                 # anker_setzen | undatierbar
    jahr_von: int | None = None
    jahr_bis: int | None = None
    datum: str | None = None
    praezision: str | None = None
    fundstelle: str = ""


# ── Datum von Hand ────────────────────────────────────────────────────────────

class UnlesbaresDatum(ValueError):
    pass


def datum_teile(roh: str) -> tuple[str, int, str]:
    """'2012' | '2012-07' | '2012-07-30' → (normiert, jahr, granularität).

    Ein Feld, drei Genauigkeiten — statt einer Regel, die vorschreibt, wie
    genau der Historiker sein darf. Was er schreibt, bestimmt die Präzision.
    """
    s = (roh or "").strip()
    if m := _ISO_TAG.match(s):
        tag = s[:10]
        try:
            datetime.strptime(tag, "%Y-%m-%d")
        except ValueError:
            raise UnlesbaresDatum(f"'{roh}' ist kein gültiger Tag.")
        return tag, int(m.group(1)), "tag"
    if m := _ISO_MONAT.match(s):
        if not 1 <= int(m.group(2)) <= 12:
            raise UnlesbaresDatum(f"'{roh}' hat keinen gültigen Monat.")
        return s[:7], int(m.group(1)), "monat"
    if m := _ISO_JAHR.match(s):
        return s[:4], int(m.group(1)), "jahr"
    raise UnlesbaresDatum(
        f"'{roh}' ist kein Datum. Erlaubt: 2012, 2012-07 oder 2012-07-30."
    )


def handdatierung(datum_von: str | None, datum_bis: str | None = None
                  ) -> tuple[str | None, int | None, int | None, str]:
    """(datum, jahr_von, jahr_bis, praezision) aus zwei Feldern.

    datum_von leer heißt undatierbar. datum_bis leer heißt Zeitpunkt — dann
    ist die Präzision die Genauigkeit des Feldes selbst.

    Bei einer Spanne, deren Enden feiner als ein Jahr sind, steht in `datum`
    das ISO-Intervall '2012-07-30/2013-02-01'. Die Spalte trägt sonst nur den
    Anfang, und das Ende wäre auf das Jahr eingedampft, ohne dass es jemand
    merkt. Wer `datum` liest, bekommt damit eher mehr als vorher; der Export
    fällt für alles, was kein reines Jahr und kein reiner Tag ist, ohnehin auf
    jahr_von zurück (src/neu/export/kern.py:_datum_js).
    """
    if not (datum_von or "").strip():
        return None, None, None, "keine"

    dv, jahr_von, granular = datum_teile(datum_von)
    if not (datum_bis or "").strip() or (datum_bis or "").strip() == dv:
        return dv, jahr_von, jahr_von, granular

    db, jahr_bis, _ = datum_teile(datum_bis)
    if jahr_bis < jahr_von or (jahr_bis == jahr_von and db < dv):
        raise UnlesbaresDatum(f"'{db}' liegt vor '{dv}'.")
    datum = dv if (len(dv) == 4 and len(db) == 4) else f"{dv}/{db}"
    return datum, jahr_von, jahr_bis, "spanne"


# ── Text zerlegen ─────────────────────────────────────────────────────────────

def ohne_nicht_anker(text: str) -> str:
    """Entfernt Lebensdaten, Todesjahre und Klammerjahre vor der Jahressuche.

    Unverändert aus _strip_non_anchors: Lebensdaten nur, wenn beide Jahre
    zwischen 1700 und 2000 liegen und weniger als 120 Jahre auseinander.
    """
    def entferne_lebensdaten(m: re.Match) -> str:
        j1, j2 = int(m.group(1)), int(m.group(2))
        if 1700 <= j1 <= 2000 and 1700 <= j2 <= 2000 and abs(j2 - j1) < 120:
            return ""
        return m.group(0)

    text = _LEBENSDATEN.sub(entferne_lebensdaten, text)
    text = _TODESJAHR.sub("", text)
    text = _KLAMMERJAHR.sub("", text)
    return text


def anker_im_text(text: str, einheit_id: int) -> list[Anker]:
    """Alle Anker aus einem Fließtext: Jahreszahlen, Jahrzehnte, Ereignisse."""
    gefunden: list[Anker] = []
    sauber = ohne_nicht_anker(text)

    for m in _NACKTES_JAHR.finditer(sauber):
        gefunden.append(Anker(einheit_id, int(m.group(1)), "text", m.group(1)))

    for muster in _JAHRZEHNT:
        for m in muster.finditer(text):
            gefunden.append(Anker(einheit_id, None, "jahrzehnt", m.group(0)))

    for muster, bezeichnung, jahr in EREIGNISSE:
        if muster.search(text):
            gefunden.append(Anker(einheit_id, jahr, "ereignis", bezeichnung))

    return gefunden


def jahr_aus_ueberschrift(text: str) -> int | None:
    m = _NUR_JAHR.match(text)
    return int(m.group(1)) if m else None


def quellendatum_lesen(roh: str | None) -> tuple[str, int] | None:
    """'01.01.1989' → ('1989-01-01', 1989). Zweistellige Jahre werden ergänzt.

    Mehrfachtreffer stehen mit ';' verkettet im Feld — es zählt der erste.
    None, wenn nichts Verwertbares dasteht.
    """
    if not roh:
        return None
    erster = roh.split(";")[0].strip()
    m = _QUELLENDATUM.match(erster)
    if not m:
        return None
    tag, monat, jahr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if jahr < 100:
        # Die Chronik läuft 1989–2017: 89 → 1989, 17 → 2017
        jahr += 1900 if jahr >= 50 else 2000
    if not (1 <= monat <= 12 and 1 <= tag <= 31):
        return None
    return f"{jahr:04d}-{monat:02d}-{tag:02d}", jahr


def frontmatter_datum_lesen(roh: str | None) -> tuple[str, int, str] | None:
    """ISO-Datum → (datum, jahr, praezision). None, wenn unlesbar."""
    if not roh:
        return None
    s = roh.strip()
    if m := _ISO_TAG.match(s):
        return s[:10], int(m.group(1)), "tag"
    if m := _ISO_MONAT.match(s):
        return s[:7], int(m.group(1)), "monat"
    if m := _ISO_JAHR.match(s):
        return s[:4], int(m.group(1)), "jahr"
    return None


# ── Anker erkennen, je Quellformat ────────────────────────────────────────────

def _datierung_literatur(einheiten: Sequence[Einheit]) -> list[Datierung]:
    """Rangfolge unverändert aus _process_literatur.

    1. Jahreszahlen im Text  → min/max spannen auf
    2. sonst Ereignisse      → min/max
    3. sonst Jahrzehnt       → erkannt, aber ohne Jahr
    4. sonst Überschriftsjahr
    5. sonst nichts

    Abweichung: Fall 4 bekommt herkunft='ueberschrift'. Die Vorlage schrieb
    dort precision='exact', obwohl der Anker 'heading' trug.
    """
    ergebnis: list[Datierung] = []
    aktives_jahr: int | None = None

    for e in einheiten:
        if e.typ == "heading":
            aktives_jahr = jahr_aus_ueberschrift(e.text)
            continue
        if e.typ != "content":
            continue

        anker = anker_im_text(e.text, e.id)
        jahre_text = [a.jahr for a in anker if a.herkunft == "text"]
        jahre_ereignis = [a.jahr for a in anker
                          if a.herkunft == "ereignis" and a.jahr is not None]

        if jahre_text:
            von, bis = min(jahre_text), max(jahre_text)
            d = Datierung(e.id, str(von), von, bis,
                          "jahr" if von == bis else "spanne", "text", anker)
        elif jahre_ereignis:
            von, bis = min(jahre_ereignis), max(jahre_ereignis)
            d = Datierung(e.id, str(von), von, bis,
                          "jahr" if von == bis else "spanne", "ereignis", anker)
        elif any(a.herkunft == "jahrzehnt" for a in anker):
            # Der Jahrzehntwert wird nicht ausgewertet — wie in der Vorlage.
            d = Datierung(e.id, None, None, None, "keine", None, anker)
        elif aktives_jahr is not None:
            anker = [Anker(e.id, aktives_jahr, "ueberschrift", str(aktives_jahr))]
            d = Datierung(e.id, str(aktives_jahr), aktives_jahr, aktives_jahr,
                          "jahr", "ueberschrift", anker)
        else:
            d = Datierung(e.id, None, None, None, "keine", None, anker)

        ergebnis.append(d)
    return ergebnis


def _datierung_presseexzerpt(einheiten: Sequence[Einheit]) -> list[Datierung]:
    """Erscheinungsdatum schlägt Jahresüberschrift — es ist genauer.

    Neu gegenüber der Vorlage: publikationsdatum wird gelesen. Fehlt es,
    gilt weiterhin die Überschrift.
    """
    ergebnis: list[Datierung] = []
    aktives_jahr: int | None = None

    for e in einheiten:
        if e.typ == "heading":
            j = jahr_aus_ueberschrift(e.text)
            if j is not None:
                aktives_jahr = j
            continue
        if e.typ != "content":
            continue

        notiert = quellendatum_lesen(e.publikationsdatum)
        if notiert is not None:
            datum, jahr = notiert
            anker = [Anker(e.id, jahr, "quellennotation", e.publikationsdatum or "")]
            ergebnis.append(Datierung(e.id, datum, jahr, jahr, "tag",
                                      "quellennotation", anker))
        elif aktives_jahr is not None:
            anker = [Anker(e.id, aktives_jahr, "ueberschrift", str(aktives_jahr))]
            ergebnis.append(Datierung(e.id, str(aktives_jahr), aktives_jahr,
                                      aktives_jahr, "jahr", "ueberschrift", anker))
        else:
            ergebnis.append(Datierung(e.id, None, None, None, "keine", None, []))
    return ergebnis


def _datierung_pressesammlung(einheiten: Sequence[Einheit]) -> list[Datierung]:
    """Ein Artikel, ein Datum aus dem Frontmatter."""
    ergebnis: list[Datierung] = []
    for e in einheiten:
        if e.typ != "content":
            continue
        gelesen = frontmatter_datum_lesen(e.datum_frontmatter)
        if gelesen is not None:
            datum, jahr, praez = gelesen
            anker = [Anker(e.id, jahr, "frontmatter", e.datum_frontmatter or "")]
            ergebnis.append(Datierung(e.id, datum, jahr, jahr, praez,
                                      "frontmatter", anker))
        else:
            ergebnis.append(Datierung(e.id, None, None, None, "keine", None, []))
    return ergebnis


def anker_erkennen(einheiten: Sequence[Einheit], quellformat: str) -> list[Datierung]:
    """Erste Stufe: Anker aus dem Material. Das Quellformat ist ein Parameter."""
    quellformat_pruefen(quellformat)
    if quellformat == "literaturexzerpt":
        return _datierung_literatur(einheiten)
    if quellformat == "presseexzerpt":
        return _datierung_presseexzerpt(einheiten)
    return _datierung_pressesammlung(einheiten)


# ── Overrides ─────────────────────────────────────────────────────────────────

def overrides_anwenden(
    datierungen: Sequence[Datierung], overrides: Sequence[Override]
) -> tuple[list[Datierung], set[int], list[int]]:
    """Wendet Handkorrekturen an, vor der Interpolation.

    Gibt (Datierungen, undatierbare Einheiten, ins Leere zeigende Overrides)
    zurück. Ein Override auf eine Einheit, die es im Bestand nicht gibt, wird
    gemeldet statt stillschweigend verworfen.
    """
    bekannt = {d.einheit_id for d in datierungen}
    ins_leere = [o.einheit_id for o in overrides if o.einheit_id not in bekannt]
    nach_id = {o.einheit_id: o for o in overrides if o.einheit_id in bekannt}

    ergebnis: list[Datierung] = []
    undatierbar: set[int] = set()

    for d in datierungen:
        o = nach_id.get(d.einheit_id)
        if o is None:
            ergebnis.append(d)
            continue

        if o.aktion == "anker_setzen":
            von, bis = o.jahr_von, o.jahr_bis
            if von is not None and bis is None:
                bis = von
            # Was die Korrektur mitbringt, gilt: sonst käme sie beim
            # Wiederanwenden gröber zurück, als sie gesetzt wurde.
            praez = o.praezision or (
                "keine" if von is None else ("jahr" if von == bis else "spanne")
            )
            datum = o.datum if o.datum is not None else (
                None if von is None else str(von)
            )
            fundstelle = o.fundstelle or (
                f"{von}–{bis}" if von != bis else str(von)
            )
            ergebnis.append(Datierung(
                d.einheit_id,
                datum=datum,
                jahr_von=von, jahr_bis=bis, praezision=praez,
                herkunft="manuell",
                # Die Handkorrektur wird eine echte anker-Zeile.
                anker=[Anker(d.einheit_id, von, "manuell", fundstelle)]
                if von is not None else [],
            ))
        elif o.aktion == "undatierbar":
            undatierbar.add(d.einheit_id)
            # Auch 'undatierbar' bekommt eine anker-Zeile, wenn eine Begründung
            # dabei ist: sie ist der einzige Ort, an dem sie stehen kann, und
            # ohne sie wäre nach dem nächsten Lauf nicht mehr zu sehen, warum
            # hier nichts steht. jahr bleibt NULL — die Spalte erlaubt es.
            ergebnis.append(Datierung(
                d.einheit_id, None, None, None, "keine", "manuell",
                [Anker(d.einheit_id, None, "manuell", o.fundstelle)]
                if o.fundstelle else [],
            ))
        else:
            ergebnis.append(d)

    return ergebnis, undatierbar, ins_leere


# ── Interpolation ─────────────────────────────────────────────────────────────

def _mittleres_jahr(d: Datierung) -> int | None:
    """Ein repräsentatives Jahr — der Mittelpunkt der Spanne."""
    if d.jahr_von is not None and d.jahr_bis is not None:
        return (d.jahr_von + d.jahr_bis) // 2
    return d.jahr_von if d.jahr_von is not None else d.jahr_bis


def interpolieren(
    datierungen: Sequence[Datierung],
    gruppen: dict[int, str],
    undatierbar: set[int] | None = None,
) -> list[Datierung]:
    """Undatierte Einheiten aus ihren Nachbarn datieren, je Gruppe.

    Unverändert aus interpolate_anchors.interpolate:
      - zwischen zwei Ankern wird eine Spanne aufgespannt, nicht verteilt
      - nach dem letzten Anker wird vorwärts geerbt
      - vor dem ersten Anker bleibt es undatiert; kein Rückwärtserben
      - eine Gruppe ohne einen einzigen Anker bleibt ganz undatiert
    """
    undatierbar = undatierbar or set()
    ergebnis = [Datierung(d.einheit_id, d.datum, d.jahr_von, d.jahr_bis,
                          d.praezision, d.herkunft, list(d.anker))
                for d in datierungen]

    nach_gruppe: dict[str, list[int]] = {}
    for i, d in enumerate(ergebnis):
        nach_gruppe.setdefault(gruppen.get(d.einheit_id, "") or "", []).append(i)

    for _gruppe, stellen in nach_gruppe.items():
        datiert = [i for i in stellen
                   if _mittleres_jahr(ergebnis[i]) is not None
                   and ergebnis[i].einheit_id not in undatierbar]
        if not datiert:
            continue

        for pos in stellen:
            d = ergebnis[pos]
            if d.einheit_id in undatierbar:
                continue
            if _mittleres_jahr(d) is not None:
                continue

            davor = [i for i in datiert if i < pos]
            danach = [i for i in datiert if i > pos]
            jahr_davor = _mittleres_jahr(ergebnis[davor[-1]]) if davor else None
            jahr_danach = _mittleres_jahr(ergebnis[danach[0]]) if danach else None

            if jahr_davor is None:
                continue                      # kein Rückwärtserben
            if jahr_danach is None:
                von = bis = jahr_davor        # Vorwärtserben
            else:
                von, bis = jahr_davor, jahr_danach   # aufspannen

            d.jahr_von, d.jahr_bis = von, bis
            d.datum = str(von)
            d.praezision = "jahr" if von == bis else "spanne"
            d.herkunft = "interpoliert"

    return ergebnis


# ── Beides zusammen ───────────────────────────────────────────────────────────

@dataclass
class DatierungsErgebnis:
    datierungen: list[Datierung]
    ins_leere_zeigende_overrides: list[int] = field(default_factory=list)


def datieren(
    einheiten: Sequence[Einheit],
    quellformat: str,
    overrides: Sequence[Override] = (),
) -> DatierungsErgebnis:
    """Anker erkennen, Overrides anwenden, interpolieren.

    Kein Bypass: die Overrides gelten für alle drei Quellformate, und
    interpoliert wird ebenfalls überall — bei den Presseformaten ist meist
    nichts mehr zu tun, weil schon alles datiert ist.
    """
    datierungen = anker_erkennen(einheiten, quellformat)
    datierungen, undatierbar, ins_leere = overrides_anwenden(datierungen, overrides)
    gruppen = {e.id: (e.chronologie_gruppe or "") for e in einheiten}
    datierungen = interpolieren(datierungen, gruppen, undatierbar)
    return DatierungsErgebnis(datierungen, ins_leere)
