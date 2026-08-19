"""
vektoren.py — Embeddings der Einheiten zwischenspeichern

Der Text einer Einheit ändert sich nach dem Ingest nicht mehr, die
Kategorienbeschreibungen dauernd. Jedes Zuordnen rechnete bisher trotzdem beide
Seiten neu — bei damaskus 672 Einheiten für 30 Sekunden, damit sich sieben kurze
Beschreibungen um ein paar Worte geändert hatten.

Der Schlüssel ist (einheit_id, modell), festgehalten wird zusätzlich eine
Prüfsumme über genau die Zeichenkette, die dem Modell gereicht wurde. Zwei
Dinge machen den Speicher damit von selbst ehrlich:

  Text geändert     — die Prüfsumme stimmt nicht mehr, der Wert gilt als nicht
                      vorhanden und wird überschrieben. Es braucht kein
                      Aufräumen von Hand und keine Stelle, die daran denken muss.
  Anbieter gewechselt — MiniLM, bge-m3 und voyage-4 liefern verschiedene Vektoren
                      verschiedener Länge. Weil das Modell im Schlüssel steht,
                      kann ein Wechsel keine alten Werte weiterverwenden; die
                      Werte des anderen Modells bleiben liegen und gelten sofort
                      wieder, wenn zurückgewechselt wird.

In der Datenbank und nicht in einer .npy neben den Daten: die Vektoren gehören
zu den Einheiten, sie sollen mit ihnen gelöscht werden (ON DELETE CASCADE) und
mit ihnen gesichert werden. Eine Datei daneben veraltet still.

Platzbedarf: 4 Byte je Dimension. bge-m3 hat 1024 Dimensionen, also 4 KB je
Einheit — bei damaskus 2,7 MB. MiniLM hat 384, also 1,5 KB je Einheit.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Sequence

import numpy as np

# SQLite nimmt in einer Abfrage nur begrenzt viele Platzhalter. 500 liegt unter
# jeder Grenze, die je gegolten hat.
STAPEL = 500


def pruefsumme(text: str) -> str:
    """sha256 über die Zeichenkette, die embeddet wird — nicht über den Rohtext.

    Der Unterschied ist die Kürzung auf SEG_CHARS: was hinter Zeichen 500 steht,
    hat den Vektor nie berührt und darf ihn nicht ungültig machen.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gespeicherte(
    con: sqlite3.Connection, ids: Sequence[int], modell: str
) -> dict[int, tuple[str, np.ndarray]]:
    """(pruefsumme, vektor) je Einheit, soweit für dieses Modell abgelegt."""
    gefunden: dict[int, tuple[str, np.ndarray]] = {}
    for anfang in range(0, len(ids), STAPEL):
        teil = ids[anfang:anfang + STAPEL]
        platz = ",".join("?" * len(teil))
        for z in con.execute(
            f"SELECT einheit_id, pruefsumme, vektor FROM einheit_embedding "
            f"WHERE modell = ? AND einheit_id IN ({platz})",
            (modell, *teil),
        ):
            gefunden[z[0]] = (z[1], np.frombuffer(z[2], dtype=np.float32))
    return gefunden


def hole(
    con: sqlite3.Connection,
    einheiten: Sequence[tuple[int, str]],
    modell: str,
    embed: Callable[[list[str]], np.ndarray],
    melden: Callable[[int, int], None] | None = None,
) -> np.ndarray:
    """Die Vektoren zu (einheit_id, text), in derselben Reihenfolge.

    Was abgelegt ist und dessen Prüfsumme stimmt, kommt aus der Datenbank; der
    Rest wird in einem einzigen embed()-Aufruf gerechnet und abgelegt.

    `melden(aus_speicher, zu_rechnen)` wird einmal gerufen, bevor gerechnet wird
    — für die Fortschrittsanzeige eines Laufs. Der Aufruf kommt auch dann, wenn
    nichts zu rechnen ist; sonst könnte die Fläche 'fertig' nicht von 'noch
    nicht angefangen' unterscheiden.
    """
    if not einheiten:
        return np.zeros((0, 0), dtype=np.float32)

    ids = [i for i, _ in einheiten]
    summen = [pruefsumme(t) for _, t in einheiten]
    gespeichert = _gespeicherte(con, ids, modell)

    treffer: dict[int, np.ndarray] = {}
    for (einheit_id, _), summe in zip(einheiten, summen):
        abgelegt = gespeichert.get(einheit_id)
        if abgelegt is not None and abgelegt[0] == summe:
            treffer[einheit_id] = abgelegt[1]

    # Verschiedene Längen unter einem Modellnamen kann es nicht geben; wenn doch,
    # ist der Speicher kaputt und nicht bloß veraltet. Dann gilt nichts davon.
    laengen = {v.shape[0] for v in treffer.values()}
    if len(laengen) > 1:
        treffer = {}

    offen = [(i, t) for (i, t) in einheiten if i not in treffer]
    if melden is not None:
        melden(len(einheiten) - len(offen), len(offen))

    if offen:
        frisch = np.asarray(embed([t for _, t in offen]), dtype=np.float32)
        if treffer and frisch.shape[1] != next(iter(laengen)):
            # Das Modell liefert eine andere Länge als das, was unter seinem
            # Namen liegt — ein umbenanntes oder neu trainiertes Modell. Alles
            # noch einmal, sonst stünden zwei Maße in einer Matrix.
            treffer = {}
            offen = list(einheiten)
            frisch = np.asarray(embed([t for _, t in offen]), dtype=np.float32)

        zeit = _jetzt()
        summe_je_id = dict(zip(ids, summen))
        with con:
            con.executemany(
                "INSERT INTO einheit_embedding "
                "(einheit_id, modell, pruefsumme, masse, vektor, berechnet_am) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (einheit_id, modell) DO UPDATE SET "
                "pruefsumme = excluded.pruefsumme, masse = excluded.masse, "
                "vektor = excluded.vektor, berechnet_am = excluded.berechnet_am",
                [
                    (einheit_id, modell, summe_je_id[einheit_id],
                     int(frisch.shape[1]), frisch[n].tobytes(), zeit)
                    for n, (einheit_id, _) in enumerate(offen)
                ],
            )
        for n, (einheit_id, _) in enumerate(offen):
            treffer[einheit_id] = frisch[n]

    return np.vstack([treffer[i] for i in ids])


def lage(con: sqlite3.Connection, projekt_id: str, modell: str) -> dict:
    """Wie viele content-Einheiten für dieses Modell noch zu rechnen wären.

    Für die Fläche: sie soll eine Dauer nur ankündigen, wenn es eine gibt. Die
    Prüfsumme wird hier nicht nachgerechnet — dafür müsste jeder Text durch
    sha256, und die Frage lautet 'gleich fertig oder nicht', nicht 'auf die
    Einheit genau'. Ein geänderter Text kommt in dieser Zählung als vorhanden
    durch; nach dem Ingest ändert sich keiner mehr.
    """
    gesamt = con.execute(
        "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content'",
        (projekt_id,),
    ).fetchone()[0]
    abgelegt = con.execute(
        "SELECT COUNT(*) FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "JOIN einheit_embedding v ON v.einheit_id = e.id AND v.modell = ? "
        "WHERE q.projekt_id = ? AND e.typ = 'content'",
        (modell, projekt_id),
    ).fetchone()[0]
    return {
        "modell": modell,
        "einheiten": gesamt,
        "gespeichert": abgelegt,
        "zu_rechnen": gesamt - abgelegt,
    }
