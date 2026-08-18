"""
dienst.py — Akteure erkennen, ändern, verschmelzen

Liest die Einheiten aus der Datenbank, lässt Erkenner, Embedding und Kern
rechnen und schreibt in einer Transaktion: akteur, akteur_alias,
einheit_akteur, verschmelzungskandidat, die lauf-Zeile.

Kein print — wer etwas anzeigen will, nimmt das AkteurErgebnis.

Was ein Neulauf nicht anfasst, steht in der Datenbank: akteur.herkunft.
'manuell' bleibt unberührt, 'abgelehnt' bleibt und filtert den Fehlfund
erneut heraus. Alles, was über einen PATCH geht, wird dadurch 'manuell'.

Die Zuordnung zu Einheiten wird aus Normalform und Aliasen abgeleitet, nicht
aus dem Erkenner. Wer Aliase ändert, bekommt sie deshalb sofort neu — heute
läuft match_entities.py nach dem Editor nicht.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence

import numpy as np

from src.neu.akteure import kern
from src.neu.akteure.kern import Akteur


class AkteurFehler(Exception):
    def __init__(self, meldung: str, code: str = "akteur_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class AkteurErgebnis:
    projekt_id: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    embedding_modell: str
    gliner_modell: str
    schwelle: float
    anzahl_einheiten: int
    anzahl_funde: int
    anzahl_vor_gruppierung: int
    anzahl_neu: int
    anzahl_manuell: int
    anzahl_abgelehnt: int
    anzahl_zuordnungen: int
    anzahl_einheiten_mit_akteur: int
    anzahl_je_typ: dict[str, int] = field(default_factory=dict)
    anzahl_kandidaten_je_grund: dict[str, int] = field(default_factory=dict)
    # Labels, die die Abbildung nicht kennt — gemeldet, nicht still zu Konzept.
    unbekannte_labels: dict[str, int] = field(default_factory=dict)
    # Funde, die auf einen von Hand gepflegten Namen fielen; der bleibt stehen.
    verdraengt_von_manuell: list[str] = field(default_factory=list)


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _projekt_pruefen(con: sqlite3.Connection, projekt_id: str) -> None:
    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise AkteurFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )


def _einheiten(con: sqlite3.Connection, projekt_id: str) -> list[tuple[int, str]]:
    """Alle content-Einheiten des Projekts in Dokumentreihenfolge."""
    return [(z[0], z[1]) for z in con.execute(
        "SELECT e.id, e.text FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' "
        "ORDER BY e.quelle_id, e.position",
        (projekt_id,),
    ).fetchall()]


def _akteure_lesen(
    con: sqlite3.Connection, projekt_id: str, status: str | None = None,
    herkunft: str | None = None,
) -> list[tuple[int, Akteur, str, str]]:
    """Akteure des Projekts als (id, Akteur, status, herkunft)."""
    sql = ("SELECT id, normalform, typ, status, herkunft FROM akteur "
           "WHERE projekt_id = ?")
    args: list = [projekt_id]
    if status is not None:
        sql += " AND status = ?"
        args.append(status)
    if herkunft is not None:
        sql += " AND herkunft = ?"
        args.append(herkunft)
    sql += " ORDER BY id"

    zeilen = con.execute(sql, args).fetchall()
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

    return [(z[0], Akteur(normalform=z[1], typ=z[2], aliase=aliase[z[0]]), z[3], z[4])
            for z in zeilen]


# ── Schreiben ─────────────────────────────────────────────────────────────────

def _akteur_schreiben(
    con: sqlite3.Connection, projekt_id: str, akteur: Akteur,
    status: str, herkunft: str,
) -> int:
    zeiger = con.execute(
        "INSERT INTO akteur (projekt_id, normalform, typ, status, herkunft) "
        "VALUES (?, ?, ?, ?, ?)",
        (projekt_id, akteur.normalform, akteur.typ, status, herkunft),
    )
    akteur_id = zeiger.lastrowid
    _aliase_schreiben(con, akteur_id, akteur.aliase)
    return akteur_id


def _aliase_schreiben(con: sqlite3.Connection, akteur_id: int, aliase: Sequence[str]) -> None:
    """Setzt die Aliasliste. Die Normalform steht nicht darunter."""
    con.execute("DELETE FROM akteur_alias WHERE akteur_id = ?", (akteur_id,))
    gesehen: set[str] = set()
    zeilen = []
    for alias in aliase:
        alias = (alias or "").strip()
        if not alias or alias.lower() in gesehen:
            continue
        gesehen.add(alias.lower())
        zeilen.append((akteur_id, alias))
    con.executemany(
        "INSERT INTO akteur_alias (akteur_id, alias) VALUES (?, ?)", zeilen
    )


def _zuordnen(
    con: sqlite3.Connection,
    einheiten: Sequence[tuple[int, str]],
    akteure: Sequence[tuple[int, Akteur]],
) -> int:
    """Legt einheit_akteur für die genannten Akteure neu an.

    Die Fundstellen kommen aus dem Wortgrenz-Regex über Normalform und Aliase.
    """
    ids = [a[0] for a in akteure]
    if ids:
        platz = ",".join("?" * len(ids))
        con.execute(f"DELETE FROM einheit_akteur WHERE akteur_id IN ({platz})", ids)

    zeilen: list[tuple[int, int, int, int]] = []
    for akteur_id, akteur in akteure:
        muster = kern.muster_fuer(akteur)
        if muster is None:
            continue
        for stelle in kern.fundstellen(einheiten, muster):
            zeilen.append((stelle.einheit_id, akteur_id, stelle.start, stelle.ende))

    con.executemany(
        "INSERT INTO einheit_akteur (einheit_id, akteur_id, start, ende) "
        "VALUES (?, ?, ?, ?)", zeilen,
    )
    return len(zeilen)


def _kandidaten_schreiben(
    con: sqlite3.Connection, projekt_id: str,
    akteure: Sequence[tuple[int, Akteur]], embeddings: np.ndarray | None,
    schwelle: float,
) -> dict[str, int]:
    """Berechnet die Verschmelzungskandidaten neu und ersetzt die alten.

    Serverseitig und einmal je Lauf — nicht bei jedem Tastendruck im Browser,
    und nicht aus zwei Quellen, die sich widersprechen.
    """
    con.execute("DELETE FROM verschmelzungskandidat WHERE projekt_id = ?", (projekt_id,))
    if len(akteure) < 2:
        return {}

    jetzt = _jetzt()
    gefunden = kern.kandidaten([a[1] for a in akteure], embeddings, schwelle)
    zeilen = []
    je_grund: Counter = Counter()
    for k in gefunden:
        a_id, b_id = akteure[k.a][0], akteure[k.b][0]
        if a_id > b_id:
            a_id, b_id = b_id, a_id
        zeilen.append((projekt_id, a_id, b_id, k.grund, k.mass, jetzt))
        je_grund[k.grund] += 1

    con.executemany(
        "INSERT INTO verschmelzungskandidat "
        "(projekt_id, akteur_a_id, akteur_b_id, grund, mass, berechnet_am) "
        "VALUES (?, ?, ?, ?, ?, ?)", zeilen,
    )
    return dict(je_grund)


# ── Erkennen ──────────────────────────────────────────────────────────────────

def erkennen(
    con: sqlite3.Connection,
    projekt_id: str,
    vorhersage: Callable[[str, list[str], float], list[dict]] | None = None,
    embed: Callable[[list[str]], np.ndarray] | None = None,
    embedding_modell: str | None = None,
    gliner_modell: str | None = None,
    schwelle: float | None = None,
) -> AkteurErgebnis:
    """Erkennt die Akteure eines Projekts und ordnet sie den Einheiten zu.

    Erkenner und Embedding kommen aus src.neu.akteure.anbieter, wenn sie nicht
    übergeben werden — dann bricht ein fehlender Anbieter den Lauf ab, statt
    stillschweigend ein anderes Modell zu nehmen.
    """
    begonnen_am = _jetzt()
    _projekt_pruefen(con, projekt_id)

    if vorhersage is None or embed is None:
        from src.neu.akteure.anbieter import embedding_funktion, gliner_funktion

        if embed is None:
            embed, embedding_modell, schwelle_anbieter = embedding_funktion()
            if schwelle is None:
                schwelle = schwelle_anbieter
        if vorhersage is None:
            vorhersage, gliner_modell = gliner_funktion()
    if schwelle is None:
        raise AkteurFehler(
            "Ohne Anbieter muss die Schwelle übergeben werden.", "schwelle_fehlt"
        )

    parameter = json.dumps({
        "embedding_modell": embedding_modell,
        "gliner_modell": gliner_modell,
        "schwelle": schwelle,
    }, ensure_ascii=False)

    try:
        einheiten = _einheiten(con, projekt_id)
        if not einheiten:
            raise AkteurFehler(
                f"Projekt '{projekt_id}' hat keine content-Einheiten.", "keine_einheiten"
            )

        bestand = _akteure_lesen(con, projekt_id)
        abgelehnt = [a.normalform for _, a, st, _ in bestand if st == "abgelehnt"]
        geschuetzt = [(i, a) for i, a, st, hk in bestand
                      if hk == "manuell" and st == "aktiv"]

        # Der Bestand dient als Landkarte: Kurzformen werden auf die bekannten
        # Vollnamen zurückgeführt, bevor zusammengefasst wird.
        landkarte = kern.alias_landkarte([a for _, a in geschuetzt])

        funde, unbekannte = kern.erkenne(
            [t for _, t in einheiten], vorhersage,
            landkarte=landkarte, abgelehnt=abgelehnt,
        )
        vor_gruppierung = kern.zusammenfassen([kern.funde_zu_akteuren(funde)])

        if vor_gruppierung:
            embs = embed([a.normalform for a in vor_gruppierung])
            neue = kern.gruppiere(vor_gruppierung, embs, schwelle)
        else:
            neue = []

        # Ein Fund, der auf einen von Hand gepflegten Namen fällt, wird nicht
        # geschrieben: die Handkorrektur bleibt, samt ihrer Aliase.
        belegt = {a.normalform.lower() for _, a, st, hk in bestand
                  if hk == "manuell" or st == "abgelehnt"}
        verdraengt = [a.normalform for a in neue if a.normalform.lower() in belegt]
        neue = [a for a in neue if a.normalform.lower() not in belegt]

        with con:
            zeiger = con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, status) "
                "VALUES (?, 'akteure', ?, ?, 'laeuft')",
                (projekt_id, begonnen_am, parameter),
            )
            lauf_id = zeiger.lastrowid

            con.execute(
                "DELETE FROM akteur WHERE projekt_id = ? AND herkunft = 'gliner'",
                (projekt_id,),
            )
            for akteur in neue:
                _akteur_schreiben(con, projekt_id, akteur, "aktiv", "gliner")

            # Ein abgelehnter Akteur zeigt auf nichts. Seine Verknüpfungen aus
            # einem früheren Lauf würden sonst stehen bleiben, weil _zuordnen
            # nur die aktiven anfasst.
            con.execute(
                "DELETE FROM einheit_akteur WHERE akteur_id IN "
                "(SELECT id FROM akteur WHERE projekt_id = ? AND status <> 'aktiv')",
                (projekt_id,),
            )

            aktive = [(i, a) for i, a, st, _ in _akteure_lesen(con, projekt_id)
                      if st == "aktiv"]
            anzahl_zuordnungen = _zuordnen(con, einheiten, aktive)

            kand_embs = embed([a.normalform for _, a in aktive]) if len(aktive) > 1 else None
            je_grund = _kandidaten_schreiben(
                con, projekt_id, aktive, kand_embs, schwelle
            )

            beendet_am = _jetzt()
            con.execute(
                "UPDATE lauf SET beendet_am = ?, parameter = ?, status = 'erfolg' "
                "WHERE id = ?",
                (beendet_am, json.dumps({
                    "embedding_modell": embedding_modell,
                    "gliner_modell": gliner_modell,
                    "schwelle": schwelle,
                    "funde": len(funde),
                    "akteure": len(aktive),
                    "zuordnungen": anzahl_zuordnungen,
                    "unbekannte_labels": dict(unbekannte),
                    "verdraengt_von_manuell": verdraengt,
                }, ensure_ascii=False), lauf_id),
            )

    except Exception as exc:
        with con:
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'akteure', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"fehler": str(exc)}, ensure_ascii=False)),
            )
        raise

    je_typ: dict[str, int] = {}
    for _, a in aktive:
        schluessel = a.typ or "ohne Typ"
        je_typ[schluessel] = je_typ.get(schluessel, 0) + 1

    mit_akteur = con.execute(
        "SELECT COUNT(DISTINCT einheit_id) FROM einheit_akteur ea "
        "JOIN akteur k ON k.id = ea.akteur_id WHERE k.projekt_id = ?",
        (projekt_id,),
    ).fetchone()[0]

    return AkteurErgebnis(
        projekt_id=projekt_id,
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        embedding_modell=embedding_modell or "",
        gliner_modell=gliner_modell or "",
        schwelle=schwelle,
        anzahl_einheiten=len(einheiten),
        anzahl_funde=len(funde),
        anzahl_vor_gruppierung=len(vor_gruppierung),
        anzahl_neu=len(neue),
        anzahl_manuell=len(geschuetzt),
        anzahl_abgelehnt=len(abgelehnt),
        anzahl_zuordnungen=anzahl_zuordnungen,
        anzahl_einheiten_mit_akteur=mit_akteur,
        anzahl_je_typ=je_typ,
        anzahl_kandidaten_je_grund=je_grund,
        unbekannte_labels=dict(unbekannte),
        verdraengt_von_manuell=verdraengt,
    )


# ── Handkorrektur ─────────────────────────────────────────────────────────────

UNGESETZT = object()
"""Kennzeichen für „nicht mitgeschickt" — zu unterscheiden von einem gesetzten None."""


