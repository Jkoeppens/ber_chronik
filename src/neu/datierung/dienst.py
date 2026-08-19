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
    Mitgelesen werden datum, praezision und die Begründung aus der
    manuell-anker-Zeile: ohne sie käme die Korrektur beim nächsten Lauf
    gröber zurück, als sie gesetzt wurde, und die Begründung wäre weg.
    """
    zeilen = con.execute(
        "SELECT e.id, e.jahr_von, e.jahr_bis, e.datum, e.praezision, "
        "       (SELECT a.fundstelle FROM anker a "
        "        WHERE a.einheit_id = e.id AND a.herkunft = 'manuell' LIMIT 1) "
        "FROM einheit e WHERE e.quelle_id = ? AND e.datierung_herkunft = 'manuell'",
        (quelle_id,),
    ).fetchall()
    return [Override(einheit_id=z[0],
                     aktion="undatierbar" if z[1] is None else "anker_setzen",
                     jahr_von=z[1], jahr_bis=z[2],
                     datum=z[3], praezision=z[4], fundstelle=z[5] or "")
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
    datum_von: str | None,
    datum_bis: str | None = None,
    begruendung: str = "",
) -> dict:
    """Setzt die Datierung einer Einheit von Hand.

    Zwei Felder mit freier Genauigkeit: '2012', '2012-07' oder '2012-07-30'.
    datum_bis leer heißt Zeitpunkt, datum_von leer heißt undatierbar. Die
    Präzision folgt daraus, sie wird nicht angegeben.

    Die Korrektur wird eine echte anker-Zeile mit herkunft='manuell'. Die
    Begründung steht in deren fundstelle — dort, wo bei einem maschinellen
    Anker steht, welche Zeichenfolge ihn ausgelöst hat. Beides beantwortet
    dieselbe Frage: woher kommt dieses Datum. Eine eigene Spalte dafür wäre
    dieselbe Auskunft an einer zweiten Stelle.
    """
    zeile = con.execute("SELECT id FROM einheit WHERE id = ?", (einheit_id,)).fetchone()
    if zeile is None:
        raise DatierungFehler(
            f"Keine Einheit mit der Kennung {einheit_id}.", "einheit_nicht_gefunden"
        )

    try:
        dat, von, bis, praez = kern.handdatierung(datum_von, datum_bis)
    except kern.UnlesbaresDatum as exc:
        raise DatierungFehler(str(exc), "datum_unlesbar")

    begruendung = (begruendung or "").strip()
    fundstelle = begruendung or (
        "" if von is None else (str(von) if von == bis else f"{von}–{bis}")
    )

    with con:
        con.execute("DELETE FROM anker WHERE einheit_id = ?", (einheit_id,))
        con.execute(
            "UPDATE einheit SET datum = ?, jahr_von = ?, jahr_bis = ?, praezision = ?, "
            "datierung_herkunft = 'manuell', datierung_lauf_id = NULL WHERE id = ?",
            (dat, von, bis, praez, einheit_id),
        )
        if von is not None or fundstelle:
            con.execute(
                "INSERT INTO anker (einheit_id, jahr, herkunft, fundstelle) "
                "VALUES (?, ?, 'manuell', ?)",
                (einheit_id, von, fundstelle),
            )

    return {
        "einheit_id": einheit_id,
        "datum": dat,
        "jahr_von": von,
        "jahr_bis": bis,
        "praezision": praez,
        "datierung_herkunft": "manuell",
        "datierung_lauf_id": None,
        "begruendung": fundstelle,
    }


def text_setzen(con: sqlite3.Connection, einheit_id: int, text: str) -> dict:
    """Ändert den Text einer Einheit und räumt auf, was daran hing.

    Zwei Dinge hängen am Wortlaut:

    Die Akteursfundstellen (`einheit_akteur.start`/`ende`) sind Zeichen-
    positionen. Nach einer Textänderung zeigen sie auf andere Wörter — nicht
    auf nichts, sondern auf falsche. Sie werden deshalb **gelöscht**, nicht
    stehengelassen; beim nächsten Akteurslauf entstehen sie neu. Eine falsche
    Markierung ist schlimmer als eine fehlende, weil sie wie ein Befund
    aussieht.

    Die Anker leiten sich aus dem Text ab. Sie werden neu abgeleitet, indem
    die Datierung der Quelle noch einmal läuft (Umfang 'alle', also mit
    geschützten Handkorrekturen). Nicht nur für diese Einheit: die
    Interpolation der Nachbarn hängt an ihr mit, und eine Einheit, die ihr
    Jahr verliert, verschiebt die Datierung der Absätze um sie herum.
    """
    zeile = con.execute(
        "SELECT e.text, q.projekt_id FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE e.id = ?", (einheit_id,)
    ).fetchone()
    if zeile is None:
        raise DatierungFehler(
            f"Keine Einheit mit der Kennung {einheit_id}.", "einheit_nicht_gefunden"
        )
    alt, projekt_id = zeile[0], zeile[1]
    text = text if text is not None else ""
    if not text.strip():
        raise DatierungFehler("Der Text darf nicht leer sein.", "text_leer")

    if text == alt:
        return {"einheit_id": einheit_id, "text": text, "geaendert": False,
                "fundstellen_geloescht": 0, "datierung_neu": 0, "projekt_id": projekt_id}

    vorher = _datierungsstand(con, projekt_id)
    with con:
        fundstellen = con.execute(
            "SELECT COUNT(*) FROM einheit_akteur WHERE einheit_id = ?", (einheit_id,)
        ).fetchone()[0]
        con.execute("DELETE FROM einheit_akteur WHERE einheit_id = ?", (einheit_id,))
        con.execute("UPDATE einheit SET text = ? WHERE id = ?", (text, einheit_id))

    datieren(con, projekt_id=projekt_id, umfang="alle")
    nachher = _datierungsstand(con, projekt_id)
    geaendert = sum(1 for k, v in nachher.items() if vorher.get(k) != v)

    return {"einheit_id": einheit_id, "text": text, "geaendert": True,
            "fundstellen_geloescht": fundstellen, "datierung_neu": geaendert,
            "projekt_id": projekt_id}


# Was als Jahreszahl überhaupt in Frage kommt. Kein statistischer Wert, sondern
# eine Aussage über das Material dieses Systems: Presseartikel und Exzerpte zur
# Geschichte des 18. bis 21. Jahrhunderts. Ein Projekt über die Antike müsste
# die Untergrenze senken — dann ist es eine Einstellung, heute ist es eine
# Feststellung.
JAHR_UNTERGRENZE = 1400


def ausreisser(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Einheiten mit einem Jahr, das es nicht geben kann.

    Der Zeitraum eines Projekts ist MIN/MAX über seine Einheiten. Zwei
    Zifferndreher in der Quelle ziehen ihn deshalb über Jahrhunderte — bei ber
    auf 1201–3012, obwohl das Material 1989–2017 abdeckt. Ohne eine Stelle,
    die das benennt, findet man die beiden Sätze nur durch Blättern.

    Die Regel ist ein festes Fenster: nichts vor 1400, nichts in der Zukunft.
    Der naheliegende statistische Weg — Quartilsabstand — ist daran
    gescheitert, dass er das Falsche misst. Gemessen an vier Projekten meldete
    er bei ber richtig zwei, bei damaskus aber 62 und bei osmanisch 40
    Einheiten, die alle in Ordnung sind: ein Werk über das 19. Jahrhundert
    streut nun einmal breit, und eine Warnung, die bei jedem zehnten Absatz
    anschlägt, ist keine. Ein Faktor, der alle vier zufriedenstellt, wäre an
    genau diese vier angepasst.

    Was einen Zifferndreher ausmacht, ist nicht Abstand vom Mittel, sondern
    Unmöglichkeit. 3012 ist keine ungewöhnliche Datierung, sondern gar keine.
    """
    heute = datetime.now(timezone.utc).year
    ids = [z[0] for z in con.execute(
        "SELECT e.id FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? AND e.typ = 'content' AND e.jahr_von IS NOT NULL "
        "AND (e.jahr_von < ? OR e.jahr_von > ? OR e.jahr_bis > ?) "
        "ORDER BY e.jahr_von",
        (projekt_id, JAHR_UNTERGRENZE, heute, heute))]
    return {"projekt_id": projekt_id, "unten": JAHR_UNTERGRENZE,
            "oben": heute, "einheiten": ids}


