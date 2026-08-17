"""
import_damaskus.py — Damaskus-Notizen als Fixture in data/neu.db

Liest die vorhandene segments.json aus data/projects/damaskus/documents/*/
und füllt genau zwei Tabellen: quelle und einheit.

Keine Anker, keine Kategorien, keine Akteure — die Datierung, Klassifikation
und Entitäten der bestehenden Pipeline bleiben außen vor.

Eine projekt-Zeile entsteht zwangsläufig mit: quelle.projekt_id ist
NOT NULL REFERENCES projekt(id), und PRAGMA foreign_keys ist an.

data/projects.db wird nicht angefasst.
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT       = Path(__file__).parent
SCHEMA     = ROOT / "schema.sql"
DB_PATH    = ROOT / "data" / "neu.db"
ALT_DB     = ROOT / "data" / "projects.db"   # nur lesend
PROJEKT_ID = "damaskus"
PROJEKT_DIR = ROOT / "data" / "projects" / PROJEKT_ID

QUELLFORMAT = "literaturexzerpt"


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def create_db() -> sqlite3.Connection:
    if DB_PATH.exists():
        DB_PATH.unlink()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = connect(DB_PATH)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    # executescript committet implizit und setzt foreign_keys zurück
    con.execute("PRAGMA foreign_keys = ON")
    return con


def projekt_aus_alt_db(projekt_id: str) -> tuple[str, str]:
    """(created_at, owner_token) aus data/projects.db. Streng lesend (mode=ro)."""
    alt = sqlite3.connect(f"file:{ALT_DB}?mode=ro", uri=True)
    try:
        row = alt.execute(
            "SELECT created_at, owner_token FROM projects WHERE id = ?", (projekt_id,)
        ).fetchone()
    finally:
        alt.close()
    if not row or not row[0] or not row[1]:
        print(f"created_at/owner_token fehlt für '{projekt_id}' in {ALT_DB}", file=sys.stderr)
        sys.exit(1)
    return row[0], row[1]


def import_eigentuemer(con: sqlite3.Connection, owner_token: str, angelegt_am: str) -> int:
    """Eine zugang-Zeile für den Eigentümer. Gibt die zugang.id zurück.

    Name und Organisation kommen aus invites.json, dem heutigen Ablageort der
    Einladungscodes. projekt.eigentuemer_id ist NOT NULL — diese Zeile muss
    vor dem Projekt stehen.
    """
    invites = json.loads((ROOT / "invites.json").read_text(encoding="utf-8"))
    eintrag = invites.get(owner_token)
    if eintrag is None:
        print(f"owner_token {owner_token} steht nicht in invites.json", file=sys.stderr)
        sys.exit(1)

    cur = con.execute(
        "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
        "VALUES (?, ?, ?, ?, ?)",
        (owner_token, eintrag.get("name", ""), eintrag.get("org", ""),
         "nutzer", angelegt_am),
    )
    return cur.lastrowid


def import_quelle(con: sqlite3.Connection, doc_dir: Path) -> str:
    """Eine Zeile in quelle. Gibt die quelle_id zurück."""
    doc_cfg  = json.loads((doc_dir / "config.json").read_text(encoding="utf-8"))
    dateiname = doc_cfg.get("original_filename") or ""
    pfad      = f"data/raw/{dateiname}" if dateiname else None

    con.execute(
        "INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_dir.name, PROJEKT_ID, QUELLFORMAT, pfad, doc_cfg.get("ingested_at", "")),
    )
    return doc_dir.name


def import_einheiten(con: sqlite3.Connection, quelle_id: str, segments: list[dict]) -> int:
    """Eine Zeile je Segment, position aus der Reihenfolge in der Datei."""
    rows = [
        (
            quelle_id,
            position,
            seg["type"],
            seg["text"],
            seg.get("source"),
            # literaturexzerpt: das exzerpierte Werk ist die Interpolationsgruppe
            seg.get("source"),
            seg.get("level"),
            seg.get("page"),
        )
        for position, seg in enumerate(segments, start=1)
    ]
    con.executemany(
        "INSERT INTO einheit "
        "(quelle_id, position, typ, text, publikation, chronologie_gruppe, ebene, seite) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return len(rows)


def main() -> None:
    doc_dirs = sorted(
        d for d in (PROJEKT_DIR / "documents").iterdir()
        if d.is_dir() and (d / "segments.json").exists()
    )
    if not doc_dirs:
        print(f"Keine segments.json unter {PROJEKT_DIR / 'documents'}", file=sys.stderr)
        sys.exit(1)

    con = create_db()

    # zugang + projekt: erzwungen durch quelle.projekt_id NOT NULL REFERENCES
    # projekt(id) und projekt.eigentuemer_id NOT NULL REFERENCES zugang(id)
    angelegt_am, owner_token = projekt_aus_alt_db(PROJEKT_ID)
    eigentuemer_id = import_eigentuemer(con, owner_token, angelegt_am)

    projekt_cfg = json.loads((PROJEKT_DIR / "config.json").read_text(encoding="utf-8"))
    con.execute(
        "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) VALUES (?, ?, ?, ?)",
        (PROJEKT_ID, projekt_cfg.get("title", ""), eigentuemer_id, angelegt_am),
    )

    gesamt = 0
    for doc_dir in doc_dirs:
        segments  = json.loads((doc_dir / "segments.json").read_text(encoding="utf-8"))
        quelle_id = import_quelle(con, doc_dir)
        n         = import_einheiten(con, quelle_id, segments)
        gesamt   += n
        print(f"{doc_dir.name}: {n} Einheiten aus {len(segments)} Segmenten")

    con.commit()

    # ── Bericht ───────────────────────────────────────────────────────────────
    n_quelle  = con.execute("SELECT count(*) FROM quelle").fetchone()[0]
    n_einheit = con.execute("SELECT count(*) FROM einheit").fetchone()[0]
    print(f"\nquelle:  {n_quelle}")
    print(f"einheit: {n_einheit}")

    print("\nEinheiten nach typ:")
    for typ, n in con.execute(
        "SELECT typ, count(*) FROM einheit GROUP BY typ ORDER BY count(*) DESC"
    ):
        print(f"  {typ:14s} {n:4d}")

    print("\nBefüllung der Spalten (nicht NULL):")
    for spalte in ("publikation", "ebene", "seite", "chronologie_gruppe",
                   "datum", "praezision", "kategorie_id"):
        n = con.execute(f"SELECT count(*) FROM einheit WHERE {spalte} IS NOT NULL").fetchone()[0]
        print(f"  {spalte:20s} {n:4d} / {n_einheit}")

    con.close()
    print(f"\n→ {DB_PATH}")


if __name__ == "__main__":
    main()
