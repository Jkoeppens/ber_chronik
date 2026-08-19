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

# Die drei Quellformate aus CLAUDE.md.
Quellformat = Literal["literaturexzerpt", "presseexzerpt", "pressesammlung"]


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
    oeffentlich: bool
    dropbox_ordner: str | None = None
    # dropbox_token wird bewusst nicht ausgeliefert.


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
    anzahl_perioden: int
    jahr_von: int | None
    jahr_bis: int | None
    hat_export: bool
    laeufe: list[Lauf] = Field(description="Die letzten Läufe, neueste zuerst")



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


# ── Ingest ────────────────────────────────────────────────────────────────────

class QuelleAnlegen(BaseModel):
    """Rumpf von POST /api/projekt/{id}/quelle."""

    pfad: str = Field(description="Pfad unterhalb von data/raw/, z.B. 'Notizen.docx'")
    quellformat: Quellformat


Verfahren = Literal["bge", "llm"]
Umfang = Literal["offen", "alle", "auch_manuell"]


class KlassifizierenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/klassifizieren.

    Kein Umfang: zugeordnet wird immer alles, und Handkorrekturen bleiben
    unangetastet. Das ist eine Regel, keine Einstellung — sie zur Wahl zu
    stellen hieße, das Überschreiben von Handarbeit als gleichwertige
    Möglichkeit anzubieten.
    """

    verfahren: Verfahren = Field(default="bge", description="bge = lokal, llm = API")


class KlassifikationAntwort(BaseModel):
    projekt_id: str
    verfahren: Verfahren
    umfang: Umfang
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int
    anzahl_ohne_kategorie: int
    anzahl_je_konfidenz: dict[str, int]
    anzahl_je_kategorie: dict[str, int]


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


class Kategorie(BaseModel):
    """Ein Taxonomie-Vorschlag, wie kern.verfeinern ihn baut.

    Name und Beschreibung entstehen durch Aufteilen der Modellantwort am ersten
    '. '; fehlt der Punkt, bleibt description leer.
    """

    name: str
    description: str = Field(
        default="", description="Leer, wenn die Antwort keinen Satzteil dahinter hatte"
    )
    keywords: list[str] = Field(
        default_factory=list, description="Höchstens drei, aus den TF-IDF-Schlagworten"
    )


class TrajektorieRunde(BaseModel):
    """Was in einer LLM-Runde geschah — eine Zeile der Trajektorie.

    Die Schlüssel von label_sim, delta und titel sind Clusternummern als
    Zeichenketten: JSON kennt keine Zahlen als Schlüssel.
    """

    llm_runde: int
    km_iter: int
    aenderungsanteil: float
    eingefroren_gesamt: int
    neu_eingefroren: list[int]
    label_sim: dict[str, float | None] = Field(
        description="Je Cluster die Ähnlichkeit zum vorigen Label; null in Runde 1"
    )
    delta: dict[str, float | None] = Field(
        description="Je Cluster die Veränderung dieser Ähnlichkeit"
    )
    titel: dict[str, str]


class TaxonomieAntwort(BaseModel):
    projekt_id: str
    warm_start: bool
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    n_clusters: int
    kategorien: list[Kategorie]
    llm_runden: int
    fruehzeitig_beendet: bool
    eingefroren: list[int]
    in_tokens: int
    out_tokens: int
    kosten_usd: float
    embedding_modell: str
    llm_modell: str
    trajektorie: list[TrajektorieRunde]
    anzahl_zugeordnet: int = Field(
        description="Einheiten, die der Lauf zugeordnet hat — die Zuordnung "
                    "entsteht im Verfahren ohnehin und wird jetzt festgehalten"
    )
    anzahl_geschuetzt: int = Field(
        description="Handkorrekturen, die er nicht angefasst hat"
    )
    anzahl_je_kategorie: dict[str, int]


Praezision = Literal["tag", "monat", "jahr", "spanne", "keine"]
DatierungHerkunft = Literal["text", "ueberschrift", "frontmatter", "quellennotation",
                            "ereignis", "interpoliert", "manuell"]
DatierungUmfang = Literal["offen", "alle", "auch_manuell"]


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
        default_factory=list,
        description="z.B. Handkorrekturen, die auf eine nicht vorhandene Einheit zeigen",
    )


class DatierungRumpf(BaseModel):
    """Rumpf von PATCH /api/einheit/{id}/datierung."""

    jahr_von: int | None = Field(description="null bedeutet: undatierbar")
    jahr_bis: int | None = Field(default=None, description="nur bei einer Spanne")
    datum: str | None = Field(default=None, description="genauer als das Jahr, ISO")


class DatierungZeileAntwort(BaseModel):
    einheit_id: int
    datum: str | None
    jahr_von: int | None
    jahr_bis: int | None
    praezision: Praezision
    datierung_herkunft: str
    datierung_lauf_id: int | None


# ── Akteure ───────────────────────────────────────────────────────────────────

AkteurTyp = Literal["Person", "Organisation", "Ort", "Konzept"]
AkteurStatus = Literal["aktiv", "abgelehnt"]
AkteurHerkunft = Literal["gliner", "manuell"]
KandidatGrund = Literal["alias", "schreibweise", "aehnlichkeit"]


class AkteureErkennenRumpf(BaseModel):
    """Rumpf von POST /api/projekt/{id}/akteure/erkennen.

    Leer: der Lauf nimmt sich immer alles außer den Handkorrekturen.
    """


class AkteurErkennungAntwort(BaseModel):
    projekt_id: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    embedding_modell: str
    gliner_modell: str
    schwelle: float
    anzahl_einheiten: int
    anzahl_funde: int
    anzahl_vor_gruppierung: int
    anzahl_neu: int
    anzahl_manuell: int
    anzahl_abgelehnt: int
    anzahl_zuordnungen: int
    anzahl_einheiten_mit_akteur: int
    anzahl_je_typ: dict[str, int]
    anzahl_kandidaten_je_grund: dict[str, int]
    unbekannte_labels: dict[str, int] = Field(
        default_factory=dict,
        description="GLiNER-Label ohne Abbildung; die Funde bleiben ohne Typ",
    )
    verdraengt_von_manuell: list[str] = Field(
        default_factory=list,
        description="Funde, die auf einen von Hand gepflegten Namen fielen",
    )


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


# ── Läufe ─────────────────────────────────────────────────────────────────────

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


class LaufBegonnen(BaseModel):
    """Antwort auf das Anstoßen eines langen Schritts."""

    lauf_id: int
    projekt_id: str
    schritt: str
    status: str = Field(description="immer 'laeuft' — der Stand kommt aus GET /api/lauf/{id}")


# ── Kategorien ────────────────────────────────────────────────────────────────

KategorieHerkunft = Literal["vorschlag", "manuell"]


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


class KategorieEintrag(BaseModel):
    """Eine Zeile im Editor. Ohne id wird angelegt, mit id geändert.

    Ohne Vorgabewerte, damit die erzeugten TypeScript-Typen die Felder als
    vorhanden führen: der Editor schickt immer die ganze Zeile.
    """

    id: int | None
    name: str = Field(min_length=1)
    beschreibung: str
    schlagworte: list[str]


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


# ── Export ────────────────────────────────────────────────────────────────────

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
    anzahl_perioden: int
    anzahl_je_kategorie: dict[str, int]
    jahr_min: int | None = Field(description="MIN(einheit.jahr_von), abgeleitet")
    jahr_max: int | None = Field(description="MAX(einheit.jahr_bis), abgeleitet")
    zusammenfassungen: int


# ── Konfiguration ─────────────────────────────────────────────────────────────

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


# ── Dropbox ───────────────────────────────────────────────────────────────────

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
