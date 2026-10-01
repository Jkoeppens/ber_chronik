"""
zugang_cli.py — Zugänge anlegen, entziehen, auflisten

    python3 -m src.neu.zugang_cli --anlegen "Jakob Koppermann" --rolle verwalter
    python3 -m src.neu.zugang_cli --entziehen 3
    python3 -m src.neu.zugang_cli --auflisten

Ein eigenes Modul und kein Unterbefehl von ingest/cli.py: das liest Dokumente
ein, das hier vergibt Zugänge. Zwei Arbeiten, die nichts miteinander zu tun
haben, außer dass beide einen Zugang brauchen — und genau diese Verwechslung
war der Grund, warum es bis Oktober 2026 keinen Weg gab, einen Zugang ohne ein
Projekt anzulegen.

Der Token wird EINMAL ausgegeben und steht danach nirgends mehr: nicht in der
Liste, nicht im Protokoll. Wer ihn verliert, bekommt einen neuen und gibt den
alten zurück — das ist die Rechnung, die ein nicht anzeigbares Geheimnis
aufmacht, und sie ist die richtige.
"""

from __future__ import annotations

import argparse
import sys

from src.neu import zugang
from src.neu.db import anlegen_wenn_noetig, db_pfad, verbindung, verbindung_schreibend
from src.neu.vokabular import ROLLEN


def _anlegen(name: str, organisation: str, rolle: str) -> int:
    anlegen_wenn_noetig()
    con = verbindung_schreibend()
    try:
        kennung, token = zugang.anlegen(con, name, organisation, rolle)
    except ValueError as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1
    finally:
        con.close()

    print(f"Zugang {kennung} angelegt: {name} ({rolle})")
    print()
    print("Token — er wird genau einmal gezeigt:")
    print()
    print(f"    {token}")
    print()
    print("Im Browser: Benutzername beliebig, dieser Wert als Passwort.")
    return 0


def _entziehen(kennung: str) -> int:
    con = verbindung_schreibend()
    try:
        weg = zugang.entziehen(con, kennung)
    except ValueError as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1
    finally:
        con.close()
    print(f"Zugang {weg['id']} entzogen: {weg['name']} ({weg['rolle']})")
    print("Er wirkt sofort nicht mehr — der Riegel schlägt bei jeder Anfrage nach.")
    return 0


def _auflisten() -> int:
    con = verbindung()
    try:
        zeilen = zugang.auflisten(con)
    finally:
        con.close()

    if not zeilen:
        print("Kein Zugang eingetragen.")
    else:
        print(f"{'id':>3}  {'Name':<24} {'Organisation':<18} {'Rolle':<10} "
              f"{'angelegt':<12} Projekte")
        for z in zeilen:
            print(f"{z['id']:>3}  {(z['name'] or '—'):<24.24} "
                  f"{(z['organisation'] or '—'):<18.18} {z['rolle']:<10} "
                  f"{z['angelegt_am'][:10]:<12} {z['projekte']:>5}")
    print()
    print(zugang.KEINE_PROJEKTRECHTE)
    return 0


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(
        prog="python3 -m src.neu.zugang_cli",
        description="Zugänge zu diesem Dienst verwalten. "
                    "Ein Token je Person, kein Ablaufdatum.",
    )
    gruppe = zerleger.add_mutually_exclusive_group(required=True)
    gruppe.add_argument("--anlegen", metavar="NAME",
                        help="Legt einen Zugang an und zeigt seinen Token einmal")
    gruppe.add_argument("--entziehen", metavar="ID_ODER_NAME",
                        help="Löscht einen Zugang. Nicht über den Tokenwert — "
                             "den hat man gerade nicht zur Hand")
    gruppe.add_argument("--auflisten", action="store_true",
                        help="Alle Zugänge, ohne Token")
    zerleger.add_argument("--organisation", default="")
    zerleger.add_argument("--rolle", default="nutzer", choices=ROLLEN)
    werte = zerleger.parse_args(argv)

    if werte.anlegen:
        return _anlegen(werte.anlegen, werte.organisation, werte.rolle)
    if werte.entziehen:
        return _entziehen(werte.entziehen)
    return _auflisten()


if __name__ == "__main__":
    print(f"Datenbank: {db_pfad()}", file=sys.stderr)
    raise SystemExit(main())
