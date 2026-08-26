"""
server.py — Leseserver auf data/neu.db

Endpoints:
  GET /api/konfiguration            welche Anbieter, Modelle und Schwellen gelten
  GET /api/projekte                 alle Projekte
  GET /api/projekt/{id}             ein Projekt
  GET /api/projekt/{id}/einheiten   seine Einheiten, nach Quelle und Position
                                    sortiert, Filter ?typ=content
  dazu die Schritte: quelle, klassifizieren, taxonomie, datieren, akteure

Starten:
  uvicorn src.neu.server:app --port 8002 --reload

Beim Hochfahren wird .env geladen (ohne override — was in der Umgebung steht,
gewinnt) und eine Zeile protokolliert, welche Anbieter aktiv sind und was
fehlt. Ein fehlender Anbieter bricht den Start nicht ab; nur die Schritte, die
ihn brauchen, antworten dann mit 503.

Liest und schreibt ausschließlich data/neu.db. data/projects.db und
dev_server.py bleiben unberührt.
"""

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.neu.konfiguration import env_laden, lage, protokollzeilen

# Vor allem anderen: die Anbieterwahl steht in der Umgebung, und die Module
# darunter lesen sie beim Import. override=False — was schon in der Umgebung
# steht (Railway), gewinnt gegen die Datei.
env_laden()

from src.neu.db import verbindung, verbindung_schreibend  # noqa: E402
from src.neu.ingest.dienst import IngestFehler, einlesen  # noqa: E402
from src.neu.ingest import anmeldung as anmelde_dienst  # noqa: E402
from src.neu.ingest import dropbox_anbindung  # noqa: E402
from src.neu.ingest.anmeldung import AnmeldungFehler  # noqa: E402
from src.neu.ingest.kern import RohDatei  # noqa: E402
from src.neu.kategorien.dienst import (  # noqa: E402
    KlassifikationFehler,
    klassifizieren,
    zuordnung_setzen,
)
from src.neu.datierung import dienst as datierung_dienst  # noqa: E402
from src.neu.datierung.dienst import (  # noqa: E402
    DatierungFehler,
    datieren,
    datierung_setzen,
)
from src.neu.akteure import dienst as akteur_dienst  # noqa: E402
from src.neu.akteure.dienst import (  # noqa: E402
    UNGESETZT,
    AkteurFehler,
    akteur_aendern,
    akteure_verschmelzen,
    duplikatskandidaten,
    erkennen,
)
from src.neu.export.dienst import ExportFehler, exportieren  # noqa: E402
from src.neu import laeufe, vektoren  # noqa: E402
from src.neu.laeufe import LaufFehler  # noqa: E402
from src.neu.kategorien import verwaltung as kategorie_verwaltung  # noqa: E402
from src.neu.kategorien.verwaltung import KategorieFehler  # noqa: E402
from src.neu import projekte as projekt_dienst  # noqa: E402
from src.neu.projekte import ProjektFehler  # noqa: E402
from src.neu.taxonomie.anbieter import AnbieterFehler  # noqa: E402
from src.neu.taxonomie.dienst import TaxonomieFehler, vorschlagen  # noqa: E402
from src.neu.modelle import (  # noqa: E402
    AkteurAendernRumpf,
    AkteurAnlegenRumpf,
    AkteurAntwort,
    AkteurErkennungAntwort,
    AkteurListe,
    AkteureErkennenRumpf,
    FundstelleGeloescht,
    HerausgeloestAntwort,
    HerausloesenRumpf,
    MarkierungenListe,
    AnmeldungBeginn,
    DropboxOrdnerListe,
    DropboxOrdnerRumpf,
    DropboxStand,
    Einheit,
    ExportAntwort,
    Kennzahlen,
    ProjektAnlegenRumpf,
    ExportierenRumpf,
    KandidatenListe,
    KategorieRumpf,
    KategorienGespeichert,
    KategorienSpeichernRumpf,
    KategorieZeile,
    KategorienListe,
    LaufBegonnen,
    LaufStand,
    KonfigurationAntwort,
    VerschmelzenRumpf,
    EinheitTyp,
    EinheitenListe,
    Fehler,
    FehlerAntwort,
    DatierenRumpf,
    DatierungAntwort,
    DatierungRumpf,
    DatierungVerteilung,
    DatierungZeileAntwort,
    TextAntwort,
    TextRumpf,
    IngestAntwort,
    KlassifikationAntwort,
    KlassifizierenRumpf,
    Projekt,
    ProjektListe,
    ProjektZeile,
    QuelleAnlegen,
    Quellformat,
    TaxonomieAntwort,
    TaxonomieVorschlagRumpf,
    ZuordnungAntwort,
    ZuordnungRumpf,
)

# Alle Fehlerantworten tragen dieselbe Gestalt — auch in der OpenAPI-Ausgabe.
FEHLER_ANTWORTEN = {
    404: {"model": FehlerAntwort, "description": "Nicht gefunden"},
    409: {"model": FehlerAntwort, "description": "Steht dem gerade etwas entgegen"},
    422: {"model": FehlerAntwort, "description": "Ungültiger Parameter"},
    500: {"model": FehlerAntwort, "description": "Serverfehler"},
    502: {"model": FehlerAntwort, "description": "Ein Dienst dahinter antwortet nicht"},
    503: {"model": FehlerAntwort, "description": "Anbieter nicht verfügbar"},
}

