"""
test_neu_pfade.py — dass geschriebene Daten aufs Laufwerk gehen, nicht in den Code

Der Fehler, den diese Tests festhalten, war nicht sichtbar: lokal liegen
Quellbestand und Datenverzeichnis übereinander, und dort stimmt jeder Pfad.
Erst mit DATA_ROOT auf einem eingehängten Laufwerk fallen sie auseinander — und
dann schrieb src/neu Uploads und Exporte in den Container, wo sie beim nächsten
Deploy verschwanden.
"""

import sqlite3

import pytest

from src.neu import db as db_modul
from src.neu import pfade, projekte
from src.neu.server import gemeinsam


@pytest.fixture
def laufwerk(tmp_path, monkeypatch):
    """Ein leeres DATA_ROOT, und NEU_DB ausdrücklich weg."""
    ziel = tmp_path / "laufwerk"
    monkeypatch.setenv("DATA_ROOT", str(ziel))
    monkeypatch.delenv("NEU_DB", raising=False)
    return ziel


# ── Was mitwandert ────────────────────────────────────────────────────────────

def test_alles_geschriebene_liegt_unter_data_root(laufwerk):
    assert pfade.daten_wurzel() == laufwerk
    assert pfade.datenbank() == laufwerk / "neu.db"
    assert pfade.rohdaten() == laufwerk / "raw"
    assert pfade.export_verzeichnis("ber") == laufwerk / "exporte" / "ber"


def test_die_drei_module_bilden_keine_eigenen_pfade(laufwerk):
    """db, projekte und der Server fragen pfade — sie rechnen nicht selbst.

    Drei getrennte Zugänge, weil es bis September 2026 drei getrennte
    Herleitungen aus WURZEL waren.
    """
    assert db_modul.db_pfad() == laufwerk / "neu.db"
    assert projekte.export_verzeichnis("ber") == laufwerk / "exporte" / "ber"
    assert gemeinsam.rohdaten() == laufwerk / "raw"


def test_rohdaten_ist_traege(laufwerk, tmp_path, monkeypatch):
    """Ein zweites DATA_ROOT nach dem Import wirkt noch.

    Als Konstante hielt ROHDATEN den Wert vom ersten Import fest.
    """
    zweites = tmp_path / "anderswo"
    monkeypatch.setenv("DATA_ROOT", str(zweites))
    assert gemeinsam.rohdaten() == zweites / "raw"


def test_hochgeladenes_bleibt_unter_rohdaten(laufwerk):
    """Der Riegel gegen .. gilt gegen das Laufwerk, nicht gegen den Quellbestand."""
    assert gemeinsam.pfad_in_rohdaten("a.docx") == laufwerk / "raw" / "a.docx"
    with pytest.raises(Exception):
        gemeinsam.pfad_in_rohdaten("../../etc/passwd")


# ── Was nicht mitwandert ──────────────────────────────────────────────────────

def test_quellbestand_bleibt_wo_der_code_liegt(laufwerk):
    """anbieter.toml, schema.sql, viz/ und frontend/build kommen aus dem Git."""
    from src.neu import anbieter, konfiguration
    from src.neu.server import BUILD_DIR, VIZ_DIR

    assert laufwerk not in anbieter.DATEI.parents
    assert laufwerk not in konfiguration.ENV_DATEI.parents
    assert laufwerk not in db_modul.SCHEMA.parents
    assert laufwerk not in VIZ_DIR.parents
    assert laufwerk not in BUILD_DIR.parents
    assert db_modul.SCHEMA == pfade.WURZEL / "schema.sql"


def test_neu_db_uebersteuert_data_root(laufwerk, tmp_path):
    """Die engere Angabe gewinnt — die Tests brauchen einzelne Datenbanken."""
    import os
    eigene = tmp_path / "eigene.db"
    os.environ["NEU_DB"] = str(eigene)
    try:
        assert pfade.datenbank() == eigene
        assert pfade.rohdaten() == laufwerk / "raw"   # der Rest bleibt
    finally:
        del os.environ["NEU_DB"]


def test_ohne_data_root_bleibt_alles_wie_vorher(monkeypatch):
    """Der lokale Betrieb ändert sich nicht: data/ im Quellbestand."""
    monkeypatch.delenv("DATA_ROOT", raising=False)
    monkeypatch.delenv("NEU_DB", raising=False)
    assert pfade.daten_wurzel() == pfade.WURZEL / "data"
    assert pfade.datenbank() == pfade.WURZEL / "data" / "neu.db"


# ── Lesen: zwei Orte ──────────────────────────────────────────────────────────

def test_export_quelle_findet_das_mitgelieferte_pruefstueck(laufwerk):
    """Das Prüfstück liegt im Git und wandert nicht mit — gefunden wird es doch.

    Sonst wäre der Browsertest gegen /data/exporte/pruefstueck/ tot, sobald
    DATA_ROOT gesetzt ist.
    """
    assert pfade.export_quelle("pruefstueck") == (
        pfade.WURZEL / "data" / "exporte" / "pruefstueck"
    )


def test_das_laufwerk_gewinnt_gegen_das_mitgelieferte(laufwerk):
    (laufwerk / "exporte" / "pruefstueck").mkdir(parents=True)
    assert pfade.export_quelle("pruefstueck") == (
        laufwerk / "exporte" / "pruefstueck"
    )


def test_export_quelle_ohne_export_ist_none(laufwerk):
    assert pfade.export_quelle("gibtsnicht") is None


# ── Erststart auf leerem Laufwerk ─────────────────────────────────────────────

def test_leeres_laufwerk_bekommt_eine_datenbank(laufwerk):
    """Vorher gab dort jeder Aufruf 500 'datenbank_fehlt'."""
    assert not laufwerk.exists()
    assert db_modul.anlegen_wenn_noetig() is True
    assert (laufwerk / "neu.db").is_file()

    con = sqlite3.connect(laufwerk / "neu.db")
    try:
        tabellen = {
            z[0] for z in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"projekt", "einheit", "akteur", "lauf", "zugang"} <= tabellen
        assert list(con.execute("PRAGMA foreign_key_check")) == []
    finally:
        con.close()


def test_anlegen_ruehrt_eine_vorhandene_datenbank_nicht_an(laufwerk):
    db_modul.anlegen_wenn_noetig()
    con = sqlite3.connect(laufwerk / "neu.db")
    with con:
        con.execute(
            "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
            "VALUES ('t', '', '', 'nutzer', '2026-01-01')"
        )
    con.close()

    assert db_modul.anlegen_wenn_noetig() is False
    con = sqlite3.connect(laufwerk / "neu.db")
    try:
        assert con.execute("SELECT count(*) FROM zugang").fetchone()[0] == 1
    finally:
        con.close()


def test_ohne_schema_kein_stilles_ersatzschema(laufwerk, monkeypatch):
    """Fehlt schema.sql, ist der Quellbestand kaputt — und das soll auffallen."""
    monkeypatch.setattr(db_modul, "SCHEMA", laufwerk / "gibtsnicht.sql")
    with pytest.raises(FileNotFoundError):
        db_modul.anlegen_wenn_noetig()
    assert not (laufwerk / "neu.db").exists()
