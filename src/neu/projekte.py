"""
projekte.py — Projekte anlegen und ihre Kennzahlen ausrechnen

Alle Zahlen hier sind gerechnet, keine steht in einer Konfigurationsdatei:
anzahl_einheiten ist ein COUNT(*), der Zeitraum MIN/MAX über die Einheiten. Das
alte System las `entry_count` aus `exploration/data.json` und `year_min` aus
`config.json` — beide konnten veralten, ohne dass es jemandem auffiel.

Der Eigentümer: projekt.eigentuemer_id ist NOT NULL und zeigt auf zugang. Ohne
Anmeldung gibt es niemanden, dem ein Projekt gehören könnte. Bis Schritt 8 einen
echten Zugang bringt, gehört alles einer festen lokalen Zeile, die beim ersten
Anlegen entsteht. Sie ist an ihrem Token erkennbar und später umzuhängen:

    UPDATE projekt SET eigentuemer_id = <neu> WHERE eigentuemer_id = <lokal>;

Das ist bewusst eine Zeile in der Tabelle und kein Sonderfall im Code: der
Fremdschlüssel bleibt scharf, und niemand muss sich merken, dass 0 oder NULL
etwas Besonderes bedeuten.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent.parent

LOKALER_TOKEN = "lokal"
LOKALER_NAME = "Lokaler Zugang"


class ProjektFehler(Exception):
    def __init__(self, meldung: str, code: str = "projekt_fehler"):
        super().__init__(meldung)
        self.code = code


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kennung_aus_titel(titel: str) -> str:
    """Macht aus 'Damaskus 1908–1918' die Kennung 'damaskus-1908-1918'.

    Umlaute werden ausgeschrieben, alles Übrige auf a–z, 0–9 und Bindestrich
    zurückgeführt. Eine Kennung steht in Pfaden (data/projects/<id>/) und in
    URLs; sie darf deshalb nichts enthalten, was dort etwas anderes bedeutet.
    """
    text = titel.strip().lower()
    for von, nach in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(von, nach)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(z for z in text if not unicodedata.combining(z))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def lokaler_zugang(con: sqlite3.Connection) -> int:
    """Die Kennung des lokalen Zugangs; legt ihn beim ersten Aufruf an."""
    zeile = con.execute(
        "SELECT id FROM zugang WHERE token = ?", (LOKALER_TOKEN,)
    ).fetchone()
    if zeile is not None:
        return zeile[0]
    with con:
        zeiger = con.execute(
            "INSERT INTO zugang (token, name, rolle, angelegt_am) "
            "VALUES (?, ?, 'verwalter', ?)",
            (LOKALER_TOKEN, LOKALER_NAME, _jetzt()),
        )
    return zeiger.lastrowid


def anlegen(con: sqlite3.Connection, titel: str, kennung: str | None = None) -> dict:
    """Legt ein Projekt an und gibt seine Zeile zurück."""
    titel = titel.strip()
    if not titel:
        raise ProjektFehler("titel darf nicht leer sein.", "titel_leer")

    projekt_id = (kennung or kennung_aus_titel(titel)).strip()
    if not projekt_id:
        raise ProjektFehler(
            f"Aus '{titel}' lässt sich keine Kennung bilden. "
            "Bitte eine eigene angeben (a–z, 0–9, Bindestrich).",
            "kennung_leer",
        )
    if projekt_id != kennung_aus_titel(projekt_id):
        raise ProjektFehler(
            f"'{projekt_id}' ist keine gültige Kennung. Erlaubt sind a–z, 0–9 "
            "und Bindestrich.",
            "kennung_ungueltig",
        )
    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone():
        raise ProjektFehler(
            f"Es gibt schon ein Projekt mit der Kennung '{projekt_id}'.",
            "projekt_gibt_es_schon",
        )

    eigentuemer = lokaler_zugang(con)
    with con:
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES (?, ?, ?, ?)",
            (projekt_id, titel, eigentuemer, _jetzt()),
        )
    return zeile(con, projekt_id)


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _export_vorhanden(projekt_id: str) -> bool:
    return (WURZEL / "data" / "projects" / projekt_id / "exploration" / "data.json").exists()


def _aggregate(con: sqlite3.Connection, projekt_id: str) -> dict:
    formate = [z[0] for z in con.execute(
        "SELECT DISTINCT quellformat FROM quelle WHERE projekt_id = ? "
        "ORDER BY quellformat", (projekt_id,))]
    quellen = con.execute(
        "SELECT COUNT(*) FROM quelle WHERE projekt_id = ?", (projekt_id,)
    ).fetchone()[0]
    einheiten, jahr_von, jahr_bis = con.execute(
        "SELECT COUNT(*), MIN(e.jahr_von), MAX(COALESCE(e.jahr_bis, e.jahr_von)) "
        "FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content'", (projekt_id,)
    ).fetchone()
    return {
        "quellformate": formate,
        "anzahl_quellen": quellen,
        "anzahl_einheiten": einheiten,
        "jahr_von": jahr_von,
        "jahr_bis": jahr_bis,
        "hat_export": _export_vorhanden(projekt_id),
    }


def zeile(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Ein Projekt samt seiner Zahlen, wie die Übersicht es zeigt."""
    z = con.execute(
        "SELECT id, titel, eigentuemer_id, angelegt_am, oeffentlich, dropbox_ordner "
        "FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone()
    if z is None:
        raise ProjektFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )
    return {
        "id": z[0], "titel": z[1], "eigentuemer_id": z[2], "angelegt_am": z[3],
        "oeffentlich": bool(z[4]), "dropbox_ordner": z[5],
        **_aggregate(con, projekt_id),
    }


