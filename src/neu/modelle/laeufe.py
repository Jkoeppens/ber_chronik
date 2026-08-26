"""
laeufe.py — der Stand eines langen Schritts

Zwei Modelle für alle Schritte: was ein Lauf beim Anstoßen zurückgibt und was
beim Nachfragen. Der Fortschritt steht in lauf.parameter und ist deshalb ein
offenes Wörterbuch, kein festes Feld je Schritt.
"""

from pydantic import BaseModel, Field


class LaufBegonnen(BaseModel):
    """Antwort auf das Anstoßen eines langen Schritts."""

    lauf_id: int
    projekt_id: str
    schritt: str
    status: str = Field(description="immer 'laeuft' — der Stand kommt aus GET /api/lauf/{id}")


class LaufStand(BaseModel):
    """Der Stand eines Schritts — abgefragt, nicht gestreamt.

    Der Fortschritt steht in der lauf-Zeile: reißt die Verbindung, ist er
    trotzdem da, und ein neu geladener Reiter sieht denselben Lauf.
    """

    id: int
    projekt_id: str
    schritt: str
    status: str = Field(description="laeuft | erfolg | fehler")
    begonnen_am: str
    beendet_am: str | None
    parameter: dict = Field(
        description="Was der Schritt bisher gemeldet hat; am Ende sein Ergebnis"
    )
    fehler: str | None