def verteilung(con: sqlite3.Connection, projekt_id: str) -> dict:
    """Woher die Daten kommen — je Herkunft und je Präzision.

    'interpoliert' heißt geraten: zwischen zwei bekannten Ankern gemittelt.
    Bei damaskus sind das 392 von 672 Einheiten, und das soll man sehen, ohne
    danach zu suchen.
    """
    def zaehle(spalte: str) -> dict[str, int]:
        return {(z[0] or "undatiert"): z[1] for z in con.execute(
            f"SELECT e.{spalte}, COUNT(*) FROM einheit e "
            "JOIN quelle q ON q.id = e.quelle_id "
            "WHERE q.projekt_id = ? AND e.typ = 'content' "
            f"GROUP BY e.{spalte}", (projekt_id,))}

    je_herkunft = zaehle("datierung_herkunft")
    je_praezision = zaehle("praezision")
    gesamt = sum(je_herkunft.values())
    return {
        "projekt_id": projekt_id,
        "anzahl": gesamt,
        "je_herkunft": je_herkunft,
        "je_praezision": je_praezision,
        "anzahl_interpoliert": je_herkunft.get("interpoliert", 0),
        "anzahl_manuell": je_herkunft.get("manuell", 0),
        "anzahl_undatiert": je_herkunft.get("undatiert", 0),
        "ausreisser": ausreisser(con, projekt_id),
    }


def anker_je_einheit(con: sqlite3.Connection, projekt_id: str) -> dict[int, list[dict]]:
    """Die Belege je Einheit — welche Fundstelle welches Jahr geliefert hat.

    Die alte Vorschau zeigte nur das Ergebnis. Eine falsche Datierung war
    damit nicht aufzuklären: man sah, dass 3012 dasteht, aber nicht, dass es
    aus '30.07.3012' in der Quellennotation kommt und kein Rechenfehler ist.
    """
    ergebnis: dict[int, list[dict]] = {}
    for z in con.execute(
        "SELECT a.einheit_id, a.jahr, a.herkunft, a.fundstelle FROM anker a "
        "JOIN einheit e ON e.id = a.einheit_id JOIN quelle q ON q.id = e.quelle_id "
        "WHERE q.projekt_id = ? ORDER BY a.einheit_id, a.id", (projekt_id,)
    ):
        ergebnis.setdefault(z[0], []).append(
            {"jahr": z[1], "herkunft": z[2], "fundstelle": z[3]})
    return ergebnis


def _datierungsstand(con: sqlite3.Connection, projekt_id: str) -> dict[int, tuple]:
    return {z[0]: (z[1], z[2], z[3]) for z in con.execute(
        "SELECT e.id, e.datum, e.jahr_von, e.jahr_bis FROM einheit e "
        "JOIN quelle q ON q.id = e.quelle_id WHERE q.projekt_id = ?", (projekt_id,))}
