"""
bestand.py — was auf dem Laufwerk liegt

Byteangaben und keine formatierten Zeichenketten: die Fläche formatiert, der
Server zählt. Wer '4,3 GB' liefert, kann nicht mehr sortieren und nicht mehr
addieren.
"""

from pydantic import BaseModel, Field


class BestandPosten(BaseModel):
    """Ein Eintrag im Überblick."""

    name: str = Field(description="Modellname, Projektkennung oder Dateiname")
    bytes: int
    dateien: int = Field(default=0, description="0 heißt: nicht nach Dateien gezählt")
    hinweis: str = ""


class VektorPosten(BaseModel):
    """Vektoren eines Modells im Zwischenspeicher."""

    modell: str
    bytes: int
    einheiten: int
    masse: int = Field(description="Dimensionen je Vektor")
    benutzt: bool = Field(
        description="True, wenn der eingestellte Anbieter dieses Modell nimmt"
    )


class BestandAntwort(BaseModel):
    """Der ganze Überblick über die Datenwurzel."""

    daten_wurzel: str
    platz_knapp: bool = Field(
        description="True, wenn weniger als 6 GB oder weniger als 10 % frei sind — "
                    "dann passt BAAI/bge-m3 (4,3 GB) nicht mehr dazu"
    )
    laufwerk_bytes: int
    laufwerk_frei: int
    laufwerk_belegt: int
    datenbank: BestandPosten
    modelle: list[BestandPosten]
    modelle_wurzel: str = Field(description="HF_HOME, oder der Vorgabeort")
    modelle_auf_datenwurzel: bool = Field(
        description="False heißt: die Gewichte überleben keinen Neustart"
    )
    rohdaten: list[BestandPosten]
    exporte: list[BestandPosten]
    vektoren: list[VektorPosten]
    gezaehlt_bytes: int = Field(
        description="Summe der Posten — nicht laufwerk_belegt, dort liegt auch Fremdes"
    )
    warnungen: list[str]


class ProjektBestandAntwort(BaseModel):
    """Was am Löschen eines Projekts hängt. Für die Rückfrage, vor dem Löschen."""

    projekt_id: str
    titel: str
    anzahl_einheiten: int
    anzahl_quellen: int
    rohdateien: list[BestandPosten]
    rohdateien_geteilt: list[BestandPosten] = Field(
        description="Von anderen Projekten mitbenutzt — bleiben liegen"
    )
    export: BestandPosten | None
    vektoren_bytes: int
    bytes_gesamt: int = Field(description="Was durch das Löschen tatsächlich frei wird")


class VektorenLoeschenRumpf(BaseModel):
    """Rumpf von POST /api/bestand/vektoren/loeschen.

    Das Modell im Rumpf und nicht im Pfad: 'BAAI/bge-m3' enthält einen
    Schrägstrich und wäre als Pfadsegment nur verkodiert übertragbar.
    """

    modell: str = Field(description="Genau wie in der Übersicht, z. B. BAAI/bge-m3")


class VektorenGeloescht(BaseModel):
    modell: str
    geloeschte_vektoren: int
    freigegebene_bytes: int
    hinweis: str
