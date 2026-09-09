"""
chat.py — Fragen an ein Projekt, als Ereignisstrom

Der einzige Endpunkt im ganzen Server, der streamt. Alles andere ist entweder
sofort fertig oder ein Lauf mit 202 und lauf_id — beides passt hier nicht: eine
Antwort, die man beim Entstehen liest, ist kein Hintergrundlauf mit
Fortschrittszahl, und auf sie zu warten hieße, eine Minute lang nichts zu
sehen.

Das Protokoll: Server-Sent Events mit benannten Ereignissen.

    event: stueck
    data: {"text": "…"}

    event: fertig
    data: {"quellen": [...], "stichwoerter": [...], "absaetze": 20,
           "wege": ["stichwoerter", "bedeutung"], "modell": "…"}

    event: abbruch
    data: {"code": "…", "meldung": "…"}

Die Art des Ereignisses steht in der event-Zeile, nie im Text. Der alte Server
schob __done__, __error__ und __link__ mitten in den Textstrom und ließ den
Browser sie wieder herausklauben; ein Absatz, der zufällig so anfing, brachte
den Leser durcheinander. Hier ist der Text nur Text.

'abbruch' und nicht 'fehler': ab dem ersten Stück ist die HTTP-Antwort
unterwegs und ein Status nicht mehr zu setzen. Was vorher schiefgeht — kein
Projekt, leere Frage — kommt weiterhin als gewöhnlicher Fehler mit Status und
der einen Fehlergestalt.
"""

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.neu.chat.dienst import Abbruch, Fertig, Stueck, antworten
from src.neu.db import verbindung
from src.neu.modelle import ChatRumpf
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN, projekt_muss_es_geben

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts.
router = APIRouter()


def _ereignis(art: str, inhalt: dict) -> str:
    """Eine SSE-Nachricht. json.dumps schützt die Zeilenstruktur.

    Ein Zeilenumbruch im Antworttext würde die data-Zeile sonst zerreißen und
    den Rest als eigenes Ereignis erscheinen lassen — genau die Klasse Fehler,
    gegen die die benannten Ereignisse hier antreten.
    """
    return f"event: {art}\ndata: {json.dumps(inhalt, ensure_ascii=False)}\n\n"


@router.post(
    "/api/projekt/{projekt_id}/chat",
    responses=FEHLER_ANTWORTEN,
    response_class=StreamingResponse,
)
def chat(projekt_id: str, rumpf: ChatRumpf) -> StreamingResponse:
    """Beantwortet eine Frage aus den Absätzen des Projekts.

    Gesucht wird zweifach — nach Stichwörtern und nach Bedeutung — und beides
    per Reciprocal Rank Fusion zusammengelegt; die besten 20 Absätze gehen in
    den Prompt. Das Abschlussereignis nennt unter `quellen` die Anker, die im
    Antworttext tatsächlich vorkommen, nicht die angebotenen.

    Antwortet als text/event-stream. Die Ereignisse stehen oben im Modul.
    """
    con = verbindung()
    projekt_muss_es_geben(con, projekt_id)

    def strom() -> Iterator[str]:
        try:
            for ereignis in antworten(con, projekt_id, rumpf.frage):
                if isinstance(ereignis, Stueck):
                    yield _ereignis("stueck", {"text": ereignis.text})
                elif isinstance(ereignis, Fertig):
                    yield _ereignis("fertig", {
                        "quellen": ereignis.quellen,
                        "stichwoerter": ereignis.stichwoerter,
                        "absaetze": ereignis.absaetze,
                        "wege": ereignis.wege,
                        "modell": ereignis.modell,
                    })
                elif isinstance(ereignis, Abbruch):
                    yield _ereignis("abbruch", {"code": ereignis.code,
                                                "meldung": ereignis.meldung})
        finally:
            con.close()

    return StreamingResponse(
        strom(),
        media_type="text/event-stream",
        # Ohne diese zwei sammelt ein Proxy die Antwort und liefert sie am
        # Stück — dann war das Streamen umsonst.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
