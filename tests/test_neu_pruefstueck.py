"""
tests/test_neu_pruefstueck.py — das eingefrorene Prüfstück

data/exporte/pruefstueck/ ist ein Export des Projekts `ber` vom 9. September
2026, unverändert eingefroren. Die Playwright-Tests laden ihn über
/viz/?project=pruefstueck und vergleichen gegen feste Zahlen.

Ein Prüfmaß, das sich ändern kann, ist keines. Deshalb steht hier die
Prüfsumme jeder Datei: ein versehentliches `--projekt pruefstueck` würde ihn
sonst still überschreiben — die Kennung ist nicht reserviert, `export_verzeichnis`
bildet den Pfad für jede Kennung gleich, und ein Projekt mit dem Titel
„Prüfstück" bekäme genau diese. Dann wären die Zahlen andere, und niemand
wüsste, warum.

Ausführen:
  python3 -m pytest tests/test_neu_pruefstueck.py -v
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRUEFSTUECK = ROOT / "data" / "exporte" / "pruefstueck"

# sha256 der eingefrorenen Dateien. Schlägt der Vergleich fehl, ist das kein
# Testfehler, sondern ein Hinweis: jemand hat das Prüfmaß angefasst.
PRUEFSUMMEN = {
    "data.json":
        "968e62c4f14c50422eac64354841b6e55b0d9889cdbb94efac5a2f1eca29f929",
    "entities_seed.csv":
        "b494a614b7dd288ff7b4a4e3b347d9b20824a9248a474b24ba2e161e82efcf6e",
    "network_layout.json":
        "bef5be79f275a3af443009a490241aa7fc1c040a466a9b421154d85613856f68",
    "project_meta.json":
        "52a4ace4602692d8421ffe2a7d6827c4691e1362e2fc0f808d8f9fc7be73897a",
}

# Die Zahlen, gegen die die Playwright-Tests prüfen. Sie stehen hier ein
# zweites Mal, damit ein Bruch am Prüfstück in pytest auffällt und nicht erst
# im Browser.
EINTRAEGE = 949
KATEGORIEN = 7
KNOTEN = 869
JAHR_VON, JAHR_BIS = 1989, 2017


def test_das_pruefstueck_liegt_da() -> None:
    assert PRUEFSTUECK.is_dir(), f"{PRUEFSTUECK} fehlt"
    vorhanden = {p.name for p in PRUEFSTUECK.iterdir()}
    assert set(PRUEFSUMMEN) <= vorhanden, set(PRUEFSUMMEN) - vorhanden


@pytest.mark.parametrize("datei", sorted(PRUEFSUMMEN))
def test_pruefstueck_ist_unveraendert(datei: str) -> None:
    """Die eine Eigenschaft, die es zum Prüfmaß macht."""
    ist = hashlib.sha256((PRUEFSTUECK / datei).read_bytes()).hexdigest()
    assert ist == PRUEFSUMMEN[datei], (
        f"{datei} hat sich geändert. Wenn das Absicht war, gehört die neue "
        f"Prüfsumme hierher — und die Zahlen in tests/viz.spec.js dazu."
    )


def test_die_zahlen_stimmen_mit_den_browsertests() -> None:
    daten = json.loads((PRUEFSTUECK / "data.json").read_text(encoding="utf-8"))
    meta = json.loads((PRUEFSTUECK / "project_meta.json").read_text(encoding="utf-8"))
    netz = json.loads((PRUEFSTUECK / "network_layout.json").read_text(encoding="utf-8"))

    assert daten["count"] == EINTRAEGE == len(daten["entries"])
    assert len(meta["taxonomy"]) == KATEGORIEN
    assert len(netz["nodes"]) == KNOTEN
    assert (meta["year_min"], meta["year_max"]) == (JAHR_VON, JAHR_BIS)


def test_das_pruefstueck_traegt_die_neue_ankerform() -> None:
    """Nicht s0001 — daran hing der alte Datensatz in viz/.

    Die Anker müssen dieselbe Form haben, die export/kern.anker() erzeugt,
    sonst prüfen die Browsertests einen Weg, den es nicht mehr gibt.
    """
    daten = json.loads((PRUEFSTUECK / "data.json").read_text(encoding="utf-8"))
    anker = [e["doc_anchor"] for e in daten["entries"] if e.get("doc_anchor")]
    assert len(anker) == EINTRAEGE
    assert all("-e" in a for a in anker), [a for a in anker if "-e" not in a][:5]
    assert not any(a.startswith("s0") for a in anker)


def test_keine_felder_aus_dem_alten_export() -> None:
    """is_geicke, causal_theme und date_precision schreibt niemand mehr."""
    daten = json.loads((PRUEFSTUECK / "data.json").read_text(encoding="utf-8"))
    felder = {k for e in daten["entries"] for k in e}
    assert not felder & {"is_geicke", "causal_theme", "date_precision"}, felder


def test_es_gibt_genug_stoff_fuer_die_drei_ansichten() -> None:
    """Ein Prüfstück, das eine Ansicht leer lässt, prüft sie auch nicht."""
    daten = json.loads((PRUEFSTUECK / "data.json").read_text(encoding="utf-8"))
    mit_akteuren = [e for e in daten["entries"] if e.get("actors")]
    mit_datum = [e for e in daten["entries"] if e.get("date_js") or e.get("year")]

    assert len(mit_datum) > 900, len(mit_datum)          # Zeitachse
    assert len(mit_akteuren) > 900, len(mit_akteuren)    # Netzwerk und Panel

    aliase = list(csv.DictReader((PRUEFSTUECK / "entities_seed.csv")
                                 .read_text(encoding="utf-8").splitlines()))
    assert len(aliase) > 500
    assert set(aliase[0]) == {"alias", "normalform", "typ"}


def test_die_zusammenfassungen_fehlen_und_das_ist_bekannt() -> None:
    """ber hat keine — der Kasten .ep-summary ist nicht abgedeckt.

    Steht als Test da und nicht nur im Fließtext: wer später ein Prüfstück mit
    Zusammenfassungen einfriert, soll hier vorbeikommen und die Abdeckung
    nachziehen.
    """
    assert not (PRUEFSTUECK / "entities_summary.json").exists()
