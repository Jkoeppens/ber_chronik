"""
zugang.py — ein Riegel vor allem, mit HTTP Basic

WAS GEPRÜFT WIRD. Das eingegebene Passwort wird in der Tabelle zugang
nachgeschlagen — ein Token je Person. ZUGANG_PASSWORT gilt zusätzlich weiter,
denn sonst sperrte eine leere Tabelle auf einem frischen Laufwerk den Betreiber
aus. Beim Hochfahren steht als Warnung, dass es noch gilt und wie viele Token
daneben stehen: sonst bleibt es liegen, weil niemand merkt, dass es da ist.

KEIN ZWISCHENSPEICHER. Jede Anfrage schlägt nach. Ein Speicher, der nur bei
unbekanntem Token neu lädt, ließe einen entzogenen Token weitergelten — und
Widerrufbarkeit ist der ganze Zweck dieser Änderung. Die Abfrage geht über eine
Tabelle mit einstelliger Zeilenzahl; das kostet nichts gegen den Nutzen,
jemandem den Zugang wirklich nehmen zu können.

DREI WEGE, in dieser Reihenfolge geprüft: ein Sitzungskeks, HTTP Basic, das
gemeinsame ZUGANG_PASSWORT. Der Keks zuerst, weil er der Normalfall im Browser
ist. Basic bleibt ausdrücklich — daran hängen curl, die Prüfungen und alles,
was ohne Browser läuft.

WARUM BASIC UND KEIN ANMELDEFORMULAR (gilt weiter für Basic selbst, die
Anmeldeseite in server/anmeldung.py kam im Oktober 2026 daneben). Es deckt in einem Zug alles ab — die
Fläche unter /, die API, /viz/ und die Exportdateien —, der Browser fragt selbst
danach und merkt es sich, und am Frontend ändert sich keine Zeile. Damit nimmt
es nichts vorweg: wenn die zugang-Tabelle mit Token je Person drankommt, wird
diese Middleware ersetzt, und das Frontend war nie um ein Behelfsverfahren herum
gebaut. Ein selbstgebautes Formular wäre genau das Gegenteil — Zustand im
Frontend, ein Kekssatz, eine Abmeldung, und alles davon wegzuwerfen, sobald es
richtig gemacht wird.

WARUM KEINE VORGABE. Fehlt ZUGANG_PASSWORT, startet der Server nicht. Eine
Vorgabe würde hier behaupten 'das darf offen stehen', und ein stiller offener
Betrieb ist der Fehler, den es zu verhindern gilt — dieselbe Wahl wie bei
EMBEDDING_PROVIDER und aus demselben Grund: was falsch gesetzt erst Wochen
später auffällt, wird nicht geraten.

REINE ASGI-MIDDLEWARE und nicht BaseHTTPMiddleware. Der Chat antwortet als
Ereignisstrom; BaseHTTPMiddleware legt sich zwischen Antwort und Leitung und ist
für Ströme wiederholt die Ursache von Puffern und hängenden Verbindungen
gewesen. Diese hier fasst die Antwort überhaupt nicht an — sie lässt durch oder
antwortet selbst mit 401.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone

#: Die Variable, die das Geheimnis trägt. Als Konstante, weil die Meldung beim
#: Start sie nennen muss und ein Tippfehler dort nicht auffiele.
VARIABLE = "ZUGANG_PASSWORT"

#: Blieb aus der Zeit, als der Browser sein eigenes Anmeldefenster zeigte. Wird
#: seit der Anmeldeseite nirgends mehr gesetzt — WWW-Authenticate ist genau die
#: Kopfzeile, die dieses Fenster öffnet.
BEREICH = "BER Chronik"

#: Pfade ohne Riegel. Absichtlich LEER.
#:
#: Geprüft am 29. September: railway.toml setzt kein healthcheckPath und das
#: Dockerfile kein HEALTHCHECK. Railway fragt damit nichts über HTTP ab, sondern
#: wartet darauf, dass der Prozess auf $PORT lauscht — es gibt also nichts
#: auszunehmen. Wer später einen Gesundheitscheck einträgt, muss seinen Pfad
#: hier aufnehmen, sonst hält Railway den Dienst wegen 401 für tot. Und was hier
#: steht, steht ohne Passwort offen: es darf nichts verraten, auch keine
#: Versionsnummer und keinen Projektnamen.
OHNE_RIEGEL: tuple[str, ...] = ("/anmelden", "/abmelden")

#: Pfade, hinter denen Programme sitzen und keine Menschen. Sie bekommen 401 und
#: niemals eine Weiterleitung: ein Aufruf aus der Fläche oder aus curl soll
#: keine HTML-Seite geliefert bekommen, die er nicht lesen kann.
#:
#: Über den Pfad und nicht über Accept: eine Kopfzeile lässt sich weglassen und
#: fälschen, der Pfadraum liegt fest.
PROGRAMM_PFADE: tuple[str, ...] = (
    "/api/", "/data/", "/openapi.json", "/docs", "/redoc",
)

protokoll = logging.getLogger("ber.neu")


@dataclass(frozen=True)
class Person:
    """Wer gerade angefragt hat. Ohne den Token — der gehört nicht weitergereicht.

    'id' ist None für das gemeinsame ZUGANG_PASSWORT: dahinter steht keine
    Zeile und damit niemand Bestimmtes. Wer später projekt_zugang verdrahtet,
    muss genau diesen Fall entscheiden, und ein None zwingt ihn dazu — eine
    erfundene Kennung täte das nicht.
    """

    id: int | None
    name: str
    rolle: str


#: Das gemeinsame Geheimnis, als Person gedacht. Es gehört niemandem.
GEMEINSAM = Person(id=None, name="gemeinsames Passwort", rolle="verwalter")


# ── Der Sitzungskeks ──────────────────────────────────────────────────────────
#
# Er trägt NUR die zugang.id und eine Frist, dazu eine Signatur. Kein Token,
# kein Name, nichts Geheimes. Das ist der Zweck der Bauform: der Riegel schlägt
# die Zeile bei jeder Anfrage nach, also beendet --entziehen auch bestehende
# Sitzungen sofort. Ein Keks, der den Token selbst trüge, wäre für sich gültig
# und überlebte jedes Entziehen bis zum Ablauf — bis zu dreißig Tage.
#
# Form:  <id>.<gueltig_bis>.<signatur>,  Signatur = HMAC-SHA256 über den Rumpf.

KEKS = "ber_zugang"

#: 30 Tage. Bei Gebrauch NICHT verlängert — der Keks läuft ab, der Token nicht.
#: Ein verlorener Browser vergisst von selbst, ein verlorener Token nicht.
KEKS_DAUER = 30 * 24 * 3600

#: Wo das Signaturgeheimnis in der Tabelle einstellung steht.
GEHEIMNIS_SCHLUESSEL = "keks_geheimnis"


def keks_geheimnis(con: sqlite3.Connection | None = None) -> str:
    """Das Geheimnis, mit dem Kekse signiert werden. Legt es einmalig an.

    In der Datenbank und nicht in einer Umgebungsvariablen: eine Variable mehr
    im Dashboard ist eine mehr, die jemand setzen, vergessen und falsch setzen
    kann — und dort wird gerade aufgeräumt.

    Wer die Zeile löscht, meldet alle Sitzungen ab: die Signaturen stimmen dann
    nicht mehr. Kein Token wird davon ungültig. Das ist der Notausgang, falls
    ein Keks abhanden kommt.
    """
    from src.neu.db import verbindung_schreibend

    eigene = con is None
    con = con or verbindung_schreibend()
    try:
        zeile = con.execute(
            "SELECT wert FROM einstellung WHERE schluessel = ?",
            (GEHEIMNIS_SCHLUESSEL,),
        ).fetchone()
        if zeile is not None:
            return zeile[0]
        wert = secrets.token_urlsafe(32)
        with con:
            con.execute(
                "INSERT INTO einstellung (schluessel, wert, gesetzt_am) "
                "VALUES (?, ?, ?)",
                (GEHEIMNIS_SCHLUESSEL, wert,
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )
        return wert
    finally:
        if eigene:
            con.close()


def _unterschrift(rumpf: str, geheimnis: str) -> str:
    return hmac.new(
        geheimnis.encode("utf-8"), rumpf.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def keks_backen(zugang_id: int, geheimnis: str, jetzt: float | None = None) -> str:
    """Der Wert, der in den Keks geht."""
    bis = int((jetzt if jetzt is not None else time.time()) + KEKS_DAUER)
    rumpf = f"{zugang_id}.{bis}"
    return f"{rumpf}.{_unterschrift(rumpf, geheimnis)}"


def keks_lesen(wert: str, geheimnis: str, jetzt: float | None = None) -> int | None:
    """Die zugang.id aus einem Keks — oder None.

    None bei allem, was nicht stimmt: falsche Form, falsche Signatur, Frist
    abgelaufen. Kein Unterschied in der Antwort, denn für den Aufrufer ist jeder
    dieser Fälle derselbe: nicht angemeldet.

    Die Signatur wird VOR der Frist geprüft. Umgekehrt verriete die Reihenfolge
    einem Fälscher, ob sein Rumpf wenigstens die richtige Gestalt hat.
    """
    if not wert:
        return None
    teile = wert.rsplit(".", 1)
    if len(teile) != 2:
        return None
    rumpf, gegeben = teile
    if not hmac.compare_digest(_unterschrift(rumpf, geheimnis), gegeben):
        return None
    try:
        roh_id, roh_bis = rumpf.split(".", 1)
        zugang_id, bis = int(roh_id), int(roh_bis)
    except ValueError:
        return None
    if (jetzt if jetzt is not None else time.time()) >= bis:
        return None
    return zugang_id


def nach_id(zugang_id: int) -> Person | None:
    """Die Zeile zu einer id — oder None, wenn es sie nicht mehr gibt.

    Der zweite Teil der Bauform: der Keks sagt nur, WER behauptet zu sein; ob es
    diesen Zugang noch gibt, sagt die Tabelle. Deshalb wirkt --entziehen sofort,
    auch auf laufende Sitzungen.
    """
    from src.neu.db import verbindung

    try:
        con = verbindung()
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        zeile = con.execute(
            "SELECT id, name, rolle FROM zugang WHERE id = ?", (zugang_id,)
        ).fetchone()
        if zeile is None:
            return None
        return Person(
            id=zeile["id"],
            name=zeile["name"] or f"Zugang {zeile['id']}",
            rolle=zeile["rolle"],
        )
    except sqlite3.Error:
        return None
    finally:
        con.close()


class ZugangFehlt(RuntimeError):
    """Kein Passwort in der Umgebung. Wird beim Hochfahren geworfen."""


def passwort() -> str:
    """Das gemeinsame Geheimnis. Wirft, wenn es fehlt.

    Blanks werden abgeschnitten, und ein Passwort, das nur daraus besteht, gilt
    als nicht gesetzt: ZUGANG_PASSWORT=" " in einer .env ist ein Versehen und
    kein Geheimnis.
    """
    roh = (os.environ.get(VARIABLE) or "").strip()
    if not roh:
        raise ZugangFehlt(
            f"{VARIABLE} ist nicht gesetzt. Ohne sie startet der Server nicht — "
            f"es gibt keine Vorgabe, weil eine Vorgabe behaupten würde, dieser "
            f"Dienst dürfe offen stehen. Setzen: {VARIABLE}=<Geheimnis> in .env "
            f"(lokal) oder in den Variablen des Dienstes (Railway)."
        )
    return roh


def _angebotenes(kopfzeilen: list[tuple[bytes, bytes]]) -> str | None:
    """Das Passwort aus einem Basic-Kopf — oder None, wenn keines drinsteht.

    Der Benutzername wird nicht geprüft. Das Geheimnis ist das Passwort, und
    eine zweite Variable daneben wäre vor allem eine zweite Möglichkeit, sich
    auszusperren. Der Browser braucht das Feld, wir nicht.
    """
    for name, wert in kopfzeilen:
        if name != b"authorization":
            continue
        teile = wert.split(None, 1)
        if len(teile) != 2 or teile[0].lower() != b"basic":
            return None
        try:
            entpackt = base64.b64decode(teile[1], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
        # Ohne Doppelpunkt ist es kein Basic-Wert. rsplit wäre falsch: ein
        # Passwort darf Doppelpunkte enthalten, ein Benutzername nicht.
        if ":" not in entpackt:
            return None
        return entpackt.split(":", 1)[1]
    return None


def nachschlagen(angeboten: str) -> Person | None:
    """Sucht das angebotene Passwort in zugang. None heißt: kein Treffer.

    Alle Zeilen werden geholt und einzeln mit compare_digest verglichen, statt
    mit WHERE token = ? zu suchen. Zwei Gründe, und der zweite ist der
    wichtigere:

      SQLite vergleicht Zeichenketten abbrechend. Über die Dauer verriete das,
      wie viele Zeichen gestimmt haben.

      Ein WHERE auf den geheimen Wert schriebe ihn in jede Abfragestatistik und
      in jedes Protokoll, das SQL mitschneidet. Der Wert soll die Middleware
      nicht verlassen.

    Die Tabelle hat einstellig viele Zeilen. Wenn sie das einmal nicht mehr hat,
    ist der Gedanke oben trotzdem richtig und die Lösung eine andere — nicht
    WHERE token = ?.
    """
    from src.neu.db import verbindung

    try:
        con = verbindung()
    except (FileNotFoundError, sqlite3.Error):
        # Keine Datenbank heißt: nur das gemeinsame Geheimnis gilt. Ein frisches
        # Laufwerk darf nicht aussperren.
        return None
    try:
        gesucht = angeboten.encode("utf-8")
        for zeile in con.execute(
            "SELECT id, token, name, rolle FROM zugang"
        ):
            if secrets.compare_digest(zeile["token"].encode("utf-8"), gesucht):
                return Person(
                    id=zeile["id"],
                    name=zeile["name"] or f"Zugang {zeile['id']}",
                    rolle=zeile["rolle"],
                )
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return None


def anzahl_token() -> int:
    """Wie viele Zeilen in zugang stehen. Für die Warnung beim Hochfahren."""
    from src.neu.db import verbindung

    try:
        con = verbindung()
    except (FileNotFoundError, sqlite3.Error):
        return 0
    try:
        return con.execute("SELECT COUNT(*) FROM zugang").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def _keks_aus(kopfzeilen: list[tuple[bytes, bytes]]) -> str | None:
    """Unseren Keks aus der Cookie-Zeile — oder None.

    Von Hand und nicht über http.cookies: dessen SimpleCookie verschluckt fremde
    Kekse mit ungewöhnlichen Zeichen still und gibt dann auch unseren nicht mehr
    her. Hier wird nur nach dem einen gesucht; was daneben steht, ist
    gleichgültig.

    Der erste Treffer gewinnt. Zwei Kekse gleichen Namens kommen vor, wenn einer
    für eine Unterdomäne gesetzt wurde; einen davon auszuwählen ist in jedem
    Fall willkürlich, und alle der Reihe nach zu versuchen hieße, einem
    Angreifer, der einen zweiten setzen kann, einen zweiten Versuch zu schenken.
    """
    for name, wert in kopfzeilen:
        if name != b"cookie":
            continue
        for stueck in wert.decode("latin-1").split(";"):
            schluessel, _, inhalt = stueck.partition("=")
            if schluessel.strip() == KEKS:
                return inhalt.strip()
    return None


class Riegel:
    """Lässt eine Anfrage durch oder antwortet mit 401. Nichts dazwischen."""

    def __init__(self, app, geheimnis: str, ohne_riegel: tuple[str, ...] = OHNE_RIEGEL):
        self.app = app
        self._geheimnis = geheimnis
        self._ohne_riegel = frozenset(ohne_riegel)
        #: Wer schon einmal gemeldet wurde. Ein Set und keine Zählung: es geht
        #: um 'ist genannt', nicht um 'wie oft'.
        self._gemeldet: set[tuple[int | None, str]] = set()

    def _wer_auch_immer(self, scope) -> Person | None:
        """Drei Wege, in dieser Reihenfolge: Keks, Basic, gemeinsames Passwort.

        Der Keks zuerst, weil er der Normalfall im Browser ist und ohne ihn jede
        Anfrage einen Basic-Kopf mitschleppen müsste.

        Basic bleibt ausdrücklich: daran hängen curl, die Prüfungen und alles,
        was ohne Browser läuft. Es ist der Weg, der keine Sitzung braucht.
        """
        kopfzeilen = scope.get("headers") or []
        wert = _keks_aus(kopfzeilen)
        if wert:
            zugang_id = keks_lesen(wert, self._geheimnis_keks())
            if zugang_id is not None:
                # Der Keks sagt nur, WER behauptet zu sein. Ob es den Zugang
                # noch gibt, sagt die Tabelle — darum wirkt --entziehen sofort.
                wer = nach_id(zugang_id)
                if wer is not None:
                    return wer
        return self._wer(_angebotenes(kopfzeilen))

    def _geheimnis_keks(self) -> str:
        """Das Signaturgeheimnis, je Anfrage gelesen. NICHT gemerkt.

        Eine erste Fassung merkte es sich für den Serverlauf — eine Abfrage
        weniger je Anfrage. Das war falsch, aus demselben Grund, aus dem der
        Token je Anfrage nachgeschlagen wird: ein gemerkter Wert ließe das
        Löschen der Zeile erst beim nächsten Neustart wirken, und das Löschen
        ist der Notausgang, falls ein Keks abhanden kommt. Ein Notausgang, der
        erst nach einem Neustart aufgeht, ist keiner.

        Es kostet eine Abfrage auf eine Tabelle mit einer Zeile. Dieselbe
        Rechnung wie beim Token, und dieselbe Antwort.
        """
        try:
            return keks_geheimnis()
        except (FileNotFoundError, sqlite3.Error):
            # Ohne Datenbank gibt es keine Sitzungen. Ein zufälliger Wert lässt
            # jeden Keks scheitern, statt ihn durchzulassen.
            return secrets.token_urlsafe(32)

    def _wer(self, angeboten: str | None) -> Person | None:
        """Wer das ist — oder None. Zwei Wege, beide mit compare_digest.

        Erst das gemeinsame Geheimnis, weil es ohne Datenbank auskommt und den
        Betreiber auf einem leeren Laufwerk hereinlassen muss. Dann die Tabelle.

        compare_digest und nicht ==: ein Vergleich, der beim ersten
        unterschiedlichen Zeichen abbricht, verrät über die Dauer, wie viele
        Zeichen gestimmt haben.
        """
        if not angeboten:
            return None
        if secrets.compare_digest(
            angeboten.encode("utf-8"), self._geheimnis.encode("utf-8")
        ):
            return GEMEINSAM
        return nachschlagen(angeboten)

    def _melden(self, wer: Person) -> None:
        """Einmal je Zugang und Serverlauf. Name und Rolle, nie der Token.

        Nicht je Anfrage: ein Aufruf von /viz/ lädt rund zwanzig Dateien, und
        zwanzig gleiche Zeilen sind keine Auskunft, sondern Rauschen.
        """
        schluessel = (wer.id, wer.name)
        if schluessel in self._gemeldet:
            return
        self._gemeldet.add(schluessel)
        protokoll.info("Zugang: %s (%s)", wer.name, wer.rolle)

    async def __call__(self, scope, receive, send):
        art = scope.get("type")
        if art == "lifespan":
            return await self.app(scope, receive, send)
        pfad = scope.get("path", "")
        if art == "http" and pfad in self._ohne_riegel:
            return await self.app(scope, receive, send)
        wer = self._wer_auch_immer(scope)
        if wer is not None:
            # Die erkannte Person für die Anfrage hinterlegen. Noch liest das
            # niemand; es ist die Fläche, auf der projekt_zugang später steht.
            scope["zugang"] = wer
            self._melden(wer)
            return await self.app(scope, receive, send)
        if art == "websocket":
            # Es gibt heute keine; ohne diesen Zweig fiele eine spätere
            # ungeprüft durch, weil 401 kein Websocket-Abschluss ist.
            await send({"type": "websocket.close", "code": 1008})
            return

        # Ein Mensch, der eine Seite aufruft, gehört zur Anmeldeseite. Ein
        # Programm bekommt 401. Schreibende Zugriffe ebenfalls: eine
        # Weiterleitung auf ein POST verwandelte es stillschweigend in ein GET.
        if (scope.get("method") == "GET"
                and not any(pfad.startswith(v) for v in PROGRAMM_PFADE)):
            await self._weiterleiten(send, pfad, scope.get("query_string", b""))
            return
        await self._abweisen(send)

    async def _weiterleiten(self, send, pfad: str, abfrage: bytes) -> None:
        """302 auf die Anmeldeseite, mit dem Ziel im Gepäck.

        Das Ziel wird kodiert mitgegeben, damit man nach der Anmeldung dort
        landet, wo man hinwollte, und nicht auf der Startseite.
        """
        from urllib.parse import quote

        ziel = pfad + ("?" + abfrage.decode("latin-1") if abfrage else "")
        ort = f"/anmelden?weiter={quote(ziel, safe='')}"
        await send({
            "type": "http.response.start",
            "status": 302,
            "headers": [
                (b"location", ort.encode("latin-1")),
                (b"content-length", b"0"),
                # Keine zwischengespeicherte Weiterleitung: wer sich anmeldet,
                # soll beim nächsten Aufruf die Seite sehen und nicht erneut die
                # Umleitung aus dem Zwischenspeicher.
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": b""})

    async def _abweisen(self, send) -> None:
        """401 in der einen Fehlergestalt des Servers.

        Dieselbe Gestalt wie jeder andere Fehler ({"fehler": {...}}), damit die
        Fläche nicht zwei Formen auseinanderhalten muss.
        """
        koerper = json.dumps(
            {"fehler": {
                "code": "zugang_verweigert",
                "meldung": "Dieser Dienst verlangt eine Anmeldung. "
                           "Im Browser: /anmelden",
                "status": 401,
            }},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            # KEIN WWW-Authenticate. Es ist genau die Kopfzeile, die das
            # Browserfenster öffnet — und das abzulösen ist der Zweck der
            # Anmeldeseite. Basic funktioniert ohne sie weiter: wer
            # Anmeldedaten mitschickt, wird geprüft. Nur die unaufgeforderte
            # Rückfrage entfällt. Für curl heißt das --basic -u, siehe
            # DEPLOYMENT.md.
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(koerper)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": koerper})


# ── Die erkannte Person in einer Route ────────────────────────────────────────

def wer_fragt(anfrage) -> Person:
    """Die erkannte Person aus dem Umfeld der Anfrage.

    Als FastAPI-Abhängigkeit gedacht:

        def route(wer: Person = Depends(wer_fragt)): …

    Noch benutzt sie niemand. Sie steht hier, damit die Stelle feststeht, an der
    projekt_zugang später nachsieht — und damit keine Route sich ihren eigenen
    Weg an scope baut.

    Kein Rückfall auf 'irgendwer': ist nichts hinterlegt, ist der Riegel
    umgangen worden, und das ist ein Fehler im Aufbau und keine Anfrage ohne
    Anmeldung. Darum ein harter Abbruch und keine 401 — eine 401 lüde zum
    Wiederholen ein, obwohl Wiederholen nichts ändert.
    """
    wer = anfrage.scope.get("zugang")
    if not isinstance(wer, Person):
        raise RuntimeError(
            "Kein Zugang im Umfeld der Anfrage. Diese Route liegt nicht hinter "
            "dem Riegel — siehe src/neu/zugang.py."
        )
    return wer


# ── Zugänge anlegen und entziehen ─────────────────────────────────────────────

def neuer_token() -> str:
    """Ein frischer Tokenwert. Die EINE Stelle, die ihn erzeugt.

    token_urlsafe(32) sind 256 Bit Zufall — genug, dass Raten ausscheidet, und
    kurz genug, um ihn einmal weiterzugeben. Hier und nicht in ingest/cli.py:
    dort stand er neben dem Anlegen eines Projekts, und wer einen Zugang ohne
    Projekt brauchte, hatte keinen Weg.
    """
    return secrets.token_urlsafe(32)


def anlegen(
    con: sqlite3.Connection,
    name: str,
    organisation: str = "",
    rolle: str = "nutzer",
) -> tuple[int, str]:
    """Legt einen Zugang an und gibt (id, token) zurück.

    Ohne Projekt. Die Kopplung in ingest/cli.py — ein Zugang entsteht nur
    zusammen mit einem Projekt — war der Fehler und nicht das Vorbild: sie ließ
    sich nicht trennen, und ein zweiter Mensch am selben Projekt brauchte
    trotzdem ein eigenes Projekt.
    """
    from datetime import datetime, timezone

    from src.neu.vokabular import ROLLEN, pruefen

    name = name.strip()
    if not name:
        raise ValueError("Ein Zugang braucht einen Namen — sonst sagt die Liste nichts.")
    pruefen(rolle, ROLLEN, "Rolle")

    token = neuer_token()
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        zeiger = con.execute(
            "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, name, organisation.strip(), rolle, jetzt),
        )
    return zeiger.lastrowid, token


def entziehen(con: sqlite3.Connection, kennung: str) -> dict:
    """Löscht einen Zugang, benannt über seine id oder seinen Namen.

    NICHT über den Tokenwert: wer einen Zugang entzieht, hat ihn gerade nicht
    zur Hand — das ist ja der Anlass. Ein Befehl, der den Token verlangt, wäre
    genau dann unbenutzbar, wenn man ihn braucht.

    Der Eigentümer eines Projekts lässt sich nicht entziehen, solange ihm eines
    gehört: projekt.eigentuemer_id ist NOT NULL ohne ON DELETE, das Löschen
    bräche den Fremdschlüssel. Die Meldung sagt, was stattdessen zu tun ist.
    """
    zeile = con.execute(
        "SELECT id, name, rolle FROM zugang WHERE id = ? OR name = ?",
        (kennung if kennung.isdigit() else -1, kennung),
    ).fetchone()
    if zeile is None:
        raise ValueError(f"Kein Zugang mit id oder Name '{kennung}'.")

    besitzt = con.execute(
        "SELECT COUNT(*) FROM projekt WHERE eigentuemer_id = ?", (zeile["id"],)
    ).fetchone()[0]
    if besitzt:
        raise ValueError(
            f"'{zeile['name']}' gehören noch {besitzt} Projekt(e). Erst umhängen:\n"
            f"    UPDATE projekt SET eigentuemer_id = <neu> "
            f"WHERE eigentuemer_id = {zeile['id']};"
        )
    with con:
        con.execute("DELETE FROM zugang WHERE id = ?", (zeile["id"],))
    return {"id": zeile["id"], "name": zeile["name"], "rolle": zeile["rolle"]}


#: Was die Liste unter sich schreibt. Steht hier und nicht im Druckbefehl,
#: damit ein Test sie halten kann — der Satz ist eine Aussage über das
#: Verhalten, und Aussagen über Verhalten veralten still.
KEINE_PROJEKTRECHTE = (
    "Projektzugänge werden nicht geprüft: jeder Zugang sieht alle Projekte. "
    "Die Tabelle projekt_zugang wird von keiner Zeile Code gelesen."
)


def auflisten(con: sqlite3.Connection) -> list[dict]:
    """Alle Zugänge mit Name, Organisation, Rolle, Datum und Projektzahl.

    Ohne den Token. Eine Liste, die Geheimnisse zeigt, wird nicht gezeigt, wenn
    jemand zusieht — also taugt sie nicht als Übersicht.
    """
    return [
        dict(z) for z in con.execute(
            "SELECT z.id, z.name, z.organisation, z.rolle, z.angelegt_am, "
            "       (SELECT COUNT(*) FROM projekt p WHERE p.eigentuemer_id = z.id) "
            "           AS projekte "
            "FROM zugang z ORDER BY z.id"
        )
    ]
