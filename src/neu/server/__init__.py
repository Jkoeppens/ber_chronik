"""
server — Leseserver auf data/neu.db

Endpoints:
  GET /api/konfiguration            welche Anbieter, Modelle und Schwellen gelten
  GET /anmelden                     die Anmeldeseite (ohne Riegel)
  GET /api/bestand                  was auf dem Laufwerk liegt, nach Art getrennt
  GET /api/projekte                 alle Projekte
  GET /api/projekt/{id}/kennzahlen  ein Projekt mit seinen Zahlen
  GET /api/projekt/{id}/einheiten   seine Einheiten, nach Quelle und Position
                                    sortiert, Filter ?typ=content
  POST /api/projekt/{id}/chat       eine Frage, beantwortet im Ereignisstrom
  dazu die Schritte: quelle, themen, datieren, akteure, export

Starten:
  uvicorn src.neu.server:app --port 8002 --reload

Ein Modul je Schritt, jedes mit seinem eigenen APIRouter. Vorher stand alles in
einer Datei mit 1414 Zeilen, die jeder Schritt anfassen musste — zwei Arbeiten
an verschiedenen Schritten trafen sich dort zwangsläufig.

Was hier in der Wurzel bleibt, ist das, was keinem Schritt gehört: das Laden
von .env, die vier Fehlerbehandler, der Riegel vor dem Ausweich-Mount und die
Mounts selbst. Die Reihenfolge dieser drei letzten Dinge ist nicht beliebig —
siehe die Kommentare unten.

Beim Hochfahren wird .env geladen (ohne override — was in der Umgebung steht,
gewinnt) und protokolliert, welche Anbieter aktiv sind und was fehlt. Ein
fehlender Anbieter bricht den Start nicht ab; nur die Schritte, die ihn
brauchen, antworten dann mit 503.

ZUGANG_PASSWORT dagegen bricht ihn ab. Jede Anfrage — Fläche, API, /viz/,
Exportdateien — verlangt HTTP Basic damit; siehe src/neu/zugang.py. Es gibt
keine Vorgabe, weil eine Vorgabe behaupten würde, dieser Dienst dürfe offen
stehen.

Die einzige Datenbank ist data/neu.db. data/projects.db wird nie geöffnet —
darüber wacht test_projects_db_wird_nie_geoeffnet, das jede Zeichenkette im
Code prüft. dev_server.py bleibt unberührt.

Dateien schreibt der Server sehr wohl: die fünf Exportdateien nach
data/exporte/{projekt}/ (server/export.py) und die hochgeladenen DOCX nach
data/raw/ (server/ingest.py). Beides sind Dateien, keine Datenbanken.
"""

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.neu.konfiguration import env_laden, lage, protokollzeilen

# Vor allem anderen: die Anbieterwahl steht in der Umgebung, und die Module
# darunter lesen sie beim Import. override=False — was schon in der Umgebung
# steht (Railway), gewinnt gegen die Datei.
env_laden()

from src.neu.server import (  # noqa: E402
    akteure,
    anmeldung,
    bestand,
    chat,
    datierung,
    export,
    ingest,
    konfiguration,
    laeufe,
    projekte,
    themen,
)
from src.neu import db as db_modul  # noqa: E402
from src.neu import pfade  # noqa: E402
from src.neu import zugang  # noqa: E402
from src.neu.server.gemeinsam import (  # noqa: E402
    WURZEL,
    fehler_antwort,
    nicht_gefunden,
)

protokoll = logging.getLogger("ber.neu")


def protokoll_einrichten() -> None:
    """Gibt 'ber' einen eigenen Ausgang nach stderr.

    Ohne das war jede Startmeldung unsichtbar: uvicorn richtet Handler für
    seine eigenen Logger ein, nicht für den Wurzel-Logger, und ohne Handler
    verschluckt logging alles unter WARNING. Gemessen mit --log-level info —
    die Anbieterzeilen standen nirgends.

    Nur wenn noch keiner da ist: wer den Server einbettet und sein eigenes
    Protokoll aufgesetzt hat, soll es behalten.
    """
    wurzel = logging.getLogger("ber")
    if wurzel.handlers:
        return
    ausgang = logging.StreamHandler()
    ausgang.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    wurzel.addHandler(ausgang)
    wurzel.setLevel(logging.INFO)