def akteur_aendern(
    con: sqlite3.Connection,
    akteur_id: int,
    normalform: str | None = None,
    typ: object = UNGESETZT,
    status: str | None = None,
    aliase: Sequence[str] | None = None,
) -> dict:
    """Ändert einen Akteur von Hand.

    Was hier geändert wird, gilt danach als 'manuell' und bleibt bei Neuläufen
    unberührt. Ändern sich Normalform oder Aliase, werden die Verknüpfungen zu
    den Einheiten für diesen Akteur sofort neu abgeleitet.
    """
    zeile = con.execute(
        "SELECT a.projekt_id, a.normalform, a.typ, a.status FROM akteur a WHERE a.id = ?",
        (akteur_id,),
    ).fetchone()
    if zeile is None:
        raise AkteurFehler(
            f"Kein Akteur mit der Kennung {akteur_id}.", "akteur_nicht_gefunden"
        )
    projekt_id, alte_normalform, alter_typ, alter_status = zeile

    neue_normalform = (normalform or alte_normalform).strip()
    if not neue_normalform:
        raise AkteurFehler("normalform darf nicht leer sein.", "normalform_leer")

    neuer_typ = alter_typ if typ is UNGESETZT else typ
    if neuer_typ is not None and neuer_typ not in kern.TYPEN:
        raise AkteurFehler(
            f"Unbekannter Typ '{neuer_typ}'. Erlaubt: {' | '.join(kern.TYPEN)}",
            "typ_unbekannt",
        )

    neuer_status = status or alter_status
    if neuer_status not in kern.STATUS:
        raise AkteurFehler(
            f"Unbekannter Status '{neuer_status}'. Erlaubt: {' | '.join(kern.STATUS)}",
            "status_unbekannt",
        )

    if neue_normalform.lower() != alte_normalform.lower():
        kollision = con.execute(
            "SELECT id FROM akteur WHERE projekt_id = ? AND lower(normalform) = ? "
            "AND id <> ?",
            (projekt_id, neue_normalform.lower(), akteur_id),
        ).fetchone()
        if kollision is not None:
            raise AkteurFehler(
                f"'{neue_normalform}' gibt es in diesem Projekt schon "
                f"(Akteur {kollision[0]}). Zum Zusammenlegen verschmelzen.",
                "normalform_belegt",
            )

    with con:
        con.execute(
            "UPDATE akteur SET normalform = ?, typ = ?, status = ?, herkunft = 'manuell' "
            "WHERE id = ?",
            (neue_normalform, neuer_typ, neuer_status, akteur_id),
        )
        if aliase is not None:
            _aliase_schreiben(con, akteur_id, aliase)

        akteur = _akteur_holen(con, akteur_id)
        einheiten = _einheiten(con, projekt_id)
        if neuer_status == "aktiv":
            _zuordnen(con, einheiten, [(akteur_id, akteur)])
        else:
            # Ein abgelehnter Akteur zeigt auf nichts mehr.
            con.execute("DELETE FROM einheit_akteur WHERE akteur_id = ?", (akteur_id,))

        # Die Kandidatenpaare dieses Akteurs sind nach der Änderung überholt.
        # Neu gerechnet wird beim nächsten Lauf, nicht bei jedem Tastendruck.
        con.execute(
            "DELETE FROM verschmelzungskandidat "
            "WHERE akteur_a_id = ? OR akteur_b_id = ?", (akteur_id, akteur_id),
        )

    return _akteur_antwort(con, akteur_id)


