"""
dienst.py — Einheiten klassifizieren und Zuordnungen von Hand korrigieren

Liest die Einheiten aus der Datenbank, lässt den Kern entscheiden und schreibt
das Ergebnis in einer Transaktion, zusammen mit der lauf-Zeile, die es erklärt.

Kein print — wer etwas anzeigen will, nimmt das KlassifikationErgebnis.

Wiederaufnahme steht in der Datenbank, nicht in einer Datei: ein Lauf mit
Umfang 'offen' nimmt sich, was gerade keine Kategorie hat. Es gibt kein
classified.json.

Die Einheiten-Embeddings kommen aus src/neu/vektoren.py und werden nur beim
ersten Mal gerechnet. Neu ist je Lauf nur die andere Seite: die Kategorien,
deren Beschreibungen sich dauernd ändern. Danach ist ein Zuordnen sieben kurze
Einbettungen und eine Matrixmultiplikation.

Dieser Schritt ist kein Nachlauf mehr. Der Themenlauf ordnet bereits jede
Einheit zu (siehe src/neu/taxonomie/dienst.py); hier geht es um zwei Fälle:
eine Kategorie wurde von Hand geändert oder ergänzt, oder es sind Einheiten
dazugekommen.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from src.neu import laeufe, projekte, vektoren
from src.neu.kategorien import kern
from src.neu.kategorien.kern import Zuordnung

# Umfang eines Laufs.
#   offen    — Einheiten ohne Kategorie, ausgenommen Handkorrekturen
#   alle     — auch maschinell klassifizierte erneut; manuell gesetzte bleiben
#   auch_manuell — auch die Handkorrekturen überschreiben. Eigener Wert, weil
#              das die Arbeit des Historikers verwirft und nie beiläufig
#              passieren darf.
from src.neu.vokabular import UMFAENGE  # noqa: E402


class KlassifikationFehler(Exception):
    def __init__(self, meldung: str, code: str = "klassifikation_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class KlassifikationErgebnis:
    projekt_id: str
    verfahren: str
    umfang: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    anzahl_einheiten: int
    anzahl_ohne_kategorie: int
    anzahl_je_konfidenz: dict[str, int] = field(default_factory=dict)
    anzahl_je_kategorie: dict[str, int] = field(default_factory=dict)
    # Woher die Einheiten-Embeddings kamen. Beim 'llm'-Verfahren beides 0 —
    # dort wird nicht embeddet.
    anzahl_aus_speicher: int = 0
    anzahl_gerechnet: int = 0


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def taxonomie_lesen(con: sqlite3.Connection, projekt_id: str) -> list[dict]:
    """Die Kategorien eines Projekts, in der Reihenfolge ihrer Anlage."""
    zeilen = con.execute(
        "SELECT id, name, beschreibung, schlagworte FROM kategorie "
        "WHERE projekt_id = ? ORDER BY id",
        (projekt_id,),
    ).fetchall()
    return [
        {
            "id": z[0],
            "name": z[1],
            "description": z[2],
            "keywords": [k.strip() for k in (z[3] or "").split(",") if k.strip()],
        }
        for z in zeilen
    ]


def _einheiten_lesen(
    con: sqlite3.Connection, projekt_id: str, umfang: str
) -> list[tuple[int, str]]:
    """(einheit_id, text) der zu klassifizierenden content-Einheiten."""
    sql = (
        "SELECT e.id, e.text FROM einheit e "
        "JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content'"
    )
    if umfang == "offen":
        # Nicht "nie angefasst", sondern "hat gerade keine Kategorie". Der
        # Unterschied wurde sichtbar, als der Themenlauf anfing, die alten
        # Kategorien zu ersetzen: die Einheiten daran verlieren durch
        # ON DELETE SET NULL ihre Zuordnung, behalten aber ihre Herkunft. Mit
        # der alten Bedingung (herkunft IS NULL) wären sie unerreichbar
        # geworden — bei den vier Projekten 80 Stück.
        # Eine Handkorrektur auf "keine Kategorie" bleibt außen vor.
        sql += (" AND e.kategorie_id IS NULL "
                "AND (e.kategorie_herkunft IS NULL OR e.kategorie_herkunft != 'manuell')")
    elif umfang == "alle":
        # Handkorrekturen bleiben unberührt — auch bei einem erzwungenen Neulauf.
        sql += " AND (e.kategorie_herkunft IS NULL OR e.kategorie_herkunft != 'manuell')"
    # 'auch_manuell': keine Einschränkung
    sql += " ORDER BY e.quelle_id, e.position"
    return [(z[0], z[1]) for z in con.execute(sql, (projekt_id,)).fetchall()]


# ── Verfahren ─────────────────────────────────────────────────────────────────

def _zuordnungen_bge(
    con: sqlite3.Connection,
    einheiten: list[tuple[int, str]],
    taxonomie: list[dict],
    melden: Callable[[int, int], None] | None = None,
) -> list[Zuordnung]:
    """Embeddet Einheiten und Taxonomie und ordnet per Argmax zu.

    Die Einheitenseite kommt aus dem Zwischenspeicher (src/neu/vektoren.py) —
    ihre Texte ändern sich nach dem Ingest nicht mehr. Die Kategorienseite wird
    immer gerechnet: sieben kurze Zeichenketten, die sich bei jedem Speichern
    geändert haben können.

    Der Embedding-Anbieter ist der einzige Teil, der die Außenwelt berührt;
    die Entscheidung selbst trifft der Kern. Er kommt aus src.neu.anbieter und
    nicht aus generalized.embeddings.get_embedding_provider, weil nur der erste
    den Modellnamen mitgibt — und ohne Modellnamen gibt es keinen Schlüssel für
    den Speicher. Aufgabe 'themen', dasselbe Modell wie beim Themenlauf.
    """
    from src.neu.anbieter import embedding_funktion

    embed, modell = embedding_funktion("themen")
    # Gekürzt wird vor dem Nachschlagen: die Prüfsumme steht über der
    # Zeichenkette, die das Modell gesehen hat, nicht über dem ganzen Absatz.
    gekuerzt = [(einheit_id, text[:kern.SEG_CHARS]) for einheit_id, text in einheiten]
    einheit_embs = vektoren.hole(con, gekuerzt, modell, embed, melden)
    tax_embs = embed(kern.taxonomie_texte(taxonomie))
    namen = [c["name"] for c in taxonomie]
    return kern.zuordnungen_aus_embeddings(einheit_embs, tax_embs, namen)


def _zuordnungen_llm(
    con: sqlite3.Connection,
    einheiten: list[tuple[int, str]],
    taxonomie: list[dict],
    melden: Callable[[int, int], None] | None = None,
) -> list[Zuordnung]:
    from src.generalized.llm import TASK_CLASSIFY, get_provider

    provider = get_provider(task=TASK_CLASSIFY)
    block = kern.baue_kategorienblock(taxonomie)
    namen = [c["name"] for c in taxonomie]

    def frage_modell(prompt: str, system: str) -> str:
        return provider.complete(prompt, system)

    return [kern.klassifiziere_eine(t, block, namen, frage_modell)
            for _, t in einheiten]


VERFAHREN = {"bge": _zuordnungen_bge, "llm": _zuordnungen_llm}


# ── Klassifizieren ────────────────────────────────────────────────────────────

def klassifizieren(
    con: sqlite3.Connection,
    projekt_id: str,
    verfahren: str = "bge",
    umfang: str = "offen",
    lauf_id: int | None = None,
) -> KlassifikationErgebnis:
    """Klassifiziert die offenen Einheiten eines Projekts.

    Schreibt kategorie_id, konfidenz, kategorie_herkunft und kategorie_lauf_id
    in einer Transaktion, zusammen mit der lauf-Zeile. Bei einem Fehler wird
    alles zurückgerollt und der Fehlversuch als lauf-Zeile festgehalten.
    """
    if verfahren not in VERFAHREN:
        raise KlassifikationFehler(
            f"Unbekanntes Verfahren '{verfahren}'. Erlaubt: {' | '.join(VERFAHREN)}",
            "verfahren_unbekannt",
        )
    if umfang not in UMFAENGE:
        raise KlassifikationFehler(
            f"Unbekannter Umfang '{umfang}'. Erlaubt: {' | '.join(UMFAENGE)}",
            "umfang_unbekannt",
        )

    begonnen_am = _jetzt()
    parameter = json.dumps(
        {"verfahren": verfahren, "umfang": umfang}, ensure_ascii=False
    )

    if not projekte.gibt_es(con, projekt_id):
        raise KlassifikationFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )

    try:
        taxonomie = taxonomie_lesen(con, projekt_id)
        if not taxonomie:
            raise KlassifikationFehler(
                f"Projekt '{projekt_id}' hat keine Kategorien.", "keine_taxonomie"
            )

        einheiten = _einheiten_lesen(con, projekt_id, umfang)
        if not einheiten:
            raise KlassifikationFehler(
                f"Projekt '{projekt_id}' hat keine offenen Einheiten "
                f"(Umfang '{umfang}').",
                "keine_einheiten",
            )

        if lauf_id is not None:
            laeufe.fortschritt(con, lauf_id, phase="embedding",
                               einheiten=len(einheiten), kategorien=len(taxonomie))

        aus_speicher = zu_rechnen = 0

        def melden(gespeichert: int, offen: int) -> None:
            nonlocal aus_speicher, zu_rechnen
            aus_speicher, zu_rechnen = gespeichert, offen
            if lauf_id is not None:
                laeufe.fortschritt(con, lauf_id, phase="embedding",
                                   aus_speicher=gespeichert, zu_rechnen=offen)

        zuordnungen = VERFAHREN[verfahren](con, einheiten, taxonomie, melden)
        id_je_name = {c["name"]: c["id"] for c in taxonomie}

        with con:
            if lauf_id is None:
                zeiger = con.execute(
                    "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, "
                    "status) VALUES (?, 'klassifikation', ?, ?, 'laeuft')",
                    (projekt_id, begonnen_am, parameter),
                )
                lauf_id = zeiger.lastrowid
            else:
                # Eine schon angelegte Zeile fortschreiben, damit die Oberfläche
                # den Stand von Anfang an abfragen kann (src/neu/laeufe.py).
                # Ergänzend, nicht ersetzend: was laeufe.starten hineingeschrieben
                # hat, soll stehen bleiben.
                laeufe.fortschritt(
                    con, lauf_id, phase="schreiben",
                    einheiten=len(einheiten), verfahren=verfahren, umfang=umfang,
                )

            con.executemany(
                "UPDATE einheit SET kategorie_id = ?, konfidenz = ?, "
                "kategorie_herkunft = ?, kategorie_lauf_id = ? WHERE id = ?",
                [
                    (
                        None if z.kategorie is None else id_je_name.get(z.kategorie),
                        z.konfidenz,
                        z.herkunft,
                        lauf_id,
                        einheit_id,
                    )
                    for (einheit_id, _), z in zip(einheiten, zuordnungen)
                ],
            )

            beendet_am = _jetzt()
            con.execute(
                "UPDATE lauf SET beendet_am = ?, status = 'erfolg' WHERE id = ?",
                (beendet_am, lauf_id),
            )

    except Exception as exc:
        with con:
            if lauf_id is not None:
                con.execute(
                    "UPDATE lauf SET beendet_am = ?, status = 'fehler' WHERE id = ?",
                    (_jetzt(), lauf_id),
                )
                raise
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'klassifikation', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"verfahren": verfahren, "umfang": umfang,
                             "fehler": str(exc)}, ensure_ascii=False)),
            )
        raise

    je_konfidenz: dict[str, int] = {}
    je_kategorie: dict[str, int] = {}
    ohne = 0
    for z in zuordnungen:
        schluessel = z.konfidenz or "keine"
        je_konfidenz[schluessel] = je_konfidenz.get(schluessel, 0) + 1
        if z.kategorie is None:
            ohne += 1
        else:
            je_kategorie[z.kategorie] = je_kategorie.get(z.kategorie, 0) + 1

    return KlassifikationErgebnis(
        projekt_id=projekt_id,
        verfahren=verfahren,
        umfang=umfang,
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        anzahl_einheiten=len(einheiten),
        anzahl_ohne_kategorie=ohne,
        anzahl_je_konfidenz=je_konfidenz,
        anzahl_je_kategorie=je_kategorie,
        anzahl_aus_speicher=aus_speicher,
        anzahl_gerechnet=zu_rechnen,
    )


# ── Handkorrektur ─────────────────────────────────────────────────────────────

def zuordnung_setzen(
    con: sqlite3.Connection, einheit_id: int, kategorie_id: int | None
) -> dict:
    """Setzt die Kategorie einer Einheit von Hand.

    Setzt kategorie_herkunft auf 'manuell' und konfidenz auf NULL: die
    Konfidenz beschrieb ein maschinelles Urteil, das damit hinfällig ist.
    kategorie_lauf_id wird geleert — die Zuordnung stammt aus keinem Lauf.
    """
    zeile = con.execute(
        "SELECT e.id, q.projekt_id FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE e.id = ?",
        (einheit_id,),
    ).fetchone()
    if zeile is None:
        raise KlassifikationFehler(
            f"Keine Einheit mit der Kennung {einheit_id}.", "einheit_nicht_gefunden"
        )
    projekt_id = zeile[1]

    if kategorie_id is not None:
        gehoert = con.execute(
            "SELECT 1 FROM kategorie WHERE id = ? AND projekt_id = ?",
            (kategorie_id, projekt_id),
        ).fetchone()
        if gehoert is None:
            raise KlassifikationFehler(
                f"Kategorie {kategorie_id} gehört nicht zu Projekt '{projekt_id}'.",
                "kategorie_nicht_gefunden",
            )

    with con:
        con.execute(
            "UPDATE einheit SET kategorie_id = ?, konfidenz = NULL, "
            "kategorie_herkunft = 'manuell', kategorie_lauf_id = NULL WHERE id = ?",
            (kategorie_id, einheit_id),
        )

    return {
        "einheit_id": einheit_id,
        "kategorie_id": kategorie_id,
        "konfidenz": None,
        "kategorie_herkunft": "manuell",
        "kategorie_lauf_id": None,
    }
