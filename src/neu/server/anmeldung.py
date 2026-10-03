"""
anmeldung.py — die Anmeldeseite und ihr Gegenstück

Drei Routen, und alle drei liegen VOR dem Riegel (zugang.OHNE_RIEGEL):

    GET  /anmelden   das Formular
    POST /anmelden   Token prüfen, Keks setzen, weiterleiten
    GET  /abmelden   Keks löschen

/abmelden muss mit offen sein: Abmelden mit einem bereits ungültigen Keks soll
nicht an einem 401 scheitern — das wäre eine Tür, die nur von innen zugeht.

include_in_schema=False für alle drei: sie stünden sonst in /openapi.json und
damit in der erzeugten api-typen.ts. Das Frontend hat mit ihnen nichts zu tun
und soll von ihnen auch nichts wissen.
"""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.neu import zugang

router = APIRouter()

#: Die Seite liegt neben dem Code, nicht in frontend/. Sie gehört dem Dienst.
SEITE = Path(__file__).resolve().parent.parent / "anmeldeseite.html"

#: Wohin, wenn kein Ziel mitkam oder das Ziel nicht taugt.
VORGABE_ZIEL = "/"


def ziel_pruefen(roh: str | None) -> str:
    """Nur Pfade auf diesem Dienst. Alles andere wird zur Startseite.

    Der Wert kommt aus der Adresszeile und damit von außen. Ohne diese Prüfung
    wäre '/anmelden?weiter=https://woanders' eine offene Weiterleitung: eine
    Adresse, die auf unserem Dienst beginnt und auf einem fremden endet — und
    genau so etwas verschickt man in einer Mail.

    Zwei Schrägstriche am Anfang sind der Fall, den man übersieht: '//fremd.de'
    ist für den Browser eine vollständige Adresse, für eine Prüfung auf
    startswith('/') aber ein Pfad.
    """
    if not roh or not roh.startswith("/"):
        return VORGABE_ZIEL
    if roh.startswith("//") or roh.startswith("/\\"):
        return VORGABE_ZIEL
    return roh


def seite(fehler: str = "", weiter: str = VORGABE_ZIEL) -> str:
    """Die Seite mit eingesetzter Meldung und Ziel.

    Beides maskiert: das Ziel kommt aus der Adresszeile, die Meldung ist zwar
    unsere eigene, aber eine Ausnahme beim Maskieren wäre eine Ausnahme zu viel
    — wer die Meldung später aus einer Angabe von außen baut, hätte sonst eine
    Lücke, die niemand bemerkt.
    """
    kasten = f'<div class="fehler">{html.escape(fehler)}</div>' if fehler else ""
    return (SEITE.read_text(encoding="utf-8")
            .replace("{{FEHLER}}", kasten)
            .replace("{{WEITER}}", html.escape(weiter, quote=True)))


def _antwort(inhalt: str, status: int = 200) -> HTMLResponse:
    # no-store: die Seite trägt ein Formular für ein Geheimnis. Sie gehört
    # nicht in den Zwischenspeicher des Browsers und nicht in den eines
    # Vermittlers dazwischen.
    return HTMLResponse(inhalt, status_code=status,
                        headers={"Cache-Control": "no-store"})


@router.get("/anmelden", include_in_schema=False)
def anmeldeseite(weiter: str = VORGABE_ZIEL) -> HTMLResponse:
    return _antwort(seite(weiter=ziel_pruefen(weiter)))


@router.post("/anmelden", include_in_schema=False)
def anmelden(
    anfrage: Request,
    token: str = Form(default=""),
    weiter: str = Form(default=VORGABE_ZIEL),
) -> Response:
    """Token prüfen, Keks setzen, weiterleiten.

    Bei einem falschen Token kommt die Seite mit einer Meldung zurück — kein
    401 und damit kein Browserfenster. 200 und nicht 401 ist dabei Absicht: für
    den Browser ist das eine gewöhnliche Seite, und ein 401 ohne
    WWW-Authenticate verwirrt Zwischenschichten mehr, als es nützt.

    Der eingegebene Wert steht in keiner Meldung und in keinem Protokoll.
    """
    ziel = ziel_pruefen(weiter)
    wer = zugang.nachschlagen(token.strip()) if token.strip() else None
    if wer is None or wer.id is None:
        # wer.id is None hieße: das gemeinsame Passwort. Dahinter steht keine
        # Zeile, also lässt sich auch kein Keks darauf ausstellen — der trägt
        # eine zugang.id und nichts sonst. Wer es benutzt, nimmt Basic.
        return _antwort(
            seite(fehler="Dieser Token gilt nicht.", weiter=ziel),
            status=200,
        )

    try:
        geheimnis = zugang.keks_geheimnis()
    except (FileNotFoundError, sqlite3.Error):
        return _antwort(
            seite(fehler="Die Anmeldung ist gerade nicht möglich — der Dienst "
                         "erreicht seine Datenbank nicht.", weiter=ziel),
            status=503,
        )

    antwort = RedirectResponse(ziel, status_code=303)
    antwort.set_cookie(
        zugang.KEKS,
        zugang.keks_backen(wer.id, geheimnis),
        max_age=zugang.KEKS_DAUER,
        httponly=True,    # kein Zugriff aus JavaScript
        secure=True,      # nur über HTTPS; localhost gilt dem Browser als sicher
        samesite="lax",   # nicht bei fremden POSTs mitgeschickt
        path="/",
    )
    return antwort


@router.get("/abmelden", include_in_schema=False)
def abmelden() -> Response:
    """Löscht den Keks und führt zur Anmeldeseite.

    Der Token bleibt gültig — abgemeldet wird dieser Browser, nicht der Zugang.
    Wer einen Zugang wirklich beenden will, nimmt zugang_cli --entziehen; das
    wirkt sofort und auf alle Sitzungen, weil der Riegel jede Anfrage in der
    Tabelle nachschlägt.
    """
    antwort = RedirectResponse("/anmelden", status_code=303)
    # Dieselben Eigenschaften wie beim Setzen — sonst löscht der Browser einen
    # anderen Keks als den, der da ist, und zwar wortlos.
    antwort.delete_cookie(
        zugang.KEKS, path="/", httponly=True, secure=True, samesite="lax"
    )
    return antwort
