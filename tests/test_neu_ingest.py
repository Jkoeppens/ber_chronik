"""
tests/test_neu_ingest.py — src/neu/ingest/dienst.py gegen eine echte Datenbank

Jeder Test baut seine eigene Datenbank aus schema.sql in einem tmp_path.
data/neu.db und data/projects.db werden nicht angefasst.

Der Abnahmetest liest data/raw/Damakus Notizen.docx ein und vergleicht
Feld für Feld gegen die segments.json der alten Pipeline.

Ausführen:
  python3 -m pytest tests/test_neu_ingest.py -v
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.ingest.dienst import IngestFehler, einlesen  # noqa: E402

SCHEMA = ROOT / "schema.sql"
DAMASKUS_DOCX = ROOT / "data" / "raw" / "Damakus Notizen.docx"

EINHEIT_FELDER = (
    "position", "typ", "text", "publikation", "chronologie_gruppe", "ebene", "seite",
)


@pytest.fixture
def con(tmp_path) -> sqlite3.Connection:
    """Frische Datenbank mit einem Projekt und seinem Eigentümer."""
    db = tmp_path / "test.db"
    verbindung = sqlite3.connect(db)
    verbindung.executescript(SCHEMA.read_text(encoding="utf-8"))
    verbindung.execute("PRAGMA foreign_keys = ON")
    with verbindung:
        verbindung.execute(
            "INSERT INTO zugang (token, angelegt_am, rolle) VALUES ('t', '2026-01-01', 'nutzer')"
        )
        verbindung.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES ('damaskus', 'Damaskus', 1, '2026-01-01')"
        )
    yield verbindung
    verbindung.close()


def _md_ordner(tmp_path: Path) -> Path:
    ordner = tmp_path / "vault"
    ordner.mkdir()
    (ordner / "b_zweiter.md").write_text(
        "---\ntitle: Zweiter\npublished: 2025-11-04\n---\nRumpf zwei.\n", encoding="utf-8"
    )
    (ordner / "a_erster.md").write_text(
        "---\ntitle: Erster\npublished: 2025-11-03\n---\nRumpf eins.\n", encoding="utf-8"
    )
    return ordner


# ── Abnahme ───────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not DAMASKUS_DOCX.exists(), reason=f"{DAMASKUS_DOCX} fehlt")
def test_damaskus_docx_ergibt_718_einheiten(con: sqlite3.Connection) -> None:
    ergebnis = einlesen(con, "damaskus", DAMASKUS_DOCX, "literaturexzerpt")

    assert ergebnis.anzahl_einheiten == 718
    assert ergebnis.anzahl_je_typ["content"] == 672
    assert ergebnis.anzahl_je_typ["bibliography"] == 44
    assert ergebnis.anzahl_je_typ["meta"] == 2
    assert ergebnis.status == "erfolg"

    assert con.execute("SELECT count(*) FROM einheit").fetchone()[0] == 718
    assert con.execute("SELECT count(*) FROM quelle").fetchone()[0] == 1


SEGMENTS_JSON = ROOT / "data" / "projects" / "damaskus" / "documents" / "56da8203" / "segments.json"


@pytest.mark.skipif(
    not DAMASKUS_DOCX.exists() or not SEGMENTS_JSON.exists(),
    reason="DOCX oder segments.json fehlt",
)
def test_deckungsgleich_mit_der_alten_pipeline(con: sqlite3.Connection) -> None:
    """Feld für Feld gegen die segments.json der alten Pipeline.

    Verglichen wird gegen die Ausgangsdatei, nicht gegen data/neu.db: die
    Datenbank wird vom selben Code erzeugt, der hier geprüft wird, und ein
    Vergleich gegen sie wäre zirkulär. segments.json entstand am 13.04.2026
    aus parse_document.parse(), bevor das Modul unbrauchbar wurde.
    """
    einlesen(con, "damaskus", DAMASKUS_DOCX, "literaturexzerpt")
    felder = ", ".join(EINHEIT_FELDER)
    neu = con.execute(f"SELECT {felder} FROM einheit ORDER BY position").fetchall()

    segmente = json.loads(SEGMENTS_JSON.read_text(encoding="utf-8"))
    alt = [
        (
            i,
            s["type"],
            s["text"],
            s.get("source"),
            s.get("source"),      # chronologie_gruppe: bei Exzerpten das Werk
            s.get("level"),
            s.get("page"),
        )
        for i, s in enumerate(segmente, start=1)
    ]

    assert len(neu) == len(alt) == 718
    abweichungen = [(i + 1, a, b) for i, (a, b) in enumerate(zip(neu, alt)) if a != b]
    assert abweichungen == []


BER_DOCX = ROOT / "data" / "raw" / "Flh Bln Chronik 1989 - 2017 bis 13.dez.docx"
BER_SEGMENTS = ROOT / "data" / "projects" / "ber" / "documents" / "main" / "segments.json"

CHRONIK_FELDER = ("position", "typ", "text", "publikation", "publikationsdatum",
                  "ist_zitat", "seite", "ebene", "chronologie_gruppe")


@pytest.mark.skipif(not BER_DOCX.exists(), reason=f"{BER_DOCX} fehlt")
def test_ber_chronik_ergibt_978_einheiten(con: sqlite3.Connection) -> None:
    ergebnis = einlesen(con, "damaskus", BER_DOCX, "presseexzerpt")

    assert ergebnis.anzahl_einheiten == 978
    assert ergebnis.anzahl_je_typ["content"] == 949
    assert ergebnis.anzahl_je_typ["heading"] == 29
    assert ergebnis.status == "erfolg"


@pytest.mark.skipif(
    not BER_DOCX.exists() or not BER_SEGMENTS.exists(),
    reason="DOCX oder segments.json fehlt",
)
def test_chronik_deckungsgleich_mit_der_alten_pipeline(con: sqlite3.Connection) -> None:
    """Feld für Feld gegen ber/documents/main/segments.json.

    Die Vorlage parse_presseartikel() trug zusätzlich is_geicke und
    ingest_source; beide sind laut SCHEMA.md ersatzlos entfallen und werden
    deshalb nicht verglichen.
    """
    einlesen(con, "damaskus", BER_DOCX, "presseexzerpt")
    felder = ", ".join(CHRONIK_FELDER)
    neu = con.execute(f"SELECT {felder} FROM einheit ORDER BY position").fetchall()

    segmente = json.loads(BER_SEGMENTS.read_text(encoding="utf-8"))
    alt = [
        (
            i,
            s["type"],
            s["text"],
            s.get("source"),
            s.get("source_date"),
            None if s.get("is_quote") is None else int(s["is_quote"]),
            s.get("page"),
            None,          # ebene: die Chronik ist flach
            None,          # chronologie_gruppe: durchgehende Zeitachse
        )
        for i, s in enumerate(segmente, start=1)
    ]

    assert len(neu) == len(alt) == 978
    abweichungen = [(i + 1, a, b) for i, (a, b) in enumerate(zip(neu, alt)) if a != b]
    assert abweichungen == []


# ── position ──────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not DAMASKUS_DOCX.exists(), reason=f"{DAMASKUS_DOCX} fehlt")
def test_position_ist_ausdruecklich_und_lueckenlos(con: sqlite3.Connection) -> None:
    einlesen(con, "damaskus", DAMASKUS_DOCX, "literaturexzerpt")
    positionen = [r[0] for r in con.execute("SELECT position FROM einheit ORDER BY position")]
    assert positionen == list(range(1, 719))


def test_ordner_wird_sortiert_gelesen(con: sqlite3.Connection, tmp_path: Path) -> None:
    """position folgt dem Dateinamen, nicht der Reihenfolge des Dateisystems."""
    einlesen(con, "damaskus", _md_ordner(tmp_path), "pressesammlung")
    zeilen = con.execute(
        "SELECT position, publikation, quellpfad, datum FROM einheit ORDER BY position"
    ).fetchall()
    assert [z[1] for z in zeilen] == ["Erster", "Zweiter"]
    assert [z[2] for z in zeilen] == ["a_erster.md", "b_zweiter.md"]
    assert [z[3] for z in zeilen] == ["2025-11-03", "2025-11-04"]


# ── lauf ──────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not DAMASKUS_DOCX.exists(), reason=f"{DAMASKUS_DOCX} fehlt")
def test_erfolgreicher_lauf_wird_festgehalten(con: sqlite3.Connection) -> None:
    ergebnis = einlesen(con, "damaskus", DAMASKUS_DOCX, "literaturexzerpt")
    zeile = con.execute(
        "SELECT projekt_id, schritt, begonnen_am, beendet_am, parameter, status "
        "FROM lauf WHERE id = ?", (ergebnis.lauf_id,)
    ).fetchone()
    assert zeile[0] == "damaskus"
    assert zeile[1] == "ingest"
    assert zeile[2] and zeile[3]
    assert json.loads(zeile[4])["quellformat"] == "literaturexzerpt"
    assert zeile[5] == "erfolg"


def test_fehlschlag_rollt_daten_zurueck_und_haelt_den_lauf_fest(
    con: sqlite3.Connection, tmp_path: Path
) -> None:
    kaputt = tmp_path / "kaputt.docx"
    kaputt.write_bytes(b"kein gueltiges DOCX")

    with pytest.raises(IngestFehler):
        einlesen(con, "damaskus", kaputt, "literaturexzerpt")

    assert con.execute("SELECT count(*) FROM quelle").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM einheit").fetchone()[0] == 0

    lauf = con.execute("SELECT status, beendet_am, parameter FROM lauf").fetchall()
    assert len(lauf) == 1
    assert lauf[0][0] == "fehler"
    assert lauf[0][1]
    assert "fehler" in json.loads(lauf[0][2])


# ── Prüfungen ─────────────────────────────────────────────────────────────────

def test_unbekanntes_projekt(con: sqlite3.Connection) -> None:
    with pytest.raises(IngestFehler) as exc:
        einlesen(con, "gibtsnicht", DAMASKUS_DOCX, "literaturexzerpt")
    assert exc.value.code == "projekt_nicht_gefunden"


def test_quellformat_wird_nicht_durchgereicht(con: sqlite3.Connection) -> None:
    from src.neu.ingest.kern import UnbekanntesQuellformat

    with pytest.raises(UnbekanntesQuellformat):
        einlesen(con, "damaskus", DAMASKUS_DOCX, "buchnotizen")


def test_jedes_quellformat_wird_bedient(con: sqlite3.Connection, tmp_path: Path) -> None:
    """Kein Wert des Vorrats läuft mehr in 'nicht implementiert'.

    Geprüft wird über einen absichtlich unlesbaren Gegenstand: entscheidend
    ist, dass die Verzweigung greift und nicht am Quellformat scheitert.
    """
    from src.neu.ingest.kern import QUELLFORMATE

    datei = tmp_path / "kaputt.docx"
    datei.write_bytes(b"kein gueltiges DOCX")
    ordner = tmp_path / "leerer_ordner"
    ordner.mkdir()

    for quellformat in QUELLFORMATE:
        ziel = ordner if quellformat == "pressesammlung" else datei
        with pytest.raises(IngestFehler) as exc:
            einlesen(con, "damaskus", ziel, quellformat)
        assert exc.value.code != "quellformat_nicht_implementiert", quellformat


def test_fehlende_datei(con: sqlite3.Connection, tmp_path: Path) -> None:
    with pytest.raises(IngestFehler) as exc:
        einlesen(con, "damaskus", tmp_path / "weg.docx", "literaturexzerpt")
    assert exc.value.code == "datei_nicht_gefunden"
