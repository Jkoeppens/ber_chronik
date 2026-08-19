"""
dienst.py — Taxonomie vorschlagen und verfeinern

Liest die Einheiten aus der Datenbank, lässt den Kern den Kreislauf drehen und
schreibt das Ergebnis in einer Transaktion: die Kategorien nach kategorie mit
herkunft='vorschlag', die Trajektorie in die lauf-Zeile.

Zwei getrennte Aufrufe statt einer Beschriftung, die lügt:
  vorschlagen(warm_start=False) — von null, n_clusters als Parameter
  vorschlagen(warm_start=True)  — aus den vorhandenen Kategorien,
                                  n_clusters = deren Anzahl

Kein print — wer etwas anzeigen will, nimmt das TaxonomieErgebnis.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from src.neu import laeufe, vektoren
from src.neu.taxonomie import anbieter, kern


class TaxonomieFehler(Exception):
    def __init__(self, meldung: str, code: str = "taxonomie_fehler"):
        super().__init__(meldung)
        self.code = code


@dataclass
class TaxonomieErgebnis:
    projekt_id: str
    warm_start: bool
    lauf_id: int
    begonnen_am: str
    beendet_am: str
    status: str
    n_clusters: int
    kategorien: list[dict]
    llm_runden: int
    fruehzeitig_beendet: bool
    eingefroren: list[int]
    in_tokens: int
    out_tokens: int
    kosten_usd: float
    embedding_modell: str
    llm_modell: str
    trajektorie: list[dict] = field(default_factory=list)
    # Die Zuordnung, die der Lauf nebenbei erzeugt und jetzt auch festhält.
    anzahl_zugeordnet: int = 0
    anzahl_geschuetzt: int = 0
    anzahl_je_kategorie: dict[str, int] = field(default_factory=dict)
    # Teilweise gelesene Modellantworten. Leer heißt: jede Runde ganz gelesen.
    warnungen: list[str] = field(default_factory=list)
    # Kategorien mit herkunft='manuell', die der Lauf nicht angefasst hat.
    anzahl_unangetastet: int = 0


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _texte_lesen(con: sqlite3.Connection, projekt_id: str) -> list[tuple[int, str]]:
    """content-Einheiten als (id, Text) in Dokumentreihenfolge, auf SEG_CHARS gekürzt.

    MIN_LENGTH und die Kürzung stammen aus der Vorlage: zu kurze Segmente
    tragen kein Signal, zu lange werden beim Embedden ohnehin abgeschnitten.

    Die Kennung kommt mit, weil der Lauf seine Zuordnung mitschreibt: das
    Verfahren ordnet in jeder Runde ohnehin jede Einheit zu, und dieses
    Ergebnis wurde bisher weggeworfen.
    """
    zeilen = con.execute(
        "SELECT e.id, e.text FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' "
        "ORDER BY e.quelle_id, e.position",
        (projekt_id,),
    ).fetchall()
    return [(z[0], z[1][:kern.SEG_CHARS]) for z in zeilen
            if z[1] and len(z[1]) >= kern.MIN_LENGTH]


def _vorhandene_kategorien(con: sqlite3.Connection, projekt_id: str) -> list[dict]:
    """Die Kategorien mit ihrer Kennung, in fester Reihenfolge.

    Die Kennung kommt mit. Vorher wurde sie hier weggeworfen, und damit war an
    der Grenze zum Kern nicht mehr feststellbar, welche der neuen Beschreibungen
    zu welcher alten Zeile gehört — der Lauf konnte deshalb nur alles löschen
    und neu anlegen. cid ist die Position in dieser Liste, also ist cid → id
    bekannt, solange die Reihenfolge dieselbe bleibt.
    """
    zeilen = con.execute(
        "SELECT id, name, beschreibung, schlagworte, herkunft FROM kategorie "
        "WHERE projekt_id = ? ORDER BY id",
        (projekt_id,),
    ).fetchall()
    return [{"id": z[0], "name": z[1], "description": z[2],
             "keywords": [k.strip() for k in (z[3] or "").split(",") if k.strip()],
             "herkunft": z[4]}
            for z in zeilen]


def _eindeutige_namen(vorschlaege: dict[int, str], belegt: set[str]) -> dict[int, str]:
    """Sorgt dafür, dass kein Name zweimal vorkommt — UNIQUE (projekt_id, name).

    Zwei Gruppen mit demselben Titel sind vom Modell nicht ausgeschlossen, und
    ein UNIQUE-Verstoß mitten im Schreiben lässt den ganzen Lauf mit einer
    SQLite-Meldung platzen, mit der niemand etwas anfangen kann. Ein Zusatz in
    Klammern ist sichtbar und behebbar.

    `belegt` sind die Namen, die stehen bleiben — die eingefrorenen.
    """
    ergebnis: dict[int, str] = {}
    genommen = set(belegt)
    for cid in sorted(vorschlaege):
        name = vorschlaege[cid].strip() or f"Cluster {cid + 1}"
        kandidat, n = name, 1
        while kandidat in genommen:
            n += 1
            kandidat = f"{name} ({n})"
        genommen.add(kandidat)
        ergebnis[cid] = kandidat
    return ergebnis


# ── Vorschlagen ───────────────────────────────────────────────────────────────

def vorschlagen(
    con: sqlite3.Connection,
    projekt_id: str,
    warm_start: bool = False,
    n_clusters: int | None = None,
    lauf_id: int | None = None,
) -> TaxonomieErgebnis:
    """Schlägt eine Taxonomie vor und schreibt sie nach kategorie.

    warm_start=False: von null. n_clusters bestimmt die Anzahl (Vorgabe 7).
    warm_start=True : aus den vorhandenen Kategorien; n_clusters ist dann
                      deren Anzahl und der Parameter wird abgewiesen.

    lauf_id: eine bereits angelegte 'laeuft'-Zeile, die fortgeschrieben wird,
    statt am Ende eine neue anzulegen. So kann die Oberfläche den Stand
    abfragen, während gerechnet wird (siehe src/neu/laeufe.py).
    """
    begonnen_am = _jetzt()

    if con.execute("SELECT 1 FROM projekt WHERE id = ?", (projekt_id,)).fetchone() is None:
        raise TaxonomieFehler(
            f"Kein Projekt mit der Kennung '{projekt_id}'.", "projekt_nicht_gefunden"
        )

    vorhanden = _vorhandene_kategorien(con, projekt_id)
    if warm_start:
        if not vorhanden:
            raise TaxonomieFehler(
                f"Projekt '{projekt_id}' hat keine Kategorien — "
                "Verfeinern braucht einen Ausgangspunkt.",
                "kein_warm_start_moeglich",
            )
        if n_clusters is not None and n_clusters != len(vorhanden):
            raise TaxonomieFehler(
                f"Beim Verfeinern ist n_clusters die Anzahl der vorhandenen "
                f"Kategorien ({len(vorhanden)}), nicht {n_clusters}.",
                "n_clusters_beim_verfeinern",
            )
        anzahl = len(vorhanden)
        eingefroren_start = [i for i, c in enumerate(vorhanden)
                             if c["herkunft"] == "manuell"]
    else:
        if vorhanden:
            # Kalt heißt bei null anfangen, und das geht nur, wenn null ist.
            # Solange der Lauf alles löschte, war das dasselbe; jetzt schreibt
            # er in die vorhandenen Zeilen, und ein kalter Lauf wüsste nicht,
            # in welche. Die Fläche sagt es ohnehin so: "Um bei null
            # anzufangen, erst alle Kategorien löschen."
            raise TaxonomieFehler(
                f"Projekt '{projekt_id}' hat schon {len(vorhanden)} Kategorien. "
                "Entweder verfeinern (warm_start=true) oder sie vorher löschen.",
                "kalt_bei_vorhandenen",
            )
        anzahl = n_clusters or kern.N_CLUSTERS
        eingefroren_start = []
        if anzahl < 2:
            raise TaxonomieFehler("n_clusters muss mindestens 2 sein.", "n_clusters_zu_klein")

    parameter = json.dumps(
        {"warm_start": warm_start, "n_clusters": anzahl}, ensure_ascii=False
    )

    try:
        einheiten = _texte_lesen(con, projekt_id)
        texte = [t for _, t in einheiten]
        if len(texte) < anzahl:
            raise TaxonomieFehler(
                f"Projekt '{projekt_id}' hat {len(texte)} verwertbare Einheiten, "
                f"gebraucht werden mindestens {anzahl}.",
                "zu_wenige_einheiten",
            )

        embed, emb_modell = anbieter.embedding_funktion()
        frage_modell, llm_modell = anbieter.llm_funktion()

        if lauf_id is not None:
            laeufe.fortschritt(
                con, lauf_id, phase="embedding", einheiten=len(texte),
                embedding_modell=emb_modell, llm_modell=llm_modell,
            )

        # Derselbe Zwischenspeicher wie beim Zuordnen: die Texte sind dieselben,
        # auf SEG_CHARS gekürzten, und das Modell ist dasselbe. Wer erst eine
        # Taxonomie vorschlagen lässt, hat die Einheitenseite danach schon
        # bezahlt. Die Titel-Embeddings im Kreislauf gehen nicht durch den
        # Speicher — sie sind in jeder Runde neu und gehören keiner Einheit.
        aus_speicher = zu_rechnen = 0

        def melden(gespeichert: int, offen: int) -> None:
            nonlocal aus_speicher, zu_rechnen
            aus_speicher, zu_rechnen = gespeichert, offen
            if lauf_id is not None:
                laeufe.fortschritt(con, lauf_id, phase="embedding",
                                   aus_speicher=gespeichert, zu_rechnen=offen)

        roh_embs = vektoren.hole(con, einheiten, emb_modell, embed, melden)
        seg_embs = kern.nachbar_aggregat(roh_embs, texte)

        if lauf_id is not None:
            # Der Fortschritt entsteht ohne Eingriff in den Kern: gezählt wird,
            # wie oft er das Modell fragt.
            roh_frage, runde = frage_modell, {"n": 0}

            def frage_modell(prompt: str, system: str):   # noqa: F811
                runde["n"] += 1
                laeufe.fortschritt(con, lauf_id, phase="llm",
                                   runde=runde["n"], runden_max=kern.N_ITER)
                antwort = roh_frage(prompt, system)
                laeufe.fortschritt(con, lauf_id, phase="clustering",
                                   runde=runde["n"], runden_max=kern.N_ITER)
                return antwort

        vorschlag = kern.verfeinern(
            seg_embs=seg_embs,
            texte=texte,
            embed=embed,
            frage_modell=frage_modell,
            n_clusters=anzahl,
            warm_start=vorhanden if warm_start else None,
            eingefroren_start=eingefroren_start,
        )

        beendet_am = _jetzt()
        kosten_usd = anbieter.kosten(llm_modell, vorschlag.in_tokens, vorschlag.out_tokens)
        trajektorie = [
            {
                "llm_runde": r.llm_runde,
                "km_iter": r.km_iter,
                "aenderungsanteil": round(r.aenderungsanteil, 4),
                "eingefroren_gesamt": r.eingefroren_gesamt,
                "neu_eingefroren": r.neu_eingefroren,
                "label_sim": {str(c): (None if v is None else round(v, 4))
                              for c, v in r.sim.items()},
                "delta": {str(c): (None if v is None else round(v, 4))
                          for c, v in r.delta.items()},
                "titel": {str(c): t for c, t in r.titel.items()},
            }
            for r in vorschlag.runden
        ]

        with con:
            # Zuerst die lauf-Zeile: die Zuordnung verweist mit
            # kategorie_lauf_id auf sie.
            if lauf_id is None:
                zeiger = con.execute(
                    "INSERT INTO lauf (projekt_id, schritt, begonnen_am, "
                    "parameter, status) VALUES (?, 'taxonomie', ?, '{}', 'laeuft')",
                    (projekt_id, begonnen_am),
                )
                lauf_id = zeiger.lastrowid

            # Abgleichen statt ersetzen. Warm: in die vorhandenen Zeilen
            # schreiben, cid für cid — die Kennungen bleiben, und damit bleibt
            # auch alles bestehen, was auf sie zeigt. Kalt: anlegen, es gibt
            # noch nichts. Ein DELETE über das ganze Projekt gibt es nicht mehr;
            # es hat jedes Mal auch die von Hand gepflegten Kategorien
            # mitgenommen und die Kennungen neu vergeben.
            fest = set(eingefroren_start)
            if warm_start:
                kategorie_ids = [c["id"] for c in vorhanden]
                namen = _eindeutige_namen(
                    {cid: k["name"] for cid, k in enumerate(vorschlag.kategorien)
                     if cid not in fest},
                    {vorhanden[cid]["name"] for cid in fest},
                )
                # Zwei Durchgänge: UNIQUE (projekt_id, name) prüft je Anweisung,
                # und ein Tausch zweier Namen verstieße im Zwischenschritt.
                for cid in namen:
                    con.execute("UPDATE kategorie SET name = ? WHERE id = ?",
                                (f"\x1f-{kategorie_ids[cid]}", kategorie_ids[cid]))
                for cid, name in namen.items():
                    k = vorschlag.kategorien[cid]
                    con.execute(
                        "UPDATE kategorie SET name = ?, beschreibung = ?, "
                        "schlagworte = ?, herkunft = 'vorschlag' WHERE id = ?",
                        (name, k["description"], ",".join(k["keywords"]),
                         kategorie_ids[cid]),
                    )
                for cid, name in namen.items():
                    vorschlag.kategorien[cid]["name"] = name
            else:
                kategorie_ids = []
                namen = _eindeutige_namen(
                    {cid: k["name"] for cid, k in enumerate(vorschlag.kategorien)}, set()
                )
                for cid, k in enumerate(vorschlag.kategorien):
                    k["name"] = namen[cid]
                    zeiger = con.execute(
                        "INSERT INTO kategorie (projekt_id, name, beschreibung, "
                        "schlagworte, herkunft) VALUES (?, ?, ?, ?, 'vorschlag')",
                        (projekt_id, k["name"], k["description"],
                         ",".join(k["keywords"])),
                    )
                    kategorie_ids.append(zeiger.lastrowid)

            # Die Zuordnung der letzten Runde festhalten. Sie entsteht im
            # Verfahren ohnehin — labels = argmax(seg_embs @ label_embs.T) —
            # und wurde bisher verworfen, damit ein zweiter Schritt dasselbe
            # noch einmal rechnet, nur leicht anders.
            geschuetzt = {z[0] for z in con.execute(
                "SELECT e.id FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
                "WHERE q.projekt_id = ? AND e.kategorie_herkunft = 'manuell'",
                (projekt_id,))}
            zuordnungen = [
                (kategorie_ids[int(label)], lauf_id, einheit_id)
                for (einheit_id, _), label in zip(einheiten, vorschlag.labels)
                if einheit_id not in geschuetzt
            ]
            con.executemany(
                "UPDATE einheit SET kategorie_id = ?, konfidenz = NULL, "
                "kategorie_herkunft = 'automatisch', kategorie_lauf_id = ? WHERE id = ?",
                zuordnungen,
            )
            je_kategorie: dict[str, int] = {}
            for kategorie_id, _, _ in zuordnungen:
                name = vorschlag.kategorien[kategorie_ids.index(kategorie_id)]["name"]
                je_kategorie[name] = je_kategorie.get(name, 0) + 1

            werte = json.dumps({
                "warm_start": warm_start,
                "n_clusters": anzahl,
                "embedding_modell": emb_modell,
                "llm_modell": llm_modell,
                "llm_calls": vorschlag.llm_calls,
                "in_tokens": vorschlag.in_tokens,
                "out_tokens": vorschlag.out_tokens,
                "kosten_usd": round(kosten_usd, 6),
                "fruehzeitig_beendet": vorschlag.fruehzeitig_beendet,
                "eingefroren": vorschlag.eingefroren,
                "trajektorie": trajektorie,
                "anzahl_zugeordnet": len(zuordnungen),
                "anzahl_geschuetzt": len(geschuetzt),
                "anzahl_je_kategorie": je_kategorie,
                "warnungen": vorschlag.warnungen,
                "anzahl_unangetastet": len(fest),
            }, ensure_ascii=False)
            con.execute(
                "UPDATE lauf SET beendet_am = ?, parameter = ?, status = 'erfolg' "
                "WHERE id = ?",
                (beendet_am, werte, lauf_id),
            )

    except Exception as exc:
        with con:
            if lauf_id is None:
                con.execute(
                    "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                    "parameter, status) VALUES (?, 'taxonomie', ?, ?, ?, 'fehler')",
                    (projekt_id, begonnen_am, _jetzt(),
                     json.dumps({"warm_start": warm_start, "n_clusters": anzahl,
                                 "fehler": str(exc)}, ensure_ascii=False)),
                )
            else:
                con.execute(
                    "UPDATE lauf SET beendet_am = ?, status = 'fehler' WHERE id = ?",
                    (_jetzt(), lauf_id),
                )
        raise

    return TaxonomieErgebnis(
        projekt_id=projekt_id,
        warm_start=warm_start,
        lauf_id=lauf_id,
        begonnen_am=begonnen_am,
        beendet_am=beendet_am,
        status="erfolg",
        n_clusters=anzahl,
        kategorien=vorschlag.kategorien,
        llm_runden=vorschlag.llm_calls,
        fruehzeitig_beendet=vorschlag.fruehzeitig_beendet,
        eingefroren=vorschlag.eingefroren,
        in_tokens=vorschlag.in_tokens,
        out_tokens=vorschlag.out_tokens,
        kosten_usd=round(kosten_usd, 6),
        embedding_modell=emb_modell,
        llm_modell=llm_modell,
        trajektorie=trajektorie,
        anzahl_zugeordnet=len(zuordnungen),
        anzahl_geschuetzt=len(geschuetzt),
        anzahl_je_kategorie=je_kategorie,
        warnungen=vorschlag.warnungen,
        anzahl_unangetastet=len(fest),
    )
