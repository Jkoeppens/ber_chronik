"""
akteure.py — erkennen, pflegen, verschmelzen, markieren

Fünfzehn Modelle, weil der Schritt fünfzehn Gestalten hat. Was auffällt: es
gibt kein Löschmodell. Ablehnen ist die Bedienung, und sie überlebt einen
Neulauf — Löschen täte das nicht.
"""

from pydantic import BaseModel, Field

from src.neu.vokabular import AkteurHerkunft, AkteurStatus, AkteurTyp, KandidatGrund

__all_vokabular__ = (AkteurHerkunft, AkteurStatus, AkteurTyp, KandidatGrund)


class AkteureErkennenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/akteure/erkennen.

    Leer: der Lauf nimmt sich immer alles außer den Handkorrekturen.
    """


class AkteurAendernRumpf(BaseModel):
    """Rumpf von PATCH /api/akteur/{id}. Nur was gesetzt ist, wird geändert."""

    normalform: str | None = None
    typ: AkteurTyp | None = Field(
        default=None, description="null lässt den Typ, wie er ist"
    )
    status: AkteurStatus | None = None
    aliase: list[str] | None = Field(
        default=None, description="Ersetzt die Aliasliste vollständig"
    )


class AkteurAntwort(BaseModel):
    id: int
    projekt_id: str
    normalform: str
    typ: AkteurTyp | None
    status: AkteurStatus
    herkunft: AkteurHerkunft
    aliase: list[str]
    anzahl_fundstellen: int
    aufgeloeste_akteure: list[int] = Field(
        default_factory=list, description="Beim Verschmelzen entfallene Kennungen"
    )


class VerschmelzenRumpf(BaseModel):
    """Rumpf von POST /api/akteure/verschmelzen."""

    ids: list[int] = Field(min_length=2, description="Mindestens zwei Akteure")
    behalten_id: int = Field(description="Dessen Normalform bleibt stehen")


class Namenstreffer(BaseModel):
    """Wie oft dieser Name die Fundstelle war."""

    name: str
    ist_normalform: bool
    anzahl: int


class AkteurZeile(BaseModel):
    """Ein Akteur in der Liste, mit allem, was die Fläche zeigt."""

    id: int
    projekt_id: str
    normalform: str
    typ: AkteurTyp | None
    status: AkteurStatus
    herkunft: AkteurHerkunft
    aliase: list[str]
    anzahl_fundstellen: int
    namen: list[Namenstreffer] = Field(
        description="Normalform und Aliase mit ihren Trefferzahlen, häufigster zuerst"
    )
    anteil_normalform: float | None = Field(
        description="Anteil der Fundstellen auf den eigenen Namen; null ohne Fundstellen"
    )
    ist_klumpen: bool = Field(
        description="Viele Aliase und der eigene Name trifft fast nie — "
                    "der Eintrag heißt nach etwas, das er kaum ist"
    )


class AkteurListe(BaseModel):
    projekt_id: str
    anzahl: int
    anzahl_manuell: int
    anzahl_abgelehnt: int
    anzahl_klumpen: int
    akteure: list[AkteurZeile]


class AkteurAnlegenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/akteure."""

    normalform: str = Field(min_length=1)
    typ: AkteurTyp | None = None
    aliase: list[str] = Field(default_factory=list)


class HerausloesenRumpf(BaseModel):
    """Rumpf von POST /api/akteur/{id}/herausloesen."""

    alias: str = Field(min_length=1, description="Wird Normalform des neuen Akteurs")
    typ: AkteurTyp | None = Field(
        default=None, description="null übernimmt den Typ des alten"
    )


class HerausgeloestAntwort(BaseModel):
    quelle: AkteurAntwort = Field(description="Der Akteur, aus dem gelöst wurde")
    neu: AkteurAntwort


class FundstelleGeloescht(BaseModel):
    fundstelle_id: int
    akteur_id: int
    einheit_id: int
    normalform: str
    wortlaut: str = Field(description="Was an der Stelle stand")
    anzahl_fundstellen: int = Field(description="Die des Akteurs, danach")


class Markierung(BaseModel):
    """Eine Fundstelle im Text einer Einheit — gelesen, nicht gesucht."""

    id: int
    akteur_id: int
    start: int
    ende: int
    normalform: str
    typ: AkteurTyp | None


class MarkierungenListe(BaseModel):
    projekt_id: str
    anzahl: int
    je_einheit: dict[str, list[Markierung]] = Field(
        description="Schlüssel ist die einheit_id als Text"
    )


class Kandidat(BaseModel):
    id: int
    akteur_a_id: int
    akteur_a: str
    akteur_b_id: int
    akteur_b: str
    grund: KandidatGrund
    mass: float | None = Field(
        description="Kosinusähnlichkeit bzw. Editierabstand; null bei 'alias'"
    )
    berechnet_am: str


class KandidatenListe(BaseModel):
    projekt_id: str
    anzahl: int
    kandidaten: list[Kandidat]
