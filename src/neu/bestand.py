"""
bestand.py — was auf der Datenwurzel liegt, nach Art getrennt

Der Anlass ist eine Zahl: GLiNER wiegt 1,1 GB, bge-m3 4,3 GB, MiniLM 0,5 GB.
Auf einem Laufwerk von 5 GB — die Vorgabe bei Railway — passen GLiNER und
bge-m3 zusammen nicht mehr hinein. Ein Umschalten von voyage auf local im
Betrieb füllt das Laufwerk also, und heute sagt das niemand: gemessen am
29. September wuchs ein Laufwerk von 1,2 GB auf 5,4 GB, ohne eine einzige
Meldung. Erst beim nächsten Schreibversuch wäre es aufgefallen.

Deshalb zählt dieses Modul nicht nur, sondern trennt nach Art. 'Das Laufwerk
ist voll' ist keine Auskunft, mit der sich etwas tun lässt; 'vier Gigabyte
liegen in einem Modell, das der eingestellte Anbieter nicht benutzt' ist eine.

Was hier NICHT passiert: löschen. Das Modul liest. Die eine Stelle, die
Vektoren wegräumt, ist vektoren_loeschen() — und sie wird nur von Hand
angestoßen, nie von einem Lauf. Der Grund steht dort.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.neu import pfade

# ── Wie ein HF-Cache-Verzeichnis heißt ────────────────────────────────────────
# huggingface_hub legt je Repo ein Verzeichnis 'models--<org>--<name>' an. Der
# Modellname entsteht daraus zurück, indem '--' wieder zu '/' wird. Kein
# Auslesen der Metadaten darin: der Verzeichnisname ist die Angabe, und wer ihn
# umbenennt, hat den Cache ohnehin kaputt gemacht.
MODELL_PRAEFIX = "models--"

# ── Wann der Platz knapp ist ──────────────────────────────────────────────────
# Zwei Grenzen, und keine davon ist ein Prozentsatz allein. Ein Anteil misst die
# falsche Sache: 19 % frei auf einer 228-GB-Platte sind 44 GB und kein Problem,
# 40 % frei auf einem 10-GB-Laufwerk sind 4 GB und reichen für bge-m3 nicht.
#
# Die absolute Grenze ist deshalb die wichtigere: 6 GiB, weil das größte Modell,
# das dieses System nachlädt, 4,3 GiB wiegt (BAAI/bge-m3) und GLiNER mit 1,1 GiB
# daneben liegt. Wer weniger frei hat, kann nicht mehr auf 'local' umschalten.
KNAPP_BYTES = 6 * 1024**3
# Der Anteil bleibt als zweite Grenze, für sehr große Laufwerke: 10 % frei heißt
# 'bald voll', unabhängig davon, wie viele Gigabyte das sind.
KNAPP_ANTEIL = 0.10


def hf_wurzel() -> Path:
    """Wo die Modellgewichte liegen. HF_HOME, sonst der Vorgabeort von HF.

    Nicht pfade.daten_wurzel() / 'huggingface': das Abbild setzt HF_HOME
    ausdrücklich, und wer es anders setzt, soll hier sein Verzeichnis sehen und
    nicht das, das wir vermuten. Ohne HF_HOME gilt ~/.cache/huggingface — dann
    liegen die Gewichte NICHT auf der Datenwurzel, und genau das soll man
    sehen können.
    """
    roh = (os.environ.get("HF_HOME") or "").strip()
    return Path(roh) if roh else Path.home() / ".cache" / "huggingface"


def _bytes_im_baum(wurzel: Path) -> int:
    """Belegte Bytes unter einem Verzeichnis, Symlinks NICHT gefolgt.

    st_size des Symlinks und nicht des Ziels: der HF-Cache legt jede Datei
    einmal unter blobs/ ab und verlinkt sie aus snapshots/. Wer den Links folgt,
    zählt jedes Gewicht zweimal — bei bge-m3 wären das 8,6 statt 4,3 GB.
    """
    gesamt = 0
    if not wurzel.exists():
        return 0
    for pfad in wurzel.rglob("*"):
        try:
            zustand = pfad.lstat()
        except OSError:
            continue          # zwischen rglob und lstat verschwunden
        if not pfad.is_symlink() and pfad.is_dir():
            continue
        gesamt += zustand.st_size
    return gesamt


# ── Die Auskunft ──────────────────────────────────────────────────────────────

@dataclass
class Posten:
    """Ein Eintrag im Überblick: was, wie viel, und woraus es besteht."""

    name: str
    bytes: int
    dateien: int = 0
    hinweis: str = ""


@dataclass
class Vektorbestand:
    """Vektoren eines Modells. 'benutzt' heißt: der eingestellte Anbieter nimmt sie."""

    modell: str
    bytes: int
    einheiten: int
    masse: int
    benutzt: bool


@dataclass
class Bestand:
    daten_wurzel: str
    platz_knapp: bool
    laufwerk_bytes: int
    laufwerk_frei: int
    laufwerk_belegt: int
    datenbank: Posten
    modelle: list[Posten] = field(default_factory=list)
    modelle_wurzel: str = ""
    modelle_auf_datenwurzel: bool = True
    rohdaten: list[Posten] = field(default_factory=list)
    exporte: list[Posten] = field(default_factory=list)
    vektoren: list[Vektorbestand] = field(default_factory=list)
    gezaehlt_bytes: int = 0
    warnungen: list[str] = field(default_factory=list)


def _datenbank_posten() -> Posten:
    """Die Datenbank samt -wal und -shm.

    Die beiden Nebendateien gehören dazu und werden im WAL-Betrieb groß: ohne
    sie sähe eine 4-MB-Datenbank mit 60 MB WAL nach 4 MB aus.
    """
    pfad = pfade.datenbank()
    teile = [pfad, Path(str(pfad) + "-wal"), Path(str(pfad) + "-shm")]
    vorhanden = [p for p in teile if p.is_file()]
    return Posten(
        name=pfad.name,
        bytes=sum(p.stat().st_size for p in vorhanden),
        dateien=len(vorhanden),
        hinweis=" + ".join(p.name for p in vorhanden[1:]) if len(vorhanden) > 1 else "",
    )


def _modell_posten() -> tuple[list[Posten], bool]:
    """Ein Posten je Modell im HF-Cache, absteigend nach Größe."""
    hub = hf_wurzel() / "hub"
    posten = []
    if hub.is_dir():
        for eintrag in hub.iterdir():
            if not eintrag.is_dir() or not eintrag.name.startswith(MODELL_PRAEFIX):
                continue
            name = eintrag.name[len(MODELL_PRAEFIX):].replace("--", "/")
            posten.append(Posten(
                name=name,
                bytes=_bytes_im_baum(eintrag),
                dateien=sum(1 for p in (eintrag / "blobs").glob("*")) if (eintrag / "blobs").is_dir() else 0,
            ))
    # Alles unter HF_HOME, das kein Modell ist (xet/, Protokolle), als ein Posten:
    # es ist keine Null, und als Einzelzeilen wäre es Rauschen.
    rest = _bytes_im_baum(hf_wurzel()) - sum(p.bytes for p in posten)
    if rest > 0:
        posten.append(Posten(name="(Übertragung und Protokolle)", bytes=rest))

    auf_datenwurzel = pfade.daten_wurzel() in hf_wurzel().parents or \
        hf_wurzel() == pfade.daten_wurzel()
    return sorted(posten, key=lambda p: -p.bytes), auf_datenwurzel


def _projekt_dateien(con: sqlite3.Connection) -> tuple[list[Posten], list[str]]:
    """Rohdateien je Projekt — aus der Datenbank, nicht aus dem Verzeichnis.

    Aus der Datenbank, weil nur sie sagt, WEM eine Datei gehört: data/raw/
    liegt flach, die Namen tragen keine Projektkennung, und dieselbe Datei darf
    von mehreren Projekten benutzt werden (siehe server/ingest.py). Eine
    Auflistung nach Verzeichnis könnte 'je Projekt' also gar nicht beantworten.

    Eine Datei, die in keiner quelle-Zeile steht, ist verwaist und kommt als
    eigener Posten dazu — sonst wäre sie unsichtbar und niemand räumte sie weg.
    """
    posten: list[Posten] = []
    warnungen: list[str] = []
    beansprucht: set[Path] = set()

    zeilen = con.execute(
        "SELECT p.id, p.titel, q.pfad, q.quellformat FROM projekt p "
        "JOIN quelle q ON q.projekt_id = p.id ORDER BY p.id"
    ).fetchall()

    je_projekt: dict[str, list[Path]] = {}
    for projekt_id, _titel, pfad, quellformat in zeilen:
        if not pfad:
            continue
        p = Path(pfad)
        # Eine Sammlung nennt einen Dropbox-ORDNER, keine Datei bei uns. Der
        # liegt beim Nutzer und zählt hier nicht mit.
        if quellformat == "pressesammlung" and not p.is_file():
            continue
        je_projekt.setdefault(projekt_id, []).append(p)

    for projekt_id, pfade_ in je_projekt.items():
        vorhanden = [p for p in pfade_ if p.is_file()]
        fehlend = len(pfade_) - len(vorhanden)
        beansprucht.update(p.resolve() for p in vorhanden)
        posten.append(Posten(
            name=projekt_id,
            bytes=sum(p.stat().st_size for p in vorhanden),
            dateien=len(vorhanden),
            hinweis=f"{fehlend} Datei(en) fehlen" if fehlend else "",
        ))

    wurzel = pfade.rohdaten()
    if wurzel.is_dir():
        verwaist = [
            p for p in wurzel.rglob("*")
            if p.is_file() and p.resolve() not in beansprucht
        ]
        if verwaist:
            posten.append(Posten(
                name="(verwaist — kein Projekt nennt sie)",
                bytes=sum(p.stat().st_size for p in verwaist),
                dateien=len(verwaist),
            ))
            warnungen.append(
                f"{len(verwaist)} Rohdatei(en) gehören zu keinem Projekt mehr."
            )

    return sorted(posten, key=lambda p: -p.bytes), warnungen


def _export_posten() -> list[Posten]:
    """Exporte je Projekt. Nach Verzeichnis, denn der Name IST die Kennung.

    Nur die Datenwurzel, nicht das mitgelieferte Prüfstück: das kommt aus dem
    Git und belegt kein Laufwerk.
    """
    wurzel = pfade.daten_wurzel() / "exporte"
    if not wurzel.is_dir():
        return []
    posten = [
        Posten(
            name=eintrag.name,
            bytes=_bytes_im_baum(eintrag),
            dateien=sum(1 for p in eintrag.rglob("*") if p.is_file()),
        )
        for eintrag in wurzel.iterdir() if eintrag.is_dir()
    ]
    return sorted(posten, key=lambda p: -p.bytes)


def _vektor_bestand(con: sqlite3.Connection, benutzte: set[str]) -> list[Vektorbestand]:
    """Ein Eintrag je Modell in einheit_embedding.

    length(vektor) und nicht masse * 4: gemessen wird, was in der Datei steht.
    Die Spalte masse ist eine Angabe über den Vektor, keine über den Platz.
    """
    zeilen = con.execute(
        "SELECT modell, COUNT(*), SUM(length(vektor)), MAX(masse) "
        "FROM einheit_embedding GROUP BY modell ORDER BY SUM(length(vektor)) DESC"
    ).fetchall()
    return [
        Vektorbestand(
            modell=modell,
            bytes=int(bytes_ or 0),
            einheiten=anzahl,
            masse=masse or 0,
            benutzt=modell in benutzte,
        )
        for modell, anzahl, bytes_, masse in zeilen
    ]


def erheben(con: sqlite3.Connection, benutzte_modelle: set[str]) -> Bestand:
    """Der ganze Überblick. Liest die Datenbank und das Laufwerk, ändert nichts.

    benutzte_modelle kommt von außen (aus der Anbieterlage) und nicht von hier:
    dieses Modul soll nicht wissen, wie ein Anbieter eingestellt wird. Es
    beantwortet 'wie viel liegt wo', nicht 'womit wird gerechnet'.
    """
    wurzel = pfade.daten_wurzel()
    wurzel.mkdir(parents=True, exist_ok=True)   # damit disk_usage etwas findet
    platte = shutil.disk_usage(wurzel)

    modelle, auf_datenwurzel = _modell_posten()
    rohdaten, warnungen = _projekt_dateien(con)
    exporte = _export_posten()
    datenbank = _datenbank_posten()
    vektoren = _vektor_bestand(con, benutzte_modelle)

    gezaehlt = datenbank.bytes + sum(p.bytes for p in rohdaten + exporte)
    if auf_datenwurzel:
        gezaehlt += sum(p.bytes for p in modelle)
    else:
        warnungen.append(
            f"Die Modellgewichte liegen nicht auf der Datenwurzel, sondern unter "
            f"{hf_wurzel()} — sie überleben einen Neustart des Containers nicht."
        )

    ungenutzt = [v for v in vektoren if not v.benutzt]
    if ungenutzt:
        warnungen.append(
            f"{len(ungenutzt)} Modell(e) haben Vektoren, die der eingestellte "
            f"Anbieter nicht benutzt: "
            + ", ".join(f"{v.modell} ({v.bytes / 1_048_576:.1f} MB)" for v in ungenutzt)
            + ". Sie bleiben liegen, damit ein Zurückschalten nicht neu rechnet."
        )

    # Die Warnung, um die es eigentlich geht: passt bge-m3 noch?
    if platte.free < KNAPP_BYTES:
        warnungen.append(
            f"Nur noch {platte.free / 1_073_741_824:.1f} GB frei — zu wenig, um auf "
            f"'local' umzuschalten: BAAI/bge-m3 wiegt allein 4,3 GB."
        )
    elif platte.free < platte.total * KNAPP_ANTEIL:
        warnungen.append(
            f"Nur noch {platte.free / 1_073_741_824:.1f} GB von "
            f"{platte.total / 1_073_741_824:.1f} GB frei."
        )

    return Bestand(
        daten_wurzel=str(wurzel),
        # Ausgerechnet und nicht der Fläche überlassen: die Grenze gehört zur
        # Sache und nicht zur Anzeige, und sonst stünde sie zweimal da.
        platz_knapp=(
            platte.free < KNAPP_BYTES or platte.free < platte.total * KNAPP_ANTEIL
        ),
        laufwerk_bytes=platte.total,
        laufwerk_frei=platte.free,
        laufwerk_belegt=platte.used,
        datenbank=datenbank,
        modelle=modelle,
        modelle_wurzel=str(hf_wurzel()),
        modelle_auf_datenwurzel=auf_datenwurzel,
        rohdaten=rohdaten,
        exporte=exporte,
        vektoren=vektoren,
        gezaehlt_bytes=gezaehlt,
        warnungen=warnungen,
    )


# ── Von Hand wegräumen ────────────────────────────────────────────────────────

class BestandFehler(Exception):
    def __init__(self, meldung: str, code: str):
        super().__init__(meldung)
        self.code = code


def vektoren_loeschen(
    con: sqlite3.Connection, modell: str, benutzte_modelle: set[str]
) -> dict:
    """Löscht alle Vektoren eines Modells. Nur auf ausdrückliche Anweisung.

    NIE automatisch, auch nicht beim Anbieterwechsel: dass die Werte des
    anderen Modells liegenbleiben, ist der Grund, warum ein Zurückschalten
    nicht neu rechnet (siehe vektoren.py). Sie automatisch wegzuräumen hieße,
    für ein paar Megabyte eine halbe Stunde Rechenzeit zu verschenken.

    Das eingestellte Modell ist geschützt: es wegzuräumen wäre kein Aufräumen,
    sondern ein Neurechnen des nächsten Laufs. Wer das will, soll den Lauf
    starten, nicht den Speicher leeren.
    """
    if modell in benutzte_modelle:
        raise BestandFehler(
            f"'{modell}' ist gerade eingestellt. Seine Vektoren wegzuräumen "
            f"würde nur den nächsten Lauf verlängern.",
            "modell_in_benutzung",
        )
    zeile = con.execute(
        "SELECT COUNT(*), SUM(length(vektor)) FROM einheit_embedding WHERE modell = ?",
        (modell,),
    ).fetchone()
    if not zeile[0]:
        raise BestandFehler(
            f"Für '{modell}' sind keine Vektoren abgelegt.", "modell_ohne_vektoren"
        )
    with con:
        con.execute("DELETE FROM einheit_embedding WHERE modell = ?", (modell,))
    return {
        "modell": modell,
        "geloeschte_vektoren": zeile[0],
        "freigegebene_bytes": int(zeile[1] or 0),
        "hinweis": (
            "Der Platz wird erst nach VACUUM an das Dateisystem zurückgegeben; "
            "die Datenbank nutzt ihn vorher schon selbst wieder."
        ),
    }
