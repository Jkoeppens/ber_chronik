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

from src.neu import pfade

# WURZEL und die Datenpfade stehen in src/neu/pfade.py.

LOKALER_TOKEN = "lokal"
LOKALER_NAME = "Lokaler Zugang"


class ProjektFehler(Exception):
    def __init__(self, meldung: str, code: str = "projekt_fehler"):
        super().__init__(meldung)
        self.code = code


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Gibt es das Projekt? ──────────────────────────────────────────────────────
# Die Frage stand fünfzehnmal als eigenes SELECT im Bestand, achtmal allein in
# server.py. Sie hier zu stellen ist kein Selbstzweck: die Bedingung
# ('WHERE id = ?', nicht etwa auch ein Status) gehört zum Projektbegriff, und
# wer sie ändert, soll das an einer Stelle tun.
#
# Zwei Fassungen, weil die Aufrufer zwei verschiedene Ausnahmen werfen: jeder
# Dienst meldet seinen eigenen Fehler mit seinem eigenen Code, und den soll
# dieses Modul ihm nicht wegnehmen.

def gibt_es(con: sqlite3.Connection, projekt_id: str) -> bool:
    """Ob es ein Projekt mit dieser Kennung gibt."""
    return con.execute(
        "SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone() is not None


def pruefen(con: sqlite3.Connection, projekt_id: str) -> None:
    """Wirft ProjektFehler('projekt_nicht_gefunden'), wenn es das Projekt nicht gibt."""
    if not gibt_es(con, projekt_id):
        raise ProjektFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )


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
    if gibt_es(con, projekt_id):
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

def export_verzeichnis(projekt_id: str) -> Path:
    """Wohin dieses System exportiert. Siehe pfade.export_verzeichnis()."""
    return pfade.export_verzeichnis(projekt_id)


def _export_datei(projekt_id: str) -> Path:
    """Für hat_export: auch ein mitgeliefertes Verzeichnis zählt."""
    quelle = pfade.export_quelle(projekt_id)
    return (quelle or export_verzeichnis(projekt_id)) / "data.json"


def _export_vorhanden(projekt_id: str) -> bool:
    return _export_datei(projekt_id).exists()


def _export_am(projekt_id: str) -> str | None:
    """Wann zuletzt exportiert wurde — aus der Datei, nicht aus der lauf-Zeile.

    'Befüllt' heißt bei diesem Schritt: die Dateien liegen da. Dann ist auch
    ihr Zeitstempel die richtige Auskunft; eine lauf-Zeile kann auf einen Lauf
    zeigen, dessen Ergebnis inzwischen gelöscht wurde.
    """
    datei = _export_datei(projekt_id)
    if not datei.exists():
        return None
    return datetime.fromtimestamp(
        datei.stat().st_mtime, tz=timezone.utc
    ).isoformat(timespec="seconds")


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
        "export_am": _export_am(projekt_id),
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
    """Alle Projekte, das Neueste zuerst.

    Vorher aufsteigend: ein gerade angelegtes Projekt stand ganz unten, hinter
    allen älteren, und musste gesucht werden. Wer die Liste öffnet, meint
    meistens das, woran er zuletzt gearbeitet hat.
    """
    ids = [z[0] for z in con.execute(
        "SELECT id FROM projekt ORDER BY angelegt_am DESC, id DESC")]
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
        "export_am": grund["export_am"],
        "laeufe": laeufe,
    }


def einheiten(
    con: sqlite3.Connection, projekt_id: str, typ: str | None = None
) -> dict:
    """Alle Einheiten eines Projekts, nach Quelle und Position sortiert.

    Unbekanntes Projekt → ProjektFehler. Bekanntes Projekt ohne Treffer → leere
    Liste: das ist ein gültiges leeres Ergebnis, kein fehlender Gegenstand.

    Die Abfrage stand vorher im Endpoint. Sie gehört hierher, weil sie dieselbe
    Verbindung Projekt→Quelle→Einheit zieht wie kennzahlen() darüber, und weil
    ein Endpoint, der sein eigenes SQL schreibt, keinen Dienst mehr hat, den
    ein zweiter Aufrufer benutzen könnte.
    """
    pruefen(con, projekt_id)

    sql = ("SELECT e.* FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
           "WHERE q.projekt_id = ?")
    args: list = [projekt_id]
    if typ is not None:
        sql += " AND e.typ = ?"
        args.append(typ)
    sql += " ORDER BY e.quelle_id, e.position"

    zeilen = [dict(z) for z in con.execute(sql, args).fetchall()]
    return {
        "projekt_id": projekt_id,
        "anzahl": len(zeilen),
        "typ_filter": typ,
        "einheiten": zeilen,
    }


def loeschen(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Löscht ein Projekt samt allem, was daran hängt.

    Quellen, Einheiten, Kategorien, Akteure und Läufe gehen über
    ON DELETE CASCADE mit. Die Exportdateien unter data/projects/ bleiben
    liegen — sie sind ein Erzeugnis, kein Bestandteil des Projekts, und Dateien
    zu löschen ist nicht Sache dieses Diensts.

    Die Zahl der gelöschten Einheiten wird vorher gezählt: hinterher gibt es
    sie nicht mehr, und ein Löschen, das nicht sagt, was es mitgenommen hat,
    ist schlecht zu prüfen.
    """
    zeile = con.execute(
        "SELECT titel FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone()
    if zeile is None:
        raise ProjektFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )
    anzahl = con.execute(
        "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ?", (projekt_id,)
    ).fetchone()[0]

    with con:
        con.execute("DELETE FROM projekt WHERE id = ?", (projekt_id,))

    return {"projekt_id": projekt_id, "titel": zeile[0], "geloeschte_einheiten": anzahl}
