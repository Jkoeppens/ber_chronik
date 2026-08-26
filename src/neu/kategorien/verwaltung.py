"""
verwaltung.py — Kategorien von Hand pflegen

Anlegen, ändern, löschen. Was hier tatsächlich geändert wird, bekommt
`herkunft='manuell'`: einem Namen soll anzusehen sein, ob je ein Mensch ihn
geprüft hat. Ein Taxonomielauf ersetzt nur, was er selbst vorgeschlagen hat —
das ist die Regel aus SCHEMA.md, und sie hat nur Bestand, wenn die Herkunft
beim Bearbeiten mitgeführt wird. Umgesetzt ist sie in
src/neu/taxonomie/dienst.py: `manuell`-Zeilen gehen als eingefrorene Cluster in
den Lauf und werden nicht überschrieben.

Beim Löschen einer Kategorie greift ON DELETE SET NULL: die Einheiten bleiben,
ihre Kategorie ist danach offen. `kategorie_herkunft` bleibt dabei stehen; ein
Lauf mit Umfang 'offen' greift sie trotzdem wieder auf, weil er sich nimmt, was
gerade keine Kategorie hat.
"""

from __future__ import annotations

import sqlite3

from src.neu import projekte


class KategorieFehler(Exception):
    def __init__(self, meldung: str, code: str = "kategorie_fehler"):
        super().__init__(meldung)
        self.code = code


def _projekt_pruefen(con: sqlite3.Connection, projekt_id: str) -> None:
    if not projekte.gibt_es(con, projekt_id):
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


def stapel_aendern(
    con: sqlite3.Connection, projekt_id: str, eintraege: list[dict]
) -> dict:
    """Speichert die ganze Liste auf einmal.

    Der Editor hat keinen Zwischenstand: entweder alles oder nichts. Wer ihn
    ohne Speichern verlässt, bekommt beim nächsten Mal die alte Beschreibung.

    Angelegt wird, was keine `id` hat; geändert, was eine hat; gelöscht, was in
    der Liste fehlt. Die Zuordnung danach ist Sache des Aufrufers.

    'manuell' wird nur, was sich tatsächlich geändert hat. Der Editor schickt
    bei jedem Speichern die ganze Liste — würde jede Zeile gestempelt, wäre
    nach dem ersten Speichern einer einzigen Beschreibung die gesamte Taxonomie
    von Hand geprüft. Da ein Taxonomielauf 'manuell'-Zeilen nicht mehr anfasst
    (src/neu/taxonomie/dienst.py), hätte ein Speichern das Verfeinern damit
    stillgelegt. Die Spalte soll sagen, ob ein Mensch diesen Namen geprüft hat,
    nicht ob er einmal auf dieser Seite war.
    """
    _projekt_pruefen(con, projekt_id)

    vorhanden = {z[0] for z in con.execute(
        "SELECT id FROM kategorie WHERE projekt_id = ?", (projekt_id,))}
    genannt = {e["id"] for e in eintraege if e.get("id")}
    fehlend = genannt - vorhanden
    if fehlend:
        raise KategorieFehler(
            f"Kategorie {sorted(fehlend)[0]} gehört nicht zu '{projekt_id}'.",
            "kategorie_nicht_gefunden",
        )

    namen = [(e.get("name") or "").strip() for e in eintraege]
    if any(not n for n in namen):
        raise KategorieFehler("Jede Kategorie braucht einen Namen.", "name_leer")
    if len(set(namen)) != len(namen):
        doppelt = next(n for n in namen if namen.count(n) > 1)
        raise KategorieFehler(
            f"'{doppelt}' kommt zweimal vor.", "kategorie_gibt_es_schon"
        )

    alt = {z[0]: (z[1], z[2], z[3]) for z in con.execute(
        "SELECT id, name, beschreibung, schlagworte FROM kategorie WHERE projekt_id = ?",
        (projekt_id,))}

    with con:
        # Erst löschen: sonst kollidiert ein umbenannter Name mit einem, der
        # gleich verschwindet.
        weg = vorhanden - genannt
        for kategorie_id in weg:
            con.execute("DELETE FROM kategorie WHERE id = ?", (kategorie_id,))
        angelegt = geaendert = 0
        for eintrag in eintraege:
            werte = ((eintrag.get("name") or "").strip(),
                     (eintrag.get("beschreibung") or "").strip(),
                     ",".join(eintrag.get("schlagworte") or []))
            if eintrag.get("id"):
                if werte == alt.get(eintrag["id"]):
                    continue        # unverändert durchgereicht — nicht angefasst
                geaendert += 1
                con.execute(
                    "UPDATE kategorie SET name = ?, beschreibung = ?, "
                    "schlagworte = ?, herkunft = 'manuell' WHERE id = ?",
                    (*werte, eintrag["id"]),
                )
            else:
                con.execute(
                    "INSERT INTO kategorie (projekt_id, name, beschreibung, "
                    "schlagworte, herkunft) VALUES (?, ?, ?, ?, 'manuell')",
                    (projekt_id, *werte),
                )
                angelegt += 1

    return {"projekt_id": projekt_id, "anzahl": len(eintraege),
            "angelegt": angelegt, "geloescht": len(weg),
            "geaendert": geaendert}


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
