"""
modelle.py — Antwortgestalten des Servers

Jede Antwort des Servers ist eines dieser Modelle. Auch Fehler: es gibt genau
eine Fehlergestalt, und alle Fehlerwege münden in sie — eigene Prüfungen,
HTTPException und die Parametervalidierung von FastAPI gleichermaßen.

Feldnamen folgen SCHEMA.md. Was in der Datenbank NULL sein darf, ist hier
optional; NULL heißt „nicht erhoben" und wird nicht zu einem Vorgabewert
geglättet.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Die Werte, die einheit.typ laut SCHEMA.md annimmt.
EinheitTyp = Literal["content", "heading", "bibliography", "meta"]


# ── Fehler ────────────────────────────────────────────────────────────────────

class Fehler(BaseModel):
    """Die eine Fehlergestalt."""

    code: str = Field(description="Maschinenlesbare Kennung, z.B. projekt_nicht_gefunden")
    meldung: str = Field(description="Erklärung für Menschen, deutsch")
    status: int = Field(description="HTTP-Status, wiederholt für Clients ohne Zugriff darauf")


class FehlerAntwort(BaseModel):
    fehler: Fehler


# ── Projekt ───────────────────────────────────────────────────────────────────

class Projekt(BaseModel):
    id: str
    titel: str
    eigentuemer_id: int
    angelegt_am: str
    jahr_von: int | None = None
    jahr_bis: int | None = None
    oeffentlich: bool
    dropbox_ordner: str | None = None
    # dropbox_token wird bewusst nicht ausgeliefert.


class ProjektListe(BaseModel):
    anzahl: int
    projekte: list[Projekt]


# ── Einheit ───────────────────────────────────────────────────────────────────

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

    # Ergebnis der Klassifikation
    kategorie_id: int | None = None
    konfidenz: str | None = None


class EinheitenListe(BaseModel):
    projekt_id: str
    anzahl: int
    typ_filter: EinheitTyp | None = Field(
        default=None, description="Der angewandte Filter, oder null für ungefiltert"
    )
    einheiten: list[Einheit]


# ── Ingest ────────────────────────────────────────────────────────────────────

Quellformat = Literal["literaturexzerpt", "presseexzerpt", "pressesammlung"]


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
    anzahl_einheiten: int
    anzahl_je_typ: dict[str, int]
