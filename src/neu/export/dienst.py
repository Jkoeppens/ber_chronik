"""
dienst.py — die Exportdateien aus der Datenbank erzeugen

Liest das Projekt, lässt den Kern rechnen, schreibt die fünf Dateien, die
viz/ heute lädt, und legt eine lauf-Zeile an.

Kein print — wer etwas anzeigen will, nimmt das ExportErgebnis.

Die Zusammenfassungen stehen in akteur.zusammenfassung; entities_summary.json
ist nur die Ausgabedatei. Der Schalter dafür ist standardmäßig aus und gilt auf
jedem Weg — CLI wie Endpoint. Heute fehlt --no-summaries in dev_server.py:753
gegenüber :688, weshalb ein einzeln wiederholter Export ungewollt LLM-Läufe
auslöst.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from src.neu.export import kern
from src.neu.export.kern import Akteur, Einheit
from src.neu.projekte import export_verzeichnis


class ExportFehler(Exception):
    def __init__(self, meldung: str, code: str = "export_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class ExportErgebnis:
    projekt_id: str
    ziel: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    dateien: list[str] = field(default_factory=list)
    # Der Verlust, ausgezählt
    anzahl_einheiten: int = 0
    anzahl_mit_datum: int = 0
    anzahl_ohne_datum: int = 0
    anzahl_ohne_kategorie: int = 0
    anzahl_mit_akteur: int = 0
    anzahl_akteure: int = 0
    anzahl_knoten: int = 0
    anzahl_kanten: int = 0
    anzahl_je_kategorie: dict[str, int] = field(default_factory=dict)
    jahr_min: int | None = None
    jahr_max: int | None = None
    zusammenfassungen: int = 0


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _projekt(con: sqlite3.Connection, projekt_id: str) -> str:
    zeile = con.execute(
        "SELECT titel FROM projekt WHERE id = ?", (projekt_id,)
    ).fetchone()
    if zeile is None:
        raise ExportFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )
    return zeile[0] or projekt_id


def _einheiten(con: sqlite3.Connection, projekt_id: str) -> list[Einheit]:
    """Alle content-Einheiten mit Kategorie und Akteuren, in Dokumentreihenfolge."""
    zeilen = con.execute(
        "SELECT e.id, e.quelle_id, e.text, e.datum, e.jahr_von, e.jahr_bis, "
        "       k.name, e.publikation, e.publikationsdatum, e.url "
        "FROM einheit e "
        "JOIN quelle q ON q.id = e.quelle_id "
        "LEFT JOIN kategorie k ON k.id = e.kategorie_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' "
        "ORDER BY e.quelle_id, e.position",
        (projekt_id,),
    ).fetchall()

    akteure: dict[int, list[str]] = {}
    for einheit_id, normalform in con.execute(
        "SELECT DISTINCT ea.einheit_id, a.normalform "
        "FROM einheit_akteur ea "
        "JOIN akteur a ON a.id = ea.akteur_id "
        "JOIN einheit e ON e.id = ea.einheit_id "
        "JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND a.status = 'aktiv' "
        "ORDER BY ea.einheit_id, a.normalform",
        (projekt_id,),
    ):
        akteure.setdefault(einheit_id, []).append(normalform)

    return [Einheit(
        id=z[0], quelle_id=z[1], text=z[2] or "", datum=z[3],
        jahr_von=z[4], jahr_bis=z[5], kategorie=z[6],
        publikation=z[7], publikationsdatum=z[8], url=z[9],
        akteure=tuple(akteure.get(z[0], ())),
    ) for z in zeilen]


def _taxonomie(con: sqlite3.Connection, projekt_id: str) -> list[dict]:
    return [{"name": z[0], "description": z[1],
             "keywords": [k for k in (z[2] or "").split(",") if k.strip()]}
            for z in con.execute(
                "SELECT name, beschreibung, schlagworte FROM kategorie "
                "WHERE projekt_id = ? ORDER BY id", (projekt_id,))]


def _akteure(con: sqlite3.Connection, projekt_id: str) -> list[Akteur]:
    zeilen = con.execute(
        "SELECT id, normalform, typ, zusammenfassung FROM akteur "
        "WHERE projekt_id = ? AND status = 'aktiv' ORDER BY normalform",
        (projekt_id,),
    ).fetchall()
    if not zeilen:
        return []
    ids = [z[0] for z in zeilen]
    platz = ",".join("?" * len(ids))
    aliase: dict[int, list[str]] = {i: [] for i in ids}
    for akteur_id, alias in con.execute(
        f"SELECT akteur_id, alias FROM akteur_alias WHERE akteur_id IN ({platz}) "
        "ORDER BY alias", ids,
    ):
        aliase[akteur_id].append(alias)
    return [Akteur(normalform=z[1], typ=z[2], aliase=tuple(aliase[z[0]]),
                   zusammenfassung=z[3]) for z in zeilen]



# ── Schreiben ─────────────────────────────────────────────────────────────────

def _schreiben(pfad: Path, inhalt: str) -> str:
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad.name


def _json(daten) -> str:
    return json.dumps(daten, ensure_ascii=False, indent=2)


def exportieren(
    con: sqlite3.Connection,
    projekt_id: str,
    ziel: Path | None = None,
    zusammenfassungen: bool = False,
    heute: Callable[[], str] | None = None,
) -> ExportErgebnis:
    """Erzeugt data.json, entities_seed.csv, project_meta.json,
    network_layout.json und — auf Wunsch — entities_summary.json.

    zusammenfassungen=False ist die Vorgabe und gilt auf jedem Weg. Die Datei
    wird dann nicht geschrieben; viz/ fängt ihr Fehlen mit .catch(() => ({}))
    ab.
    """
    begonnen_am = _jetzt()
    verzeichnis = Path(ziel) if ziel is not None else export_verzeichnis(projekt_id)
    parameter = json.dumps(
        {"ziel": str(verzeichnis), "zusammenfassungen": zusammenfassungen},
        ensure_ascii=False,
    )

    titel = _projekt(con, projekt_id)

    try:
        einheiten = _einheiten(con, projekt_id)
        if not einheiten:
            raise ExportFehler(
                f"Projekt '{projekt_id}' hat keine content-Einheiten.",
                "keine_einheiten",
            )
        taxonomie = _taxonomie(con, projekt_id)
        akteure = _akteure(con, projekt_id)

        namen = [c["name"] for c in taxonomie if c.get("name")]
        liste = kern.eintraege(einheiten, namen)
        knoten, kanten = kern.netz(liste)
        meta = kern.metadaten(titel, taxonomie, einheiten)
        z = kern.zaehlung(liste, knoten, kanten, akteure)

        with con:
            zeiger = con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, status) "
                "VALUES (?, 'export', ?, ?, 'laeuft')",
                (projekt_id, begonnen_am, parameter),
            )
            lauf_id = zeiger.lastrowid

        verzeichnis.mkdir(parents=True, exist_ok=True)
        dateien: list[str] = []

        dateien.append(_schreiben(verzeichnis / "data.json", _json({
            "generated": str(date.today()) if heute is None else heute(),
            "count": len(liste),
            "entries": liste,
        })))
        dateien.append(_schreiben(verzeichnis / "entities_seed.csv",
                                  kern.alias_tabelle(akteure)))
        dateien.append(_schreiben(verzeichnis / "project_meta.json", _json(meta)))
        dateien.append(_schreiben(verzeichnis / "network_layout.json",
                                  _json(kern.layout(knoten, kanten))))

        anzahl_zf = 0
        if zusammenfassungen:
            inhalt = {
                a.normalform: {
                    "summary": a.zusammenfassung,
                    "paragraph_ids": [e["doc_anchor"] for e in liste
                                      if a.normalform in (e.get("actors") or [])],
                    "count": sum(1 for e in liste
                                 if a.normalform in (e.get("actors") or [])),
                }
                for a in akteure if a.zusammenfassung
            }
            anzahl_zf = len(inhalt)
            dateien.append(_schreiben(verzeichnis / "entities_summary.json",
                                      _json(inhalt)))

        beendet_am = _jetzt()
        with con:
            con.execute(
                "UPDATE lauf SET beendet_am = ?, parameter = ?, status = 'erfolg' "
                "WHERE id = ?",
                (beendet_am, json.dumps({
                    "ziel": str(verzeichnis),
                    "zusammenfassungen": zusammenfassungen,
                    "dateien": dateien,
                    "einheiten": z.einheiten,
                    "ohne_datum": z.ohne_datum,
                    "ohne_kategorie": z.ohne_kategorie,
                    "jahr_min": meta.get("year_min"),
                    "jahr_max": meta.get("year_max"),
                }, ensure_ascii=False), lauf_id),
            )

    except Exception as exc:
        with con:
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'export', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"ziel": str(verzeichnis), "fehler": str(exc)},
                            ensure_ascii=False)),
            )
        raise

    return ExportErgebnis(
        projekt_id=projekt_id,
        ziel=str(verzeichnis),
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        dateien=dateien,
        anzahl_einheiten=z.einheiten,
        anzahl_mit_datum=z.mit_datum,
        anzahl_ohne_datum=z.ohne_datum,
        anzahl_ohne_kategorie=z.ohne_kategorie,
        anzahl_mit_akteur=z.mit_akteur,
        anzahl_akteure=z.akteure,
        anzahl_knoten=z.knoten,
        anzahl_kanten=z.kanten,
        anzahl_je_kategorie=z.je_kategorie,
        jahr_min=meta.get("year_min"),
        jahr_max=meta.get("year_max"),
        zusammenfassungen=anzahl_zf,
    )
