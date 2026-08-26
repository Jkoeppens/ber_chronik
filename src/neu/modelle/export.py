"""
export.py — was der Export erzeugt hat

Die Zahlen sind das Ergebnis, nicht die Vorgabe: der Zeitraum in
project_meta.json ist MIN/MAX über die Einheiten, keine gespeicherte Angabe.
"""

from pydantic import BaseModel, Field


class ExportierenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/exportieren."""

    zusammenfassungen: bool = Field(
        default=False,
        description=("entities_summary.json aus akteur.zusammenfassung schreiben. "
                     "Vorgabe aus — gilt auf jedem Weg gleich"),
    )


class ExportAntwort(BaseModel):
    projekt_id: str
    ziel: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    dateien: list[str]
    anzahl_einheiten: int
    anzahl_mit_datum: int
    anzahl_ohne_datum: int = Field(
        description="Fehlen auf der Zeitachse — die Zahl steht hier, nicht nur im Bild"
    )
    anzahl_ohne_kategorie: int
    anzahl_mit_akteur: int
    anzahl_akteure: int
    anzahl_knoten: int
    anzahl_kanten: int
    anzahl_je_kategorie: dict[str, int]
    jahr_min: int | None = Field(description="MIN(einheit.jahr_von), abgeleitet")
    jahr_max: int | None = Field(description="MAX(einheit.jahr_bis), abgeleitet")
    zusammenfassungen: int
