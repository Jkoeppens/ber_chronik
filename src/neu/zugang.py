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

WARUM BASIC UND KEIN ANMELDEFORMULAR. Es deckt in einem Zug alles ab — die
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
import json
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass

#: Die Variable, die das Geheimnis trägt. Als Konstante, weil die Meldung beim
#: Start sie nennen muss und ein Tippfehler dort nicht auffiele.
VARIABLE = "ZUGANG_PASSWORT"

#: Was der Browser im Anmeldefenster zeigt.
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
OHNE_RIEGEL: tuple[str, ...] = ()

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


class Riegel:
    """Lässt eine Anfrage durch oder antwortet mit 401. Nichts dazwischen."""

    def __init__(self, app, geheimnis: str, ohne_riegel: tuple[str, ...] = OHNE_RIEGEL):
        self.app = app
        self._geheimnis = geheimnis
        self._ohne_riegel = frozenset(ohne_riegel)
        #: Wer schon einmal gemeldet wurde. Ein Set und keine Zählung: es geht
        #: um 'ist genannt', nicht um 'wie oft'.
        self._gemeldet: set[tuple[int | None, str]] = set()

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
        if art == "http" and scope.get("path") in self._ohne_riegel:
            return await self.app(scope, receive, send)
        wer = self._wer(_angebotenes(scope.get("headers") or []))
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
        await self._abweisen(send)

    async def _abweisen(self, send) -> None:
        """401 in der einen Fehlergestalt des Servers.

        Dieselbe Gestalt wie jeder andere Fehler ({"fehler": {...}}), damit die
        Fläche nicht zwei Formen auseinanderhalten muss. WWW-Authenticate ist
        das Entscheidende: erst damit fragt der Browser von selbst.
        """
        koerper = json.dumps(
            {"fehler": {
                "code": "zugang_verweigert",
                "meldung": "Dieser Dienst verlangt Benutzername und Passwort.",
                "status": 401,
            }},
            ensure_ascii=False,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(koerper)).encode()),
                (b"www-authenticate",
                 f'Basic realm="{BEREICH}", charset="UTF-8"'.encode()),
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