protokoll = logging.getLogger("ber.neu")


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
    anbieter_melden()
    yield


app = FastAPI(
    title="BER Chronik — Leseserver",
    description="Liest data/neu.db. Nur lesend.",
    version="0.1.0",
    lifespan=lebenszyklus,
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

@app.get(
    "/api/konfiguration",
    response_model=KonfigurationAntwort,
    responses=FEHLER_ANTWORTEN,
)
def konfiguration() -> KonfigurationAntwort:
    """Was gerade eingestellt ist: Anbieter, Modelle, Schwellen.

    Dieselbe Auskunft wie beim Hochfahren, nur abrufbar. Von Schlüsseln steht
    hier nur, ob sie gesetzt sind — nie ihr Wert, und keine Projekt-Token.
    """
    z = lage()
    return KonfigurationAntwort(
        env_datei=z.env_datei,
        embedding=vars(z.embedding),
        llm=vars(z.llm),
        schwelle_akteure=z.schwelle_akteure,
        band_akteure=z.band_akteure,
        schwellen_kategorien=z.schwellen_kategorien,
        ollama_frist_sekunden=z.ollama_frist_sekunden,
    )


@app.get("/api/projekte", response_model=ProjektListe, responses=FEHLER_ANTWORTEN)
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


@app.post(
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


@app.get(
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


@app.get("/api/projekt/{projekt_id}", response_model=Projekt, responses=FEHLER_ANTWORTEN)
def projekt(projekt_id: str) -> Projekt:
    """Ein Projekt."""
    con = verbindung()
    try:
        zeile = con.execute(
            "SELECT id, titel, eigentuemer_id, angelegt_am, "
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
    """Liest eine Quelle ein und legt quelle, einheit und lauf an.

    Ein DOCX kommt aus data/raw/ — dorthin legt der Upload es ab, und ein Pfad
    aus dem Netz darf nicht ins übrige Dateisystem zeigen.

    Ein Obsidian-Ordner liegt dort nie: er liegt in Dropbox oder als
    absoluter Pfad auf der Platte, etwa unter ~/Library/CloudStorage/. Für
    Sammlungen gilt die data/raw/-Bindung deshalb nicht — geprüft wird, dass
    der Pfad ein vorhandenes Verzeichnis ist.
    """
    if rumpf.quellformat == "pressesammlung":
        pfad = Path(rumpf.pfad).expanduser()
        if not pfad.is_absolute():
            pfad = (ROHDATEN / pfad).resolve()
        if not pfad.is_dir():
            raise HTTPException(
                status_code=422,
                detail=("ordner_nicht_gefunden",
                        f"'{rumpf.pfad}' ist kein vorhandenes Verzeichnis. Für "
                        "eine Sammlung wird ein Ordner erwartet — lokal ein "
                        "absoluter Pfad, sonst der Weg über Dropbox."),
            )
    else:
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
    response_model=LaufBegonnen,
    responses=FEHLER_ANTWORTEN,
    status_code=202,
)
def projekt_klassifizieren(
    projekt_id: str, rumpf: KlassifizierenRumpf
) -> LaufBegonnen:
    """Stößt die Klassifikation an und kommt sofort zurück.

    Das Embedding aller Einheiten dauert; den Stand liefert GET /api/lauf/{id}.
    Handkorrekturen (kategorie_herkunft='manuell') bleiben bei 'offen' und
    'alle' unberührt.
    """
    con = verbindung()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
    finally:
        con.close()

    def arbeit(eigene, lauf_id: int) -> None:
        klassifizieren(
            eigene, projekt_id=projekt_id, verfahren=rumpf.verfahren,
            umfang="alle", lauf_id=lauf_id,
        )

    try:
        lauf_id = laeufe.starten(
            projekt_id, "klassifikation",
            {"verfahren": rumpf.verfahren, "umfang": "alle", "phase": "beginnt"},
            arbeit,
        )
    except LaufFehler as exc:
        raise HTTPException(status_code=409, detail=(exc.code, str(exc)))

    return LaufBegonnen(lauf_id=lauf_id, projekt_id=projekt_id,
                        schritt="klassifikation", status="laeuft")


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


# ── Läufe ─────────────────────────────────────────────────────────────────────

@app.get("/api/lauf/{lauf_id}", response_model=LaufStand, responses=FEHLER_ANTWORTEN)
def lauf_stand(lauf_id: int) -> LaufStand:
    """Der Stand eines Schritts — so oft abfragbar, wie man mag.

    Kein Strom, keine Sentinels: der Fortschritt steht in der lauf-Zeile und
    überlebt eine abgerissene Verbindung wie einen neu geladenen Reiter.
    """
    con = verbindung()
    try:
        return LaufStand(**laeufe.stand(con, lauf_id))
    except LaufFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.post(
    "/api/projekt/{projekt_id}/taxonomie/vorschlagen",
    response_model=LaufBegonnen,
    responses=FEHLER_ANTWORTEN,
    status_code=202,
)
def taxonomie_vorschlagen(
    projekt_id: str, rumpf: TaxonomieVorschlagRumpf
) -> LaufBegonnen:
    """Stößt den Taxonomielauf an und kommt sofort zurück.

    warm_start=false: neu vorschlagen, n_clusters wählbar.
    warm_start=true : verfeinern, n_clusters ist die Anzahl der vorhandenen.

    Der Lauf dauert Minuten. Deshalb 202 mit einer lauf_id statt einer Antwort,
    auf die man wartet — den Stand liefert GET /api/lauf/{id}.
    """
    con = verbindung()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
    finally:
        con.close()

    def arbeit(eigene, lauf_id: int) -> None:
        vorschlagen(
            eigene, projekt_id=projekt_id, warm_start=rumpf.warm_start,
            n_clusters=rumpf.n_clusters, lauf_id=lauf_id,
        )

    try:
        lauf_id = laeufe.starten(
            projekt_id, "taxonomie",
            {"warm_start": rumpf.warm_start, "n_clusters": rumpf.n_clusters,
             "phase": "beginnt"},
            arbeit,
        )
    except LaufFehler as exc:
        raise HTTPException(status_code=409, detail=(exc.code, str(exc)))

    return LaufBegonnen(lauf_id=lauf_id, projekt_id=projekt_id,
                        schritt="taxonomie", status="laeuft")


@app.post(
    "/api/projekt/{projekt_id}/datieren",
    response_model=DatierungAntwort,
    responses=FEHLER_ANTWORTEN,
)
def projekt_datieren(projekt_id: str, rumpf: DatierenRumpf) -> DatierungAntwort:
    """Datiert die Einheiten eines Projekts, Quelle für Quelle.

    Handkorrekturen bleiben bei 'offen' und 'alle' unberührt; 'auch_manuell'
    überschreibt sie. Zeigt eine Handkorrektur ins Leere, steht das als
    Warnung in der Antwort — nicht stillschweigend nichts.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = datieren(con, projekt_id=projekt_id, umfang=rumpf.umfang)
    except DatierungFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return DatierungAntwort(**vars(ergebnis))


@app.patch(
    "/api/einheit/{einheit_id}/datierung",
    response_model=DatierungZeileAntwort,
    responses=FEHLER_ANTWORTEN,
)
def datierung_von_hand_setzen(
    einheit_id: int, rumpf: DatierungRumpf
) -> DatierungZeileAntwort:
    """Setzt die Datierung einer Einheit von Hand.

    datum_von leer heißt undatierbar, datum_bis leer heißt Zeitpunkt. Die
    Korrektur wird eine anker-Zeile mit herkunft='manuell' und überlebt jeden
    Neulauf außer 'auch_manuell' — samt ihrer Genauigkeit und ihrer Begründung.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = datierung_setzen(
            con, einheit_id, rumpf.datum_von, rumpf.datum_bis, rumpf.begruendung
        )
    except DatierungFehler as exc:
        status = 404 if exc.code.endswith("nicht_gefunden") else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return DatierungZeileAntwort(**ergebnis)


@app.patch(
    "/api/einheit/{einheit_id}/text",
    response_model=TextAntwort,
    responses=FEHLER_ANTWORTEN,
)
def einheit_text_setzen(einheit_id: int, rumpf: TextRumpf) -> TextAntwort:
    """Ändert den Wortlaut einer Einheit und räumt auf, was daran hing.

    Die Akteursfundstellen dieser Einheit werden gelöscht — ihre Zeichen-
    positionen zeigten danach auf andere Wörter, und eine falsche Markierung
    ist schlimmer als eine fehlende. Der nächste Akteurslauf legt sie neu an.
    Die Anker werden neu abgeleitet, indem die Datierung noch einmal läuft
    (Umfang 'alle', Handkorrekturen bleiben).
    """
    con = verbindung_schreibend()
    try:
        return TextAntwort(**datierung_dienst.text_setzen(con, einheit_id, rumpf.text))
    except DatierungFehler as exc:
        status = 404 if exc.code.endswith("nicht_gefunden") else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.get(
    "/api/projekt/{projekt_id}/datierung",
    response_model=DatierungVerteilung,
    responses=FEHLER_ANTWORTEN,
)
def datierung_verteilung(projekt_id: str) -> DatierungVerteilung:
    """Woher die Daten kommen, wo die Ausreißer sitzen, und die Belege je Einheit.

    Die Belege sind der Unterschied zur alten Vorschau: dort stand das
    Ergebnis, hier steht, was es ausgelöst hat. Ein Datum 3012 ist damit als
    Zifferndreher in der Quellennotation erkennbar und nicht als Rechenfehler.
    """
    con = verbindung()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?",
                       (projekt_id,)).fetchone() is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
        stand = datierung_dienst.verteilung(con, projekt_id)
        stand["anker"] = {
            str(k): v for k, v in datierung_dienst.anker_je_einheit(con, projekt_id).items()
        }
        return DatierungVerteilung(**stand)
    finally:
        con.close()


@app.post(
    "/api/projekt/{projekt_id}/akteure/erkennen",
    response_model=LaufBegonnen,
    responses=FEHLER_ANTWORTEN,
    status_code=202,
)
def akteure_erkennen(
    projekt_id: str, rumpf: AkteureErkennenRumpf | None = None
) -> LaufBegonnen:
    """Stößt die Akteurserkennung an und kommt sofort zurück.

    Akteure mit herkunft='manuell' bleiben unberührt, abgelehnte filtern den
    Fehlfund erneut heraus. Verschmelzungskandidaten werden dabei neu berechnet.

    202 mit einer lauf_id statt einer Antwort, auf die man wartet: gemessen an
    den vorhandenen lauf-Zeilen dauert der Schritt 81 Sekunden bei damaskus und
    267 bei ber. Synchron läuft das in jeden Zeitablauf, der zwischen Browser
    und Server steht. Den Stand liefert GET /api/lauf/{id}.
    """
    con = verbindung()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?",
                       (projekt_id,)).fetchone() is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
    finally:
        con.close()

    # Den Anbieter vorher prüfen, nicht im Faden: ein fehlender Schlüssel soll
    # 503 an der Stelle des Klicks geben und nicht als gescheiterter Lauf vier
    # Minuten später. Der Aufruf ist billig — das Modell lädt erst beim ersten
    # encode. GLiNER wird hier nicht geprüft, weil dessen Prüfung das Modell
    # lädt; sein Fehlen erscheint in der lauf-Zeile.
    try:
        from src.neu.akteure.anbieter import embedding_funktion

        embedding_funktion()
    except AnbieterFehler as exc:
        raise HTTPException(status_code=503, detail=(exc.code, str(exc)))

    def arbeit(eigene, lauf_id: int) -> None:
        akteur_dienst.erkennen(eigene, projekt_id=projekt_id, lauf_id=lauf_id)

    try:
        lauf_id = laeufe.starten(projekt_id, "akteure", {"phase": "beginnt"}, arbeit)
    except LaufFehler as exc:
        raise HTTPException(status_code=409, detail=(exc.code, str(exc)))

    return LaufBegonnen(lauf_id=lauf_id, projekt_id=projekt_id,
                        schritt="akteure", status="laeuft")


@app.get(
    "/api/projekt/{projekt_id}/akteure",
    response_model=AkteurListe,
    responses=FEHLER_ANTWORTEN,
)
def akteure_liste(projekt_id: str) -> AkteurListe:
    """Alle Akteure mit Aliasen, Fundstellen und Trefferzahlen je Name.

    Die Trefferzahlen sind der Unterschied zur alten Fläche: sie zeigte, welche
    Namen ein Akteur trägt, nicht welcher davon die Fundstellen liefert.
    """
    con = verbindung()
    try:
        return AkteurListe(**akteur_dienst.liste(con, projekt_id))
    except AkteurFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.get(
    "/api/projekt/{projekt_id}/markierungen",
    response_model=MarkierungenListe,
    responses=FEHLER_ANTWORTEN,
)
def markierungen(projekt_id: str) -> MarkierungenListe:
    """Die Fundstellen je Einheit, mit Zeichenpositionen."""
    con = verbindung()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?",
                       (projekt_id,)).fetchone() is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
        je_einheit = akteur_dienst.fundstellen_je_einheit(con, projekt_id)
        return MarkierungenListe(
            projekt_id=projekt_id,
            anzahl=sum(len(v) for v in je_einheit.values()),
            je_einheit={str(k): v for k, v in je_einheit.items()},
        )
    finally:
        con.close()


