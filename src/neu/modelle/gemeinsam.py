"""
gemeinsam.py — die eine Fehlergestalt

Alle Fehlerwege münden hierher: eigene Prüfungen, HTTPException und die
Parametervalidierung von FastAPI gleichermaßen. Deshalb steht sie nicht bei
einem Schritt, sondern für sich.
"""

from pydantic import BaseModel, Field


class Fehler(BaseModel):
    """Die eine Fehlergestalt."""

    code: str = Field(description="Maschinenlesbare Kennung, z.B. projekt_nicht_gefunden")
    meldung: str = Field(description="Erklärung für Menschen, deutsch")
    status: int = Field(description="HTTP-Status, wiederholt für Clients ohne Zugriff darauf")


class FehlerAntwort(BaseModel):
    fehler: Fehler