def akteure_verschmelzen(
    con: sqlite3.Connection, ids: Sequence[int], behalten_id: int
) -> dict:
    """Führt beliebige Akteure zu einem zusammen.

    Der Aufrufer bestimmt, welche Normalform bleibt — die Vorlage nahm immer
    den linken Eintrag des vorgeschlagenen Paares. Vorgeschlagen sein muss ein
    Paar hier nicht.
    """
    eindeutig = list(dict.fromkeys(ids))
    if len(eindeutig) < 2:
        raise AkteurFehler(
            "Zum Verschmelzen braucht es mindestens zwei verschiedene Akteure.",
            "zu_wenige_akteure",
        )
    if behalten_id not in eindeutig:
        raise AkteurFehler(
            f"behalten_id {behalten_id} steht nicht in ids.", "behalten_nicht_in_ids"
        )

    platz = ",".join("?" * len(eindeutig))
    zeilen = con.execute(
        f"SELECT id, projekt_id FROM akteur WHERE id IN ({platz})", eindeutig
    ).fetchall()
    gefunden = {z[0] for z in zeilen}
    fehlend = [i for i in eindeutig if i not in gefunden]
    if fehlend:
        raise AkteurFehler(
            f"Kein Akteur mit der Kennung {fehlend[0]}.", "akteur_nicht_gefunden"
        )
    projekte = {z[1] for z in zeilen}
    if len(projekte) > 1:
        raise AkteurFehler(
            "Akteure aus verschiedenen Projekten lassen sich nicht verschmelzen.",
            "projekte_verschieden",
        )
    projekt_id = projekte.pop()

    akteure = [_akteur_holen(con, i) for i in eindeutig]
    behalten = _akteur_holen(con, behalten_id)
    verschmolzen = kern.verschmelzen(akteure, behalten.normalform)

    with con:
        con.execute(
            "UPDATE akteur SET normalform = ?, typ = ?, herkunft = 'manuell' WHERE id = ?",
            (verschmolzen.normalform, verschmolzen.typ, behalten_id),
        )
        _aliase_schreiben(con, behalten_id, verschmolzen.aliase)

        weg = [i for i in eindeutig if i != behalten_id]
        platz_weg = ",".join("?" * len(weg))
        # Die Verknüpfungen und Kandidatenpaare der aufgelösten Akteure gehen
        # per ON DELETE CASCADE mit.
        con.execute(f"DELETE FROM akteur WHERE id IN ({platz_weg})", weg)

        _zuordnen(con, _einheiten(con, projekt_id), [(behalten_id, verschmolzen)])
        con.execute(
            "DELETE FROM verschmelzungskandidat "
            "WHERE akteur_a_id = ? OR akteur_b_id = ?", (behalten_id, behalten_id),
        )

    return _akteur_antwort(con, behalten_id, aufgeloest=weg)


