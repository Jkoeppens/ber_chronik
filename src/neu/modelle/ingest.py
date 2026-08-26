"""
ingest.py — Quellen einlesen und die Dropbox-Anbindung

Der Quellentyp bestimmt, wie eingelesen wird — deshalb steht Quellformat hier
und nirgends sonst als Feld eines Rumpfes.
"""

from pydantic import BaseModel, Field

from src.neu.vokabular import Quellformat

__all_vokabular__ = (Quellformat,)


class QuelleAnlegen(BaseModel):
    """Rumpf von POST /api/projekt/{id}/quelle."""

    pfad: str = Field(description="Pfad unterhalb von data/raw/, z.B. 'Notizen.docx'")
    quellformat: Quellformat


class IngestAntwort(BaseModel):
    projekt_id: str
    quelle_id: str
    quellformat: Quellformat
    pfad: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int = Field(description="Stand der Quelle nach dem Lauf")
    anzahl_je_typ: dict[str, int]
    # Ohne Vorgabewerte: der Dienst liefert sie immer, und ein optionales Feld
    # zwingt jeden Aufrufer zu einer Prüfung, die nie zutrifft.
    fortgesetzt: bool = Field(description="Ob eine vorhandene Quelle fortgeführt wurde")
    anzahl_neu: int
    anzahl_uebersprungen: int = Field(
        description="Dateien, die schon in der Quelle standen"
    )
    geaenderte_dateien: list[str] = Field(
        description="Bekannte Dateien mit geändertem Inhalt — gemeldet, nicht angefasst"
    )
    hinweise: list[str]


class DropboxStand(BaseModel):
    """Der Verbindungsstand eines Projekts — aus projekt.dropbox_token."""

    projekt_id: str
    verbunden: bool = Field(description="Ob ein refresh_token hinterlegt ist")
    ordner: str | None
    anbieter_bereit: bool = Field(
        description="Ob SDK und DROPBOX_APP_KEY/SECRET vorliegen"
    )


class DropboxOrdnerRumpf(BaseModel):
    """Rumpf von PUT /api/projekt/{id}/dropbox."""

    ordner: str = Field(min_length=1, description="Pfad im App-Ordner, z.B. /Dropbox_test1")


class DropboxOrdnerListe(BaseModel):
    """Was im App-Ordner liegt — zur Auswahl, statt zum Auswendiglernen."""

    projekt_id: str
    ordner: list[str] = Field(description="Pfade wie /Dropbox_test1")


class AnmeldungBeginn(BaseModel):
    auth_url: str = Field(description="Dorthin schickt man den Browser")
    csrf: str
    projekt_id: str | None
