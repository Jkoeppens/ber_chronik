"""
anmeldung.py — der Dropbox-Anmeldevorgang, in der Datenbank

Zwischen dem Beginn der Anmeldung und der Rückleitung von Dropbox liegt ein
Besuch beim Nutzer. Das alte System hielt den Zustand in einem Wörterbuch im
Arbeitsspeicher (`_obsidian_oauth_states` in dev_server.py) — mit zwei Folgen:

- Ein Neustart zwischen 'start' und 'rueckleitung' ließ die Anmeldung mit
  "Ungültiger OAuth-State" auflaufen.
- Ein Neustart zwischen 'rueckleitung' und dem Speichern verlor die
  Zugangsdaten stillschweigend: sie lagen unter dem Schlüssel 'pending' im
  selben Wörterbuch.

Beides ist auf Railway kein Randfall, sondern Alltag. Hier steht der Zustand in
der Tabelle `anmeldung`, und der Token wird beim Eintreffen sofort an
`projekt.dropbox_token` geschrieben — nicht erst beim nächsten Formular.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from src.neu import projekte
from src.neu.ingest import dropbox_anbindung

# Wie lange ein begonnener Vorgang gültig bleibt. Wer länger braucht, fängt neu
# an; liegengebliebene Zeilen sollen nicht ewig stehen.
FRIST_MINUTEN = 30


class AnmeldungFehler(Exception):
    def __init__(self, meldung: str, code: str = "anmeldung_fehler"):
        super().__init__(meldung)
        self.code = code


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def beginnen(con: sqlite3.Connection, projekt_id: str | None = None) -> dict:
    """Beginnt einen Anmeldevorgang und legt ihn ab. Gibt die Adresse zurück."""
    if projekt_id is not None:
        if not projekte.gibt_es(con, projekt_id):
            raise AnmeldungFehler(
                f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
            )

    auth_url, csrf, sitzung = dropbox_anbindung.anmeldung_beginnen()
    with con:
        aufraeumen(con)
        con.execute(
            "INSERT INTO anmeldung (csrf, projekt_id, sitzung, begonnen_am) "
            "VALUES (?, ?, ?, ?)",
            (csrf, projekt_id, json.dumps(sitzung, ensure_ascii=False), _jetzt()),
        )
    return {"auth_url": auth_url, "csrf": csrf, "projekt_id": projekt_id}


def beenden(con: sqlite3.Connection, code: str, state: str) -> dict:
    """Löst den Code ein und schreibt den refresh_token ans Projekt."""
    zeile = con.execute(
        "SELECT projekt_id, sitzung FROM anmeldung WHERE csrf = ?", (state,)
    ).fetchone()
    if zeile is None:
        raise AnmeldungFehler(
            "Zu dieser Rückleitung gibt es keinen begonnenen Vorgang. Entweder "
            "ist er älter als eine halbe Stunde, oder die Anmeldung wurde "
            "zweimal abgeschlossen. Bitte neu beginnen.",
            "anmeldung_unbekannt",
        )
    projekt_id, sitzung_roh = zeile[0], json.loads(zeile[1])

    # Der Tausch geht ins Netz und kann scheitern. Erst danach wird aufgeräumt:
    # ein Fehlschlag soll den Vorgang nicht verbrauchen.
    refresh_token = dropbox_anbindung.anmeldung_beenden(sitzung_roh, code, state)

    with con:
        if projekt_id:
            con.execute(
                "UPDATE projekt SET dropbox_token = ? WHERE id = ?",
                (refresh_token, projekt_id),
            )
        con.execute("DELETE FROM anmeldung WHERE csrf = ?", (state,))

    if not projekt_id:
        raise AnmeldungFehler(
            "Die Anmeldung war keinem Projekt zugeordnet. Der Zugang wurde "
            "verworfen — bitte die Anmeldung aus dem Projekt heraus beginnen.",
            "anmeldung_ohne_projekt",
        )
    return {"projekt_id": projekt_id, "verbunden": True}


def aufraeumen(con: sqlite3.Connection) -> int:
    """Entfernt abgelaufene Vorgänge. Gibt zurück, wie viele es waren."""
    grenze = (datetime.now(timezone.utc) - timedelta(minutes=FRIST_MINUTEN)).isoformat(
        timespec="seconds"
    )
    zeiger = con.execute("DELETE FROM anmeldung WHERE begonnen_am < ?", (grenze,))
    return zeiger.rowcount or 0


# ── Verbindung eines Projekts ─────────────────────────────────────────────────

def verbindung(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Was über die Dropbox-Verbindung eines Projekts bekannt ist.

    Der Verbindungsstatus kommt aus projekt.dropbox_token — nicht aus einer
    Datei, die mit den benutzten Zugangsdaten nichts zu tun hat.
    """
    zeile = con.execute(
        "SELECT dropbox_ordner, dropbox_token FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone()
    if zeile is None:
        raise AnmeldungFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )
    return {
        "projekt_id": projekt_id,
        "verbunden": bool(zeile[1]),
        "ordner": zeile[0],
        "anbieter_bereit": dropbox_anbindung.verfuegbar(),
    }


def ordner_setzen(con: sqlite3.Connection, projekt_id: str, ordner: str) -> dict:
    """Trägt den Ordner ein, gegen den gelesen wird."""
    normal = dropbox_anbindung.ordner_normalisieren(ordner)
    if not normal:
        raise AnmeldungFehler("Der Ordner darf nicht leer sein.", "ordner_leer")
    stand = verbindung(con, projekt_id)
    with con:
        con.execute(
            "UPDATE projekt SET dropbox_ordner = ? WHERE id = ?", (normal, projekt_id)
        )
    return {**stand, "ordner": normal}


def token(con: sqlite3.Connection, projekt_id: str) -> str:
    """Der refresh_token des Projekts, oder ein Abbruch mit klarer Meldung."""
    stand = verbindung(con, projekt_id)
    if not stand["verbunden"]:
        raise AnmeldungFehler(
            f"Projekt '{projekt_id}' ist nicht mit Dropbox verbunden. "
            "Zuerst anmelden.",
            "dropbox_nicht_verbunden",
        )
    return con.execute(
        "SELECT dropbox_token FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone()[0]
