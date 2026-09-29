"""
export.py — die Dateien erzeugen, die viz/ liest, und sie ausliefern

Der Export leitet ab, er entscheidet nichts. Jede Angabe in den Dateien steht
so schon in einer Tabelle — kein Datum wird hier erkannt, keine Kategorie
zugeordnet, kein Akteur gefunden.

Gerechnet wird trotzdem, und zwar dreierlei: das Netzwerklayout (300
Iterationen Kräftesimulation über export/kern.layout), die Knoten und Kanten
daraus (export/kern.netz, mit LINK_MIN_COUNT) und die Farbzuordnung nach
Listenplatz (export/kern.farbzuordnung). Alle drei sind Darstellungsfragen,
für die es in der Datenbank nichts gibt, woraus man sie ablesen könnte — die
Farbvergabe soll auf Dauer nach viz/, siehe den offenen Punkt in SCHEMA.md.

Geschrieben wird ebenfalls: die fünf Dateien, und eine lauf-Zeile, die
festhält, wann mit welchen Parametern exportiert wurde. Deshalb steht hier
verbindung_schreibend() und nicht verbindung().

Ausgeliefert werden genau die fünf Dateien, die viz/ lädt — data/ enthält auch
Datenbanken und Rohdokumente.

Die Wurzel ist data/exporte/, nicht data/projects/. Dort schreibt das alte
System; drei Kennungen gibt es in beiden Datenbanken. Gebildet wird der Pfad
in src/neu/pfade.py — und dort an zwei Stellen, weil Schreiben und Lesen
auseinanderfallen, sobald DATA_ROOT gesetzt ist: geschrieben wird immer aufs
Laufwerk, gelesen notfalls auch aus dem Quellbestand (das Prüfstück).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.neu.db import verbindung_schreibend
from src.neu.export.dienst import ExportFehler, exportieren
from src.neu.modelle import ExportAntwort, ExportierenRumpf
from src.neu.pfade import export_quelle
from src.neu.server.gemeinsam import (
    FEHLER_ANTWORTEN,
    nicht_gefunden,
)

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()

EXPORT_DATEIEN = {
    "data.json", "project_meta.json", "entities_seed.csv",
    "entities_summary.json", "network_layout.json",
}

# Die Form, die projekte.kennung_aus_titel() erzeugt.
KENNUNG = re.compile(r"[a-z0-9][a-z0-9-]*")


@router.post(
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


@router.get("/data/exporte/{projekt_id}/{datei}", include_in_schema=False)
def exportdatei(projekt_id: str, datei: str) -> FileResponse:
    """Eine der fünf Exportdateien. Alles andere gibt es hier nicht.

    Die Kennung muss eine Kennung sein: Path(...).name allein reicht nicht, denn
    '..' hat keinen Schrägstrich und überlebt ihn unverändert. Kodiert (%2E%2E)
    kommt es auch durch die Normalisierung davor. Deshalb hier die Form, die
    kennung_aus_titel() ohnehin erzeugt.
    """
    if datei not in EXPORT_DATEIEN:
        raise nicht_gefunden(
            "datei_nicht_ausgeliefert",
            f"'{datei}' gehört nicht zu den Dateien, die die Visualisierung lädt.",
        )
    if not KENNUNG.fullmatch(projekt_id):
        raise nicht_gefunden(
            "kennung_ungueltig",
            f"'{projekt_id}' ist keine Projektkennung.",
        )
    # export_quelle und nicht export_verzeichnis: geschrieben wird aufs
    # Laufwerk, gelesen auch aus dem Quellbestand — das Prüfstück liegt im
    # Git und wandert nicht mit. Mit DATA_ROOT fallen die beiden auseinander.
    verzeichnis = export_quelle(projekt_id)
    pfad = (verzeichnis / datei) if verzeichnis else None
    if pfad is None or not pfad.is_file():
        raise nicht_gefunden(
            "exportdatei_fehlt",
            f"'{datei}' gibt es für '{projekt_id}' nicht — schon exportiert?",
        )
    return FileResponse(pfad)
