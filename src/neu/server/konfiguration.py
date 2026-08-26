"""
konfiguration.py — was gerade eingestellt ist

Eine Route. Sie steht hier und nicht bei den Projekten, weil sie kein Projekt
kennt: sie beantwortet, womit gerechnet würde, nicht was gerechnet wurde.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.neu.konfiguration import lage
from src.neu.modelle import KonfigurationAntwort
from src.neu.server.gemeinsam import FEHLER_ANTWORTEN

# Ohne tags: sie stünden in /openapi.json und damit in api-typen.ts —
# die Aufteilung soll dort nichts verändern.
router = APIRouter()


@router.get(
    "/api/konfiguration",
    response_model=KonfigurationAntwort,
    responses=FEHLER_ANTWORTEN,
)
def konfiguration() -> KonfigurationAntwort:
    """Was gerade eingestellt ist: Anbieter, Modelle, Schwellen.

    Dieselbe Auskunft wie beim Hochfahren, nur abrufbar. Von Schlüsseln steht
    hier nur, ob sie gesetzt sind — nie ihr Wert, und keine Projekt-Token.
    """
    z = lage()
    return KonfigurationAntwort(
        env_datei=z.env_datei,
        embedding=vars(z.embedding),
        llm=vars(z.llm),
        schwelle_akteure=z.schwelle_akteure,
        band_akteure=z.band_akteure,
        schwellen_kategorien=z.schwellen_kategorien,
        ollama_frist_sekunden=z.ollama_frist_sekunden,
    )
