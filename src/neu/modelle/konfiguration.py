"""
konfiguration.py — was gerade eingestellt ist

Von Schlüsseln steht hier nur, ob sie gesetzt sind — nie ihr Wert.
"""

from pydantic import BaseModel, Field


class AnbieterLage(BaseModel):
    """Was für einen Anbieter eingestellt ist. Nie ein Schlüssel, nie ein Token."""

    anbieter: str | None = Field(description="null heißt: nicht gesetzt")
    bekannt: bool = Field(description="steht im Wertevorrat")
    modell: str | None = Field(
        description="Beim Embedding: das Modell für Themen und Zuordnung"
    )
    modell_akteure: str | None = Field(
        description="Nur beim Embedding: das Modell fürs Zusammenführen von "
                    "Akteuren. Bei 'local' ein anderes als modell; beim "
                    "Sprachmodell immer null.",
    )
    modelle: dict[str, str] = Field(
        default_factory=dict,
        description="Aufgabe → Modell, so wie es tatsächlich benutzt wird. "
                    "Beim Sprachmodell taxonomie/zusammenfassungen/chat, beim "
                    "Embedding themen/akteure. Wo kein eigenes Modell "
                    "eingetragen ist, steht hier die Vorgabe — aufgelöst, "
                    "damit die Fläche die Vorrangregel nicht nachbauen muss.",
    )
    schluessel_name: str | None = Field(
        description="Welche Variable gebraucht wird; null bei lokalen Anbietern"
    )
    schluessel_vorhanden: bool | None = Field(
        description="Ob sie gesetzt ist — nicht ihr Wert. null: wird keine gebraucht"
    )
    einsatzbereit: bool
    hinweis: str | None = Field(default=None, description="Was fehlt, in einem Satz")


class KonfigurationAntwort(BaseModel):
    env_datei: str | None
    embedding: AnbieterLage
    llm: AnbieterLage
    schwelle_akteure: float | None = Field(
        description="Ab hier werden Akteure zusammengeführt; hängt am Modell"
    )
    band_akteure: tuple[float, float] | None = Field(
        description="Der Streifen darunter, aus dem Vorschläge kommen"
    )
    schwellen_kategorien: dict[str, float]
    ollama_frist_sekunden: int | None = Field(
        description="Frist je Modellaufruf; null, wenn Ollama nicht aktiv ist"
    )
