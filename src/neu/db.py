"""
db.py — Zugriff auf data/neu.db

Zwei Verbindungsarten, ausdrücklich getrennt:

  verbindung()             mode=ro. Ein Schreibversuch scheitert an SQLite
                           selbst, nicht an einer Zusage im Code. Alles
                           Lesende benutzt diese.
  verbindung_schreibend()  schreibfähig. Jeder Schritt, der etwas ablegt.

Beide schalten WAL ein: ein langer Schritt schreibt im Hintergrund, während die
Oberfläche den Fortschritt abfragt. Ohne WAL sperrt der Schreiber die Leser aus,
und genau das Abfragen liefe dann in "database is locked".

data/projects.db wird von diesem Modul nie angefasst.

Wo die Datei liegt, entscheidet src/neu/pfade.py — nicht dieses Modul. Bis
September 2026 stand hier ROOT / "data" / "neu.db", also im Quellbestand; auf
Railway hätte sie damit jeden Deploy nicht überlebt.
"""

import sqlite3
from pathlib import Path

from src.neu import pfade

SCHEMA = pfade.WURZEL / "schema.sql"


def db_pfad() -> Path:
    """Pfad zur Datenbank. Siehe pfade.datenbank()."""
    return pfade.datenbank()


def anlegen_wenn_noetig() -> bool:
    """Legt die Datenbank aus schema.sql an, wenn es sie nicht gibt.

    Gibt True zurück, wenn sie neu entstanden ist. Ein leeres Laufwerk ist der
    Normalfall einer frischen Installation und kein Fehler — vorher startete
    der Server in dem Fall durch und jeder Aufruf gab 500 'datenbank_fehlt',
    bis jemand von Hand die CLI bemühte.

    Kein eingebautes Ersatzschema: fehlt schema.sql, ist der Quellbestand
    kaputt, und das soll auffallen.
    """
    pfad = db_pfad()
    if pfad.exists():
        return False
    if not SCHEMA.is_file():
        raise FileNotFoundError(
            f"{SCHEMA} fehlt — ohne sie lässt sich keine Datenbank anlegen."
        )
    pfad.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(pfad)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
    finally:
        con.close()
    return True


def verbindung() -> sqlite3.Connection:
    """Nur-Lese-Verbindung. Zeilen kommen als sqlite3.Row (Zugriff über Spaltennamen)."""
    pfad = db_pfad()
    if not pfad.exists():
        raise FileNotFoundError(
            f"{pfad} fehlt. Beim Hochfahren wird sie sonst angelegt; von Hand "
            f"mit: python3 -m src.neu.ingest.cli --anlegen …"
        )
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def verbindung_schreibend() -> sqlite3.Connection:
    """Schreibfähige Verbindung."""
    pfad = db_pfad()
    if not pfad.exists():
        raise FileNotFoundError(
            f"{pfad} fehlt. Beim Hochfahren wird sie sonst angelegt; von Hand "
            f"mit: python3 -m src.neu.ingest.cli --anlegen …"
        )
    con = sqlite3.connect(pfad)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    # WAL bleibt an der Datei haften, einmal gesetzt genügt — hier trotzdem bei
    # jeder Verbindung, damit eine frisch angelegte Datenbank es auch hat.
    con.execute("PRAGMA journal_mode = WAL")
    return con