def liste(con: sqlite3.Connection) -> list[dict]:
    ids = [z[0] for z in con.execute(
        "SELECT id FROM projekt ORDER BY angelegt_am, id")]
    return [zeile(con, i) for i in ids]


def kennzahlen(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Alles, was die Projektseite anzeigt — in einem Zug gelesen."""
    grund = zeile(con, projekt_id)

    je_typ: dict[str, int] = {}
    for typ, n in con.execute(
        "SELECT e.typ, COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? GROUP BY e.typ ORDER BY COUNT(*) DESC", (projekt_id,)
    ):
        je_typ[typ] = n

    def zaehle(bedingung: str) -> int:
        return con.execute(
            "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
            f"WHERE q.projekt_id = ? AND e.typ = 'content' AND {bedingung}",
            (projekt_id,),
        ).fetchone()[0]

    datiert = zaehle("e.jahr_von IS NOT NULL")
    klassifiziert = zaehle("e.kategorie_id IS NOT NULL")

    laeufe = [{"id": z[0], "schritt": z[1], "status": z[2],
               "begonnen_am": z[3], "beendet_am": z[4]}
              for z in con.execute(
                  "SELECT id, schritt, status, begonnen_am, beendet_am FROM lauf "
                  "WHERE projekt_id = ? ORDER BY id DESC LIMIT 20", (projekt_id,))]

    return {
        "projekt_id": grund["id"],
        "titel": grund["titel"],
        "quellformate": grund["quellformate"],
        "anzahl_quellen": grund["anzahl_quellen"],
        "anzahl_einheiten": grund["anzahl_einheiten"],
        "anzahl_je_typ": je_typ,
        "anzahl_datiert": datiert,
        "anzahl_ohne_datum": grund["anzahl_einheiten"] - datiert,
        "anzahl_kategorien": con.execute(
            "SELECT COUNT(*) FROM kategorie WHERE projekt_id = ?", (projekt_id,)
        ).fetchone()[0],
        "anzahl_klassifiziert": klassifiziert,
        "anzahl_akteure": con.execute(
            "SELECT COUNT(*) FROM akteur WHERE projekt_id = ? AND status = 'aktiv'",
            (projekt_id,)
        ).fetchone()[0],
        "anzahl_fundstellen": con.execute(
            "SELECT COUNT(*) FROM einheit_akteur ea JOIN akteur a ON a.id = ea.akteur_id "
            "WHERE a.projekt_id = ?", (projekt_id,)
        ).fetchone()[0],
        "jahr_von": grund["jahr_von"],
        "jahr_bis": grund["jahr_bis"],
        "hat_export": grund["hat_export"],
        "laeufe": laeufe,
    }
