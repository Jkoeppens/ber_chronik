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
"""

import sqlite3
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "neu.db"


def db_pfad() -> Path:
    """Pfad zur Datenbank. Über NEU_DB überschreibbar (Tests)."""
    import os
    return Path(os.environ.get("NEU_DB") or DB_PATH)


def verbindung() -> sqlite3.Connection:
    """Nur-Lese-Verbindung. Zeilen kommen als sqlite3.Row (Zugriff über Spaltennamen)."""
    pfad = db_pfad()
    if not pfad.exists():
        raise FileNotFoundError(
            f"{pfad} fehlt. Anlegen mit: python3 -m src.neu.ingest.cli --anlegen …"
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
            f"{pfad} fehlt. Anlegen mit: python3 -m src.neu.ingest.cli --anlegen …"
        )
    con = sqlite3.connect(pfad)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    # WAL bleibt an der Datei haften, einmal gesetzt genügt — hier trotzdem bei
    # jeder Verbindung, damit eine frisch angelegte Datenbank es auch hat.
    con.execute("PRAGMA journal_mode = WAL")
    return con
