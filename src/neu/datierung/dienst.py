"""
dienst.py — Einheiten datieren und Datierungen von Hand korrigieren

Liest die Einheiten aus der Datenbank, lässt den Kern rechnen und schreibt in
einer Transaktion: die Datierungsfelder je Einheit, die anker-Zeilen, die
lauf-Zeile.

Kein print — wer etwas anzeigen will, nimmt das DatierungErgebnis.

Wiederaufnahme steht in der Datenbank: WHERE datierung_herkunft IS NULL.
Handkorrekturen (herkunft='manuell') bleiben bei einem Neulauf unberührt;
sie zu überschreiben verlangt den ausdrücklichen Umfang 'auch_manuell'.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.neu.datierung import kern
from src.neu.datierung.kern import Einheit, Override

UMFAENGE = ("offen", "alle", "auch_manuell")


class DatierungFehler(Exception):
    def __init__(self, meldung: str, code: str = "datierung_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class DatierungErgebnis:
    projekt_id: str
    quellformat: str
    umfang: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int
    anzahl_datiert: int
    anzahl_ohne_datum: int
    anzahl_anker: int
    anzahl_je_praezision: dict[str, int] = field(default_factory=dict)
    anzahl_je_herkunft: dict[str, int] = field(default_factory=dict)
    # Overrides, die auf eine Einheit zeigen, die es im Bestand nicht gibt.
    warnungen: list[str] = field(default_factory=list)


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _quellen(con: sqlite3.Connection, projekt_id: str) -> list[tuple[str, str]]:
    return [(z[0], z[1]) for z in con.execute(
        "SELECT id, quellformat FROM quelle WHERE projekt_id = ? ORDER BY id",
        (projekt_id,),
    ).fetchall()]


def _einheiten(con: sqlite3.Connection, quelle_id: str) -> list[Einheit]:
    """Alle Einheiten einer Quelle in Dokumentreihenfolge.

    Auch heading-Einheiten: der Kern braucht sie, um den Jahreskontext zu
    setzen. Er gibt für sie keine Datierung zurück.
    """
    zeilen = con.execute(
        "SELECT id, position, typ, text, chronologie_gruppe, publikationsdatum, datum "
        "FROM einheit WHERE quelle_id = ? ORDER BY position",
        (quelle_id,),
    ).fetchall()
    return [Einheit(id=z[0], position=z[1], typ=z[2], text=z[3],
                    chronologie_gruppe=z[4], publikationsdatum=z[5],
                    datum_frontmatter=z[6])
            for z in zeilen]


def _overrides(con: sqlite3.Connection, quelle_id: str) -> list[Override]:
    """Handkorrekturen sind Einheiten mit datierung_herkunft='manuell'.

    Es gibt keine overrides.json mehr — der Zustand steht an der Einheit.
    """
    zeilen = con.execute(
        "SELECT id, jahr_von, jahr_bis FROM einheit "
        "WHERE quelle_id = ? AND datierung_herkunft = 'manuell'",
        (quelle_id,),
    ).fetchall()
    return [Override(einheit_id=z[0],
                     aktion="undatierbar" if z[1] is None else "anker_setzen",
                     jahr_von=z[1], jahr_bis=z[2])
            for z in zeilen]


# ── Datieren ──────────────────────────────────────────────────────────────────

def datieren(
    con: sqlite3.Connection, projekt_id: str, umfang: str = "offen"
) -> DatierungErgebnis:
    """Datiert die Einheiten eines Projekts, Quelle für Quelle.

    Das Quellformat kommt aus quelle.quellformat — ein Parameter je Quelle,
    keine Datei, die mitten in der Verzweigung gelesen wird.
    """
    if umfang not in UMFAENGE:
        raise DatierungFehler(
            f"Unbekannter Umfang '{umfang}'. Erlaubt: {' | '.join(UMFAENGE)}",
            "umfang_unbekannt",
        )

    begonnen_am = _jetzt()
    parameter = json.dumps({"umfang": umfang}, ensure_ascii=False)

    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise DatierungFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )

    try:
        quellen = _quellen(con, projekt_id)
        if not quellen:
            raise DatierungFehler(
                f"Projekt '{projekt_id}' hat keine Quelle.", "keine_quelle"
            )

        alle_datierungen = []
        alle_anker = []
        warnungen: list[str] = []
        formate: set[str] = set()

        for quelle_id, quellformat in quellen:
            formate.add(quellformat)
            einheiten = _einheiten(con, quelle_id)
            overrides = _overrides(con, quelle_id) if umfang != "auch_manuell" else []

            ergebnis = kern.datieren(einheiten, quellformat, overrides)

            for fehlend in ergebnis.ins_leere_zeigende_overrides:
                warnungen.append(
                    f"Quelle {quelle_id}: Handkorrektur zeigt auf Einheit {fehlend}, "
                    "die es in dieser Quelle nicht gibt — übersprungen."
                )

            # Welche Einheiten geschrieben werden dürfen
            geschuetzt: set[int] = set()
            if umfang == "offen":
                offen = {z[0] for z in con.execute(
                    "SELECT id FROM einheit WHERE quelle_id = ? "
                    "AND datierung_herkunft IS NULL", (quelle_id,))}
                geschuetzt = {d.einheit_id for d in ergebnis.datierungen
                              if d.einheit_id not in offen}
            elif umfang == "alle":
                manuell = {z[0] for z in con.execute(
                    "SELECT id FROM einheit WHERE quelle_id = ? "
                    "AND datierung_herkunft = 'manuell'", (quelle_id,))}
                geschuetzt = manuell

            for d in ergebnis.datierungen:
                if d.einheit_id in geschuetzt:
                    continue
                alle_datierungen.append(d)
                alle_anker.extend(d.anker)

        if not alle_datierungen:
            raise DatierungFehler(
                f"Projekt '{projekt_id}' hat keine zu datierenden Einheiten "
                f"(Umfang '{umfang}').",
                "keine_einheiten",
            )

        with con:
            zeiger = con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, status) "
                "VALUES (?, 'datierung', ?, ?, 'laeuft')",
                (projekt_id, begonnen_am, parameter),
            )
            lauf_id = zeiger.lastrowid

            ids = [d.einheit_id for d in alle_datierungen]
            platz = ",".join("?" * len(ids))
            con.execute(f"DELETE FROM anker WHERE einheit_id IN ({platz})", ids)

            con.executemany(
                "UPDATE einheit SET datum = ?, jahr_von = ?, jahr_bis = ?, "
                "praezision = ?, datierung_herkunft = ?, datierung_lauf_id = ? "
                "WHERE id = ?",
                [(d.datum, d.jahr_von, d.jahr_bis, d.praezision, d.herkunft,
                  lauf_id, d.einheit_id) for d in alle_datierungen],
            )
            con.executemany(
                "INSERT INTO anker (einheit_id, jahr, herkunft, fundstelle) "
                "VALUES (?, ?, ?, ?)",
                [(a.einheit_id, a.jahr, a.herkunft, a.fundstelle) for a in alle_anker],
            )

            beendet_am = _jetzt()
            con.execute(
                "UPDATE lauf SET beendet_am = ?, parameter = ?, status = 'erfolg' "
                "WHERE id = ?",
                (beendet_am, json.dumps({
                    "umfang": umfang,
                    "quellformate": sorted(formate),
                    "einheiten": len(alle_datierungen),
                    "anker": len(alle_anker),
                    "warnungen": warnungen,
                }, ensure_ascii=False), lauf_id),
            )

    except Exception as exc:
        with con:
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'datierung', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"umfang": umfang, "fehler": str(exc)}, ensure_ascii=False)),
            )
        raise

    je_praez: dict[str, int] = {}
    je_herk: dict[str, int] = {}
    ohne = 0
    for d in alle_datierungen:
        je_praez[d.praezision] = je_praez.get(d.praezision, 0) + 1
        schluessel = d.herkunft or "keine"
        je_herk[schluessel] = je_herk.get(schluessel, 0) + 1
        if d.jahr_von is None:
            ohne += 1

    return DatierungErgebnis(
        projekt_id=projekt_id,
        quellformat="+".join(sorted(formate)),
        umfang=umfang,
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        anzahl_einheiten=len(alle_datierungen),
        anzahl_datiert=len(alle_datierungen) - ohne,
        anzahl_ohne_datum=ohne,
        anzahl_anker=len(alle_anker),
        anzahl_je_praezision=je_praez,
        anzahl_je_herkunft=je_herk,
        warnungen=warnungen,
    )


# ── Handkorrektur ─────────────────────────────────────────────────────────────

def datierung_setzen(
    con: sqlite3.Connection,
    einheit_id: int,
    jahr_von: int | None,
    jahr_bis: int | None = None,
    datum: str | None = None,
) -> dict:
    """Setzt die Datierung einer Einheit von Hand.

    jahr_von=None heißt 'undatierbar'. Die Korrektur wird eine echte
    anker-Zeile mit herkunft='manuell' und ist gegen Neuläufe geschützt.
    """
    zeile = con.execute("SELECT id FROM einheit WHERE id = ?", (einheit_id,)).fetchone()
    if zeile is None:
        raise DatierungFehler(
            f"Keine Einheit mit der Kennung {einheit_id}.", "einheit_nicht_gefunden"
        )

    if jahr_von is None:
        praez, bis, dat = "keine", None, None
    else:
        bis = jahr_bis if jahr_bis is not None else jahr_von
        if bis < jahr_von:
            raise DatierungFehler(
                f"jahr_bis ({bis}) liegt vor jahr_von ({jahr_von}).", "spanne_verkehrt"
            )
        praez = "jahr" if jahr_von == bis else "spanne"
        dat = datum or str(jahr_von)

    with con:
        con.execute("DELETE FROM anker WHERE einheit_id = ?", (einheit_id,))
        con.execute(
            "UPDATE einheit SET datum = ?, jahr_von = ?, jahr_bis = ?, praezision = ?, "
            "datierung_herkunft = 'manuell', datierung_lauf_id = NULL WHERE id = ?",
            (dat, jahr_von, bis, praez, einheit_id),
        )
        if jahr_von is not None:
            con.execute(
                "INSERT INTO anker (einheit_id, jahr, herkunft, fundstelle) "
                "VALUES (?, ?, 'manuell', ?)",
                (einheit_id, jahr_von,
                 str(jahr_von) if jahr_von == bis else f"{jahr_von}–{bis}"),
            )

    return {
        "einheit_id": einheit_id,
        "datum": dat,
        "jahr_von": jahr_von,
        "jahr_bis": bis,
        "praezision": praez,
        "datierung_herkunft": "manuell",
        "datierung_lauf_id": None,
    }
