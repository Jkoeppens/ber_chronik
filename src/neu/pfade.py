"""
pfade.py — wo etwas liegt, einmal entschieden

Zwei Wurzeln, und die Trennung ist der ganze Zweck des Moduls:

  WURZEL         der Quellbestand. Kommt aus dem Git, wird nur gelesen,
                 verschwindet bei jedem Deploy und entsteht neu.
                 anbieter.toml, schema.sql, viz/, frontend/build.

  DATEN_WURZEL   was der Betrieb erzeugt. Muss einen Neustart überleben.
                 Die Datenbank, hochgeladene Rohdokumente, Exporte.

Bis September 2026 gab es die zweite nicht: db.py, projekte.py und
server/gemeinsam.py bildeten ihre Pfade alle aus WURZEL. Auf Railway ist ein
Laufwerk unter /data eingehängt und DATA_ROOT darauf gesetzt — gelesen hat die
Variable aber nur src/generalized/. Im neuen System landeten Uploads und
Exporte damit im Container und waren beim nächsten Deploy weg. Gemessen: ein
Export schrieb nach /app/data/exporte/ber, während /data leer blieb.

Der Name ist derselbe wie drüben (src/generalized/config.py:5), und das ist
Absicht: solange beide Systeme nebeneinander laufen, sollen sie sich dasselbe
Laufwerk teilen, ohne dass jemand zwei Variablen setzen muss.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Der Quellbestand — drei Ebenen hoch von src/neu/pfade.py.
WURZEL = Path(__file__).resolve().parent.parent.parent


def daten_wurzel() -> Path:
    """Wohin geschrieben wird. DATA_ROOT, sonst data/ im Quellbestand.

    Als Funktion und nicht als Konstante: Tests setzen die Umgebung nach dem
    Import. Eine Konstante hielte den Wert vom ersten Import fest, und dann
    schriebe ein Test in den Arbeitsbaum statt in sein tmp_path.
    """
    roh = (os.environ.get("DATA_ROOT") or "").strip()
    return Path(roh) if roh else WURZEL / "data"


def datenbank() -> Path:
    """Die Datenbank. NEU_DB übersteuert, sonst {DATEN_WURZEL}/neu.db.

    NEU_DB bleibt, weil die Tests einzelne Datenbanken in tmp_path brauchen
    und nicht ein ganzes Datenverzeichnis umhängen wollen. Es ist die engere
    Angabe und gewinnt deshalb.
    """
    roh = (os.environ.get("NEU_DB") or "").strip()
    return Path(roh) if roh else daten_wurzel() / "neu.db"


def rohdaten() -> Path:
    """Wohin hochgeladene DOCX gelegt werden."""
    return daten_wurzel() / "raw"


def export_verzeichnis(projekt_id: str) -> Path:
    """Wohin ein Export SCHREIBT: {DATEN_WURZEL}/exporte/{id}/.

    Nicht data/projects/{id}/exploration/ — dort schreibt der alte Wizard, und
    ber, nahda und osmanisch gibt es in beiden Datenbanken.
    """
    return daten_wurzel() / "exporte" / projekt_id


def export_quelle(projekt_id: str) -> Path | None:
    """Woher ein Export GELESEN wird — oder None, wenn es keinen gibt.

    Zwei Orte, und darum kommt dieses Modul nicht herum: das Prüfstück
    (data/exporte/pruefstueck/) liegt im Git und wird nur gelesen, alle
    übrigen Exporte entstehen im Betrieb auf dem Laufwerk. Mit DATA_ROOT=/data
    fallen die beiden auseinander.

    Das Laufwerk gewinnt: wer ein Projekt namens 'pruefstueck' wirklich
    exportiert, soll seinen eigenen Stand sehen und nicht den mitgelieferten.
    """
    vom_laufwerk = export_verzeichnis(projekt_id)
    if vom_laufwerk.is_dir():
        return vom_laufwerk
    mitgeliefert = WURZEL / "data" / "exporte" / projekt_id
    if mitgeliefert != vom_laufwerk and mitgeliefert.is_dir():
        return mitgeliefert
    return None


def lage() -> dict[str, str]:
    """Alle Pfade auf einen Blick — für die Startmeldung und /api/konfiguration."""
    return {
        "quellbestand": str(WURZEL),
        "daten_wurzel": str(daten_wurzel()),
        "datenbank": str(datenbank()),
        "rohdaten": str(rohdaten()),
        "exporte": str(daten_wurzel() / "exporte"),
    }
