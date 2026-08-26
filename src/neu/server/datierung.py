"""
datierung.py — datieren, von Hand korrigieren, den Wortlaut ändern

Der Textänderung liegt eine Aufräumregel bei, die über den Schritt hinausgeht:
sie löscht die Akteursfundstellen der Einheit. Das steht im Dienst, nicht hier
— dieser Router entscheidet nichts, er reicht durch.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.neu.datierung import dienst as datierung_dienst
from src.neu.datierung.dienst import DatierungFehler, datieren, datierung_setzen
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.modelle import (
    DatierenRumpf,
    DatierungAntwort,
    DatierungRumpf,
    DatierungVerteilung,
    DatierungZeileAntwort,
    TextAntwort,
    TextRumpf,
)
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN, projekt_muss_es_geben

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.post(
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


@router.patch(
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


@router.patch(
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


@router.get(
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
        projekt_muss_es_geben(con, projekt_id)
        stand = datierung_dienst.verteilung(con, projekt_id)
        stand["anker"] = {
            str(k): v for k, v in datierung_dienst.anker_je_einheit(con, projekt_id).items()
        }
        return DatierungVerteilung(**stand)
    finally:
        con.close()