# ── Lesen für die Antwort ─────────────────────────────────────────────────────

def _akteur_holen(con: sqlite3.Connection, akteur_id: int) -> Akteur:
    zeile = con.execute(
        "SELECT normalform, typ FROM akteur WHERE id = ?", (akteur_id,)
    ).fetchone()
    if zeile is None:
        raise AkteurFehler(
            f"Kein Akteur mit der Kennung {akteur_id}.", "akteur_nicht_gefunden"
        )
    aliase = [z[0] for z in con.execute(
        "SELECT alias FROM akteur_alias WHERE akteur_id = ? ORDER BY alias", (akteur_id,)
    )]
    return Akteur(normalform=zeile[0], typ=zeile[1], aliase=aliase)


def _akteur_antwort(
    con: sqlite3.Connection, akteur_id: int, aufgeloest: Sequence[int] = ()
) -> dict:
    zeile = con.execute(
        "SELECT id, projekt_id, normalform, typ, status, herkunft FROM akteur WHERE id = ?",
        (akteur_id,),
    ).fetchone()
    aliase = [z[0] for z in con.execute(
        "SELECT alias FROM akteur_alias WHERE akteur_id = ? ORDER BY alias", (akteur_id,)
    )]
    anzahl = con.execute(
        "SELECT COUNT(*) FROM einheit_akteur WHERE akteur_id = ?", (akteur_id,)
    ).fetchone()[0]
    return {
        "id": zeile[0],
        "projekt_id": zeile[1],
        "normalform": zeile[2],
        "typ": zeile[3],
        "status": zeile[4],
        "herkunft": zeile[5],
        "aliase": aliase,
        "anzahl_fundstellen": anzahl,
        "aufgeloeste_akteure": list(aufgeloest),
    }


def duplikatskandidaten(con: sqlite3.Connection, projekt_id: str) -> list[dict]:
    """Die gespeicherten Verschmelzungskandidaten eines Projekts.

    Gelesen, nicht gerechnet: berechnet wird beim Erkennungslauf.
    """
    _projekt_pruefen(con, projekt_id)
    return [{
        "id": z[0],
        "akteur_a_id": z[1],
        "akteur_a": z[2],
        "akteur_b_id": z[3],
        "akteur_b": z[4],
        "grund": z[5],
        "mass": z[6],
        "berechnet_am": z[7],
    } for z in con.execute(
        "SELECT k.id, k.akteur_a_id, a.normalform, k.akteur_b_id, b.normalform, "
        "       k.grund, k.mass, k.berechnet_am "
        "FROM verschmelzungskandidat k "
        "JOIN akteur a ON a.id = k.akteur_a_id "
        "JOIN akteur b ON b.id = k.akteur_b_id "
        "WHERE k.projekt_id = ? "
        "ORDER BY k.grund, k.mass IS NULL, k.mass DESC, k.id",
        (projekt_id,),
    )]
