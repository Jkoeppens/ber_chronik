"""
themen.py — Taxonomie, Kategorien, Zuordnung

Ein Modul, weil es ein Schritt ist: Kategorien und die Zuordnung darauf sind
nicht zu trennen.
"""

from pydantic import BaseModel, Field

from src.neu.vokabular import Umfang, Verfahren
from src.neu.vokabular import VorschlagHerkunft as KategorieHerkunft

__all_vokabular__ = (Umfang, KategorieHerkunft, Verfahren)


class KlassifizierenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/klassifizieren.

    Kein Umfang: zugeordnet wird immer alles, und Handkorrekturen bleiben
    unangetastet. Das ist eine Regel, keine Einstellung — sie zur Wahl zu
    stellen hieße, das Überschreiben von Handarbeit als gleichwertige
    Möglichkeit anzubieten.
    """

    verfahren: Verfahren = Field(
        default="vektoren",
        description="vektoren = Ähnlichkeit zum Einbettungsmodell, llm = Sprachmodell",
    )


class ZuordnungRumpf(BaseModel):
    """Rumpf von PATCH /api/einheit/{id}/kategorie."""

    kategorie_id: int | None = Field(
        description="Kennung der Kategorie, oder null für 'keine Kategorie'"
    )


class ZuordnungAntwort(BaseModel):
    einheit_id: int
    kategorie_id: int | None
    konfidenz: str | None
    kategorie_herkunft: str
    kategorie_lauf_id: int | None


class TaxonomieVorschlagRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/taxonomie/vorschlagen."""

    warm_start: bool = Field(
        default=False,
        description=("false = neu vorschlagen, ohne Ausgangspunkt; "
                     "true = die vorhandenen Kategorien verfeinern"),
    )
    n_clusters: int | None = Field(
        default=None, ge=2, le=20,
        description="Anzahl Kategorien; nur ohne warm_start erlaubt (Vorgabe 7)",
    )


class KategorieZeile(BaseModel):
    id: int
    projekt_id: str
    name: str
    beschreibung: str
    schlagworte: list[str]
    herkunft: KategorieHerkunft = Field(
        description="vorschlag = aus einem Lauf, manuell = von Hand angefasst"
    )
    anzahl_einheiten: int = Field(description="Wie viele Einheiten darauf zeigen")


class KategorienListe(BaseModel):
    projekt_id: str
    anzahl: int
    kategorien: list[KategorieZeile]
    anzahl_ohne_kategorie: int
    anzahl_manuell_zugeordnet: int = Field(
        description="Handkorrekturen — vor jedem Neulauf sicher"
    )
    einheiten_ohne_vektor: int | None = Field(
        description="Wie viele Einheiten beim nächsten Zuordnen erst embeddet "
                    "werden müssen. 0 heißt: das Speichern ist in etwa einer "
                    "Sekunde durch. null, wenn kein Embedding-Anbieter steht."
    )
    dauer_schaetzung_sekunden: int | None = Field(
        default=None,
        description="Wie lange das Einbetten dieser Einheiten etwa dauert. "
                    "Gerechnet aus dem gemessenen Tempo des Modells "
                    "(anbieter.toml). null, wenn nichts einzubetten ist oder "
                    "für das Modell keine Messung vorliegt — dann kündigt die "
                    "Fläche keine Dauer an.",
    )


class KategorieEintrag(BaseModel):
    """Eine Zeile im Editor. Ohne id wird angelegt, mit id geändert.

    Ohne Vorgabewerte, damit die erzeugten TypeScript-Typen die Felder als
    vorhanden führen: der Editor schickt immer die ganze Zeile.
    """

    id: int | None
    name: str = Field(min_length=1)
    beschreibung: str
    schlagworte: list[str]


class KategorienGespeichert(BaseModel):
    """Antwort auf PUT /api/projekt/{id}/kategorien.

    Kein LaufBegonnen, weil es nicht immer einen Lauf gibt: wer alle Kategorien
    entfernt, hat nichts, wogegen zugeordnet werden könnte. Dann ist lauf_id
    null und das Speichern ist fertig — vorher scheiterte an dieser Stelle ein
    Lauf mit 'keine_taxonomie', obwohl das Löschen gelungen war.
    """

    projekt_id: str
    anzahl: int = Field(description="Kategorien nach dem Speichern")
    angelegt: int
    geaendert: int
    geloescht: int
    lauf_id: int | None = Field(
        description="Der Zuordnungslauf; null, wenn es nichts zuzuordnen gibt"
    )


class KategorienSpeichernRumpf(BaseModel):
    """Rumpf von PUT /api/projekt/{id}/kategorien.

    Die ganze Liste auf einmal: was fehlt, wird gelöscht. Danach wird neu
    zugeordnet — das ist der Moment, in dem Beschreibungen und Zuordnung wieder
    zusammenpassen.
    """

    kategorien: list[KategorieEintrag]


class KategorieRumpf(BaseModel):
    """Rumpf zum Anlegen und Ändern. Nur was gesetzt ist, wird geändert."""

    name: str | None = Field(default=None, min_length=1)
    beschreibung: str | None = None
    schlagworte: list[str] | None = None
