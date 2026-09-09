"""
dienst.py — eine Frage beantworten, stückweise

Liest die Einheiten eines Projekts, lässt den Kern die Absätze finden, fragt
das Sprachmodell und gibt Ereignisse aus. Kein print, keine HTTP-Begriffe —
was daraus SSE macht, steht in src/neu/server/chat.py.

Der Chat schreibt nichts. Keine lauf-Zeile: ein Lauf ist etwas, dessen
Ergebnis in der Datenbank steht und das man wiederaufnehmen kann. Eine Frage
ist beides nicht.

Die Embeddings kommen aus dem Speicher und werden hier nie gerechnet
(vektoren.vorhandene). Für ber lägen sonst 949 Einheiten vor dem ersten Wort
der Antwort — der Themenlauf hat sie längst berechnet, und wenn nicht, ist die
richtige Antwort 'dann sucht der Chat eben nur nach Stichwörtern' und nicht
'dann wartet der Fragende zehn Minuten'.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from src.neu import vektoren
from src.neu.anbieter import AnbieterFehler, embedding_funktion, llm_strom_funktion
from src.neu.chat import kern
from src.neu.chat.kern import Einheit
from src.neu.export.kern import Einheit as ExportEinheit
from src.neu.export.kern import anker as anker_bilden

# Genau die Kürzung, mit der der Themenlauf embeddet hat. Stünde sie hier
# anders, passte keine Prüfsumme mehr, vektoren.vorhandene() fände nichts, und
# der Bedeutungsweg fiele still aus — ohne dass irgendwo etwas bricht.
from src.neu.kategorien.kern import SEG_CHARS

protokoll = logging.getLogger("ber.neu")


class ChatFehler(Exception):
    def __init__(self, meldung: str, code: str = "chat_fehler"):
        super().__init__(meldung)
        self.code = code


# ── Ereignisse ────────────────────────────────────────────────────────────────
# Typisiert, nicht als Wörter im Text. Der alte Weg schob __done__, __error__
# und __link__ mitten in den Textstrom und ließ den Browser sie wieder
# herausklauben — womit jeder Absatz, der zufällig so anfing, den Leser
# durcheinanderbrachte. Hier ist die Art des Ereignisses eine eigene Angabe
# neben dem Text, nie in ihm.

@dataclass(frozen=True)
class Stueck:
    """Ein Stück Antworttext, roh."""

    text: str


@dataclass(frozen=True)
class Fertig:
    """Der Abschluss: womit gesucht wurde und was die Antwort belegt."""

    quellen: list[str]          # Anker, die im Antworttext vorkommen
    stichwoerter: list[str]
    absaetze: int               # wie viele in den Prompt gingen
    wege: list[str]             # 'stichwoerter' und/oder 'bedeutung'
    modell: str


@dataclass(frozen=True)
class Abbruch:
    """Etwas ist schiefgegangen. Eigener Typ, kein Text im Strom."""

    code: str
    meldung: str


Ereignis = Stueck | Fertig | Abbruch


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _jahr(datum: str | None, jahr_von: int | None) -> int | None:
    """Das Jahr für die Anzeige im Prompt — wie im Export."""
    if jahr_von is not None:
        return jahr_von
    if datum:
        try:
            return int(str(datum)[:4])
        except ValueError:
            return None
    return None


def einheiten_lesen(con: sqlite3.Connection, projekt_id: str) -> list[Einheit]:
    """Die content-Einheiten des Projekts, mit ihrem Anker und ihrem Jahr.

    Der Anker kommt aus export.kern.anker() und wird hier nicht nachgebaut. Er
    muss derselbe sein wie in data.json, sonst nennt die Antwort Kennungen, zu
    denen viz/ keinen Absatz findet — und der Fehler fiele erst dem Leser auf,
    der auf eine Quellenangabe klickt.
    """
    zeilen = con.execute(
        "SELECT e.id, e.quelle_id, e.text, e.datum, e.jahr_von "
        "FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' "
        "ORDER BY q.id, e.position",
        (projekt_id,),
    ).fetchall()
    return [
        Einheit(
            id=einheit_id,
            anker=anker_bilden(ExportEinheit(id=einheit_id, quelle_id=quelle_id, text="")),
            jahr=_jahr(datum, jahr_von),
            text=text or "",
        )
        for einheit_id, quelle_id, text, datum, jahr_von in zeilen
    ]


# ── Suchen ────────────────────────────────────────────────────────────────────

def bedeutungs_rangliste(
    con: sqlite3.Connection, einheiten: list[Einheit], frage: str
) -> list[int]:
    """Rangliste nach Kosinus zur Frage — oder leer, wenn das nicht geht.

    Leer heißt hier nicht 'Fehler', sondern 'dieser Weg trägt nichts bei'. Die
    Zusammenführung kommt damit zurecht, und eine Antwort nur nach Stichwörtern
    ist besser als keine. Es tritt ein, wenn kein Embedding-Anbieter
    eingerichtet ist oder für dieses Projekt noch kein Themenlauf gelaufen ist.
    """
    if not einheiten:
        return []
    try:
        einbetten, modell = embedding_funktion("themen")
    except AnbieterFehler as exc:
        protokoll.info("Chat ohne Bedeutungssuche: %s", exc)
        return []

    gekuerzt = [(e.id, e.text[:SEG_CHARS]) for e in einheiten]
    abgelegt = vektoren.vorhandene(con, gekuerzt, modell)
    if not abgelegt:
        protokoll.info(
            "Chat ohne Bedeutungssuche: kein Vektor unter %s für dieses Projekt "
            "— erst den Themenlauf laufen lassen.", modell,
        )
        return []

    ids = [e.id for e in einheiten if e.id in abgelegt]
    matrix = np.vstack([abgelegt[i] for i in ids])
    frage_vektor = np.asarray(einbetten([frage]), dtype=np.float32)[0]
    werte = kern.aehnlichkeiten(frage_vektor, matrix)
    return kern.aehnlichkeits_rangliste(ids, werte, hoechstens=kern.ABSAETZE)


@dataclass(frozen=True)
class Fund:
    """Was die Suche gefunden hat, bevor gefragt wird."""

    absaetze: list[Einheit]
    stichwoerter: list[str]
    wege: list[str]


def suchen(con: sqlite3.Connection, projekt_id: str, frage: str) -> Fund:
    """Die Absätze zu einer Frage — beide Wege, per RRF zusammengelegt."""
    einheiten = einheiten_lesen(con, projekt_id)
    worte = kern.stichwoerter(frage)

    nach_wort = kern.stichwort_rangliste(einheiten, worte)
    nach_sinn = bedeutungs_rangliste(con, einheiten, frage)

    wege = [name for name, liste in (("stichwoerter", nach_wort),
                                     ("bedeutung", nach_sinn)) if liste]
    gewaehlt = kern.verschmelzen([nach_wort, nach_sinn])

    nach_id = {e.id: e for e in einheiten}
    return Fund(absaetze=[nach_id[i] for i in gewaehlt],
                stichwoerter=worte, wege=wege)


# ── Antworten ─────────────────────────────────────────────────────────────────

OHNE_TREFFER = ("Zu dieser Frage wurden keine passenden Einträge im Material "
                "gefunden.")


def antworten(
    con: sqlite3.Connection,
    projekt_id: str,
    frage: str,
    strom_funktion: Callable[[], tuple[Callable[[str, str], Iterator[str]], str]]
    | None = None,
) -> Iterator[Ereignis]:
    """Die Antwort als Folge von Ereignissen.

    `strom_funktion` ist für Tests da: von außen hereingereicht bleibt der
    ganze Weg ohne Netz prüfbar.

    Ohne Treffer wird das Modell nicht gefragt. Ein Prompt ohne Auszüge lädt
    genau die Erfindungen ein, gegen die der Systemprompt anschreibt.

    Ab dem ersten Stück ist die HTTP-Antwort unterwegs; ein Fehler danach kann
    keinen Status mehr setzen. Deshalb ist Abbruch ein Ereignis wie die
    anderen — der Leser erfährt davon im selben Strom.
    """
    if not frage.strip():
        yield Abbruch("frage_leer", "Die Frage darf nicht leer sein.")
        return

    fund = suchen(con, projekt_id, frage)

    if not fund.absaetze:
        yield Stueck(OHNE_TREFFER)
        yield Fertig(quellen=[], stichwoerter=fund.stichwoerter,
                     absaetze=0, wege=fund.wege, modell="")
        return

    try:
        strom, modell = (strom_funktion or llm_strom_funktion)()
    except AnbieterFehler as exc:
        yield Abbruch(exc.code, str(exc))
        return

    prompt = kern.benutzer_prompt(frage, fund.absaetze)
    angeboten = [e.anker for e in fund.absaetze]
    gesammelt: list[str] = []

    try:
        for stueck in strom(prompt, kern.SYSTEM):
            gesammelt.append(stueck)
            yield Stueck(stueck)
    except AnbieterFehler as exc:
        yield Abbruch(exc.code, str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        yield Abbruch("modell_fehler", f"{type(exc).__name__}: {exc}")
        return

    yield Fertig(
        quellen=kern.genannte_quellen("".join(gesammelt), angeboten),
        stichwoerter=fund.stichwoerter,
        absaetze=len(fund.absaetze),
        wege=fund.wege,
        modell=modell,
    )
