"""
themen.py — Taxonomie vorschlagen, Kategorien pflegen, Einheiten zuordnen

Ein Modul, weil es ein Schritt ist: die Kategorien und die Zuordnung darauf
sind nicht zu trennen. Eine geänderte Beschreibung ändert, wohin die Einheiten
gehören — deshalb hängt PUT …/kategorien einen Klassifikationslauf an, statt
das dem Nutzer als zweiten Knopf zu überlassen.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.neu import laeufe, vektoren
from src.neu.anbieter import AnbieterFehler
from src.neu.db import verbindung, verbindung_schreibend
from src.neu.kategorien import verwaltung as kategorie_verwaltung
from src.neu.kategorien.dienst import (
    KlassifikationFehler,
    klassifizieren,
    zuordnung_setzen,
)
from src.neu.kategorien.verwaltung import KategorieFehler
from src.neu.laeufe import LaufFehler
from src.neu.modelle import (
    KategorieRumpf,
    KategorieZeile,
    KategorienGespeichert,
    KategorienListe,
    KategorienSpeichernRumpf,
    KlassifizierenRumpf,
    LaufBegonnen,
    TaxonomieVorschlagRumpf,
    ZuordnungAntwort,
    ZuordnungRumpf,
)
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN, projekt_muss_es_geben
from src.neu.taxonomie.dienst import vorschlagen

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.post(
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
        projekt_muss_es_geben(con, projekt_id)
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


@router.post(
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
        projekt_muss_es_geben(con, projekt_id)
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


@router.patch(
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


# ── Kategorien pflegen ───────────────────────────────────────────────────────

@router.get(
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
            from src.neu.anbieter import embedding_modellname

            stand["einheiten_ohne_vektor"] = vektoren.lage(
                con, projekt_id, embedding_modellname("themen")
            )["zu_rechnen"]
        except AnbieterFehler:
            stand["einheiten_ohne_vektor"] = None
        return KategorienListe(**stand)
    except KategorieFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()


@router.post(
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


@router.put(
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


@router.patch(
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


@router.delete("/api/kategorie/{kategorie_id}", responses=FEHLER_ANTWORTEN)
def kategorie_loeschen(kategorie_id: int) -> dict:
    """Löscht eine Kategorie. Die Einheiten bleiben, ihre Zuordnung wird offen."""
    con = verbindung_schreibend()
    try:
        return kategorie_verwaltung.loeschen(con, kategorie_id)
    except KategorieFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()