def datenbank_melden() -> None:
    """Legt die Datenbank an, wenn sie fehlt, und sagt in jedem Fall wo sie liegt.

    Ein leeres Laufwerk ist der Normalfall einer frischen Installation. Vorher
    fuhr der Server dort hoch und jeder Aufruf gab 500 'datenbank_fehlt' —
    ein toter Dienst, dessen Ursache man nur im Fehlertext sah.

    Dass eine Datenbank NEU entstanden ist, steht als Warnung im Protokoll und
    nicht als Notiz: auf einem Laufwerk, das Daten tragen sollte, ist es die
    wichtigste Zeile des Starts. Wer sie beim zweiten Deploy wiedersieht, weiß,
    dass das Laufwerk nicht hält.
    """
    z = pfade.lage()
    try:
        neu = db_modul.anlegen_wenn_noetig()
    except (FileNotFoundError, sqlite3.Error) as exc:
        protokoll.error("Datenbank konnte nicht angelegt werden: %s", exc)
        neu = False
    else:
        if neu:
            protokoll.warning("=" * 68)
            protokoll.warning("LEERE DATENBANK ANGELEGT: %s", z["datenbank"])
            protokoll.warning("aus %s. Noch kein Projekt vorhanden.", db_modul.SCHEMA)
            protokoll.warning("=" * 68)
        else:
            _altlasten_melden()

    protokoll.info("Quellbestand: %s", z["quellbestand"])
    protokoll.info(
        "Datenwurzel:  %s%s",
        z["daten_wurzel"],
        "" if os.environ.get("DATA_ROOT") else "  (DATA_ROOT nicht gesetzt)",
    )
    protokoll.info("  Datenbank:  %s", z["datenbank"])
    protokoll.info("  Rohdaten:   %s", z["rohdaten"])
    protokoll.info("  Exporte:    %s", z["exporte"])


def _altlasten_melden() -> None:
    """Zieht benannte Berichtigungen nach. Nur bei einer bestehenden Datenbank.

    Eine frisch angelegte hat keine Altlasten — sie kommt aus dem heutigen
    schema.sql. Dass eine Zeile berichtigt wurde, ist eine Information und
    keine Warnung: es ist der Normalfall beim ersten Start nach einer
    Umbenennung.
    """
    from src.neu.db import altlasten_nachziehen, verbindung_schreibend

    try:
        con = verbindung_schreibend()
    except (FileNotFoundError, sqlite3.Error) as exc:
        protokoll.error("Altlasten nicht geprüft: %s", exc)
        return
    try:
        for zeile in altlasten_nachziehen(con):
            protokoll.info("Nachgezogen: %s", zeile)
    except sqlite3.Error as exc:
        protokoll.error("Altlasten nicht nachgezogen: %s", exc)
    finally:
        con.close()


def zugang_melden() -> None:
    """Sagt, womit man hereinkommt: Token aus der Tabelle, und das Geheimnis.

    Auf WARNING und nicht auf INFO, weil ZUGANG_PASSWORT ein geteiltes Geheimnis
    ist und geteilte Geheimnisse liegenbleiben — sie fallen niemandem auf, weil
    sie funktionieren. Die Zeile soll bei jedem Start danach fragen, ob es noch
    gebraucht wird. Vom Wert steht nie etwas da, nur dass er gilt.
    """
    anzahl = zugang.anzahl_token()
    protokoll.info("Zugang: %d Token in der Tabelle 'zugang'", anzahl)
    # Das Signaturgeheimnis beim Hochfahren anlegen und nicht bei der ersten
    # Anmeldung: so ist der Start die einzige Stelle, die dafür schreibt, und
    # eine Anfrage bleibt lesend.
    try:
        zugang.keks_geheimnis()
    except (FileNotFoundError, sqlite3.Error) as exc:
        protokoll.error("Kein Signaturgeheimnis für Sitzungen: %s", exc)
    if ZUGANG_GEHEIMNIS:
        protokoll.warning(
            "ZUGANG_PASSWORT gilt zusätzlich als Anmeldung. Es ist ein geteiltes "
            "Geheimnis und gehört niemandem — entfernen, sobald ein eigener Token "
            "nachweislich hereinlässt (%d steh%s bereit).",
            anzahl, "t" if anzahl == 1 else "en",
        )
    else:
        # Keine Warnung, denn es gibt nichts zu bemängeln: das ist der Zustand,
        # auf den die Warnung oben hinarbeitet.
        protokoll.info(
            "Zugang: nur Token gelten — ZUGANG_PASSWORT ist nicht gesetzt."
        )


def anbieter_melden() -> None:
    """Sagt beim Hochfahren, womit gerechnet wird und was fehlt.

    Kein Abbruch: ein fehlender Schlüssel legt nicht den ganzen Server lahm,
    sondern nur die Schritte, die ihn brauchen. Sichtbar soll es trotzdem
    sein — beim Hochfahren, nicht erst beim ersten Klick.
    """
    z = lage()
    vollstaendig = z.embedding.einsatzbereit and z.llm.einsatzbereit
    for zeile in protokollzeilen(z):
        protokoll.info(zeile) if vollstaendig else protokoll.warning(zeile)


@asynccontextmanager
async def lebenszyklus(_: FastAPI):
    protokoll_einrichten()
    datenbank_melden()
    zugang_melden()
    anbieter_melden()
    yield


