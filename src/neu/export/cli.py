"""
cli.py — Exportdateien für viz/ erzeugen

  python3 -m src.neu.export.cli --projekt damaskus
  python3 -m src.neu.export.cli --projekt damaskus --ziel data/projects/x/exploration

Ohne --ziel wird nach data/projects/{projekt}/exploration/ geschrieben — dorthin,
wo viz/?project={projekt} nachsieht.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.neu.db import verbindung_schreibend
from src.neu.export.dienst import ExportFehler, exportieren


def main() -> int:
    ap = argparse.ArgumentParser(description="Exportdateien für viz/ erzeugen")
    ap.add_argument("--projekt", required=True, help="Projekt-Kennung, z.B. damaskus")
    ap.add_argument("--ziel", default=None,
                    help="Zielverzeichnis; Vorgabe data/projects/{projekt}/exploration")
    ap.add_argument("--zusammenfassungen", action="store_true",
                    help="entities_summary.json aus akteur.zusammenfassung schreiben")
    args = ap.parse_args()

    con = verbindung_schreibend()
    try:
        ergebnis = exportieren(
            con, projekt_id=args.projekt,
            ziel=Path(args.ziel) if args.ziel else None,
            zusammenfassungen=args.zusammenfassungen,
        )
    except ExportFehler as exc:
        print(f"Fehlgeschlagen ({exc.code}): {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"Projekt {ergebnis.projekt_id} → {ergebnis.ziel}")
    for name in ergebnis.dateien:
        print(f"    {name}")
    print(f"  {ergebnis.anzahl_einheiten} Einheiten: "
          f"{ergebnis.anzahl_mit_datum} mit Datum, "
          f"{ergebnis.anzahl_ohne_datum} ohne")
    print(f"  {ergebnis.anzahl_ohne_kategorie} ohne Kategorie, "
          f"{ergebnis.anzahl_mit_akteur} mit mindestens einem Akteur")
    print(f"  Zeitraum: {ergebnis.jahr_min} – {ergebnis.jahr_max}")
    print(f"  Netzwerk: {ergebnis.anzahl_knoten} Knoten, {ergebnis.anzahl_kanten} Kanten "
          f"(aus {ergebnis.anzahl_akteure} Akteuren)")
    print(f"  Perioden: {ergebnis.anzahl_perioden}")
    if ergebnis.zusammenfassungen:
        print(f"  Zusammenfassungen: {ergebnis.zusammenfassungen}")
    print("  Kategorien:")
    for k, n in sorted(ergebnis.anzahl_je_kategorie.items(), key=lambda x: -x[1]):
        print(f"    {k:24s} {n:6d}")
    print(f"  Lauf {ergebnis.lauf_id}: {ergebnis.status}, "
          f"{ergebnis.begonnen_am} → {ergebnis.beendet_am}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
