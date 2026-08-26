"""
projekte.py — Projekte auflisten, anlegen, lesen, löschen

Kein SQL in diesem Modul: was gelesen und geschrieben wird, steht in
src/neu/projekte.py. Hier wird nur aus einem Dienstfehler eine HTTP-Antwort.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.neu import projekte as projekt_dienst
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.modelle import (
    EinheitTyp,
    EinheitenListe,
    Kennzahlen,
    ProjektAnlegenRumpf,
    ProjektListe,
    ProjektZeile,
)
from src.neu.projekte import ProjektFehler
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.get("/api/projekte", response_model=ProjektListe, responses=FEHLER_ANTWORTEN)
def projekte() -> ProjektListe:
    """Alle Projekte mit ihren Zahlen, nach Anlagedatum.

    anzahl_einheiten ist COUNT(*), der Zeitraum MIN/MAX über die Einheiten —
    beides gerechnet, nichts aus einer Konfigurationsdatei.
    """
    con = verbindung()
    try:
        zeilen = projekt_dienst.liste(con)
    finally:
        con.close()

    # Eine leere Datenbank ist ein gültiges leeres Ergebnis, kein fehlender
    # Gegenstand. 404 gibt es nur für einen benannten, nicht existierenden.
    return ProjektListe(anzahl=len(zeilen), projekte=zeilen)


@router.post(
    "/api/projekte",
    response_model=ProjektZeile,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def projekt_anlegen(rumpf: ProjektAnlegenRumpf) -> ProjektZeile:
    """Legt ein leeres Projekt an.

    Eigentümer ist der lokale Zugang (siehe src/neu/projekte.py). Sobald es
    eine Anmeldung gibt, wird daraus ein echter — die Zeilen hängen dann nur
    umzuhängen.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = projekt_dienst.anlegen(con, titel=rumpf.titel, kennung=rumpf.id)
    except ProjektFehler as exc:
        status = 409 if exc.code == "projekt_gibt_es_schon" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return ProjektZeile(**ergebnis)


@router.get(
    "/api/projekt/{projekt_id}/kennzahlen",
    response_model=Kennzahlen,
    responses=FEHLER_ANTWORTEN,
)
def projekt_kennzahlen(projekt_id: str) -> Kennzahlen:
    """Was in der Datenbank steht: Einheiten, Datierung, Kategorien, Akteure.

    Alles gerechnet. Dazu die letzten zwanzig Läufe, damit sichtbar ist, was
    schon gelaufen ist und was noch nicht.
    """
    con = verbindung()
    try:
        werte = projekt_dienst.kennzahlen(con, projekt_id)
    except ProjektFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return Kennzahlen(**werte)


@router.get(
    "/api/projekt/{projekt_id}/einheiten",
    response_model=EinheitenListe,
    responses=FEHLER_ANTWORTEN,
)
def einheiten(
    projekt_id: str,
    typ: EinheitTyp | None = Query(default=None, description="Filter auf einheit.typ"),
) -> EinheitenListe:
    """Alle Einheiten eines Projekts, nach Quelle und Position sortiert.

    Unbekanntes Projekt → 404. Bekanntes Projekt ohne Treffer → 200, leere Liste.
    Was gelesen wird, steht in projekte.einheiten().
    """
    con = verbindung()
    try:
        return EinheitenListe(**projekt_dienst.einheiten(con, projekt_id, typ))
    except ProjektFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@router.delete("/api/projekt/{projekt_id}", responses=FEHLER_ANTWORTEN)
def projekt_loeschen(projekt_id: str) -> dict:
    """Löscht ein Projekt samt allem, was daran hängt.

    Quellen, Einheiten, Kategorien, Akteure und Läufe gehen über
    ON DELETE CASCADE mit. Die Exportdateien unter data/projects/ bleiben
    liegen — sie sind ein Erzeugnis, kein Bestandteil des Projekts, und
    Dateien zu löschen ist nicht Sache dieses Endpoints.
    """
    con = verbindung_schreibend()
    try:
        return projekt_dienst.loeschen(con, projekt_id)
    except ProjektFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()
