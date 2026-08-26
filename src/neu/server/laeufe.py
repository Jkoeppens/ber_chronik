"""
laeufe.py — der Stand eines Schritts

Eine Route für alle Schritte: jeder lange Lauf gibt 202 mit einer lauf_id
zurück, und der Stand kommt von hier. Deshalb gehört sie keinem Schritt.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.neu import laeufe
from src.neu.db import verbindung
from src.neu.laeufe import LaufFehler
from src.neu.modelle import LaufStand
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.get("/api/lauf/{lauf_id}", response_model=LaufStand, responses=FEHLER_ANTWORTEN)
def lauf_stand(lauf_id: int) -> LaufStand:
    """Der Stand eines Schritts — so oft abfragbar, wie man mag.

    Kein Strom, keine Sentinels: der Fortschritt steht in der lauf-Zeile und
    überlebt eine abgerissene Verbindung wie einen neu geladenen Reiter.
    """
    con = verbindung()
    try:
        return LaufStand(**laeufe.stand(con, lauf_id))
    except LaufFehler as exc:
        raise HTTPException(status_code=404, detail=(exc.code, str(exc)))
    finally:
        con.close()
