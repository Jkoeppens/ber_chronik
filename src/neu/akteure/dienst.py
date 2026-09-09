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

from src.neu import laeufe, projekte
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
    if not projekte.gibt_es(con, projekt_id):
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
    gliner_schwelle: float | None = None,
    lauf_id: int | None = None,
) -> AkteurErgebnis:
    """Erkennt die Akteure eines Projekts und ordnet sie den Einheiten zu.

    Erkenner und Embedding kommen aus src.neu.anbieter, wenn sie nicht
    übergeben werden — dann bricht ein fehlender Anbieter den Lauf ab, statt
    stillschweigend ein anderes Modell zu nehmen.

    lauf_id: eine bereits angelegte 'laeuft'-Zeile, die fortgeschrieben wird,
    statt am Ende eine neue anzulegen. So kann die Fläche den Stand abfragen,
    während gerechnet wird — der Schritt dauert bei ber über vier Minuten.
    """
    begonnen_am = _jetzt()
    _projekt_pruefen(con, projekt_id)

    if vorhersage is None or embed is None:
        from src.neu.anbieter import (
            embedding_funktion, embedding_schwelle, gliner_funktion,
        )

        if embed is None:
            embed, embedding_modell = embedding_funktion("akteure")
            if schwelle is None:
                schwelle = embedding_schwelle()
        if vorhersage is None:
            vorhersage, gliner_modell, geerbt = gliner_funktion()
            if gliner_schwelle is None:
                gliner_schwelle = geerbt
    if schwelle is None:
        raise AkteurFehler(
            "Ohne Anbieter muss die Schwelle übergeben werden.", "schwelle_fehlt"
        )
    if gliner_schwelle is None:
        raise AkteurFehler(
            "Ohne Anbieter muss die GLiNER-Schwelle übergeben werden.",
            "gliner_schwelle_fehlt",
        )

    parameter = json.dumps({
        "embedding_modell": embedding_modell,
        "gliner_modell": gliner_modell,
        "schwelle": schwelle,
        "gliner_schwelle": gliner_schwelle,
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
            landkarte=landkarte, abgelehnt=abgelehnt, schwelle=gliner_schwelle,
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
            if lauf_id is None:
                zeiger = con.execute(
                    "INSERT INTO lauf (projekt_id, schritt, begonnen_am, parameter, "
                    "status) VALUES (?, 'akteure', ?, ?, 'laeuft')",
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
            if lauf_id is None:
                con.execute(
                    "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                    "parameter, status) VALUES (?, 'akteure', ?, ?, ?, 'fehler')",
                    (projekt_id, begonnen_am, _jetzt(),
                     json.dumps({"fehler": str(exc)}, ensure_ascii=False)),
                )
            else:
                con.execute(
                    "UPDATE lauf SET beendet_am = ?, status = 'fehler' WHERE id = ?",
                    (_jetzt(), lauf_id),
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

    Sortiert nach der Stärke des Grundes, dann nach dem Maß. Das SQL sortierte
    nach k.grund und damit alphabetisch — 'aehnlichkeit' vor 'alias', also der
    schwächste Grund zuerst. Zurechtgerückt hat das bisher der Browser.
    """
    _projekt_pruefen(con, projekt_id)
    zeilen = [{
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
        "ORDER BY k.mass IS NULL, k.mass DESC, k.id",
        (projekt_id,),
    )]
    zeilen.sort(key=lambda k: kern.kandidat_rang(k["grund"]))
    return zeilen


# ── Zusammenfassungen ─────────────────────────────────────────────────────────
# Was ein Akteur in diesem Material war, in drei Absätzen. Ein Modellaufruf je
# Akteur, geschrieben nach akteur.zusammenfassung.
#
# Warum das hier steht und nicht im Export: jeder Schritt schreibt seine eigene
# Tabelle, der Export liest nur. Die Vorlage
# (src/generalized/generate_entity_summaries.py) erzeugte die Datei
# entities_summary.json und machte sie damit zur Wahrheit — wer zweimal
# exportierte, zahlte zweimal, und wer die Datei löschte, verlor die Arbeit.
#
# Fachlich unverändert übernommen: die Auswahl von bis zu 30 Absätzen im
# Reihum-Verfahren, die Schwelle von mindestens drei Nennungen und der Prompt.

MAX_ABSAETZE = 30

# Unter drei Nennungen steht zu wenig da, um etwas über eine Rolle zu sagen.
# Die Vorlage nannte die Zahl min_mentions und hatte sie als Parameter; sie ist
# hier eine Vorgabe, die man übergeben kann.
MINDEST_NENNUNGEN = 3

ZUSAMMENFASSUNG_PROMPT = """\
Du fasst die Rolle einer Person oder Organisation in diesem historischen Text \
zusammen, auf Basis von Auszügen aus einer Chronik.

Person/Organisation: {name}

Relevante Auszüge ({gesamt} gesamt, {gezeigt} gezeigt):
{absaetze}

Schreibe eine Zusammenfassung auf Deutsch mit genau dieser Struktur \
(drei Absätze, keine Überschriften, kein JSON):

Absatz 1 – Wer: Wer ist diese Person oder Organisation? \
Welchen Hintergrund und welche Funktion hatten sie allgemein?

Absatz 2 – Rolle: Welche konkreten Aufgaben, Entscheidungen und Beiträge \
hatten sie in diesem Kontext? \
Nenne mindestens drei konkrete Jahreszahlen aus den Auszügen. \
Nenne mindestens zwei andere beteiligte Personen oder Organisationen \
mit denen sie zusammenarbeiteten oder in Beziehung standen.

Absatz 3 – Konflikte und Wendepunkte: Welche Konflikte, Krisen oder \
Kursänderungen waren mit dieser Person/Organisation verbunden? \
Was hat sich durch ihr Handeln verändert oder verschlechtert?

Schreibe ausschließlich was explizit in den Auszügen steht. \
Wenn du unsicher bist ob ein Detail in den Auszügen vorkommt, lass es weg.\
"""


@dataclass
class ZusammenfassungErgebnis:
    projekt_id: str
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    llm_modell: str
    anzahl_kandidaten: int = 0
    anzahl_geschrieben: int = 0
    anzahl_uebersprungen: int = 0
    anzahl_gescheitert: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    kosten_usd: float = 0.0


def _absaetze_waehlen(zeilen: list[dict], hoechstens: int) -> list[dict]:
    """Bis zu `hoechstens` Absätze, reihum über die Kategorien.

    Aus der Vorlage (_sample_paragraphs), dort über event_type. Der Sinn ist
    derselbe: dreißig Absätze zum selben Thema sagen weniger über eine Rolle
    als dreißig aus verschiedenen. Die Reihenfolge wird danach wieder auf die
    Dokumentreihenfolge gebracht, damit die Auszüge chronologisch stehen.
    """
    if len(zeilen) <= hoechstens:
        return zeilen
    je_kategorie: dict[str, list[dict]] = {}
    for z in zeilen:
        je_kategorie.setdefault(z.get("kategorie") or "?", []).append(z)
    eimer = list(je_kategorie.values())
    gewaehlt: list[dict] = []
    i = 0
    while len(gewaehlt) < hoechstens:
        eimer_i = eimer[i % len(eimer)]
        if eimer_i:
            gewaehlt.append(eimer_i.pop(0))
        i += 1
        if all(not e for e in eimer):
            break
    gewaehlt.sort(key=lambda z: z["einheit_id"])
    return gewaehlt


def _absaetze_je_akteur(
    con: sqlite3.Connection, projekt_id: str
) -> dict[int, list[dict]]:
    """Je Akteur die Einheiten, in denen er vorkommt, in Dokumentreihenfolge.

    Die Vorlage baute dafür eine Alias-Landkarte und ordnete Zeichenketten zu.
    Hier steht die Zuordnung schon in einheit_akteur — mit aufgelösten Aliasen,
    weil der Erkennungslauf sie aufgelöst hat.
    """
    je_akteur: dict[int, list[dict]] = {}
    for z in con.execute(
        "SELECT ea.akteur_id, e.id, e.text, e.jahr_von, k.name "
        "FROM einheit_akteur ea "
        "JOIN einheit e ON e.id = ea.einheit_id "
        "JOIN akteur a ON a.id = ea.akteur_id "
        "LEFT JOIN kategorie k ON k.id = e.kategorie_id "
        "WHERE a.projekt_id = ? "
        "GROUP BY ea.akteur_id, e.id "
        "ORDER BY ea.akteur_id, e.quelle_id, e.position",
        (projekt_id,),
    ):
        je_akteur.setdefault(z[0], []).append(
            {"einheit_id": z[1], "text": z[2], "jahr": z[3], "kategorie": z[4]}
        )
    return je_akteur


def zusammenfassungen_stand(
    con: sqlite3.Connection, projekt_id: str, mindestens: int = MINDEST_NENNUNGEN
) -> dict:
    """Wie viele Akteure eine Zusammenfassung bekämen und wie viele schon eine haben.

    Ohne Modellaufruf: die Fläche soll die Zahl am Knopf zeigen können, ohne
    dass dafür etwas gerechnet wird.
    """
    _projekt_pruefen(con, projekt_id)
    zeile = con.execute(
        "SELECT COUNT(*), COUNT(a.zusammenfassung) FROM akteur a "
        "WHERE a.projekt_id = ? AND a.status = 'aktiv' AND ("
        "  SELECT COUNT(DISTINCT ea.einheit_id) FROM einheit_akteur ea "
        "  WHERE ea.akteur_id = a.id) >= ?",
        (projekt_id, mindestens),
    ).fetchone()
    kandidaten, mit = zeile[0], zeile[1]
    return {
        "anzahl_kandidaten": kandidaten,
        "anzahl_mit_zusammenfassung": mit,
        "anzahl_offen": kandidaten - mit,
        "mindest_nennungen": mindestens,
    }


def zusammenfassungen_erzeugen(
    con: sqlite3.Connection,
    projekt_id: str,
    frage_modell: Callable[[str, str], tuple[str, int, int]] | None = None,
    llm_modell: str | None = None,
    mindestens: int = MINDEST_NENNUNGEN,
    alle: bool = False,
    lauf_id: int | None = None,
) -> ZusammenfassungErgebnis:
    """Schreibt akteur.zusammenfassung für die Akteure mit genug Nennungen.

    Ein Modellaufruf je Akteur, und nach jedem wird geschrieben: ein Abbruch
    nach der Hälfte kostet die zweite Hälfte, nicht alles. Aus demselben Grund
    ist `alle=False` die Vorgabe — wer schon eine Zusammenfassung hat, wird
    übersprungen, und ein zweiter Klick zahlt nicht noch einmal.

    Das Sprachmodell kommt aus src.neu.anbieter, wenn es nicht übergeben wird.
    """
    begonnen_am = _jetzt()
    _projekt_pruefen(con, projekt_id)

    if frage_modell is None:
        from src.neu.anbieter import llm_funktion

        frage_modell, llm_modell = llm_funktion("zusammenfassungen")

    je_akteur = _absaetze_je_akteur(con, projekt_id)
    kandidaten = [
        (z[0], z[1], z[2]) for z in con.execute(
            "SELECT id, normalform, zusammenfassung FROM akteur "
            "WHERE projekt_id = ? AND status = 'aktiv' ORDER BY normalform",
            (projekt_id,),
        )
        if len(je_akteur.get(z[0], [])) >= mindestens
    ]
    # Die mit den meisten Nennungen zuerst: bricht der Lauf ab, ist das
    # Wichtigste getan.
    kandidaten.sort(key=lambda k: -len(je_akteur.get(k[0], [])))

    offen = [k for k in kandidaten if alle or not k[2]]
    ergebnis = ZusammenfassungErgebnis(
        projekt_id=projekt_id,
        lauf_id=lauf_id or 0,
        begonnen_am=begonnen_am,
        beendet_am=begonnen_am,
        status="erfolg",
        llm_modell=llm_modell or "",
        anzahl_kandidaten=len(kandidaten),
        anzahl_uebersprungen=len(kandidaten) - len(offen),
    )

    if lauf_id is not None:
        laeufe.fortschritt(
            con, lauf_id, phase="zusammenfassen", gesamt=len(offen),
            fertig=0, llm_modell=llm_modell,
        )

    for nr, (akteur_id, normalform, _) in enumerate(offen, 1):
        absaetze = je_akteur[akteur_id]
        gezeigt = _absaetze_waehlen(absaetze, MAX_ABSAETZE)
        block = "\n\n".join(
            f"[{a['einheit_id']}, {a['jahr'] or '?'}] {a['text']}" for a in gezeigt
        )
        prompt = ZUSAMMENFASSUNG_PROMPT.format(
            name=normalform, gesamt=len(absaetze), gezeigt=len(gezeigt),
            absaetze=block,
        )

        try:
            text, ein, aus = frage_modell(prompt, "")
        except Exception:
            # Ein Akteur, an dem das Modell scheitert, beendet nicht den Lauf:
            # die übrigen sind trotzdem zu holen, und die lauf-Zeile sagt am
            # Ende, wie viele fehlen.
            ergebnis.anzahl_gescheitert += 1
            continue

        ergebnis.in_tokens += ein
        ergebnis.out_tokens += aus
        text = (text or "").strip()
        if not text:
            ergebnis.anzahl_gescheitert += 1
            continue

        with con:
            con.execute("UPDATE akteur SET zusammenfassung = ? WHERE id = ?",
                        (text, akteur_id))
        ergebnis.anzahl_geschrieben += 1

        if lauf_id is not None:
            laeufe.fortschritt(con, lauf_id, fertig=nr, zuletzt=normalform)

    # Ein Lauf, an dem jeder einzelne Aufruf gescheitert ist, ist kein Erfolg mit
    # null Ergebnissen — er ist gescheitert, und die lauf-Zeile soll das sagen.
    if offen and ergebnis.anzahl_geschrieben == 0 and ergebnis.anzahl_gescheitert:
        raise AkteurFehler(
            f"Keine der {ergebnis.anzahl_gescheitert} Zusammenfassungen ist "
            "zustande gekommen — das Sprachmodell hat auf keinen Aufruf "
            "brauchbar geantwortet.",
            "zusammenfassungen_gescheitert",
        )

    from src.neu.anbieter import kosten

    ergebnis.kosten_usd = kosten(
        ergebnis.llm_modell, ergebnis.in_tokens, ergebnis.out_tokens
    )
    ergebnis.beendet_am = _jetzt()

    if lauf_id is not None:
        laeufe.fortschritt(
            con, lauf_id, phase="fertig",
            anzahl_geschrieben=ergebnis.anzahl_geschrieben,
            anzahl_gescheitert=ergebnis.anzahl_gescheitert,
            anzahl_uebersprungen=ergebnis.anzahl_uebersprungen,
            in_tokens=ergebnis.in_tokens, out_tokens=ergebnis.out_tokens,
            kosten_usd=ergebnis.kosten_usd,
        )
        with con:
            con.execute("UPDATE lauf SET status = 'erfolg', beendet_am = ? WHERE id = ?",
                        (ergebnis.beendet_am, lauf_id))

    return ergebnis


# ── Lesen für die Fläche ──────────────────────────────────────────────────────

# Ab wann ein Akteur als Klumpen gilt: viele Namen, und der eigene ist fast nie
# der, der gefunden wurde. Beides muss zutreffen — fünf Aliase allein sind
# normal, und ein Akteur mit einem einzigen Alias, der öfter trifft als die
# Normalform, auch. Zusammen heißt es: dieser Eintrag heißt nach etwas, das er
# kaum ist. 'mustafa al hallaq' bei damaskus trägt 22 Aliase und 78
# Fundstellen, davon eine auf seinen eigenen Namen — 1,3 %.
KLUMPEN_ALIASE = 5
KLUMPEN_ANTEIL = 0.10


def _treffer_je_name(con: sqlite3.Connection, projekt_id: str) -> dict[int, dict[str, int]]:
    """Je Akteur: welcher Name wie oft die Fundstelle war.

    Die Zeichen zwischen start und ende sind das, was tatsächlich im Text
    stand. Ohne diese Zahl sieht man einem Akteur mit 22 Aliasen nicht an,
    welcher davon die Arbeit tut — die alte Fläche kannte nur die Namen.
    """
    ergebnis: dict[int, dict[str, int]] = {}
    for z in con.execute(
        "SELECT ea.akteur_id, LOWER(SUBSTR(e.text, ea.start + 1, ea.ende - ea.start)), "
        "       COUNT(*) "
        "FROM einheit_akteur ea "
        "JOIN einheit e ON e.id = ea.einheit_id "
        "JOIN akteur a ON a.id = ea.akteur_id "
        "WHERE a.projekt_id = ? GROUP BY 1, 2", (projekt_id,)
    ):
        ergebnis.setdefault(z[0], {})[z[1]] = z[2]
    return ergebnis


def liste(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Alle Akteure eines Projekts mit Aliasen, Fundstellen und Trefferzahlen."""
    _projekt_pruefen(con, projekt_id)

    aliase: dict[int, list[str]] = {}
    for z in con.execute(
        "SELECT x.akteur_id, x.alias FROM akteur_alias x "
        "JOIN akteur a ON a.id = x.akteur_id WHERE a.projekt_id = ? "
        "ORDER BY x.alias", (projekt_id,)
    ):
        aliase.setdefault(z[0], []).append(z[1])

    treffer = _treffer_je_name(con, projekt_id)
    zahlen = {z[0]: z[1] for z in con.execute(
        "SELECT ea.akteur_id, COUNT(*) FROM einheit_akteur ea "
        "JOIN akteur a ON a.id = ea.akteur_id WHERE a.projekt_id = ? "
        "GROUP BY 1", (projekt_id,))}

    akteure = []
    for z in con.execute(
        "SELECT id, normalform, typ, status, herkunft, zusammenfassung FROM akteur "
        "WHERE projekt_id = ? ORDER BY normalform COLLATE NOCASE", (projekt_id,)
    ):
        akteur_id, normalform, typ, status, herkunft, zusammenfassung = z
        meine = treffer.get(akteur_id, {})
        gesamt = zahlen.get(akteur_id, 0)
        auf_normalform = meine.get(normalform.lower(), 0)
        namen = [{"name": normalform, "ist_normalform": True,
                  "anzahl": auf_normalform}]
        namen += [{"name": a, "ist_normalform": False,
                   "anzahl": meine.get(a.lower(), 0)}
                  for a in aliase.get(akteur_id, [])]
        namen.sort(key=lambda n: (-n["anzahl"], n["name"].lower()))
        anteil = auf_normalform / gesamt if gesamt else None
        akteure.append({
            "id": akteur_id, "projekt_id": projekt_id, "normalform": normalform,
            "typ": typ, "status": status, "herkunft": herkunft,
            "aliase": aliase.get(akteur_id, []),
            "anzahl_fundstellen": gesamt,
            "namen": namen,
            "anteil_normalform": None if anteil is None else round(anteil, 4),
            "ist_klumpen": (len(aliase.get(akteur_id, [])) >= KLUMPEN_ALIASE
                            and gesamt > 0 and anteil < KLUMPEN_ANTEIL),
            "zusammenfassung": zusammenfassung,
        })

    return {
        "projekt_id": projekt_id,
        "anzahl": len(akteure),
        "anzahl_manuell": sum(1 for a in akteure if a["herkunft"] == "manuell"),
        "anzahl_abgelehnt": sum(1 for a in akteure if a["status"] == "abgelehnt"),
        "anzahl_klumpen": sum(1 for a in akteure if a["ist_klumpen"]),
        **zusammenfassungen_stand(con, projekt_id),
        "akteure": akteure,
    }


def fundstellen_je_einheit(con: sqlite3.Connection, projekt_id: str) -> dict[int, list[dict]]:
    """Die Markierungen je Einheit — gelesen, nicht gesucht.

    Die alte Fläche suchte jeden Namen bei jedem Rendern per indexOf im Text.
    Sie zeigte damit, wo ein Name vorkommt; hier steht, wo er zugeordnet ist.
    Bei einem Akteur mit 22 Aliasen ist das der Unterschied zwischen einer
    Vermutung und einem Befund.
    """
    ergebnis: dict[int, list[dict]] = {}
    for z in con.execute(
        "SELECT ea.einheit_id, ea.id, ea.akteur_id, ea.start, ea.ende, "
        "       a.normalform, a.typ "
        "FROM einheit_akteur ea JOIN akteur a ON a.id = ea.akteur_id "
        "WHERE a.projekt_id = ? ORDER BY ea.einheit_id, ea.start", (projekt_id,)
    ):
        ergebnis.setdefault(z[0], []).append({
            "id": z[1], "akteur_id": z[2], "start": z[3], "ende": z[4],
            "normalform": z[5], "typ": z[6],
        })
    return ergebnis


# ── Von Hand anlegen, herauslösen, Fundstelle entfernen ───────────────────────

def anlegen(
    con: sqlite3.Connection, projekt_id: str, normalform: str,
    typ: str | None = None, aliase: Sequence[str] = (),
) -> dict:
    """Legt einen Akteur von Hand an — herkunft='manuell', gegen Läufe geschützt."""
    _projekt_pruefen(con, projekt_id)
    normalform = (normalform or "").strip()
    if not normalform:
        raise AkteurFehler("normalform darf nicht leer sein.", "normalform_leer")
    if typ is not None and typ not in kern.TYPEN:
        raise AkteurFehler(
            f"Unbekannter Typ '{typ}'. Erlaubt: {' | '.join(kern.TYPEN)}", "typ_unbekannt"
        )
    belegt = con.execute(
        "SELECT id FROM akteur WHERE projekt_id = ? AND lower(normalform) = ?",
        (projekt_id, normalform.lower()),
    ).fetchone()
    if belegt is not None:
        raise AkteurFehler(
            f"'{normalform}' gibt es in diesem Projekt schon (Akteur {belegt[0]}). "
            "Zum Zusammenlegen verschmelzen.",
            "normalform_belegt",
        )

    with con:
        akteur_id = _akteur_schreiben(
            con, projekt_id,
            Akteur(normalform=normalform, typ=typ, aliase=list(aliase)),
            status="aktiv", herkunft="manuell",
        )
        _zuordnen(con, _einheiten(con, projekt_id),
                  [(akteur_id, _akteur_holen(con, akteur_id))])
    return _akteur_antwort(con, akteur_id)


def alias_herausloesen(
    con: sqlite3.Connection, akteur_id: int, alias: str, typ: object = UNGESETZT,
) -> dict:
    """Macht aus einem Alias einen eigenen Akteur.

    Die Bedienung, die einen Klumpen auflöst: 'zahrawi' steckt in
    'mustafa al hallaq' und ist eine andere Person. Den Alias nur zu entfernen
    ließe ihn verschwinden; ihn von Hand neu anzulegen wäre derselbe Vorgang in
    zwei Schritten, zwischen denen die Fundstellen niemandem gehören.

    Beide werden danach neu zugeordnet — der alte verliert die Stellen des
    Alias, der neue bekommt sie.
    """
    zeile = con.execute(
        "SELECT projekt_id, typ FROM akteur WHERE id = ?", (akteur_id,)
    ).fetchone()
    if zeile is None:
        raise AkteurFehler(
            f"Kein Akteur mit der Kennung {akteur_id}.", "akteur_nicht_gefunden"
        )
    projekt_id, alter_typ = zeile

    alias = (alias or "").strip()
    vorhanden = [z[0] for z in con.execute(
        "SELECT alias FROM akteur_alias WHERE akteur_id = ?", (akteur_id,))]
    passend = next((a for a in vorhanden if a.lower() == alias.lower()), None)
    if passend is None:
        raise AkteurFehler(
            f"'{alias}' ist kein Alias von Akteur {akteur_id}.", "alias_nicht_gefunden"
        )

    belegt = con.execute(
        "SELECT id FROM akteur WHERE projekt_id = ? AND lower(normalform) = ?",
        (projekt_id, passend.lower()),
    ).fetchone()
    if belegt is not None:
        raise AkteurFehler(
            f"'{passend}' ist schon ein eigener Akteur ({belegt[0]}).",
            "normalform_belegt",
        )

    neuer_typ = alter_typ if typ is UNGESETZT else typ
    if neuer_typ is not None and neuer_typ not in kern.TYPEN:
        raise AkteurFehler(
            f"Unbekannter Typ '{neuer_typ}'. Erlaubt: {' | '.join(kern.TYPEN)}",
            "typ_unbekannt",
        )

    with con:
        con.execute("DELETE FROM akteur_alias WHERE akteur_id = ? AND alias = ?",
                    (akteur_id, passend))
        con.execute("UPDATE akteur SET herkunft = 'manuell' WHERE id = ?", (akteur_id,))
        neu_id = _akteur_schreiben(
            con, projekt_id, Akteur(normalform=passend, typ=neuer_typ, aliase=[]),
            status="aktiv", herkunft="manuell",
        )
        einheiten = _einheiten(con, projekt_id)
        _zuordnen(con, einheiten, [
            (akteur_id, _akteur_holen(con, akteur_id)),
            (neu_id, _akteur_holen(con, neu_id)),
        ])
        # Die Kandidatenpaare beider sind überholt.
        for i in (akteur_id, neu_id):
            con.execute("DELETE FROM verschmelzungskandidat "
                        "WHERE akteur_a_id = ? OR akteur_b_id = ?", (i, i))

    return {"quelle": _akteur_antwort(con, akteur_id),
            "neu": _akteur_antwort(con, neu_id)}


def fundstelle_loeschen(con: sqlite3.Connection, fundstelle_id: int) -> dict:
    """Entfernt eine einzelne Markierung, nicht den Akteur.

    Der Unterschied zum Alias-Entfernen in der Liste ist Absicht: dort geht ein
    Name samt allen seinen Stellen, hier eine falsch getroffene Stelle. Die
    alte Fläche kannte nur das Löschen des ganzen Akteurs — sie hatte keine
    Fundstellen als Gegenstände.

    Ein Erkennungslauf legt sie wieder an; das ist kein Widerspruch, sondern
    der Unterschied zwischen einer Korrektur am Befund und einer am Namen.
    """
    zeile = con.execute(
        "SELECT ea.akteur_id, ea.einheit_id, a.normalform, "
        "       SUBSTR(e.text, ea.start + 1, ea.ende - ea.start) "
        "FROM einheit_akteur ea JOIN akteur a ON a.id = ea.akteur_id "
        "JOIN einheit e ON e.id = ea.einheit_id WHERE ea.id = ?", (fundstelle_id,)
    ).fetchone()
    if zeile is None:
        raise AkteurFehler(
            f"Keine Fundstelle mit der Kennung {fundstelle_id}.",
            "fundstelle_nicht_gefunden",
        )
    with con:
        con.execute("DELETE FROM einheit_akteur WHERE id = ?", (fundstelle_id,))
    return {"fundstelle_id": fundstelle_id, "akteur_id": zeile[0],
            "einheit_id": zeile[1], "normalform": zeile[2], "wortlaut": zeile[3],
            "anzahl_fundstellen": con.execute(
                "SELECT COUNT(*) FROM einheit_akteur WHERE akteur_id = ?",
                (zeile[0],)).fetchone()[0]}
