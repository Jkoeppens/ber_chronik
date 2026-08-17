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


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Lesen ─────────────────────────────────────────────────────────────────────

def _texte_lesen(con: sqlite3.Connection, projekt_id: str) -> list[str]:
    """content-Einheiten in Dokumentreihenfolge, auf SEG_CHARS gekürzt.

    MIN_LENGTH und die Kürzung stammen aus der Vorlage: zu kurze Segmente
    tragen kein Signal, zu lange werden beim Embedden ohnehin abgeschnitten.
    """
    zeilen = con.execute(
        "SELECT e.text FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' "
        "ORDER BY e.quelle_id, e.position",
        (projekt_id,),
    ).fetchall()
    return [z[0][:kern.SEG_CHARS] for z in zeilen
            if z[0] and len(z[0]) >= kern.MIN_LENGTH]


def _vorhandene_kategorien(con: sqlite3.Connection, projekt_id: str) -> list[dict]:
    zeilen = con.execute(
        "SELECT name, beschreibung, schlagworte FROM kategorie "
        "WHERE projekt_id = ? ORDER BY id",
        (projekt_id,),
    ).fetchall()
    return [{"name": z[0], "description": z[1],
             "keywords": [k.strip() for k in (z[2] or "").split(",") if k.strip()]}
            for z in zeilen]


# ── Vorschlagen ───────────────────────────────────────────────────────────────

def vorschlagen(
    con: sqlite3.Connection,
    projekt_id: str,
    warm_start: bool = False,
    n_clusters: int | None = None,
) -> TaxonomieErgebnis:
    """Schlägt eine Taxonomie vor und schreibt sie nach kategorie.

    warm_start=False: von null. n_clusters bestimmt die Anzahl (Vorgabe 7).
    warm_start=True : aus den vorhandenen Kategorien; n_clusters ist dann
                      deren Anzahl und der Parameter wird abgewiesen.
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
    else:
        anzahl = n_clusters or kern.N_CLUSTERS
        if anzahl < 2:
            raise TaxonomieFehler("n_clusters muss mindestens 2 sein.", "n_clusters_zu_klein")

    parameter = json.dumps(
        {"warm_start": warm_start, "n_clusters": anzahl}, ensure_ascii=False
    )

    try:
        texte = _texte_lesen(con, projekt_id)
        if len(texte) < anzahl:
            raise TaxonomieFehler(
                f"Projekt '{projekt_id}' hat {len(texte)} verwertbare Einheiten, "
                f"gebraucht werden mindestens {anzahl}.",
                "zu_wenige_einheiten",
            )

        embed, emb_modell = anbieter.embedding_funktion()
        frage_modell, llm_modell = anbieter.llm_funktion()

        seg_embs = kern.nachbar_aggregat(embed(texte), texte)

        vorschlag = kern.verfeinern(
            seg_embs=seg_embs,
            texte=texte,
            embed=embed,
            frage_modell=frage_modell,
            n_clusters=anzahl,
            warm_start=vorhanden if warm_start else None,
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
            zeiger = con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'taxonomie', ?, ?, ?, 'erfolg')",
                (projekt_id, begonnen_am, beendet_am, json.dumps({
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
                }, ensure_ascii=False)),
            )
            lauf_id = zeiger.lastrowid

            # Die alten Kategorien weichen den neuen. Zuordnungen, die auf sie
            # zeigen, werden durch ON DELETE SET NULL auf NULL gesetzt — die
            # Einheiten bleiben, ihre Kategorie ist danach offen.
            con.execute("DELETE FROM kategorie WHERE projekt_id = ?", (projekt_id,))
            con.executemany(
                "INSERT INTO kategorie (projekt_id, name, beschreibung, schlagworte, herkunft) "
                "VALUES (?, ?, ?, ?, 'vorschlag')",
                [(projekt_id, k["name"], k["description"], ",".join(k["keywords"]))
                 for k in vorschlag.kategorien],
            )

    except Exception as exc:
        with con:
            con.execute(
                "INSERT INTO lauf (projekt_id, schritt, begonnen_am, beendet_am, "
                "parameter, status) VALUES (?, 'taxonomie', ?, ?, ?, 'fehler')",
                (projekt_id, begonnen_am, _jetzt(),
                 json.dumps({"warm_start": warm_start, "n_clusters": anzahl,
                             "fehler": str(exc)}, ensure_ascii=False)),
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
    )
