"""
zugang.py — ein Riegel vor allem, mit HTTP Basic

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
import os
import secrets

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


class Riegel:
    """Lässt eine Anfrage durch oder antwortet mit 401. Nichts dazwischen."""

    def __init__(self, app, geheimnis: str, ohne_riegel: tuple[str, ...] = OHNE_RIEGEL):
        self.app = app
        self._geheimnis = geheimnis
        self._ohne_riegel = frozenset(ohne_riegel)

    def _stimmt(self, angeboten: str | None) -> bool:
        """Vergleich in gleichbleibender Zeit.

        compare_digest und nicht ==: ein Vergleich, der beim ersten
        unterschiedlichen Zeichen abbricht, verrät über die Dauer, wie viele
        Zeichen gestimmt haben.
        """
        if angeboten is None:
            return False
        return secrets.compare_digest(
            angeboten.encode("utf-8"), self._geheimnis.encode("utf-8")
        )

    async def __call__(self, scope, receive, send):
        art = scope.get("type")
        if art == "lifespan":
            return await self.app(scope, receive, send)
        if art == "http" and scope.get("path") in self._ohne_riegel:
            return await self.app(scope, receive, send)
        if self._stimmt(_angebotenes(scope.get("headers") or [])):
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
