"""
gemeinsam.py — was jeder Router braucht

Die Fehlergestalt, die Existenzprüfung und die Bindung von Pfaden aus dem Netz
an data/raw/. Drei Dinge, die jeder Schritt anfasst und die deshalb keinem
einzelnen gehören.

Kein Router hier, keine Route: wer etwas hinzufügt, das eine Adresse hat, tut
das im Modul seines Schritts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from src.neu import pfade
from src.neu import projekte as projekt_dienst
from src.neu.modelle import Fehler, FehlerAntwort
from src.neu.projekte import ProjektFehler

WURZEL = Path(__file__).resolve().parent.parent.parent.parent

# Alle Fehlerantworten tragen dieselbe Gestalt — auch in der OpenAPI-Ausgabe.
FEHLER_ANTWORTEN = {
    404: {"model": FehlerAntwort, "description": "Nicht gefunden"},
    409: {"model": FehlerAntwort, "description": "Steht dem gerade etwas entgegen"},
    422: {"model": FehlerAntwort, "description": "Ungültiger Parameter"},
    500: {"model": FehlerAntwort, "description": "Serverfehler"},
    502: {"model": FehlerAntwort, "description": "Ein Dienst dahinter antwortet nicht"},
    503: {"model": FehlerAntwort, "description": "Anbieter nicht verfügbar"},
}


# ── Die eine Fehlergestalt ────────────────────────────────────────────────────

def fehler_antwort(status: int, code: str, meldung: str) -> JSONResponse:
    inhalt = FehlerAntwort(fehler=Fehler(code=code, meldung=meldung, status=status))
    return JSONResponse(status_code=status, content=inhalt.model_dump())


def nicht_gefunden(code: str, meldung: str) -> HTTPException:
    return HTTPException(status_code=404, detail=(code, meldung))


def projekt_muss_es_geben(con: sqlite3.Connection, projekt_id: str) -> None:
    """404, wenn es das Projekt nicht gibt.

    Die Frage selbst beantwortet projekte.gibt_es() — hier wird nur aus dem
    Fehler des Diensts eine HTTP-Antwort. Vorher stand dasselbe SELECT achtmal
    im Server, jedes Mal mit derselben Meldung frisch getippt.
    """
    try:
        projekt_dienst.pruefen(con, projekt_id)
    except ProjektFehler as exc:
        raise nicht_gefunden(exc.code, str(exc))


# ── Pfade aus dem Netz ────────────────────────────────────────────────────────

def rohdaten() -> Path:
    """Wohin hochgeladene DOCX gelegt werden — träge, nicht beim Import.

    Als Konstante hielte sie den Wert vom ersten Import fest; ein Test, der
    DATA_ROOT danach setzt, schriebe dann in den Arbeitsbaum.
    """
    return pfade.rohdaten()


def pfad_in_rohdaten(angabe: str) -> Path:
    """Bindet einen Pfad aus dem Rumpf an data/raw/.

    Ein Pfad aus einem HTTP-Aufruf darf nicht ins übrige Dateisystem zeigen.
    Absolute Angaben und '..' werden abgewiesen, nicht bereinigt.
    """
    kandidat = Path(angabe)
    if kandidat.is_absolute() or ".." in kandidat.parts:
        raise HTTPException(
            status_code=422,
            detail=("pfad_unzulaessig",
                    "pfad muss relativ zu data/raw/ sein und darf kein '..' enthalten."),
        )
    wurzel = rohdaten().resolve()
    ziel = (wurzel / kandidat).resolve()
    # is_relative_to und nicht startswith: '/data/rawboese' beginnt mit
    # '/data/raw' und kam damit durch. Ohne '..' und ohne absolute Angabe war
    # das nicht zu erreichen — über einen Symlink in data/raw/ aber doch, denn
    # resolve() folgt ihm.
    if not ziel.is_relative_to(wurzel):
        raise HTTPException(
            status_code=422,
            detail=("pfad_unzulaessig", "pfad zeigt aus data/raw/ heraus."),
        )
    return ziel


def pfad_in_obsidian(angabe: str) -> Path:
    """Bindet einen lokalen Obsidian-Ordner an OBSIDIAN_WURZEL.

    Ohne die Variable ist dieser Weg GESCHLOSSEN, und die Meldung sagt das.
    Kein Rückfall auf 'dann eben alles': bis September 2026 nahm dieser Weg
    jeden absoluten Pfad, und im Netz ist das eine Leseprimitive für alles, was
    der Prozess lesen darf.

    Geprüft wird gegen die AUFGELÖSTE Form und nicht gegen eine Liste
    verbotener Zeichen. Ein '..' abzuweisen genügt nicht: ein Symlink im Tresor
    führt ohne jedes '..' hinaus, und resolve() folgt ihm. Wer stattdessen die
    Zeichenkette prüft, prüft die Absicht des Aufrufers statt das Ziel.

    403 und nicht 422: die Angabe ist nicht ungültig, sie ist nicht erlaubt.
    """
    wurzel = pfade.obsidian_wurzel()
    if wurzel is None:
        raise HTTPException(
            status_code=403,
            detail=("obsidian_wurzel_fehlt",
                    "Ein lokaler Ordner als Quelle ist nicht freigegeben. Dieser "
                    "Weg braucht OBSIDIAN_WURZEL in der Umgebung — den Ordner, "
                    "unter dem ein Tresor liegen darf. Ohne sie bleibt der Weg "
                    "über Dropbox."),
        )
    ziel = Path(angabe).expanduser()
    if not ziel.is_absolute():
        ziel = wurzel / ziel
    ziel = ziel.resolve()
    if not ziel.is_relative_to(wurzel):
        raise HTTPException(
            status_code=403,
            detail=("pfad_ausserhalb_obsidian",
                    f"'{angabe}' liegt nicht unter OBSIDIAN_WURZEL ({wurzel})."),
        )
    return ziel
