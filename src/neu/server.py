"""
server.py — Leseserver auf data/neu.db

Endpoints:
  GET /api/projekte                 alle Projekte
  GET /api/projekt/{id}             ein Projekt
  GET /api/projekt/{id}/einheiten   seine Einheiten, nach Quelle und Position
                                    sortiert, Filter ?typ=content

Starten:
  uvicorn src.neu.server:app --port 8002 --reload

Liest ausschließlich data/neu.db. Kein Schreiben, keine Auth, kein SSE,
keine Pipeline. data/projects.db und dev_server.py bleiben unberührt.
"""

import sqlite3

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.neu.db import verbindung
from src.neu.modelle import (
    Einheit,
    EinheitTyp,
    EinheitenListe,
    Fehler,
    FehlerAntwort,
    Projekt,
    ProjektListe,
)

# Alle Fehlerantworten tragen dieselbe Gestalt — auch in der OpenAPI-Ausgabe.
FEHLER_ANTWORTEN = {
    404: {"model": FehlerAntwort, "description": "Nicht gefunden"},
    422: {"model": FehlerAntwort, "description": "Ungültiger Parameter"},
    500: {"model": FehlerAntwort, "description": "Serverfehler"},
}

app = FastAPI(
    title="BER Chronik — Leseserver",
    description="Liest data/neu.db. Nur lesend.",
    version="0.1.0",
)


# ── Die eine Fehlergestalt ────────────────────────────────────────────────────

def fehler_antwort(status: int, code: str, meldung: str) -> JSONResponse:
    inhalt = FehlerAntwort(fehler=Fehler(code=code, meldung=meldung, status=status))
    return JSONResponse(status_code=status, content=inhalt.model_dump())


@app.exception_handler(HTTPException)
async def http_fehler(_: Request, exc: HTTPException) -> JSONResponse:
    """Eigene 404er tragen ihren Code im detail-Feld als (code, meldung)."""
    if isinstance(exc.detail, tuple):
        code, meldung = exc.detail
    else:
        code, meldung = "fehler", str(exc.detail)
    return fehler_antwort(exc.status_code, code, meldung)


@app.exception_handler(RequestValidationError)
async def validierungs_fehler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPIs {"detail": [...]} wird in dieselbe Gestalt übersetzt."""
    erster = exc.errors()[0] if exc.errors() else {}
    ort = ".".join(str(t) for t in erster.get("loc", ()) if t != "query")
    return fehler_antwort(
        422,
        "ungueltiger_parameter",
        f"Parameter '{ort}': {erster.get('msg', 'ungültig')}",
    )


@app.exception_handler(FileNotFoundError)
async def db_fehlt(_: Request, exc: FileNotFoundError) -> JSONResponse:
    return fehler_antwort(500, "datenbank_fehlt", str(exc))


@app.exception_handler(sqlite3.Error)
async def db_fehler(_: Request, exc: sqlite3.Error) -> JSONResponse:
    return fehler_antwort(500, "datenbank_fehler", str(exc))


def nicht_gefunden(code: str, meldung: str) -> HTTPException:
    return HTTPException(status_code=404, detail=(code, meldung))


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/projekte", response_model=ProjektListe, responses=FEHLER_ANTWORTEN)
def projekte() -> ProjektListe:
    """Alle Projekte, nach Anlagedatum."""
    con = verbindung()
    try:
        zeilen = con.execute(
            "SELECT id, titel, eigentuemer_id, angelegt_am, jahr_von, jahr_bis, "
            "       oeffentlich, dropbox_ordner "
            "FROM projekt ORDER BY angelegt_am, id"
        ).fetchall()
    finally:
        con.close()

    if not zeilen:
        raise nicht_gefunden("keine_projekte", "Die Datenbank enthält kein Projekt.")

    liste = [Projekt(**dict(z)) for z in zeilen]
    return ProjektListe(anzahl=len(liste), projekte=liste)


@app.get("/api/projekt/{projekt_id}", response_model=Projekt, responses=FEHLER_ANTWORTEN)
def projekt(projekt_id: str) -> Projekt:
    """Ein Projekt."""
    con = verbindung()
    try:
        zeile = con.execute(
            "SELECT id, titel, eigentuemer_id, angelegt_am, jahr_von, jahr_bis, "
            "       oeffentlich, dropbox_ordner "
            "FROM projekt WHERE id = ?",
            (projekt_id,),
        ).fetchone()
    finally:
        con.close()

    if zeile is None:
        raise nicht_gefunden(
            "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
        )
    return Projekt(**dict(zeile))


@app.get(
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
    """
    con = verbindung()
    try:
        vorhanden = con.execute(
            "SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)
        ).fetchone()
        if vorhanden is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )

        sql = (
            "SELECT e.* FROM einheit e "
            "JOIN quelle q ON q.id = e.quelle_id "
            "WHERE q.projekt_id = ?"
        )
        args: list = [projekt_id]
        if typ is not None:
            sql += " AND e.typ = ?"
            args.append(typ)
        sql += " ORDER BY e.quelle_id, e.position"

        zeilen = con.execute(sql, args).fetchall()
    finally:
        con.close()

    # Ein bekanntes Projekt ohne Treffer ist ein gültiges leeres Ergebnis,
    # kein fehlender Gegenstand: 200 mit leerer Liste.
    liste = [Einheit(**dict(z)) for z in zeilen]
    return EinheitenListe(
        projekt_id=projekt_id, anzahl=len(liste), typ_filter=typ, einheiten=liste
    )