@app.post(
    "/api/projekt/{projekt_id}/akteure",
    response_model=AkteurAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def akteur_anlegen(projekt_id: str, rumpf: AkteurAnlegenRumpf) -> AkteurAntwort:
    """Legt einen Akteur von Hand an — herkunft='manuell', gegen Läufe geschützt."""
    con = verbindung_schreibend()
    try:
        return AkteurAntwort(**akteur_dienst.anlegen(
            con, projekt_id, rumpf.normalform, rumpf.typ, rumpf.aliase
        ))
    except AkteurFehler as exc:
        status = (404 if exc.code == "projekt_nicht_gefunden"
                  else 409 if exc.code == "normalform_belegt" else 422)
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.post(
    "/api/akteur/{akteur_id}/herausloesen",
    response_model=HerausgeloestAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def akteur_alias_herausloesen(
    akteur_id: int, rumpf: HerausloesenRumpf
) -> HerausgeloestAntwort:
    """Macht aus einem Alias einen eigenen Akteur.

    Die Bedienung, die einen Klumpen auflöst. Beide werden danach neu
    zugeordnet: der alte verliert die Stellen des Alias, der neue bekommt sie.
    """
    con = verbindung_schreibend()
    try:
        return HerausgeloestAntwort(**akteur_dienst.alias_herausloesen(
            con, akteur_id, rumpf.alias,
            typ=rumpf.typ if "typ" in rumpf.model_fields_set else akteur_dienst.UNGESETZT,
        ))
    except AkteurFehler as exc:
        status = (404 if exc.code.endswith("nicht_gefunden")
                  else 409 if exc.code == "normalform_belegt" else 422)
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.delete(
    "/api/fundstelle/{fundstelle_id}",
    response_model=FundstelleGeloescht,
    responses=FEHLER_ANTWORTEN,
)
def fundstelle_entfernen(fundstelle_id: int) -> FundstelleGeloescht:
    """Entfernt eine einzelne Markierung, nicht den Akteur.

    Der Unterschied zum Alias-Entfernen in der Liste ist Absicht: dort geht ein
    Name samt allen seinen Stellen, hier eine falsch getroffene Stelle.
    """
    con = verbindung_schreibend()
    try:
        return FundstelleGeloescht(
            **akteur_dienst.fundstelle_loeschen(con, fundstelle_id)
        )
    except AkteurFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.patch(
    "/api/akteur/{akteur_id}", response_model=AkteurAntwort, responses=FEHLER_ANTWORTEN
)
def akteur_von_hand_aendern(akteur_id: int, rumpf: AkteurAendernRumpf) -> AkteurAntwort:
    """Ändert einen Akteur von Hand.

    Der Akteur gilt danach als 'manuell' und bleibt bei Neuläufen unberührt.
    Ändern sich Normalform oder Aliase, werden die Fundstellen sofort neu
    abgeleitet — nicht erst beim nächsten Lauf.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = akteur_aendern(
            con, akteur_id,
            normalform=rumpf.normalform,
            typ=rumpf.typ if "typ" in rumpf.model_fields_set else UNGESETZT,
            status=rumpf.status,
            aliase=rumpf.aliase,
        )
    except AkteurFehler as exc:
        status = 404 if exc.code.endswith("nicht_gefunden") else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return AkteurAntwort(**ergebnis)


@app.post(
    "/api/akteure/verschmelzen",
    response_model=AkteurAntwort,
    responses=FEHLER_ANTWORTEN,
)
def akteure_zusammenlegen(rumpf: VerschmelzenRumpf) -> AkteurAntwort:
    """Führt beliebige Akteure zu einem zusammen.

    behalten_id bestimmt, welche Normalform stehen bleibt; alle übrigen Namen
    werden zu Aliasen. Ein vorgeschlagenes Paar muss es nicht sein.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = akteure_verschmelzen(con, rumpf.ids, rumpf.behalten_id)
    except AkteurFehler as exc:
        status = 404 if exc.code.endswith("nicht_gefunden") else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return AkteurAntwort(**ergebnis)


@app.get(
    "/api/projekt/{projekt_id}/akteure/duplikatskandidaten",
    response_model=KandidatenListe,
    responses=FEHLER_ANTWORTEN,
)
def akteure_duplikatskandidaten(projekt_id: str) -> KandidatenListe:
    """Die gespeicherten Verschmelzungskandidaten eines Projekts.

    Gelesen, nicht gerechnet: berechnet werden sie beim Erkennungslauf, aus
    einer Quelle mit drei Regeln — Alias-Überschneidung, Schreibweise,
    Ähnlichkeit im Band unterhalb der Schwelle.
    """
    con = verbindung()
    try:
        kandidaten = duplikatskandidaten(con, projekt_id)
    except AkteurFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return KandidatenListe(
        projekt_id=projekt_id, anzahl=len(kandidaten), kandidaten=kandidaten
    )


@app.post(
    "/api/projekt/{projekt_id}/exportieren",
    response_model=ExportAntwort,
    responses=FEHLER_ANTWORTEN,
)
def projekt_exportieren(
    projekt_id: str, rumpf: ExportierenRumpf | None = None
) -> ExportAntwort:
    """Erzeugt die Dateien, die viz/ liest — gleiche Namen, gleiches Format.

    Der Zeitraum in project_meta.json ist MIN(jahr_von) bis MAX(jahr_bis) über
    die Einheiten, keine gespeicherte Angabe. Undatierte Einheiten stehen in
    data.json und fehlen nur auf der Zeitachse; wie viele es sind, sagt
    anzahl_ohne_datum.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = exportieren(
            con, projekt_id=projekt_id,
            zusammenfassungen=bool(rumpf and rumpf.zusammenfassungen),
        )
    except ExportFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return ExportAntwort(**vars(ergebnis))


@app.post(
    "/api/projekt/{projekt_id}/quelle/datei",
    response_model=IngestAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
async def quelle_hochladen(
    projekt_id: str,
    quellformat: Quellformat = Form(description="literaturexzerpt | presseexzerpt"),
    datei: UploadFile = File(description="Die DOCX-Datei"),
) -> IngestAntwort:
    """Nimmt eine Datei aus dem Browser entgegen, legt sie in data/raw/ ab und
    liest sie ein.

    Der Dateiname kommt vom Client und wird nicht geglaubt: nur der Basisname
    zählt, und der muss unterhalb von data/raw/ landen. Eine vorhandene Datei
    wird nicht überschrieben — sonst könnte ein Upload eine fremde Quelle
    austauschen, an der schon ein Projekt hängt.

    Für Obsidian bleibt es ein Ordnerpfad: dafür ist POST …/quelle da.
    """
    name = Path(datei.filename or "").name
    if not name:
        raise HTTPException(
            status_code=422, detail=("dateiname_fehlt", "Die Datei hat keinen Namen.")
        )
    ziel = _pfad_in_rohdaten(name)
    inhalt = await datei.read()

    if ziel.exists():
        # Gleicher Name, gleicher Inhalt: kein Konflikt, die Datei ist schon da.
        # Gleicher Name, anderer Inhalt: nicht überschreiben — daran hängen
        # womöglich Quellen anderer Projekte, deren Einheiten dann nicht mehr
        # zu ihrem Ursprung passen.
        if ziel.read_bytes() != inhalt:
            raise HTTPException(
                status_code=409,
                detail=("datei_gibt_es_schon",
                        f"In data/raw/ liegt schon eine andere Datei namens '{name}'. "
                        "Bitte umbenennen — eine vorhandene Quelle wird nicht ersetzt."),
            )
    else:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(inhalt)

    con = verbindung_schreibend()
    try:
        ergebnis = einlesen(
            con, projekt_id=projekt_id, pfad=ziel, quellformat=quellformat
        )
    except IngestFehler as exc:
        # Die Datei bleibt liegen: sie ist angekommen, und ein zweiter Versuch
        # mit richtigem Quellformat soll sie nicht erneut hochladen müssen.
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return IngestAntwort(**vars(ergebnis))


# ── Kategorien pflegen ────────────────────────────────────────────────────────

@app.get(
    "/api/projekt/{projekt_id}/kategorien",
    response_model=KategorienListe,
    responses=FEHLER_ANTWORTEN,
)
def kategorien_liste(projekt_id: str) -> KategorienListe:
    """Die Kategorien eines Projekts mit der Zahl der Einheiten darauf.

    Dazu, wie viele Einheiten beim nächsten Zuordnen erst embeddet werden
    müssen: die Fläche soll eine Dauer nur ankündigen, wenn es eine gibt. Steht
    kein Anbieter, ist die Frage nicht zu beantworten — dann null statt einer
    geratenen Zahl, und der Lauf scheitert später ohnehin mit 503.
    """
    con = verbindung()
    try:
        stand = kategorie_verwaltung.liste(con, projekt_id)
        try:
            from src.neu.taxonomie.anbieter import embedding_modellname

            stand["einheiten_ohne_vektor"] = vektoren.lage(
                con, projekt_id, embedding_modellname()
            )["zu_rechnen"]
        except AnbieterFehler:
            stand["einheiten_ohne_vektor"] = None
        return KategorienListe(**stand)
    except KategorieFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.post(
    "/api/projekt/{projekt_id}/kategorien",
    response_model=KategorieZeile,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def kategorie_anlegen(projekt_id: str, rumpf: KategorieRumpf) -> KategorieZeile:
    """Legt eine Kategorie von Hand an — herkunft='manuell'."""
    if not rumpf.name:
        raise HTTPException(
            status_code=422, detail=("name_leer", "name ist zum Anlegen nötig.")
        )
    con = verbindung_schreibend()
    try:
        return KategorieZeile(**kategorie_verwaltung.anlegen(
            con, projekt_id, name=rumpf.name,
            beschreibung=rumpf.beschreibung or "",
            schlagworte=rumpf.schlagworte or [],
        ))
    except KategorieFehler as exc:
        status = (404 if exc.code == "projekt_nicht_gefunden"
                  else 409 if exc.code == "kategorie_gibt_es_schon" else 422)
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.put(
    "/api/projekt/{projekt_id}/kategorien",
    response_model=KategorienGespeichert,
    responses=FEHLER_ANTWORTEN,
    status_code=202,
)
def kategorien_speichern(
    projekt_id: str, rumpf: KategorienSpeichernRumpf
) -> KategorienGespeichert:
    """Speichert die ganze Kategorienliste und ordnet danach neu zu.

    Beides gehört zusammen: eine geänderte Beschreibung ändert, wohin die
    Einheiten gehören. Es getrennt zu lassen hieße, einen Zustand zu erlauben,
    in dem die Zuordnung zu Beschreibungen passt, die es nicht mehr gibt.

    Warum 202 und ein Lauf, obwohl das Zuordnen mit gefüllten Vektoren in etwa
    einer Sekunde durch ist: die Ausnahmen sind zu regelmäßig für einen
    gewöhnlichen Klick. Beim ersten Speichern nach dem Ingest ist der Speicher
    leer (12 bis 31 Sekunden je nach Projektgröße), nach einem Serverneustart
    liegt das Modell nicht im Arbeitsspeicher (weitere 12), und ein
    Anbieterwechsel entwertet alles auf einmal. Ein Klick, der meistens eine
    Sekunde dauert und ab und zu eine halbe Minute, ist schlechter als einer,
    der immer denselben Weg nimmt.

    Was stattdessen aufhört: die Fläche kündigt eine Dauer nur an, wenn
    einheiten_ohne_vektor aus GET …/kategorien größer als null ist.

    Eine leere Liste ist ein gültiger Sollzustand — alle Kategorien weg — und
    hängt keinen Lauf an: es gibt nichts, wogegen zugeordnet werden könnte.
    Dann kommt lauf_id null zurück.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = kategorie_verwaltung.stapel_aendern(
            con, projekt_id, [e.model_dump() for e in rumpf.kategorien]
        )
    except KategorieFehler as exc:
        status = (404 if exc.code.endswith("nicht_gefunden")
                  else 409 if exc.code == "kategorie_gibt_es_schon" else 422)
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    antwort = dict(projekt_id=projekt_id, anzahl=ergebnis["anzahl"],
                   angelegt=ergebnis["angelegt"], geaendert=ergebnis["geaendert"],
                   geloescht=ergebnis["geloescht"])
    if ergebnis["anzahl"] == 0:
        return KategorienGespeichert(**antwort, lauf_id=None)

    def arbeit(eigene, lauf_id: int) -> None:
        klassifizieren(eigene, projekt_id=projekt_id, verfahren="bge",
                       umfang="alle", lauf_id=lauf_id)

    try:
        lauf_id = laeufe.starten(
            projekt_id, "klassifikation",
            {"phase": "beginnt", "anlass": "kategorien gespeichert", **ergebnis},
            arbeit,
        )
    except LaufFehler as exc:
        raise HTTPException(status_code=409, detail=(exc.code, str(exc)))

    return KategorienGespeichert(**antwort, lauf_id=lauf_id)


@app.patch(
    "/api/kategorie/{kategorie_id}",
    response_model=KategorieZeile,
    responses=FEHLER_ANTWORTEN,
)
def kategorie_aendern(kategorie_id: int, rumpf: KategorieRumpf) -> KategorieZeile:
    """Ändert eine Kategorie. Sie gilt danach als von Hand geprüft."""
    con = verbindung_schreibend()
    try:
        return KategorieZeile(**kategorie_verwaltung.aendern(
            con, kategorie_id, name=rumpf.name,
            beschreibung=rumpf.beschreibung, schlagworte=rumpf.schlagworte,
        ))
    except KategorieFehler as exc:
        status = (404 if exc.code == "kategorie_nicht_gefunden"
                  else 409 if exc.code == "kategorie_gibt_es_schon" else 422)
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.delete("/api/kategorie/{kategorie_id}", responses=FEHLER_ANTWORTEN)
def kategorie_loeschen(kategorie_id: int) -> dict:
    """Löscht eine Kategorie. Die Einheiten bleiben, ihre Zuordnung wird offen."""
    con = verbindung_schreibend()
    try:
        return kategorie_verwaltung.loeschen(con, kategorie_id)
    except KategorieFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.delete("/api/projekt/{projekt_id}", responses=FEHLER_ANTWORTEN)
def projekt_loeschen(projekt_id: str) -> dict:
    """Löscht ein Projekt samt allem, was daran hängt.

    Quellen, Einheiten, Kategorien, Akteure und Läufe gehen über
    ON DELETE CASCADE mit. Die Exportdateien unter data/projects/ bleiben
    liegen — sie sind ein Erzeugnis, kein Bestandteil des Projekts, und
    Dateien zu löschen ist nicht Sache dieses Endpoints.
    """
    con = verbindung_schreibend()
    try:
        zeile = con.execute(
            "SELECT titel FROM projekt WHERE id = ?", (projekt_id,)
        ).fetchone()
        if zeile is None:
            raise nicht_gefunden(
                "projekt_nicht_gefunden", f"Kein Projekt mit der Kennung '{projekt_id}'."
            )
        einheiten = con.execute(
            "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
            "WHERE q.projekt_id = ?", (projekt_id,)
        ).fetchone()[0]
        with con:
            con.execute("DELETE FROM projekt WHERE id = ?", (projekt_id,))
    finally:
        con.close()
    return {"projekt_id": projekt_id, "titel": zeile[0], "geloeschte_einheiten": einheiten}


# ── Dropbox ───────────────────────────────────────────────────────────────────

@app.get(
    "/api/projekt/{projekt_id}/dropbox",
    response_model=DropboxStand,
    responses=FEHLER_ANTWORTEN,
)
def dropbox_stand(projekt_id: str) -> DropboxStand:
    """Ob das Projekt mit Dropbox verbunden ist und gegen welchen Ordner.

    Der Status kommt aus projekt.dropbox_token. Das alte System prüfte dafür
    data/dropbox_tokens.json — eine Datei, die von keiner Zeile geschrieben
    wird und mit den tatsächlich benutzten Zugangsdaten nichts zu tun hat.
    """
    con = verbindung()
    try:
        return DropboxStand(**anmelde_dienst.verbindung(con, projekt_id))
    except AnmeldungFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.put(
    "/api/projekt/{projekt_id}/dropbox",
    response_model=DropboxStand,
    responses=FEHLER_ANTWORTEN,
)
def dropbox_ordner_setzen(projekt_id: str, rumpf: DropboxOrdnerRumpf) -> DropboxStand:
    """Trägt den Ordner ein, gegen den gelesen wird."""
    con = verbindung_schreibend()
    try:
        return DropboxStand(
            **anmelde_dienst.ordner_setzen(con, projekt_id, rumpf.ordner)
        )
    except AnmeldungFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.post(
    "/api/projekt/{projekt_id}/dropbox/anmeldung",
    response_model=AnmeldungBeginn,
    responses=FEHLER_ANTWORTEN,
)
def dropbox_anmeldung_beginnen(projekt_id: str) -> AnmeldungBeginn:
    """Beginnt die Anmeldung. Der begonnene Vorgang steht in der Datenbank.

    Damit übersteht er einen Serverneustart zwischen dem Beginn und der
    Rückleitung — im alten System lag er in einem Wörterbuch im Arbeitsspeicher.
    """
    con = verbindung_schreibend()
    try:
        return AnmeldungBeginn(**anmelde_dienst.beginnen(con, projekt_id))
    except AnmeldungFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    except AnbieterFehler as exc:
        raise HTTPException(status_code=503, detail=(exc.code, str(exc)))
    finally:
        con.close()


@app.get("/api/obsidian/oauth/callback", include_in_schema=False)
def dropbox_rueckleitung(code: str = "", state: str = "") -> HTMLResponse:
    """Hierher schickt Dropbox den Nutzer zurück.

    Der Pfad trägt den alten englischen Namen, weil er in der Dropbox-App
    eingetragen ist — siehe dropbox_anbindung.RUECKLEITUNG_VORGABE.

    Der refresh_token wird sofort an projekt.dropbox_token geschrieben, nicht
    erst beim nächsten Formular — sonst verliert ein Neustart ihn still.
    """
    con = verbindung_schreibend()
    try:
        ergebnis = anmelde_dienst.beenden(con, code=code, state=state)
        meldung = f"Dropbox verbunden — Projekt {ergebnis['projekt_id']}"
        farbe = "#16a34a"
    except (AnmeldungFehler, AnbieterFehler) as exc:
        meldung = str(exc)
        farbe = "#dc2626"
    finally:
        con.close()

    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Dropbox</title>"
        "<body style=\"font-family:-apple-system,sans-serif;text-align:center;"
        "padding:48px;color:#1a1a1a\">"
        f"<h2 style='color:{farbe};font-size:16px'>{meldung}</h2>"
        "<p style='font-size:12px;color:#888'>Dieses Fenster kann geschlossen werden.</p>"
        "<script>setTimeout(() => window.close(), 2500)</script></body>"
    )


@app.get(
    "/api/projekt/{projekt_id}/dropbox/ordner",
    response_model=DropboxOrdnerListe,
    responses=FEHLER_ANTWORTEN,
)
def dropbox_ordner_auflisten(projekt_id: str) -> DropboxOrdnerListe:
    """Die Ordner im App-Ordner — damit man den Namen nicht wissen muss.

    Ein Aufruf: files_list_folder(""). Die App sieht nur ihren eigenen Ordner,
    nicht die ganze Dropbox.
    """
    con = verbindung()
    try:
        token = anmelde_dienst.token(con, projekt_id)
    except AnmeldungFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    try:
        dbx = dropbox_anbindung.klient(token)
        return DropboxOrdnerListe(
            projekt_id=projekt_id, ordner=dropbox_anbindung.ordner_liste(dbx)
        )
    except AnbieterFehler as exc:
        raise HTTPException(status_code=503, detail=(exc.code, str(exc)))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=("dropbox_nicht_erreichbar",
                    f"Dropbox antwortet nicht wie erwartet: {exc}"),
        )


