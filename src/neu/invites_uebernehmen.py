"""
invites_uebernehmen.py — Einladungstoken aus invites.json nach zugang holen

    python3 -m src.neu.invites_uebernehmen                      # data/invites.json
    python3 -m src.neu.invites_uebernehmen --datei /data/invites.json
    python3 -m src.neu.invites_uebernehmen --probe              # nur zeigen

Das alte System hatte vor der Tabelle zugang ein Einladungs-Gate: ein Token im
Kopf X-Invite-Token, die Liste als JSON auf dem Laufwerk. Seit der neue Server
läuft, gibt es dieses Gate nicht mehr — wer so einen Token hat, kommt nicht
mehr herein. Dieses Skript holt die Einträge in die Tabelle, damit sie
weitergelten.

GESTALT der Quelldatei, so wie invite_auth.gen_invite() sie schreibt:

    { "<16 Hexzeichen>": {"name": "…", "org": "…"} }

Zwei Felder, sonst nichts: kein Ablaufdatum, keine Rolle, kein Anlegedatum.
Entsprechend wird hier nichts erfunden — rolle ist 'nutzer' für alle,
angelegt_am ist der Zeitpunkt der Übernahme, und ein leerer Name bleibt leer.

EINMALIG gedacht, aber mehrfach ausführbar: eine Kollision auf token (UNIQUE)
überspringt die Zeile, statt sie zu überschreiben. Überschreiben wäre ein
stiller Verlust — hinter einer vorhandenen Zeile kann ein anderer Mensch
stehen als hinter dem gleichnamigen Eintrag in der Datei.

LÄUFT LOKAL UND IM CONTAINER. Die Datenbank bestimmt sich wie überall über
src/neu/pfade (DATA_ROOT, NEU_DB); im Container zeigt das aufs Laufwerk. Die
Quelldatei wird ausdrücklich angegeben oder unter der Datenwurzel gesucht.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.neu import pfade
from src.neu.db import db_pfad, verbindung_schreibend


def vorgabe_datei() -> Path:
    """Wo die Liste liegt, wenn niemand etwas anderes sagt.

    Unter der Datenwurzel und nicht im Quellbestand: invite_auth.py liest
    DATA_ROOT/invites.json, und im Container ist das /data/invites.json.
    """
    return pfade.daten_wurzel() / "invites.json"


def einlesen(pfad: Path) -> dict[str, dict]:
    """Die Liste als {token: {name, org}}. Wirft bei allem, was nicht passt.

    Streng und ohne Rückfall: eine halb verstandene Liste stillschweigend zur
    Hälfte zu übernehmen wäre schlimmer als ein Abbruch. Wer dreizehn Einträge
    erwartet und sieben bekommt, sucht lange.
    """
    roh = json.loads(pfad.read_text(encoding="utf-8"))
    if not isinstance(roh, dict):
        raise ValueError(
            f"{pfad} enthält kein Objekt, sondern {type(roh).__name__}. "
            "Erwartet wird {token: {name, org}}."
        )
    for token, eintrag in roh.items():
        if not isinstance(token, str) or not token.strip():
            raise ValueError(f"{pfad}: ein Eintrag hat keinen Token.")
        if not isinstance(eintrag, dict):
            raise ValueError(
                f"{pfad}: der Eintrag zu einem Token ist "
                f"{type(eintrag).__name__}, erwartet wird ein Objekt."
            )
    return roh


def uebernehmen(
    con: sqlite3.Connection, liste: dict[str, dict], probe: bool = False
) -> dict:
    """Schreibt die Einträge in zugang. Gibt die Zählung zurück, nie Token.

    Eine Transaktion für alles: entweder sind alle drin oder keiner. Auf halbem
    Weg abzubrechen hieße, beim zweiten Versuch raten zu müssen, wo es stand —
    das Überspringen bei Kollision macht einen zweiten Lauf zwar harmlos, aber
    harmlos ist nicht dasselbe wie nachvollziehbar.
    """
    jetzt = datetime.now(timezone.utc).isoformat(timespec="seconds")
    vorhanden = {z[0] for z in con.execute("SELECT token FROM zugang")}

    neu: list[tuple] = []
    uebersprungen = 0
    for token, eintrag in liste.items():
        if token in vorhanden:
            uebersprungen += 1
            continue
        neu.append((
            token,
            (eintrag.get("name") or "").strip(),
            (eintrag.get("org") or "").strip(),
            "nutzer",
            jetzt,
        ))

    if neu and not probe:
        with con:
            con.executemany(
                "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
                "VALUES (?, ?, ?, ?, ?)",
                neu,
            )

    return {
        "gelesen": len(liste),
        "uebernommen": len(neu),
        "uebersprungen": uebersprungen,
        "ohne_namen": sum(1 for z in neu if not z[1]),
        "zugang_gesamt": con.execute("SELECT COUNT(*) FROM zugang").fetchone()[0],
    }


def main(argv: list[str] | None = None) -> int:
    zerleger = argparse.ArgumentParser(
        prog="python3 -m src.neu.invites_uebernehmen",
        description="Einladungstoken aus invites.json in die Tabelle zugang holen.",
    )
    zerleger.add_argument(
        "--datei", type=Path, default=None,
        help=f"Die Liste. Vorgabe: {vorgabe_datei()}",
    )
    zerleger.add_argument(
        "--probe", action="store_true",
        help="Nur zeigen, was geschähe. Schreibt nichts.",
    )
    werte = zerleger.parse_args(argv)

    pfad = werte.datei or vorgabe_datei()
    if not pfad.is_file():
        print(f"Fehler: {pfad} gibt es nicht.", file=sys.stderr)
        return 1

    try:
        liste = einlesen(pfad)
    except (json.JSONDecodeError, ValueError) as fehler:
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1

    if not liste:
        print(f"{pfad} ist leer — nichts zu übernehmen.")
        return 0

    con = verbindung_schreibend()
    try:
        z = uebernehmen(con, liste, probe=werte.probe)
    finally:
        con.close()

    was = "Probe — nichts geschrieben" if werte.probe else "Übernommen"
    print(f"{was}.")
    print(f"  Quelle:       {pfad}")
    print(f"  Datenbank:    {db_pfad()}")
    print(f"  gelesen:      {z['gelesen']}")
    print(f"  übernommen:   {z['uebernommen']}"
          + (f"  (davon {z['ohne_namen']} ohne Namen)" if z["ohne_namen"] else ""))
    print(f"  übersprungen: {z['uebersprungen']}"
          + ("  (Token stand schon in zugang)" if z["uebersprungen"] else ""))
    print(f"  zugang jetzt: {z['zugang_gesamt']} Zeilen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
