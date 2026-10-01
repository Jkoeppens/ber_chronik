"""
cli.py — Einlesen von der Kommandozeile

  python3 -m src.neu.ingest.cli --projekt damaskus \
      --pfad "data/raw/Damakus Notizen.docx" --quellformat literaturexzerpt

Legt die Datenbank und ein fehlendes Projekt nur mit --anlegen an; ohne das
Flag wird ein unbekanntes Projekt abgelehnt statt stillschweigend erzeugt.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.neu import projekte, zugang
from src.neu.db import anlegen_wenn_noetig, db_pfad, verbindung_schreibend
from src.neu.ingest.dienst import IngestFehler, einlesen
from src.neu.ingest.kern import QUELLFORMATE

def _anlegen(projekt_id: str, titel: str) -> None:
    """Datenbank aus schema.sql erzeugen und ein Projekt mit Eigentümer anlegen."""
    # Dasselbe Anlegen macht der Server beim Hochfahren; es steht in db.py, und
    # zwar nur dort. Hier stand bis September 2026 eine zweite Fassung.
    if anlegen_wenn_noetig():
        print(f"Datenbank angelegt: {db_pfad()}")

    con = verbindung_schreibend()
    try:
        if projekte.gibt_es(con, projekt_id):
            return
        jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Aus zugang.py und nicht hier: der Tokenwert entsteht an einer Stelle,
        # damit nicht zwei Befehle verschieden viel Zufall vergeben.
        token = zugang.neuer_token()
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
