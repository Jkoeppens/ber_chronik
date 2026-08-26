"""
vokabular.py — die Wertevorräte, jeder genau einmal

Jede Spalte, die nur bestimmte Werte annehmen darf, hat hier ihren Vorrat.
Einmal als `Literal` geschrieben, die Laufzeitliste daraus abgeleitet — nicht
danebengeschrieben. Ein `Literal` und ein Tupel, die auseinanderlaufen können,
sind zwei Wahrheiten über dieselbe Sache.

Vorher standen die Vorräte an bis zu drei Stellen: 'literaturexzerpt' in
ingest/kern.py, in datierung/kern.py und als Literal in modelle.py, dazu zwei
wortgleiche quellformat_pruefen(). Und `HERKUENFTE` gab es dreimal mit drei
verschiedenen Bedeutungen — automatisch|manuell, text|ueberschrift|…,
gliner|manuell. Derselbe Name, drei Vorräte.

Die Namen hier sind deshalb nach der Spalte benannt, der sie gehören, nicht
nach dem Modul, in dem sie gebraucht werden.

Wer einen Wert prüft, nimmt `pruefen()`: eine Meldung, überall dieselbe.
"""

from __future__ import annotations

from typing import Literal, get_args

# ── quelle.quellformat ────────────────────────────────────────────────────────
# Die drei Quellentypen aus CLAUDE.md. Welcher vorliegt, bestimmt jeden
# Pipeline-Schritt — Segmentierung, Datierung, Interpolation.
Quellformat = Literal["literaturexzerpt", "presseexzerpt", "pressesammlung"]

# ── einheit.typ ───────────────────────────────────────────────────────────────
EinheitTyp = Literal["content", "heading", "bibliography", "meta"]

# ── einheit.praezision ────────────────────────────────────────────────────────
# Wie genau, nicht woher. Die Vorlage mischte beides in einer Spalte.
Praezision = Literal["tag", "monat", "jahr", "spanne", "keine"]

# ── einheit.datierung_herkunft ────────────────────────────────────────────────
# Wie das Datum zustande kam. NULL heißt: nie datiert.
DatierungHerkunft = Literal[
    "text", "ueberschrift", "frontmatter", "quellennotation",
    "ereignis", "interpoliert", "manuell",
]

# ── anker.herkunft ────────────────────────────────────────────────────────────
# Dieselben plus 'jahrzehnt': das gibt es nur am Anker, nie als Datierung —
# der Wert wird erkannt, trägt aber kein Jahr.
AnkerHerkunft = Literal[
    "text", "ueberschrift", "frontmatter", "quellennotation",
    "ereignis", "interpoliert", "manuell", "jahrzehnt",
]

# ── einheit.kategorie_herkunft ────────────────────────────────────────────────
# Zwei Urheber, nicht drei Verfahren: die Maschine oder der Historiker. Womit
# gerechnet wurde, steht genauer in der lauf-Zeile.
KategorieHerkunft = Literal["automatisch", "manuell"]

# ── einheit.konfidenz ─────────────────────────────────────────────────────────
Konfidenz = Literal["high", "medium", "low"]

# ── kategorie.herkunft ────────────────────────────────────────────────────────
VorschlagHerkunft = Literal["vorschlag", "manuell"]

# ── akteur.typ / .status / .herkunft ──────────────────────────────────────────
AkteurTyp = Literal["Person", "Organisation", "Ort", "Konzept"]
AkteurStatus = Literal["aktiv", "abgelehnt"]
AkteurHerkunft = Literal["gliner", "manuell"]

# ── verschmelzungskandidat.grund ──────────────────────────────────────────────
KandidatGrund = Literal["alias", "schreibweise", "aehnlichkeit"]

# ── lauf.status / lauf.schritt ────────────────────────────────────────────────
LaufStatus = Literal["laeuft", "erfolg", "fehler"]
LaufSchritt = Literal[
    "ingest", "datierung", "taxonomie", "klassifikation", "akteure", "export",
]

# ── Umfang eines Neulaufs ─────────────────────────────────────────────────────
# Kein Spaltenwert, sondern ein Parameter — steht hier, weil ihn Datierung und
# Klassifikation gleichlautend führten.
Umfang = Literal["offen", "alle", "auch_manuell"]


# ── Die Laufzeitlisten ────────────────────────────────────────────────────────
# Abgeleitet, nicht danebengeschrieben.

QUELLFORMATE: tuple[str, ...] = get_args(Quellformat)
EINHEIT_TYPEN: tuple[str, ...] = get_args(EinheitTyp)
PRAEZISIONEN: tuple[str, ...] = get_args(Praezision)
DATIERUNG_HERKUENFTE: tuple[str, ...] = get_args(DatierungHerkunft)
ANKER_HERKUENFTE: tuple[str, ...] = get_args(AnkerHerkunft)
KATEGORIE_HERKUENFTE: tuple[str, ...] = get_args(KategorieHerkunft)
KONFIDENZEN: tuple[str, ...] = get_args(Konfidenz)
VORSCHLAG_HERKUENFTE: tuple[str, ...] = get_args(VorschlagHerkunft)
AKTEUR_TYPEN: tuple[str, ...] = get_args(AkteurTyp)
AKTEUR_STATUS: tuple[str, ...] = get_args(AkteurStatus)
AKTEUR_HERKUENFTE: tuple[str, ...] = get_args(AkteurHerkunft)
KANDIDAT_GRUENDE: tuple[str, ...] = get_args(KandidatGrund)
LAUF_STATUS: tuple[str, ...] = get_args(LaufStatus)
LAUF_SCHRITTE: tuple[str, ...] = get_args(LaufSchritt)
UMFAENGE: tuple[str, ...] = get_args(Umfang)


class UnbekannterWert(ValueError):
    """Ein Wert, der nicht in seinem Vorrat steht.

    Eine Ausnahme für alle Vorräte, mit einer Meldung. Vorher hatte jeder
    Vorrat seine eigene (UnbekanntesQuellformat, UnbekannteHerkunft,
    UnbekanntesQuellformat noch einmal) und formulierte dieselbe Aussage
    jeweils neu.
    """

    def __init__(self, wert: object, vorrat: tuple[str, ...], was: str):
        self.wert = wert
        self.vorrat = vorrat
        self.was = was
        super().__init__(
            f"Unbekannt{'es' if was.endswith('at') else 'e'} {was} {wert!r}. "
            f"Erlaubt: {' | '.join(vorrat)}"
        )


def pruefen(wert: str, vorrat: tuple[str, ...], was: str) -> str:
    """Gibt den Wert zurück, wenn er im Vorrat steht — sonst wirft es.

    Nichts wird durchgereicht und nichts stillschweigend berichtigt: ein
    unbekanntes Quellformat hat den alten Ingest zu Segmenten kommen lassen,
    die niemand datieren konnte.
    """
    if wert not in vorrat:
        raise UnbekannterWert(wert, vorrat, was)
    return wert


def quellformat_pruefen(wert: str) -> str:
    return pruefen(wert, QUELLFORMATE, "Quellformat")


def praezision_pruefen(wert: str) -> str:
    return pruefen(wert, PRAEZISIONEN, "Präzision")


def akteur_typ_pruefen(wert: str) -> str:
    return pruefen(wert, AKTEUR_TYPEN, "Typ")


def umfang_pruefen(wert: str) -> str:
    return pruefen(wert, UMFAENGE, "Umfang")
