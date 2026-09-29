"""
bestand.py — was auf dem Laufwerk liegt, abrufbar

Drei Routen, und keine davon gehört zu einem Pipeline-Schritt: sie beantworten
nicht, was mit einem Projekt passiert ist, sondern was es kostet.

Lesend bis auf eine: das Wegräumen von Vektoren ist die einzige Stelle im ganzen
Server, die Rechenergebnisse auf Zuruf verwirft. Sie steht deshalb hier und
nicht bei den Themen, wo sie nach einem Nebeneffekt des Zuordnens aussähe.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.neu import bestand as bestand_dienst
from src.neu import projekte as projekt_dienst
from src.neu.bestand import BestandFehler
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.konfiguration import lage
from src.neu.modelle import (
    BestandAntwort,
    ProjektBestandAntwort,
    VektorenGeloescht,
    VektorenLoeschenRumpf,
)
from src.neu.projekte import ProjektFehler
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


def eingestellte_modelle() -> set[str]:
    """Welche Einbettungsmodelle der eingestellte Anbieter gerade nimmt.

    Aus der Anbieterlage und nicht aus einer Liste hier: bei 'local' sind es
    zwei (bge-m3 für Themen, MiniLM für Akteure), bei 'voyage' eines für beide
    Aufgaben. Wer das hier nachbaute, hätte eine zweite Wahrheit darüber, womit
    gerechnet wird.
    """
    e = lage().embedding
    namen = set(e.modelle.values())
    namen.update(n for n in (e.modell, e.modell_akteure) if n)
    return namen


@router.get("/api/bestand", response_model=BestandAntwort, responses=FEHLER_ANTWORTEN)
def bestand() -> BestandAntwort:
    """Was auf der Datenwurzel liegt, nach Art getrennt, mit Warnungen.

    Der Anlass: auf 5 GB — der Vorgabe bei Railway — passen GLiNER (1,1 GB) und
    bge-m3 (4,3 GB) zusammen nicht. Ein Umschalten auf 'local' im Betrieb füllt
    das Laufwerk, und vor dieser Route sagte es niemand.
    """
    con = verbindung()
    try:
        z = bestand_dienst.erheben(con, eingestellte_modelle())
    finally:
        con.close()
    return BestandAntwort(
        **{
            **vars(z),
            "datenbank": vars(z.datenbank),
            "modelle": [vars(p) for p in z.modelle],
            "rohdaten": [vars(p) for p in z.rohdaten],
            "exporte": [vars(p) for p in z.exporte],
            "vektoren": [vars(v) for v in z.vektoren],
        }
    )


@router.get(
    "/api/projekt/{projekt_id}/bestand",
    response_model=ProjektBestandAntwort,
    responses=FEHLER_ANTWORTEN,
)
def projekt_bestand(projekt_id: str) -> ProjektBestandAntwort:
    """Was am Löschen dieses Projekts hängt — für die Rückfrage, vor dem Löschen.

    Eine eigene Route und kein Feld in /api/projekte: sie sieht auf das
    Dateisystem, und die Projektliste soll das nicht je Zeile tun.
    """
    con = verbindung()
    try:
        return ProjektBestandAntwort(
            **projekt_dienst.dateien_eines_projekts(con, projekt_id)
        )
    except ProjektFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@router.post(
    "/api/bestand/vektoren/loeschen",
    response_model=VektorenGeloescht,
    responses=FEHLER_ANTWORTEN,
)
def vektoren_loeschen(rumpf: VektorenLoeschenRumpf) -> VektorenGeloescht:
    """Räumt die Vektoren eines Modells weg. Nur auf ausdrückliche Anweisung.

    Kein Lauf tut das je von selbst, auch nicht beim Anbieterwechsel: dass die
    Werte des anderen Modells liegenbleiben, ist der Grund, warum ein
    Zurückschalten nicht neu rechnet. Das eingestellte Modell ist geschützt.
    """
    con = verbindung_schreibend()
    try:
        return VektorenGeloescht(
            **bestand_dienst.vektoren_loeschen(
                con, rumpf.modell, eingestellte_modelle()
            )
        )
    except BestandFehler as exc:
        status = 404 if exc.code == "modell_ohne_vektoren" else 409
        raise HTTPException(status_code=status, detail=(exc.code, str(exc)))
    finally:
        con.close()
