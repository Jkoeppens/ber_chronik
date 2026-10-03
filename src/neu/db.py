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


# ── Altlasten ─────────────────────────────────────────────────────────────────
# Kein Migrationswerkzeug, sondern eine Liste benannter Einzelfälle. Jeder
# beschreibt, was er berichtigt und warum; jeder muss mehrfach laufen dürfen,
# ohne etwas kaputtzumachen. Wenn diese Liste lang wird, ist das das Zeichen,
# dass ein richtiges Werkzeug fällig ist — heute steht ein Eintrag darin.
ALTLASTEN: list[tuple[str, str, str]] = [
    (
        "verfahren_bge_wird_vektoren",
        # Die Umbenennung von September 2026: 'bge' nannte den Weg, klang aber
        # nach dem Modell — und war irreführend, sobald Voyage rechnete.
        # Migriert statt beides zu lesen, weil der Wert nirgends verzweigt: er
        # wird nur angezeigt. Zwei Schreibweisen für dieselbe Sache dauerhaft
        # mitzulesen, wäre teurer als eine einmalige Berichtigung.
        "UPDATE lauf SET parameter = replace(parameter, '\"verfahren\": \"bge\"',"
        " '\"verfahren\": \"vektoren\"') WHERE parameter LIKE '%\"verfahren\": \"bge\"%'",
        "lauf-Zeilen: verfahren 'bge' → 'vektoren'",
    ),
    (
        "tabelle_einstellung",
        # Oktober 2026: der Sitzungskeks braucht ein Signaturgeheimnis, und das
        # soll keine Umgebungsvariable sein. IF NOT EXISTS, weil eine frisch aus
        # schema.sql erzeugte Datenbank sie schon hat — die Liste läuft nur auf
        # bestehenden, aber billig ist billig.
        "CREATE TABLE IF NOT EXISTS einstellung ("
        " schluessel TEXT NOT NULL PRIMARY KEY,"
        " wert       TEXT NOT NULL,"
        " gesetzt_am TEXT NOT NULL)",
        "Tabelle 'einstellung' angelegt",
    ),
]


def altlasten_nachziehen(con: sqlite3.Connection) -> list[str]:
    """Führt die Berichtigungen aus und sagt, welche etwas geändert haben.

    Jede trägt ihre eigene WHERE-Bedingung, die im Normalfall auf nichts
    passt — ein Start ohne Altlasten kostet damit je Eintrag eine Abfrage und
    ändert nichts. Gemeldet wird nur, was tatsächlich Zeilen berührt hat;
    sonst stünde bei jedem Start eine Zeile, die nichts bedeutet.
    """
    getan = []
    with con:
        for name, sql, beschreibung in ALTLASTEN:
            vorher = _bestand(con, sql)
            zeiger = con.execute(sql)
            # rowcount zählt nur bei UPDATE/DELETE/INSERT; bei CREATE TABLE ist
            # er -1, auch wenn die Tabelle gerade entstanden ist. Deshalb für
            # solche Anweisungen der Vergleich davor und danach.
            if vorher is not None:
                if not vorher and _bestand(con, sql):
                    getan.append(beschreibung)
            elif zeiger.rowcount > 0:
                getan.append(f"{beschreibung} ({zeiger.rowcount} Zeilen)")
    return getan


def _bestand(con: sqlite3.Connection, sql: str) -> bool | None:
    """Ob die Tabelle einer CREATE-Anweisung schon da ist — sonst None.

    None heißt: die Anweisung ist keine, bei der sich das fragen lässt, dann
    zählt rowcount.
    """
    anfang = sql.strip().upper()
    if not anfang.startswith("CREATE TABLE IF NOT EXISTS"):
        return None
    name = sql.strip().split()[5].strip("(")
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


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
