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
    wurzel = rohdaten()
    ziel = (wurzel / kandidat).resolve()
    if not str(ziel).startswith(str(wurzel.resolve())):
        raise HTTPException(
            status_code=422,
            detail=("pfad_unzulaessig", "pfad zeigt aus data/raw/ heraus."),
        )
    return ziel