@app.post(
    "/api/projekt/{projekt_id}/quelle/dropbox",
    response_model=IngestAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def quelle_aus_dropbox(projekt_id: str) -> IngestAntwort:
    """Liest den eingestellten Dropbox-Ordner ein.

    Ein zweiter Lauf legt keine zweite Quelle an: bekannte Dateien werden
    übersprungen, neue angehängt. Der Riegel steht im Schema —
    UNIQUE (quelle_id, quellpfad).
    """
    con = verbindung_schreibend()
    try:
        stand = anmelde_dienst.verbindung(con, projekt_id)
        if not stand["ordner"]:
            raise HTTPException(
                status_code=422,
                detail=("dropbox_ordner_fehlt",
                        "Für dieses Projekt ist kein Dropbox-Ordner eingetragen."),
            )
        token = anmelde_dienst.token(con, projekt_id)
        dbx = dropbox_anbindung.klient(token)
        ordner = stand["ordner"]
        dateien = [
            RohDatei(pfad=relativ,
                     inhalt=dropbox_anbindung.datei_laden(dbx, anzeige))
            for relativ, anzeige in dropbox_anbindung.md_dateien(dbx, ordner)
        ]
        ergebnis = einlesen(
            con, projekt_id=projekt_id, pfad=ordner,
            quellformat="pressesammlung", dateien=dateien,
        )
    except AnmeldungFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    except AnbieterFehler as exc:
        raise HTTPException(status_code=503, detail=(exc.code, str(exc)))
    except IngestFehler as exc:
        status = 404 if exc.code == "projekt_nicht_gefunden" else 422
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()

    return IngestAntwort(**vars(ergebnis))


# ── Die Visualisierung ────────────────────────────────────────────────────────
# viz/ wird unverändert ausgeliefert. Von den Projektdaten geht nur das
# Exportverzeichnis über die Leitung, und dort nur die fünf Dateien, die viz/
# lädt — data/ enthält auch Datenbanken und Rohdokumente.

VIZ_DIR = Path(__file__).resolve().parent.parent.parent / "viz"
PROJEKT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "projects"
EXPORT_DATEIEN = {
    "data.json", "project_meta.json", "entities_seed.csv",
    "entities_summary.json", "network_layout.json",
}


@app.get("/data/projects/{projekt_id}/exploration/{datei}", include_in_schema=False)
def exportdatei(projekt_id: str, datei: str) -> FileResponse:
    """Eine der fünf Exportdateien. Alles andere gibt es hier nicht."""
    if datei not in EXPORT_DATEIEN:
        raise nicht_gefunden(
            "datei_nicht_ausgeliefert",
            f"'{datei}' gehört nicht zu den Dateien, die die Visualisierung lädt.",
        )
    pfad = PROJEKT_DIR / Path(projekt_id).name / "exploration" / datei
    if not pfad.is_file():
        raise nicht_gefunden(
            "exportdatei_fehlt",
            f"'{datei}' gibt es für '{projekt_id}' nicht — schon exportiert?",
        )
    return FileResponse(pfad)


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

BUILD_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "build"

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
