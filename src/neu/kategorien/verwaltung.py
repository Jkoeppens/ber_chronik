"""
verwaltung.py — Kategorien von Hand pflegen

Anlegen, ändern, löschen. Alles, was hier durchgeht, bekommt
`herkunft='manuell'`: einem Namen soll anzusehen sein, ob je ein Mensch ihn
geprüft hat. Ein Taxonomielauf ersetzt nur, was er selbst vorgeschlagen hat —
das ist die Regel aus SCHEMA.md, und sie hat nur Bestand, wenn die Herkunft
beim Bearbeiten mitgeführt wird.

Beim Löschen einer Kategorie greift ON DELETE SET NULL: die Einheiten bleiben,
ihre Kategorie ist danach offen. `kategorie_herkunft` bleibt dabei stehen —
eine Einheit, die einmal von Hand zugeordnet war, gilt weiter als von Hand
behandelt und wird von einem Lauf mit Umfang 'offen' nicht wieder aufgegriffen.
Darauf weist diese Stelle beim Löschen hin, statt es stillschweigend zu tun.
"""

from __future__ import annotations

import sqlite3


class KategorieFehler(Exception):
    def __init__(self, meldung: str, code: str = "kategorie_fehler"):
        super().__init__(meldung)
        self.code = code


def _projekt_pruefen(con: sqlite3.Connection, projekt_id: str) -> None:
    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise KategorieFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )


def _schlagworte(roh: str | None) -> list[str]:
    return [w.strip() for w in (roh or "").split(",") if w.strip()]


def liste(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Alle Kategorien eines Projekts samt der Zahl der Einheiten darauf."""
    _projekt_pruefen(con, projekt_id)

    zahlen = {z[0]: z[1] for z in con.execute(
        "SELECT e.kategorie_id, COUNT(*) FROM einheit e "
        "JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' AND e.kategorie_id IS NOT NULL "
        "GROUP BY e.kategorie_id", (projekt_id,))}

    kategorien = [{
        "id": z[0], "projekt_id": projekt_id, "name": z[1],
        "beschreibung": z[2], "schlagworte": _schlagworte(z[3]),
        "herkunft": z[4], "anzahl_einheiten": zahlen.get(z[0], 0),
    } for z in con.execute(
        "SELECT id, name, beschreibung, schlagworte, herkunft FROM kategorie "
        "WHERE projekt_id = ? ORDER BY id", (projekt_id,))]

    def zaehle(bedingung: str) -> int:
        return con.execute(
            "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
            f"WHERE q.projekt_id = ? AND e.typ = 'content' AND {bedingung}",
            (projekt_id,),
        ).fetchone()[0]

    return {
        "projekt_id": projekt_id,
        "anzahl": len(kategorien),
        "kategorien": kategorien,
        "anzahl_ohne_kategorie": zaehle("e.kategorie_id IS NULL"),
        "anzahl_manuell_zugeordnet": zaehle("e.kategorie_herkunft = 'manuell'"),
    }


def anlegen(
    con: sqlite3.Connection, projekt_id: str, name: str,
    beschreibung: str = "", schlagworte: list[str] | None = None,
) -> dict:
    """Legt eine Kategorie an — von Hand, also herkunft='manuell'."""
    _projekt_pruefen(con, projekt_id)
    name = (name or "").strip()
    if not name:
        raise KategorieFehler("Der Name darf nicht leer sein.", "name_leer")
    if con.execute("SELECT 1 FROM kategorie WHERE projekt_id = ? AND name = ?",
                   (projekt_id, name)).fetchone():
        raise KategorieFehler(
            f"'{name}' gibt es in diesem Projekt schon.", "kategorie_gibt_es_schon"
        )
    with con:
        zeiger = con.execute(
            "INSERT INTO kategorie (projekt_id, name, beschreibung, schlagworte, "
            "herkunft) VALUES (?, ?, ?, ?, 'manuell')",
            (projekt_id, name, (beschreibung or "").strip(),
             ",".join(schlagworte or [])),
        )
    return einzeln(con, zeiger.lastrowid)


def aendern(
    con: sqlite3.Connection, kategorie_id: int, name: str | None = None,
    beschreibung: str | None = None, schlagworte: list[str] | None = None,
) -> dict:
    """Ändert eine Kategorie. Sie gilt danach als 'manuell'."""
    zeile = con.execute(
        "SELECT projekt_id, name, beschreibung, schlagworte FROM kategorie WHERE id = ?",
        (kategorie_id,),
    ).fetchone()
    if zeile is None:
        raise KategorieFehler(
            f"Keine Kategorie mit der Kennung {kategorie_id}.", "kategorie_nicht_gefunden"
        )
    projekt_id, alter_name, alte_beschreibung, alte_schlagworte = zeile

    neuer_name = (name if name is not None else alter_name).strip()
    if not neuer_name:
        raise KategorieFehler("Der Name darf nicht leer sein.", "name_leer")
    if neuer_name != alter_name and con.execute(
        "SELECT 1 FROM kategorie WHERE projekt_id = ? AND name = ? AND id <> ?",
        (projekt_id, neuer_name, kategorie_id),
    ).fetchone():
        raise KategorieFehler(
            f"'{neuer_name}' gibt es in diesem Projekt schon.", "kategorie_gibt_es_schon"
        )

    with con:
        con.execute(
            "UPDATE kategorie SET name = ?, beschreibung = ?, schlagworte = ?, "
            "herkunft = 'manuell' WHERE id = ?",
            (neuer_name,
             (beschreibung if beschreibung is not None else alte_beschreibung).strip(),
             ",".join(schlagworte) if schlagworte is not None else alte_schlagworte,
             kategorie_id),
        )
    return einzeln(con, kategorie_id)


def loeschen(con: sqlite3.Connection, kategorie_id: int) -> dict:
    """Löscht eine Kategorie. Die Einheiten bleiben, ihre Zuordnung wird NULL."""
    zeile = con.execute(
        "SELECT projekt_id, name FROM kategorie WHERE id = ?", (kategorie_id,)
    ).fetchone()
    if zeile is None:
        raise KategorieFehler(
            f"Keine Kategorie mit der Kennung {kategorie_id}.", "kategorie_nicht_gefunden"
        )
    betroffen = con.execute(
        "SELECT COUNT(*) FROM einheit WHERE kategorie_id = ?", (kategorie_id,)
    ).fetchone()[0]
    with con:
        con.execute("DELETE FROM kategorie WHERE id = ?", (kategorie_id,))
    return {"kategorie_id": kategorie_id, "name": zeile[1],
            "projekt_id": zeile[0], "einheiten_ohne_kategorie": betroffen}


def einzeln(con: sqlite3.Connection, kategorie_id: int) -> dict:
    z = con.execute(
        "SELECT id, projekt_id, name, beschreibung, schlagworte, herkunft "
        "FROM kategorie WHERE id = ?", (kategorie_id,)
    ).fetchone()
    if z is None:
        raise KategorieFehler(
            f"Keine Kategorie mit der Kennung {kategorie_id}.", "kategorie_nicht_gefunden"
        )
    anzahl = con.execute(
        "SELECT COUNT(*) FROM einheit WHERE kategorie_id = ?", (kategorie_id,)
    ).fetchone()[0]
    return {"id": z[0], "projekt_id": z[1], "name": z[2], "beschreibung": z[3],
            "schlagworte": _schlagworte(z[4]), "herkunft": z[5],
            "anzahl_einheiten": anzahl}
