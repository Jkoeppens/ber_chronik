"""
dienst.py — Datei einlesen, Kern rufen, Ergebnis speichern

Der Kern kennt keine Datenbank; dieses Modul kennt beides. Es beschafft die
Rohtexte, übergibt sie an kern.py und schreibt das Ergebnis in einer einzigen
Transaktion: eine quelle-Zeile, die einheit-Zeilen mit ausdrücklicher position,
und den lauf, der beides erklärt.

Kein print — wer etwas anzeigen will, nimmt das IngestErgebnis.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.neu.ingest import kern
from src.neu.ingest.kern import Einheit, RohAbsatz, RohDatei, quellformat_pruefen


class IngestFehler(Exception):
    """Einlesen nicht möglich — mit einer Meldung, die man anzeigen kann."""

    def __init__(self, meldung: str, code: str = "ingest_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class IngestErgebnis:
    projekt_id: str
    quelle_id: str
    quellformat: str
    pfad: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int
    anzahl_je_typ: dict[str, int] = field(default_factory=dict)


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Rohtexte beschaffen ───────────────────────────────────────────────────────

def _absaetze_aus_docx(pfad: Path) -> list[RohAbsatz]:
    import docx  # lokal: nur der DOCX-Weg braucht die Abhängigkeit

    try:
        dok = docx.Document(pfad)
    except Exception as exc:
        raise IngestFehler(f"DOCX nicht lesbar: {exc}", "datei_nicht_lesbar") from exc
    return [RohAbsatz(text=p.text, stil=p.style.name) for p in dok.paragraphs]


def _dateien_aus_ordner(pfad: Path) -> list[RohDatei]:
    """Alle .md-Dateien, nach Pfad sortiert.

    Die Sortierung ist ausdrücklich: sie bestimmt die position. Die Vorlage
    verließ sich auf die Reihenfolge der Dropbox-Antwort bzw. auf rglob und
    war damit zwischen zwei Läufen nicht reproduzierbar.
    """
    dateien = sorted(pfad.rglob("*.md"), key=lambda p: str(p).lower())
    return [
        RohDatei(
            pfad=str(p.relative_to(pfad)),
            inhalt=p.read_text(encoding="utf-8", errors="replace"),
        )
        for p in dateien
    ]


def einheiten_lesen(pfad: Path, quellformat: str) -> list[Einheit]:
    """Rohtexte beschaffen und vom Kern zerlegen lassen."""
    quellformat_pruefen(quellformat)

    if quellformat == "literaturexzerpt":
        if not pfad.is_file():
            raise IngestFehler(f"Keine Datei: {pfad}", "datei_nicht_gefunden")
        return kern.aus_absaetzen(_absaetze_aus_docx(pfad))

    if quellformat == "presseexzerpt":
        if not pfad.is_file():
            raise IngestFehler(f"Keine Datei: {pfad}", "datei_nicht_gefunden")
        return kern.aus_chronik_absaetzen(_absaetze_aus_docx(pfad))

    if quellformat == "pressesammlung":
        if not pfad.is_dir():
            raise IngestFehler(f"Kein Ordner: {pfad}", "ordner_nicht_gefunden")
        return kern.aus_dateien(_dateien_aus_ordner(pfad))

    # Unerreichbar, solange QUELLFORMATE und diese Verzweigung übereinstimmen.
    raise IngestFehler(
        f"Quellformat '{quellformat}' ist noch nicht implementiert.",
        "quellformat_nicht_implementiert",
    )


# ── Schreiben ─────────────────────────────────────────────────────────────────

_EINHEIT_SPALTEN = (
    "quelle_id", "position", "typ", "text",
    "publikation", "chronologie_gruppe", "publikationsdatum", "quellpfad",
    "url", "autor", "kurzfassung", "seite", "ebene", "ist_zitat", "datum",
)


def _einheit_werte(einheit: Einheit, quelle_id: str) -> tuple:
    return (
        quelle_id,
        einheit.position,
        einheit.typ,
        einheit.text,
        einheit.publikation,
        einheit.chronologie_gruppe,
        einheit.publikationsdatum,
        einheit.quellpfad,
        einheit.url,
        einheit.autor,
        einheit.kurzfassung,
        einheit.seite,
        einheit.ebene,
        None if einheit.ist_zitat is None else int(einheit.ist_zitat),
        einheit.datum,
    )


def einlesen(
    con: sqlite3.Connection,
    projekt_id: str,
    pfad: Path,
    quellformat: str,
    quelle_id: str | None = None,
) -> IngestErgebnis:
    """Liest pfad ein und schreibt quelle, einheit und lauf in einer Transaktion.

    Die Verbindung kommt von außen und muss schreibfähig sein mit
    PRAGMA foreign_keys = ON. Bei einem Fehler wird alles zurückgerollt und
    anschließend eine lauf-Zeile mit status='fehler' geschrieben — der
    Fehlversuch bleibt sichtbar, seine Daten nicht.
    """
    quellformat_pruefen(quellformat)
    begonnen_am = _jetzt()
    parameter = json.dumps(
        {"pfad": str(pfad), "quellformat": quellformat}, ensure_ascii=False
    )

    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise IngestFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )

    try:
        einheiten = einheiten_lesen(pfad, quellformat)
        if not einheiten:
            raise IngestFehler(f"{pfad} ergibt keine Einheit.", "keine_einheiten")

        quelle_id = quelle_id or uuid.uuid4().hex[:8]

        with con:  # commit bei Erfolg, rollback bei Ausnahme
            con.execute(
                "INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
                "VALUES (?, ?, ?, ?, ?)",
                (quelle_id, projekt_id, quellformat, str(pfad), begonnen_am),
            )
            platzhalter = ", ".join("?" * len(_EINHEIT_SPALTEN))
            con.executemany(
                f"INSERT INTO einheit ({', '.join(_EINHEIT_SPALTEN)}) "
                f"VALUES ({platzhalter})",
                [_einheit_werte(e, quelle_id) for e in einheiten],
            )
            beendet_am = _jetzt()
            zeiger = con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'ingest', ?, ?, ?, 'erfolg')",
                (projekt_id, begonnen_am, beendet_am, parameter),
            )
            lauf_id = zeiger.lastrowid

    except Exception as exc:
        # Der Fehlversuch wird festgehalten, nachdem die Daten zurückgerollt sind.
        with con:
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'ingest', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"pfad": str(pfad), "quellformat": quellformat,
                             "fehler": str(exc)}, ensure_ascii=False)),
            )
        raise

    je_typ: dict[str, int] = {}
    for e in einheiten:
        je_typ[e.typ] = je_typ.get(e.typ, 0) + 1

    return IngestErgebnis(
        projekt_id=projekt_id,
        quelle_id=quelle_id,
        quellformat=quellformat,
        pfad=str(pfad),
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        anzahl_einheiten=len(einheiten),
        anzahl_je_typ=je_typ,
    )
