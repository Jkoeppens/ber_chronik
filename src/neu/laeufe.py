"""
laeufe.py — lange Schritte anstoßen und ihren Stand abfragen

Das Muster für alles, was Minuten dauert:

    POST …/taxonomie/vorschlagen  →  {lauf_id, status: 'laeuft'}   (sofort)
    GET  /api/lauf/{id}           →  Stand, so oft man will
    GET  /api/lauf/{id}           →  {status: 'erfolg', ergebnis: …}

Der Stand steht in der `lauf`-Tabelle, nicht in einer offenen Verbindung.
Reißt die Leitung, ist der Stand trotzdem da; ein neu geladener Reiter sieht
denselben Lauf. Das ist der Unterschied zum SSE-Strom des alten Systems: dort
lebt der Fortschritt nur, solange die Verbindung steht, und ein Neuladen
verliert ihn. Sentinels wie `__done__` oder `__error__` im Datenstrom gibt es
hier nicht — der Zustand hat einen Namen und eine Zeile.

Der Schritt läuft in einem eigenen Faden mit eigener Verbindung. SQLite steht
dabei auf WAL (siehe db.py), damit die Abfrage nicht am Schreiber hängen
bleibt.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import traceback
from datetime import datetime, timezone
from typing import Callable

from src.neu.db import verbindung_schreibend

# Schritte, die lange dauern und deshalb über diesen Weg laufen.
LANGE_SCHRITTE = ("taxonomie", "klassifikation", "akteure", "ingest", "export")


class LaufFehler(Exception):
    def __init__(self, meldung: str, code: str = "lauf_fehler"):
        super().__init__(meldung)
        self.code = code


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def laeuft_schon(con: sqlite3.Connection, projekt_id: str, schritt: str) -> int | None:
    """Die Kennung eines noch laufenden Schritts dieser Art, falls es einen gibt.

    Zwei Taxonomieläufe im selben Projekt gleichzeitig ergäben zwei Ergebnisse,
    von denen eines das andere überschreibt — also lieber einer nach dem
    anderen.
    """
    zeile = con.execute(
        "SELECT id FROM lauf WHERE projekt_id = ? AND schritt = ? AND status = 'laeuft' "
        "ORDER BY id DESC LIMIT 1",
        (projekt_id, schritt),
    ).fetchone()
    return zeile[0] if zeile else None


def anlegen(
    con: sqlite3.Connection, projekt_id: str, schritt: str, parameter: dict
) -> int:
    """Legt die 'laeuft'-Zeile an und gibt ihre Kennung zurück."""
    with con:
        zeiger = con.execute(
            "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, status) "
            "VALUES (?, ?, ?, ?, 'laeuft')",
            (projekt_id, schritt, _jetzt(),
             json.dumps(parameter, ensure_ascii=False)),
        )
    return zeiger.lastrowid


def fortschritt(con: sqlite3.Connection, lauf_id: int, **werte) -> None:
    """Schreibt Zwischenstände in die Parameter der laufenden Zeile.

    Bewusst additiv: was schon dasteht, bleibt. So kann ein Schritt melden,
    in welcher Runde er ist, ohne zu wissen, was sonst noch vermerkt wurde.
    """
    zeile = con.execute("SELECT parameter FROM lauf WHERE id = ?", (lauf_id,)).fetchone()
    if zeile is None:
        return
    vorhanden = json.loads(zeile[0]) if zeile[0] else {}
    vorhanden.update(werte)
    with con:
        con.execute("UPDATE lauf SET parameter = ? WHERE id = ?",
                    (json.dumps(vorhanden, ensure_ascii=False), lauf_id))


def starten(
    projekt_id: str,
    schritt: str,
    parameter: dict,
    arbeit: Callable[[sqlite3.Connection, int], None],
) -> int:
    """Legt die lauf-Zeile an, startet die Arbeit in einem Faden, gibt sofort zurück.

    `arbeit` bekommt eine eigene schreibfähige Verbindung und die lauf_id. Sie
    ist dafür zuständig, die Zeile am Ende auf 'erfolg' zu setzen; wirft sie,
    wird hier 'fehler' samt Meldung eingetragen.
    """
    con = verbindung_schreibend()
    try:
        offen = laeuft_schon(con, projekt_id, schritt)
        if offen is not None:
            raise LaufFehler(
                f"Für '{projekt_id}' läuft schon ein Schritt '{schritt}' "
                f"(Lauf {offen}). Erst dessen Ende abwarten.",
                "lauf_schon_unterwegs",
            )
        lauf_id = anlegen(con, projekt_id, schritt, parameter)
    finally:
        con.close()

    def im_faden() -> None:
        eigene = verbindung_schreibend()
        try:
            arbeit(eigene, lauf_id)
        except Exception as exc:
            try:
                fortschritt(
                    eigene, lauf_id,
                    fehler=str(exc),
                    fehlerart=type(exc).__name__,
                    spur=traceback.format_exc(limit=3),
                )
                with eigene:
                    eigene.execute(
                        "UPDATE lauf SET status = 'fehler', beendet_am = ? WHERE id = ?",
                        (_jetzt(), lauf_id),
                    )
            except Exception:
                # Wenn nicht einmal das Festhalten des Fehlers gelingt, bleibt
                # die Zeile auf 'laeuft' — sichtbar hängen ist besser als
                # unsichtbar verschwunden.
                pass
        finally:
            eigene.close()

    threading.Thread(target=im_faden, daemon=True, name=f"{schritt}-{lauf_id}").start()
    return lauf_id


def stand(con: sqlite3.Connection, lauf_id: int) -> dict:
    """Was aus der lauf-Zeile über den Stand zu erfahren ist."""
    zeile = con.execute(
        "SELECT id, projekt_id, schritt, status, begonnen_am, beendet_am, parameter "
        "FROM lauf WHERE id = ?",
        (lauf_id,),
    ).fetchone()
    if zeile is None:
        raise LaufFehler(f"Keinen Lauf mit der Kennung {lauf_id}.", "lauf_nicht_gefunden")
    parameter = json.loads(zeile[6]) if zeile[6] else {}
    return {
        "id": zeile[0],
        "projekt_id": zeile[1],
        "schritt": zeile[2],
        "status": zeile[3],
        "begonnen_am": zeile[4],
        "beendet_am": zeile[5],
        "parameter": parameter,
        "fehler": parameter.get("fehler"),
    }
