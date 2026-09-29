"""
ingest.py — Quellen einlesen: Datei, Ordner, Dropbox

Drei Wege ins System, und die Anmeldung, die den dritten möglich macht. Sie
stehen zusammen, weil sie dieselbe Frage verschieden beantworten: woher kommt
das Rohdokument.

Der Pfad aus dem Netz wird gebunden, nicht bereinigt — an data/raw/ für
Dokumente (gemeinsam.pfad_in_rohdaten), an OBSIDIAN_WURZEL für einen lokalen
Tresor (gemeinsam.pfad_in_obsidian). Zwei Wurzeln, weil ein Obsidian-Ordner nie
unter data/raw/ liegt; gebunden werden beide. Ist OBSIDIAN_WURZEL nicht gesetzt,
ist der lokale Ordnerweg geschlossen und es bleibt der über Dropbox.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from src.neu.anbieter import AnbieterFehler
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.ingest import anmeldung as anmelde_dienst
from src.neu.ingest import dropbox_anbindung
from src.neu.ingest.anmeldung import AnmeldungFehler
from src.neu.ingest.dienst import IngestFehler, einlesen
from src.neu.ingest.kern import RohDatei
from src.neu.modelle import (
    AnmeldungBeginn,
    DropboxOrdnerListe,
    DropboxOrdnerRumpf,
    DropboxStand,
    IngestAntwort,
    QuelleAnlegen,
    Quellformat,
)
from src.neu.server.gemeinsam import (
    FEHLER_ANTWORTEN,
    pfad_in_obsidian,
    pfad_in_rohdaten,
)

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.post(
    "/api/projekt/{projekt_id}/quelle",
    response_model=IngestAntwort,
    responses=FEHLER_ANTWORTEN,
    status_code=201,
)
def quelle_anlegen(projekt_id: str, rumpf: QuelleAnlegen) -> IngestAntwort:
    """Liest eine Quelle ein und legt quelle, einheit und lauf an.

    Ein DOCX kommt aus data/raw/ — dorthin legt der Upload es ab, und ein Pfad
    aus dem Netz darf nicht ins übrige Dateisystem zeigen.

    Ein Obsidian-Ordner liegt dort nie: er liegt in Dropbox oder als absoluter
    Pfad auf der Platte, etwa unter ~/Library/CloudStorage/. Für Sammlungen gilt
    die data/raw/-Bindung deshalb nicht — dafür gilt OBSIDIAN_WURZEL, und ohne
    sie ist dieser Weg geschlossen. Siehe pfad_in_obsidian().

    Bis September 2026 wurde hier jeder absolute Pfad genommen und alles
    darunter an .md-Dateien eingelesen.
    """
    if rumpf.quellformat == "pressesammlung":
        pfad = pfad_in_obsidian(rumpf.pfad)
        if not pfad.is_dir():
            raise HTTPException(
                status_code=422,
                detail=("ordner_nicht_gefunden",
                        f"'{rumpf.pfad}' ist kein vorhandenes Verzeichnis. Für "
                        "eine Sammlung wird ein Ordner erwartet — lokal ein "
                        "absoluter Pfad, sonst der Weg über Dropbox."),
            )
    else:
        pfad = pfad_in_rohdaten(rumpf.pfad)

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


@router.post(
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
    ziel = pfad_in_rohdaten(name)
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


# ── Dropbox ──────────────────────────────────────────────────────────────────

@router.get(
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


@router.put(
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


@router.post(
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


@router.get("/api/obsidian/oauth/callback", include_in_schema=False)
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


@router.get(
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


@router.post(
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