# ── Der Riegel ────────────────────────────────────────────────────────────────
# Hier und nicht im Lebenszyklus: dort ist uvicorn schon auf dem Port, und ein
# Fehler danach ergäbe einen Dienst, der lauscht und jede Anfrage abweist. Beim
# Import geworfen bricht der Start ab, bevor irgendetwas erreichbar ist.
#
# Abgebrochen wird, wenn es WEDER ein Passwort NOCH einen Token gibt. Bis
# Oktober 2026 reichte das fehlende Passwort allein — damals war es der einzige
# Weg herein. tests/conftest.py setzt die Variable weiterhin: ein Test, der den
# Riegel versehentlich umgeht, soll auffallen, indem er gar nicht erst läuft.
ZUGANG_GEHEIMNIS = zugang.riegel_oder_abbruch()

app = FastAPI(
    title="BER Chronik — Leseserver",
    description="Liest data/neu.db. Nur lesend.",
    version="0.1.0",
    lifespan=lebenszyklus,
)

# add_middleware und nicht ein Router-Abhängiges: so liegt der Riegel VOR allem,
# was unten kommt — den Routern, dem /viz-Mount, den Exportdateien und der
# SvelteKit-Fläche unter /. Eine Abhängigkeit je Route hätte bei jeder neuen
# Route vergessen werden können.
app.add_middleware(zugang.Riegel, geheimnis=ZUGANG_GEHEIMNIS)


# ── Die Router, ein Modul je Schritt ──────────────────────────────────────────
# Die Reihenfolge bestimmt die Reihenfolge der Pfade in /openapi.json und damit
# in der erzeugten api-typen.ts. Sie ist sonst ohne Wirkung: keine zwei Routen
# überschneiden sich.

for teil in (konfiguration, bestand, projekte, ingest, themen, laeufe,
             datierung, akteure, export, chat, anmeldung):
    app.include_router(teil.router)


# ── Die eine Fehlergestalt ────────────────────────────────────────────────────

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


# ── Die Visualisierung ────────────────────────────────────────────────────────
# viz/ wird unverändert ausgeliefert. Von den Projektdaten geht nur das
# Exportverzeichnis über die Leitung — das liefert der export-Router aus.

VIZ_DIR = WURZEL / "viz"

if VIZ_DIR.is_dir():
    app.mount("/viz", StaticFiles(directory=VIZ_DIR, html=True), name="viz")


# ── Der Riegel vor dem Ausweich-Mount ─────────────────────────────────────────

@app.api_route(
    "/api/{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    include_in_schema=False,
)
def unbekannter_api_pfad(rest: str) -> JSONResponse:
    """Alles unter /api/, was keine der Routen oben getroffen hat: 404.

    Diese Route steht hinter allen echten /api-Routen und vor dem Mount auf
    "/". Ohne sie fiele ein Tippfehler im Pfad in die Ausweichseite und käme
    als 200 mit <!doctype html> zurück — der Aufrufer bekäme eine Seite, wo er
    Daten erwartet, und scheiterte erst beim Auswerten, an einer Stelle, die
    mit der Ursache nichts zu tun hat.

    Registriert wird sie über api_route und nicht über einen Ausnahmebehandler,
    weil der Mount die Anfrage sonst gar nicht erst weiterreicht: er beantwortet
    sie selbst und wirft nichts, was zu behandeln wäre.
    """
    raise nicht_gefunden(
        "endpoint_nicht_gefunden",
        f"Kein Endpoint unter '/api/{rest}'. Die verfügbaren stehen in /openapi.json.",
    )


# ── Die Seite ─────────────────────────────────────────────────────────────────
# Zuletzt montiert: die /api-Routen oben werden zuerst geprüft, der Mount auf "/"
# fängt nur ab, was übrig bleibt. Ein Ursprung für Seite und Daten, kein CORS.

BUILD_DIR = WURZEL / "frontend" / "build"

if BUILD_DIR.is_dir():
    AUSWEICHSEITE = BUILD_DIR / "200.html"

    class SeiteMitAusweich(StaticFiles):
        """Liefert 200.html für alles, was keine Datei ist.

        Die Route /projekt/{id} gibt es nicht als Datei — es gibt beliebig viele
        Kennungen. SvelteKit erzeugt dafür eine Ausweichseite, die im Browser
        entscheidet, was sie lädt. Ohne diesen Griff bekäme jeder Neuladen einer
        Projektseite ein 404.
        """

        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                # StaticFiles wirft 404, es gibt keine Antwort zum Prüfen.
                if exc.status_code == 404 and AUSWEICHSEITE.is_file():
                    return FileResponse(AUSWEICHSEITE)
                raise

    app.mount("/", SeiteMitAusweich(directory=BUILD_DIR, html=True), name="seite")
else:

    @app.get("/", include_in_schema=False)
    def kein_build() -> PlainTextResponse:
        return PlainTextResponse(
            f"Kein Frontend-Build unter {BUILD_DIR}.\n"
            "Erzeugen mit:  cd frontend && npm install && npm run build\n",
            status_code=503,
        )
