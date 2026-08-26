"""
modelle — Antwortgestalten des Servers

Jede Antwort des Servers ist eines dieser Modelle. Auch Fehler: es gibt genau
eine Fehlergestalt, und alle Fehlerwege münden in sie — eigene Prüfungen,
HTTPException und die Parametervalidierung von FastAPI gleichermaßen.

Feldnamen folgen SCHEMA.md. Was in der Datenbank NULL sein darf, ist hier
optional; NULL heißt „nicht erhoben" und wird nicht zu einem Vorgabewert
geglättet.

Ein Modul je Schritt, wie beim Server nebenan. Diese Datei reicht alles weiter,
damit `from src.neu.modelle import KategorieZeile` weiter gilt: wo ein Modell
steht, ist eine Frage der Ordnung und keine, die den Aufrufer angeht.

Die Wertevorräte selbst stehen in src/neu/vokabular.py, einmal. Was in den
Modulen steht, sind Namen darauf.
"""

from src.neu.modelle.akteure import (
    AkteurAendernRumpf,
    AkteurAnlegenRumpf,
    AkteurAntwort,
    AkteurHerkunft,
    AkteurListe,
    AkteurStatus,
    AkteurTyp,
    AkteurZeile,
    AkteureErkennenRumpf,
    FundstelleGeloescht,
    HerausgeloestAntwort,
    HerausloesenRumpf,
    Kandidat,
    KandidatGrund,
    KandidatenListe,
    Markierung,
    MarkierungenListe,
    Namenstreffer,
    VerschmelzenRumpf,
)
from src.neu.modelle.datierung import (
    Anker,
    Ausreisser,
    DatierenRumpf,
    DatierungAntwort,
    DatierungHerkunft,
    DatierungRumpf,
    DatierungUmfang,
    DatierungVerteilung,
    DatierungZeileAntwort,
    Praezision,
    TextAntwort,
    TextRumpf,
)
from src.neu.modelle.export import ExportAntwort, ExportierenRumpf
from src.neu.modelle.gemeinsam import Fehler, FehlerAntwort
from src.neu.modelle.ingest import (
    AnmeldungBeginn,
    DropboxOrdnerListe,
    DropboxOrdnerRumpf,
    DropboxStand,
    IngestAntwort,
    QuelleAnlegen,
    Quellformat,
)
from src.neu.modelle.konfiguration import AnbieterLage, KonfigurationAntwort
from src.neu.modelle.laeufe import LaufBegonnen, LaufStand
from src.neu.modelle.projekte import (
    Einheit,
    EinheitTyp,
    EinheitenListe,
    Kennzahlen,
    Lauf,
    Projekt,
    ProjektAnlegenRumpf,
    ProjektListe,
    ProjektZeile,
)
from src.neu.modelle.themen import (
    KategorieEintrag,
    KategorieHerkunft,
    KategorieRumpf,
    KategorieZeile,
    KategorienGespeichert,
    KategorienListe,
    KategorienSpeichernRumpf,
    KlassifizierenRumpf,
    TaxonomieVorschlagRumpf,
    Umfang,
    Verfahren,
    ZuordnungAntwort,
    ZuordnungRumpf,
)

__all__ = [
    "AkteurAendernRumpf", "AkteurAnlegenRumpf", "AkteurAntwort", "AkteurHerkunft",
    "AkteurListe", "AkteurStatus", "AkteurTyp", "AkteurZeile", "AkteureErkennenRumpf",
    "AnbieterLage", "Anker", "AnmeldungBeginn", "Ausreisser",
    "DatierenRumpf", "DatierungAntwort", "DatierungHerkunft", "DatierungRumpf",
    "DatierungUmfang", "DatierungVerteilung", "DatierungZeileAntwort",
    "DropboxOrdnerListe", "DropboxOrdnerRumpf", "DropboxStand",
    "Einheit", "EinheitTyp", "EinheitenListe", "ExportAntwort", "ExportierenRumpf",
    "Fehler", "FehlerAntwort", "FundstelleGeloescht",
    "HerausgeloestAntwort", "HerausloesenRumpf", "IngestAntwort",
    "Kandidat", "KandidatGrund", "KandidatenListe",
    "KategorieEintrag", "KategorieHerkunft", "KategorieRumpf", "KategorieZeile",
    "KategorienGespeichert", "KategorienListe", "KategorienSpeichernRumpf",
    "Kennzahlen", "KlassifizierenRumpf", "KonfigurationAntwort",
    "TaxonomieVorschlagRumpf",
    "Lauf", "LaufBegonnen", "LaufStand",
    "Markierung", "MarkierungenListe", "Namenstreffer",
    "Praezision", "Projekt", "ProjektAnlegenRumpf", "ProjektListe", "ProjektZeile",
    "QuelleAnlegen", "Quellformat",
    "TextAntwort", "TextRumpf", "Umfang", "Verfahren", "VerschmelzenRumpf",
    "ZuordnungAntwort", "ZuordnungRumpf",
]
