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
from dataclasses import dataclass, field, replace
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
    # Der Riegel: was ein zweiter Lauf über dieselbe Quelle vorgefunden hat.
    fortgesetzt: bool = False
    anzahl_neu: int = 0
    anzahl_uebersprungen: int = 0
    geaenderte_dateien: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)


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


def _bestehende_quelle(
    con: sqlite3.Connection, projekt_id: str, pfad: str, quellformat: str
) -> tuple[str | None, str | None]:
    """Findet die Quelle, die fortzuführen ist. Gibt (quelle_id, Hinweis).

    Zuerst über (projekt_id, pfad) — der geradlinige Fall. Bei einer
    Pressesammlung zusätzlich über (projekt_id, quellformat): derselbe
    Obsidian-Ordner heißt lokal '/Users/…/Dropbox_test1' und über Dropbox
    '/Dropbox_test1'. Ein Projekt hat eine Sammlung, nicht zwei; wer denselben
    Ordner anders erreicht, soll keine zweite anlegen.
    """
    zeile = con.execute(
        "SELECT id FROM quelle WHERE projekt_id = ? AND pfad = ?", (projekt_id, pfad)
    ).fetchone()
    if zeile is not None:
        return zeile[0], None

    if quellformat != "pressesammlung":
        return None, None

    zeile = con.execute(
        "SELECT id, pfad FROM quelle WHERE projekt_id = ? AND quellformat = 'pressesammlung' "
        "ORDER BY eingelesen_am LIMIT 1", (projekt_id,)
    ).fetchone()
    if zeile is None:
        return None, None
    return zeile[0], (
        f"Die Sammlung dieses Projekts wurde bisher über '{zeile[1]}' gelesen, "
        f"jetzt über '{pfad}'. Sie wird fortgeführt, nicht neu angelegt."
    )


def einlesen(
    con: sqlite3.Connection,
    projekt_id: str,
    pfad: Path | str,
    quellformat: str,
    quelle_id: str | None = None,
    dateien: list[RohDatei] | None = None,
) -> IngestErgebnis:
    """Liest pfad ein und schreibt quelle, einheit und lauf in einer Transaktion.

    Die Verbindung kommt von außen und muss schreibfähig sein mit
    PRAGMA foreign_keys = ON. Bei einem Fehler wird alles zurückgerollt und
    anschließend eine lauf-Zeile mit status='fehler' geschrieben — der
    Fehlversuch bleibt sichtbar, seine Daten nicht.

    `dateien` übergibt den Inhalt statt ihn zu lesen — so kommt eine Sammlung
    aus Dropbox herein, ohne dass dieser Dienst das Netz kennt.

    Gibt es zu (projekt_id, pfad) schon eine Quelle, wird sie **fortgeführt**
    statt eine zweite anzulegen: bekannte quellpfade werden übersprungen, neue
    hinten angehängt. Eine Datei, deren Inhalt sich geändert hat, wird gemeldet
    und nicht angefasst — was damit geschehen soll, ist keine Entscheidung
    dieses Dienstes.
    """
    quellformat_pruefen(quellformat)
    begonnen_am = _jetzt()
    pfad_text = str(pfad)
    parameter = json.dumps(
        {"pfad": pfad_text, "quellformat": quellformat}, ensure_ascii=False
    )

    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise IngestFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )

    fortgesetzt = False
    uebersprungen = 0
    geaendert: list[str] = []
    hinweise: list[str] = []

    try:
        einheiten = (kern.aus_dateien(dateien) if dateien is not None
                     else einheiten_lesen(Path(pfad), quellformat))
        if not einheiten:
            raise IngestFehler(f"{pfad_text} ergibt keine Einheit.", "keine_einheiten")

        vorhanden, hinweis = (
            _bestehende_quelle(con, projekt_id, pfad_text, quellformat)
            if quelle_id is None else (None, None)
        )
        if hinweis:
            hinweise.append(hinweis)

        if vorhanden is not None:
            fortgesetzt = True
            quelle_id = vorhanden
            bekannt = {z[0]: z[1] for z in con.execute(
                "SELECT quellpfad, text FROM einheit "
                "WHERE quelle_id = ? AND quellpfad IS NOT NULL", (quelle_id,))}
            if not bekannt:
                raise IngestFehler(
                    f"Zu '{pfad_text}' gibt es in diesem Projekt schon eine Quelle "
                    f"({quelle_id}), deren Einheiten keinen Dateibezug haben — "
                    "ein DOCX wird nicht fortgeführt. Bitte die vorhandene Quelle "
                    "verwenden oder ein eigenes Projekt anlegen.",
                    "quelle_gibt_es_schon",
                )
            hoechste = con.execute(
                "SELECT COALESCE(MAX(position), 0) FROM einheit WHERE quelle_id = ?",
                (quelle_id,),
            ).fetchone()[0]

            neue: list[Einheit] = []
            for e in einheiten:
                if e.quellpfad in bekannt:
                    uebersprungen += 1
                    if bekannt[e.quellpfad] != e.text:
                        geaendert.append(e.quellpfad)
                    continue
                hoechste += 1
                neue.append(replace(e, position=hoechste))
            einheiten = neue
        else:
            quelle_id = quelle_id or uuid.uuid4().hex[:8]

        with con:  # commit bei Erfolg, rollback bei Ausnahme
            if not fortgesetzt:
                con.execute(
                    "INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (quelle_id, projekt_id, quellformat, pfad_text, begonnen_am),
                )
            elif pfad_text:
                # Der zuletzt benutzte Weg zur selben Sammlung.
                con.execute("UPDATE quelle SET pfad = ? WHERE id = ?",
                            (pfad_text, quelle_id))
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
                 json.dumps({"pfad": pfad_text, "quellformat": quellformat,
                             "fehler": str(exc)}, ensure_ascii=False)),
            )
        raise

    # anzahl_einheiten ist der Stand der Quelle nach dem Lauf, nicht nur das
    # neu Geschriebene — sonst zeigte ein fortgesetzter Lauf eine kleinere
    # Zahl an als der erste.
    je_typ = {z[0]: z[1] for z in con.execute(
        "SELECT typ, COUNT(*) FROM einheit WHERE quelle_id = ? GROUP BY typ "
        "ORDER BY COUNT(*) DESC", (quelle_id,))}
    gesamt = sum(je_typ.values())

    return IngestErgebnis(
        projekt_id=projekt_id,
        quelle_id=quelle_id,
        quellformat=quellformat,
        pfad=pfad_text,
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        anzahl_einheiten=gesamt,
        anzahl_je_typ=je_typ,
        fortgesetzt=fortgesetzt,
        anzahl_neu=len(einheiten),
        anzahl_uebersprungen=uebersprungen,
        geaenderte_dateien=sorted(geaendert),
        hinweise=hinweise,
    )
