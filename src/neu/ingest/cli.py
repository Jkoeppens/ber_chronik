"""
cli.py — Einlesen von der Kommandozeile

  python3 -m src.neu.ingest.cli --projekt damaskus \
      --pfad "data/raw/Damakus Notizen.docx" --quellformat literaturexzerpt

Legt die Datenbank und ein fehlendes Projekt nur mit --anlegen an; ohne das
Flag wird ein unbekanntes Projekt abgelehnt statt stillschweigend erzeugt.
"""

from __future__ import annotations

import argparse
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.neu.db import db_pfad, verbindung_schreibend
from src.neu.ingest.dienst import IngestFehler, einlesen
from src.neu.ingest.kern import QUELLFORMATE

ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMA = ROOT / "schema.sql"


def _anlegen(projekt_id: str, titel: str) -> None:
    """Datenbank aus schema.sql erzeugen und ein Projekt mit Eigentümer anlegen."""
    pfad = db_pfad()
    if not pfad.exists():
        pfad.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(pfad)
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        con.close()
        print(f"Datenbank angelegt: {pfad}")

    con = verbindung_schreibend()
    try:
        if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone():
            return
        jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        token = secrets.token_urlsafe(32)
        with con:
            zeiger = con.execute(
                "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
                "VALUES (?, '', '', 'nutzer', ?)",
                (token, jetzt),
            )
            con.execute(
                "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                "VALUES (?, ?, ?, ?)",
                (projekt_id, titel or projekt_id, zeiger.lastrowid, jetzt),
            )
        print(f"Projekt '{projekt_id}' angelegt, Eigentümer-Token: {token}")
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Quelle in data/neu.db einlesen")
    ap.add_argument("--projekt", required=True, help="Projekt-Kennung, z.B. damaskus")
    ap.add_argument("--pfad", required=True, help="DOCX-Datei oder Ordner")
    ap.add_argument("--quellformat", required=True, choices=QUELLFORMATE)
    ap.add_argument("--quelle-id", default=None, help="Kennung der Quelle (sonst zufällig)")
    ap.add_argument("--anlegen", action="store_true",
                    help="Datenbank und fehlendes Projekt anlegen")
    ap.add_argument("--titel", default="", help="Projekttitel, nur mit --anlegen")
    args = ap.parse_args()

    if args.anlegen:
        _anlegen(args.projekt, args.titel)

    con = verbindung_schreibend()
    try:
        ergebnis = einlesen(
            con,
            projekt_id=args.projekt,
            pfad=Path(args.pfad),
            quellformat=args.quellformat,
            quelle_id=args.quelle_id,
        )
    except IngestFehler as exc:
        print(f"Fehlgeschlagen ({exc.code}): {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"Quelle {ergebnis.quelle_id}  ({ergebnis.quellformat})")
    print(f"  {ergebnis.anzahl_einheiten} Einheiten")
    for typ, n in sorted(ergebnis.anzahl_je_typ.items(), key=lambda kv: -kv[1]):
        print(f"    {typ:14s} {n:5d}")
    print(f"  Lauf {ergebnis.lauf_id}: {ergebnis.status}, "
          f"{ergebnis.begonnen_am} → {ergebnis.beendet_am}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
