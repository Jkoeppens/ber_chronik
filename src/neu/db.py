"""
db.py — Nur-Lese-Zugriff auf data/neu.db

Die Verbindung wird ausschließlich mit mode=ro geöffnet. Ein Schreibversuch
scheitert damit an SQLite selbst, nicht an einer Zusage im Code.

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
            f"{pfad} fehlt. Erzeugen mit: python3 import_damaskus.py"
        )
    con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
