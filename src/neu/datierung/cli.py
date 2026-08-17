"""
cli.py — Datieren von der Kommandozeile

  python3 -m src.neu.datierung.cli --projekt damaskus
  python3 -m src.neu.datierung.cli --projekt ber --umfang alle
"""

from __future__ import annotations

import argparse
import sys

from src.neu.datierung.dienst import UMFAENGE, DatierungFehler, datieren
from src.neu.db import verbindung_schreibend


def main() -> int:
    ap = argparse.ArgumentParser(description="Einheiten eines Projekts datieren")
    ap.add_argument("--projekt", required=True, help="Projekt-Kennung, z.B. damaskus")
    ap.add_argument("--umfang", default="offen", choices=UMFAENGE,
                    help="offen = nur nie datierte; alle = auch maschinelle erneut, "
                         "Handkorrekturen bleiben; auch_manuell = auch diese")
    args = ap.parse_args()

    con = verbindung_schreibend()
    try:
        ergebnis = datieren(con, projekt_id=args.projekt, umfang=args.umfang)
    except DatierungFehler as exc:
        print(f"Fehlgeschlagen ({exc.code}): {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"Projekt {ergebnis.projekt_id}  ({ergebnis.quellformat})")
    print(f"  {ergebnis.anzahl_einheiten} Einheiten, davon {ergebnis.anzahl_datiert} datiert, "
          f"{ergebnis.anzahl_ohne_datum} ohne Datum")
    print(f"  {ergebnis.anzahl_anker} Anker")
    print("  Präzision:")
    for k, n in sorted(ergebnis.anzahl_je_praezision.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} {n:6d}")
    print("  Herkunft:")
    for k, n in sorted(ergebnis.anzahl_je_herkunft.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} {n:6d}")
    for w in ergebnis.warnungen:
        print(f"  WARNUNG: {w}", file=sys.stderr)
    print(f"  Lauf {ergebnis.lauf_id}: {ergebnis.status}, "
          f"{ergebnis.begonnen_am} → {ergebnis.beendet_am}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
