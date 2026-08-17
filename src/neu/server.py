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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.neu.db import verbindung, verbindung_schreibend
from src.neu.ingest.dienst import IngestFehler, einlesen
from src.neu.kategorien.dienst import (
    KlassifikationFehler,
    klassifizieren,
    zuordnung_setzen,
)
from src.neu.taxonomie.anbieter import AnbieterFehler
from src.neu.taxonomie.dienst import TaxonomieFehler, vorschlagen
from src.neu.modelle import (
    Einheit,
    EinheitTyp,
    EinheitenListe,
    Fehler,
    FehlerAntwort,
    IngestAntwort,
    KlassifikationAntwort,
    KlassifizierenRumpf,
    Projekt,
    ProjektListe,
    QuelleAnlegen,
    TaxonomieAntwort,
    TaxonomieVorschlagRumpf,
    ZuordnungAntwort,
    ZuordnungRumpf,
)

# Alle Fehlerantworten tragen dieselbe Gestalt — auch in der OpenAPI-Ausgabe.
FEHLER_ANTWORTEN = {
    404: {"model": FehlerAntwort, "description": "Nicht gefunden"},
    422: {"model": FehlerAntwort, "description": "Ungültiger Parameter"},
    500: {"model": FehlerAntwort, "description": "Serverfehler"},
    503: {"model": FehlerAntwort, "description": "Anbieter nicht verfügbar"},
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


# ── Pfade aus dem Netz ────────────────────────────────────────────────────────

ROHDATEN = Path(__file__).resolve().parent.parent.parent / "data" / "raw"


def _pfad_in_rohdaten(angabe: str) -> Path:
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
    ziel = (ROHDATEN / kandidat).resolve()
    if not str(ziel).startswith(str(ROHDATEN.resolve())):
        raise HTTPException(
            status_code=422,
            detail=("pfad_unzulaessig", "pfad zeigt aus data/raw/ heraus."),
        )
    return ziel


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

    # Eine leere Datenbank ist ein gültiges leeres Ergebnis, kein fehlender
    # Gegenstand. 404 gibt es nur für einen benannten, nicht existierenden.
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


@app.post(
    "/api/projekt/{projekt_id}/quelle",
    response_model=IngestAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def quelle_anlegen(projekt_id: str, rumpf: QuelleAnlegen) -> IngestAntwort:
    """Liest eine Quelle ein und legt quelle, einheit und lauf an."""
    pfad = _pfad_in_rohdaten(rumpf.pfad)

    con = verbindung_schreibend()
    try:
        ergebnis = einlesen(
            con, projekt_id=projekt_id, pfad=pfad, quellformat=rumpf.quellformat
        )
    except IngestFehler as exc:
        status = 404 if exc.code in (
            "projekt_nicht_gefunden", "datei_nicht_gefunden", "ordner_nicht_gefunden"
        ) else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return IngestAntwort(**vars(ergebnis))


@app.post(
    "/api/projekt/{projekt_id}/klassifizieren",
    response_model=KlassifikationAntwort,
    responses=FEHLER_ANTWORTEN,
)
def projekt_klassifizieren(
    projekt_id: str, rumpf: KlassifizierenRumpf
) -> KlassifikationAntwort:
    """Ordnet den offenen Einheiten eines Projekts Kategorien zu."""
    con = verbindung_schreibend()
    try:
        ergebnis = klassifizieren(
            con, projekt_id=projekt_id,
            verfahren=rumpf.verfahren, umfang=rumpf.umfang,
        )
    except KlassifikationFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return KlassifikationAntwort(**vars(ergebnis))


@app.patch(
    "/api/einheit/{einheit_id}/kategorie",
    response_model=ZuordnungAntwort,
    responses=FEHLER_ANTWORTEN,
)
def kategorie_von_hand_setzen(einheit_id: int, rumpf: ZuordnungRumpf) -> ZuordnungAntwort:
    """Setzt die Kategorie einer Einheit von Hand.

    Die Zuordnung gilt danach als 'manuell' und bleibt bei Neuläufen unberührt;
    die Konfidenz wird geleert, weil sie ein maschinelles Urteil beschrieb.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = zuordnung_setzen(con, einheit_id, rumpf.kategorie_id)
    except KlassifikationFehler as exc:
        status = 404 if exc.code.endswith("nicht_gefunden") else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return ZuordnungAntwort(**ergebnis)


@app.post(
    "/api/projekt/{projekt_id}/taxonomie/vorschlagen",
    response_model=TaxonomieAntwort,
    responses=FEHLER_ANTWORTEN,
)
def taxonomie_vorschlagen(
    projekt_id: str, rumpf: TaxonomieVorschlagRumpf
) -> TaxonomieAntwort:
    """Schlägt eine Taxonomie vor — von null oder aus den vorhandenen Kategorien.

    warm_start=false: neu vorschlagen, n_clusters wählbar.
    warm_start=true : verfeinern, n_clusters ist die Anzahl der vorhandenen.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = vorschlagen(
            con, projekt_id=projekt_id,
            warm_start=rumpf.warm_start, n_clusters=rumpf.n_clusters,
        )
    except TaxonomieFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    except AnbieterFehler as exc:
        # Fehlender Schlüssel oder Anbieter: keine stille Ersatzwahl.
        raise HTTPException(status_code=503, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return TaxonomieAntwort(**vars(ergebnis))


# ── Die Seite ─────────────────────────────────────────────────────────────────
# Zuletzt montiert: die /api-Routen oben werden zuerst geprüft, der Mount auf "/"
# fängt nur ab, was übrig bleibt. Ein Ursprung für Seite und Daten, kein CORS.

BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "build"

if BUILD_DIR.is_dir():
    app.mount("/", StaticFiles(directory=BUILD_DIR, html=True), name="seite")
else:

    @app.get("/", include_in_schema=False)
    def kein_build() -> PlainTextResponse:
        return PlainTextResponse(
            f"Kein Frontend-Build unter {BUILD_DIR}.\n"
            "Erzeugen mit:  cd frontend && npm install && npm run build\n",
            status_code=503,
        )
