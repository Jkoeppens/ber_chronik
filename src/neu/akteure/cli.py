"""
cli.py — Akteure von der Kommandozeile erkennen

  python3 -m src.neu.akteure.cli --projekt damaskus

Braucht EMBEDDING_PROVIDER (local | voyage). Fehlt es, bricht der Lauf ab.
"""

from __future__ import annotations

import argparse
import sys

from src.neu.akteure.dienst import AkteurFehler, erkennen
from src.neu.db import verbindung_schreibend
from src.neu.anbieter import AnbieterFehler


def main() -> int:
    ap = argparse.ArgumentParser(description="Akteure eines Projekts erkennen")
    ap.add_argument("--projekt", required=True, help="Projekt-Kennung, z.B. damaskus")
    args = ap.parse_args()

    con = verbindung_schreibend()
    try:
        ergebnis = erkennen(con, projekt_id=args.projekt)
    except (AkteurFehler, AnbieterFehler) as exc:
        print(f"Fehlgeschlagen ({exc.code}): {exc}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"Projekt {ergebnis.projekt_id}")
    print(f"  Erkenner  : {ergebnis.gliner_modell}")
    print(f"  Embedding : {ergebnis.embedding_modell}  (Schwelle {ergebnis.schwelle})")
    print(f"  {ergebnis.anzahl_einheiten} Einheiten → {ergebnis.anzahl_funde} Funde")
    print(f"  {ergebnis.anzahl_vor_gruppierung} nach Namensmengen, "
          f"{ergebnis.anzahl_neu} nach Gruppierung")
    print(f"  {ergebnis.anzahl_manuell} von Hand gepflegt, "
          f"{ergebnis.anzahl_abgelehnt} abgelehnt")
    print(f"  {ergebnis.anzahl_zuordnungen} Fundstellen in "
          f"{ergebnis.anzahl_einheiten_mit_akteur} Einheiten")
    print("  Typen:")
    for k, n in sorted(ergebnis.anzahl_je_typ.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} {n:6d}")
    print("  Verschmelzungskandidaten:")
    for k, n in sorted(ergebnis.anzahl_kandidaten_je_grund.items(), key=lambda x: -x[1]):
        print(f"    {k:14s} {n:6d}")
    for label, n in sorted(ergebnis.unbekannte_labels.items(), key=lambda x: -x[1]):
        print(f"  WARNUNG: {n}× Label ohne Abbildung: {label!r}", file=sys.stderr)
    for name in ergebnis.verdraengt_von_manuell:
        print(f"  Hinweis: '{name}' bleibt in der Handfassung", file=sys.stderr)
    print(f"  Lauf {ergebnis.lauf_id}: {ergebnis.status}, "
          f"{ergebnis.begonnen_am} → {ergebnis.beendet_am}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
