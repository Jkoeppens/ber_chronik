"""
akteure.py — erkennen, ansehen, von Hand pflegen

Neun Routen, weil der Schritt neun Bedienungen hat: erkennen, auflisten,
markieren, anlegen, herauslösen, eine Fundstelle entfernen, ändern,
verschmelzen, Kandidaten ansehen. Löschen gibt es nicht — ein Knopf, dessen
Wirkung der nächste Lauf rückgängig macht, wäre eine Lüge.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.neu import laeufe
from src.neu.akteure import dienst as akteur_dienst
from src.neu.akteure.dienst import (
    UNGESETZT,
    AkteurFehler,
    akteur_aendern,
    akteure_verschmelzen,
    duplikatskandidaten,
)
from src.neu.anbieter import AnbieterFehler
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.laeufe import LaufFehler
from src.neu.modelle import (
    AkteurAendernRumpf,
    AkteurAnlegenRumpf,
    AkteurAntwort,
    AkteurListe,
    AkteureErkennenRumpf,
    FundstelleGeloescht,
    HerausgeloestAntwort,
    HerausloesenRumpf,
    KandidatenListe,
    LaufBegonnen,
    MarkierungenListe,
    VerschmelzenRumpf,
)
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN, projekt_muss_es_geben

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.post(
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
        projekt_muss_es_geben(con, projekt_id)
    finally:
        con.close()

    # Den Anbieter vorher prüfen, nicht im Faden: ein fehlender Schlüssel soll
    # 503 an der Stelle des Klicks geben und nicht als gescheiterter Lauf vier
    # Minuten später. Der Aufruf ist billig — das Modell lädt erst beim ersten
    # encode. GLiNER wird hier nicht geprüft, weil dessen Prüfung das Modell
    # lädt; sein Fehlen erscheint in der lauf-Zeile.
    try:
        from src.neu.anbieter import embedding_funktion

        embedding_funktion("akteure")
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


@router.get(
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


@router.get(
    "/api/projekt/{projekt_id}/markierungen",
    response_model=MarkierungenListe,
    responses=FEHLER_ANTWORTEN,
)
def markierungen(projekt_id: str) -> MarkierungenListe:
    """Die Fundstellen je Einheit, mit Zeichenpositionen."""
    con = verbindung()
    try:
        projekt_muss_es_geben(con, projekt_id)
        je_einheit = akteur_dienst.fundstellen_je_einheit(con, projekt_id)
        return MarkierungenListe(
            projekt_id=projekt_id,
            anzahl=sum(len(v) for v in je_einheit.values()),
            je_einheit={str(k): v for k, v in je_einheit.items()},
        )
    finally:
        con.close()


@router.post(
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


@router.post(
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


@router.delete(
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


@router.patch(
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


@router.post(
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


@router.get(
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
