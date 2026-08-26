"""
projekte.py — Projekt, Kennzahlen, Einheiten

Ein Projekt und was in ihm steckt. Die Einheiten stehen hier und nicht beim
Ingest, weil sie gelesen werden, wo ein Projekt gelesen wird — der Ingest legt
sie an und sieht sie danach nicht wieder.
"""

from pydantic import BaseModel, Field

from src.neu.vokabular import EinheitTyp, Praezision, Quellformat

__all_vokabular__ = (EinheitTyp, Praezision, Quellformat)


class Projekt(BaseModel):
    id: str
    titel: str
    eigentuemer_id: int
    angelegt_am: str
    oeffentlich: bool
    dropbox_ordner: str | None = None


class ProjektZeile(Projekt):
    """Ein Projekt mit den Zahlen, die die Übersicht zeigt.

    Alle Werte sind gerechnet, keiner steht in einer Konfigurationsdatei:
    anzahl_einheiten ist COUNT(*), der Zeitraum MIN/MAX über die Einheiten.
    """

    quellformate: list[Quellformat] = Field(
        description="Je Quelle eines; meist genau eines. Leer, solange keine Quelle da ist"
    )
    anzahl_quellen: int
    anzahl_einheiten: int = Field(description="content-Einheiten, COUNT(*)")
    jahr_von: int | None = Field(description="MIN(einheit.jahr_von), abgeleitet")
    jahr_bis: int | None = Field(description="MAX(einheit.jahr_bis), abgeleitet")
    hat_export: bool = Field(
        description="Ob exploration/data.json vorliegt — nur dann führt der Viz-Link irgendwohin"
    )
    export_am: str | None = Field(
        description="Zeitstempel der Exportdatei; null, wenn keine da ist"
    )


class ProjektListe(BaseModel):
    anzahl: int
    projekte: list[ProjektZeile]


class ProjektAnlegenRumpf(BaseModel):
    """Rumpf von POST /api/projekte."""

    titel: str = Field(min_length=1, description="Anzeigename, z.B. 'Damaskus'")
    id: str | None = Field(
        default=None,
        description="Kennung; ohne Angabe aus dem Titel abgeleitet",
    )


class Lauf(BaseModel):
    id: int
    schritt: str
    status: str
    begonnen_am: str
    beendet_am: str | None


class Kennzahlen(BaseModel):
    """Was ein Projekt in der Datenbank stehen hat — alles gerechnet."""

    projekt_id: str
    titel: str
    quellformate: list[Quellformat]
    anzahl_quellen: int
    anzahl_einheiten: int
    anzahl_je_typ: dict[str, int]
    anzahl_datiert: int
    anzahl_ohne_datum: int
    anzahl_kategorien: int
    anzahl_klassifiziert: int
    anzahl_akteure: int
    anzahl_fundstellen: int
    jahr_von: int | None
    jahr_bis: int | None
    hat_export: bool
    export_am: str | None = Field(
        description="Zeitstempel der Exportdatei; null, wenn keine da ist"
    )
    laeufe: list[Lauf] = Field(description="Die letzten Läufe, neueste zuerst")


class Einheit(BaseModel):
    id: int
    quelle_id: str
    position: int
    typ: str
    text: str

    # Herkunft im Material
    publikation: str | None = None
    chronologie_gruppe: str | None = None
    publikationsdatum: str | None = None
    quellpfad: str | None = None
    url: str | None = None
    autor: str | None = None
    kurzfassung: str | None = None
    seite: int | None = None
    ebene: int | None = None
    ist_zitat: bool | None = None

    # Ergebnis der Datierung
    datum: str | None = None
    jahr_von: int | None = None
    jahr_bis: int | None = None
    praezision: str | None = None
    datierung_herkunft: str | None = None
    datierung_lauf_id: int | None = None

    # Ergebnis der Klassifikation
    kategorie_id: int | None = None
    konfidenz: str | None = None
    kategorie_herkunft: str | None = Field(
        default=None,
        description="automatisch | manuell. NULL = nie zugeordnet; "
                    "manuell ist gegen jeden Neulauf geschützt",
    )


class EinheitenListe(BaseModel):
    projekt_id: str
    anzahl: int
    typ_filter: EinheitTyp | None = Field(
        default=None, description="Der angewandte Filter, oder null für ungefiltert"
    )
    einheiten: list[Einheit]
