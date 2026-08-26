"""
datierung.py — datieren, korrigieren, den Wortlaut ändern

Praezision sagt, wie fein die Angabe ist; DatierungHerkunft, wie sie zustande
kam. Zwei Felder, weil die Vorlage beides in einem vermischte und dann nicht
mehr sagen konnte, ob 'exact' hieß 'auf den Tag' oder 'im Text gefunden'.
"""

from pydantic import BaseModel, Field

from src.neu.vokabular import DatierungHerkunft, Praezision, Umfang

# Derselbe Vorrat wie Umfang — der eigene Name bleibt, weil er in DatierenRumpf
# steht und in der erzeugten api-typen.ts auftaucht.
DatierungUmfang = Umfang

__all_vokabular__ = (DatierungHerkunft, Praezision)


class DatierenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/datieren."""

    umfang: DatierungUmfang = Field(
        default="offen",
        description=("offen = nur nie datierte; alle = auch maschinelle erneut, "
                     "Handkorrekturen bleiben; auch_manuell = auch diese"),
    )


class DatierungAntwort(BaseModel):
    projekt_id: str
    quellformat: str
    umfang: DatierungUmfang
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int
    anzahl_datiert: int
    anzahl_ohne_datum: int
    anzahl_anker: int
    anzahl_je_praezision: dict[str, int]
    anzahl_je_herkunft: dict[str, int]
    warnungen: list[str] = Field(
        description="z.B. Handkorrekturen, die auf eine nicht vorhandene Einheit zeigen"
    )


class DatierungRumpf(BaseModel):
    """Rumpf von PATCH /api/einheit/{id}/datierung.

    Zwei Felder mit freier Genauigkeit statt einer Vorschrift, wie genau man
    sein darf: '2012', '2012-07' oder '2012-07-30'. Die Präzision folgt aus
    dem, was dasteht, und wird nicht mitgeschickt.
    """

    datum_von: str | None = Field(
        description="'2012' | '2012-07' | '2012-07-30'. null oder leer: undatierbar"
    )
    datum_bis: str | None = Field(
        default=None, description="Leer heißt Zeitpunkt statt Zeitraum"
    )
    begruendung: str = Field(
        default="",
        description="Warum. Landet in anker.fundstelle — dort, wo bei einem "
                    "maschinellen Anker die auslösende Zeichenfolge steht",
    )


class DatierungZeileAntwort(BaseModel):
    einheit_id: int
    datum: str | None
    jahr_von: int | None
    jahr_bis: int | None
    praezision: Praezision
    datierung_herkunft: str
    datierung_lauf_id: int | None
    begruendung: str


class TextRumpf(BaseModel):
    """Rumpf von PATCH /api/einheit/{id}/text."""

    text: str = Field(min_length=1)


class TextAntwort(BaseModel):
    einheit_id: int
    projekt_id: str
    text: str
    geaendert: bool
    fundstellen_geloescht: int = Field(
        description="Akteursfundstellen dieser Einheit — gelöscht, nicht "
                    "umgerechnet. Veraltete Zeichenpositionen markieren sonst "
                    "still die falschen Wörter"
    )
    datierung_neu: int = Field(
        description="Einheiten des Projekts, deren Datierung sich dadurch "
                    "geändert hat — die Nachbarn hängen über die Interpolation mit dran"
    )


class Anker(BaseModel):
    jahr: int | None
    herkunft: str
    fundstelle: str = Field(
        description="Was den Anker ausgelöst hat, bei 'manuell' die Begründung"
    )


class Ausreisser(BaseModel):
    projekt_id: str
    unten: int | None = Field(description="Untere Grenze Q1 − 3·IQR; null, wenn nicht bestimmbar")
    oben: int | None
    einheiten: list[int]


class DatierungVerteilung(BaseModel):
    """Woher die Daten kommen. 'interpoliert' heißt geraten."""

    projekt_id: str
    anzahl: int
    je_herkunft: dict[str, int]
    je_praezision: dict[str, int]
    anzahl_interpoliert: int
    anzahl_manuell: int
    anzahl_undatiert: int
    ausreisser: Ausreisser
    anker: dict[str, list[Anker]] = Field(
        description="Die Belege je Einheit, Schlüssel ist die einheit_id als Text"
    )
