"""
test_neu_bestand.py — der Überblick, und dass Löschen aufräumt

Vier Dinge halten diese Tests fest, und drei davon waren Fehler:

  · Ein gelöschtes Projekt ließ seine Rohdatei und sein Exportverzeichnis
    liegen. Niemand räumte sie danach weg.
  · Eine Rohdatei, die zwei Projekten gehört, darf beim Löschen des einen
    nicht verschwinden — data/raw/ liegt flach nach Namen.
  · Vektoren eines Modells, das gerade eingestellt ist, dürfen nicht
    weggeräumt werden, und Vektoren überhaupt nie automatisch.

Das vierte ist der Überblick selbst: dass er die Größen nach Art trennt.
"""

import sqlite3
from pathlib import Path

import pytest

from src.neu import bestand as bestand_dienst
from src.neu import projekte
from src.neu.bestand import BestandFehler


@pytest.fixture
def laufwerk(tmp_path, monkeypatch):
    """Ein eigenes DATA_ROOT mit eigener Datenbank und eigenem HF-Cache."""
    ziel = tmp_path / "laufwerk"
    monkeypatch.setenv("DATA_ROOT", str(ziel))
    monkeypatch.delenv("NEU_DB", raising=False)
    monkeypatch.setenv("HF_HOME", str(ziel / "huggingface"))
    return ziel


@pytest.fixture
def con(laufwerk):
    from src.neu.db import anlegen_wenn_noetig, verbindung_schreibend

    anlegen_wenn_noetig()
    verbindung = verbindung_schreibend()
    yield verbindung
    verbindung.close()


def _projekt(con: sqlite3.Connection, projekt_id: str, pfad: str | None = None,
             quellformat: str = "literaturexzerpt") -> None:
    """Ein Projekt mit Eigentümer, einer Quelle und einer content-Einheit."""
    with con:
        zeiger = con.execute(
            "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
            "VALUES (?, '', '', 'nutzer', '2026-01-01')", (f"t-{projekt_id}",)
        )
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES (?, ?, ?, '2026-01-01')",
            (projekt_id, projekt_id.title(), zeiger.lastrowid),
        )
        con.execute(
            "INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
            "VALUES (?, ?, ?, ?, '2026-01-01')",
            (f"q-{projekt_id}", projekt_id, quellformat, pfad),
        )
        con.execute(
            "INSERT INTO einheit (quelle_id, position, typ, text) "
            "VALUES (?, 1, 'content', 'Ein Absatz.')", (f"q-{projekt_id}",),
        )


def _rohdatei(laufwerk: Path, name: str, inhalt: bytes = b"x" * 1000) -> Path:
    pfad = laufwerk / "raw" / name
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(inhalt)
    return pfad


def _export(laufwerk: Path, projekt_id: str, groesse: int = 2000) -> Path:
    verzeichnis = laufwerk / "exporte" / projekt_id
    verzeichnis.mkdir(parents=True, exist_ok=True)
    (verzeichnis / "data.json").write_bytes(b"y" * groesse)
    (verzeichnis / "project_meta.json").write_bytes(b"z" * 100)
    return verzeichnis


# ── Der Überblick ─────────────────────────────────────────────────────────────

def test_ueberblick_trennt_nach_art(con, laufwerk):
    datei = _rohdatei(laufwerk, "quelle.docx", b"a" * 5000)
    _projekt(con, "eins", str(datei))
    _export(laufwerk, "eins", 7000)

    z = bestand_dienst.erheben(con, {"BAAI/bge-m3"})

    assert z.daten_wurzel == str(laufwerk)
    assert z.laufwerk_bytes > 0 and z.laufwerk_frei > 0
    assert z.datenbank.bytes > 0
    assert [(p.name, p.bytes) for p in z.rohdaten] == [("eins", 5000)]
    assert [(p.name, p.bytes) for p in z.exporte] == [("eins", 7100)]
    # gezaehlt_bytes ist die Summe der Posten, nicht laufwerk_belegt: auf der
    # Platte liegt auch Fremdes.
    assert z.gezaehlt_bytes == z.datenbank.bytes + 5000 + 7100


def test_modellgewichte_je_modell_ohne_doppelzaehlung(con, laufwerk):
    """Symlinks aus snapshots/ zeigen auf blobs/ — wer ihnen folgt, zählt doppelt."""
    hub = laufwerk / "huggingface" / "hub" / "models--urchade--gliner_multi"
    (hub / "blobs").mkdir(parents=True)
    (hub / "snapshots" / "abc").mkdir(parents=True)
    gewicht = hub / "blobs" / "deadbeef"
    gewicht.write_bytes(b"w" * 10_000)
    (hub / "snapshots" / "abc" / "pytorch_model.bin").symlink_to(gewicht)

    z = bestand_dienst.erheben(con, set())

    modelle = {p.name: p.bytes for p in z.modelle}
    assert "urchade/gliner_multi" in modelle
    # 10 000 und nicht 20 000: der Symlink zählt mit seiner eigenen Länge.
    assert modelle["urchade/gliner_multi"] < 11_000


def test_gewichte_ausserhalb_der_datenwurzel_werden_gemeldet(con, laufwerk, tmp_path,
                                                            monkeypatch):
    """Der Fall, der auf Railway Geld kostet: HF_HOME zeigt in den Container."""
    monkeypatch.setenv("HF_HOME", str(tmp_path / "fremd"))
    z = bestand_dienst.erheben(con, set())
    assert z.modelle_auf_datenwurzel is False
    assert any("überleben einen Neustart" in w for w in z.warnungen)


def test_verwaiste_rohdatei_wird_sichtbar(con, laufwerk):
    """Sonst läge sie unsichtbar da und niemand räumte sie weg."""
    _rohdatei(laufwerk, "niemandes.docx", b"a" * 300)
    z = bestand_dienst.erheben(con, set())
    assert any("verwaist" in p.name for p in z.rohdaten)
    assert any("keinem Projekt" in w for w in z.warnungen)


def test_dropbox_ordner_zaehlt_nicht_als_rohdatei(con, laufwerk):
    """Der Ordner liegt in der Dropbox des Nutzers, nicht bei uns."""
    _projekt(con, "sammlung", "/Apps/BERChronik/presse", "pressesammlung")
    z = bestand_dienst.erheben(con, set())
    assert [p.name for p in z.rohdaten if p.name == "sammlung"] == []


def test_die_platzgrenze_ist_absolut_und_nicht_nur_ein_anteil(con, laufwerk,
                                                              monkeypatch):
    """19 % frei auf 228 GB sind 44 GB und kein Problem. 4 GB auf 10 GB sind eines.

    Ein reiner Anteil misst die falsche Sache. Gemessen: die erste Fassung
    meldete auf der Entwicklungsmaschine 'nur noch 42,9 GB frei' und färbte die
    Anzeige rot — eine Warnung, die nichts bedeutete.
    """
    import shutil

    from src.neu.bestand import KNAPP_BYTES

    def platte(gesamt_gb, frei_gb):
        return lambda _: shutil._ntuple_diskusage(
            total=int(gesamt_gb * 1024**3),
            used=int((gesamt_gb - frei_gb) * 1024**3),
            free=int(frei_gb * 1024**3),
        )

    # Große Platte, wenig Anteil, viel Platz: kein Problem.
    monkeypatch.setattr(shutil, "disk_usage", platte(228, 44))
    z = bestand_dienst.erheben(con, set())
    assert z.platz_knapp is False
    assert not any("frei" in w for w in z.warnungen)

    # Kleines Laufwerk, guter Anteil, zu wenig für bge-m3: Problem.
    monkeypatch.setattr(shutil, "disk_usage", platte(10, 4))
    z = bestand_dienst.erheben(con, set())
    assert z.platz_knapp is True
    assert any("bge-m3" in w for w in z.warnungen)

    # Und die Grenze selbst nennt den Grund, nicht nur eine Zahl.
    assert KNAPP_BYTES == 6 * 1024**3


# ── Vektoren ──────────────────────────────────────────────────────────────────

def _vektor(con: sqlite3.Connection, einheit_id: int, modell: str, masse: int = 4):
    with con:
        con.execute(
            "INSERT INTO einheit_embedding "
            "(einheit_id, modell, pruefsumme, masse, vektor, berechnet_am) "
            "VALUES (?, ?, 'x', ?, ?, '2026-01-01')",
            (einheit_id, modell, masse, b"\x00" * (masse * 4)),
        )


def test_vektoren_je_modell_mit_benutzt_kennzeichen(con, laufwerk):
    _projekt(con, "eins")
    einheit_id = con.execute("SELECT id FROM einheit").fetchone()[0]
    _vektor(con, einheit_id, "BAAI/bge-m3")
    _vektor(con, einheit_id, "voyage-4")

    z = bestand_dienst.erheben(con, {"BAAI/bge-m3"})
    nach_modell = {v.modell: v for v in z.vektoren}
    assert nach_modell["BAAI/bge-m3"].benutzt is True
    assert nach_modell["voyage-4"].benutzt is False
    assert nach_modell["voyage-4"].bytes == 16
    assert any("nicht benutzt" in w for w in z.warnungen)


def test_das_eingestellte_modell_ist_geschuetzt(con, laufwerk):
    """Seine Vektoren wegzuräumen wäre kein Aufräumen, sondern ein Neurechnen."""
    _projekt(con, "eins")
    einheit_id = con.execute("SELECT id FROM einheit").fetchone()[0]
    _vektor(con, einheit_id, "BAAI/bge-m3")

    with pytest.raises(BestandFehler) as fehler:
        bestand_dienst.vektoren_loeschen(con, "BAAI/bge-m3", {"BAAI/bge-m3"})
    assert fehler.value.code == "modell_in_benutzung"
    assert con.execute("SELECT COUNT(*) FROM einheit_embedding").fetchone()[0] == 1


def test_ungenutztes_modell_laesst_sich_wegraeumen(con, laufwerk):
    _projekt(con, "eins")
    einheit_id = con.execute("SELECT id FROM einheit").fetchone()[0]
    _vektor(con, einheit_id, "BAAI/bge-m3")
    _vektor(con, einheit_id, "voyage-4")

    ergebnis = bestand_dienst.vektoren_loeschen(con, "voyage-4", {"BAAI/bge-m3"})
    assert ergebnis["geloeschte_vektoren"] == 1
    # Das eingestellte Modell bleibt unangetastet.
    uebrig = [z[0] for z in con.execute("SELECT modell FROM einheit_embedding")]
    assert uebrig == ["BAAI/bge-m3"]


def test_nichts_raeumt_vektoren_von_selbst_weg(con, laufwerk):
    """Der Grund: ein Zurückschalten soll nicht neu rechnen müssen.

    Geprüft an der Erhebung — sie ist der einzige Weg, auf dem Vektoren eines
    ungenutzten Modells überhaupt zur Sprache kommen, und sie darf lesen.
    """
    _projekt(con, "eins")
    einheit_id = con.execute("SELECT id FROM einheit").fetchone()[0]
    _vektor(con, einheit_id, "voyage-4")

    for _ in range(3):
        bestand_dienst.erheben(con, {"BAAI/bge-m3"})
    assert con.execute("SELECT COUNT(*) FROM einheit_embedding").fetchone()[0] == 1


# ── Löschen räumt auf ─────────────────────────────────────────────────────────

def test_loeschen_nimmt_rohdatei_und_export_mit(con, laufwerk):
    datei = _rohdatei(laufwerk, "eigen.docx")
    _projekt(con, "eins", str(datei))
    verzeichnis = _export(laufwerk, "eins")

    ergebnis = projekte.loeschen(con, "eins")

    assert not datei.exists()
    assert not verzeichnis.exists()
    assert str(datei) in ergebnis["geloeschte_dateien"]
    assert str(verzeichnis) in ergebnis["geloeschte_dateien"]
    assert ergebnis["freigegebene_bytes"] == 1000 + 2100
    assert ergebnis["nicht_geloescht"] == []


def test_geteilte_rohdatei_bleibt(con, laufwerk):
    """data/raw/ liegt flach: derselbe Name gehört womöglich zwei Projekten."""
    datei = _rohdatei(laufwerk, "geteilt.docx")
    _projekt(con, "eins", str(datei))
    _projekt(con, "zwei", str(datei))

    ergebnis = projekte.loeschen(con, "eins")

    assert datei.exists(), "Die Datei von 'zwei' wurde mitgerissen"
    assert ergebnis["geteilte_dateien"] == ["geteilt.docx"]
    assert ergebnis["freigegebene_bytes"] == 0
    # 'zwei' hat seine Quelle noch, und sie zeigt auf eine Datei, die es gibt.
    pfad = con.execute(
        "SELECT pfad FROM quelle WHERE projekt_id = 'zwei'"
    ).fetchone()[0]
    assert Path(pfad).is_file()


def test_loeschen_ohne_dateien_bleibt_moeglich(con, laufwerk):
    """Ein Projekt, dessen Rohdatei schon weg ist, muss löschbar bleiben."""
    _projekt(con, "eins", str(laufwerk / "raw" / "gibtsnicht.docx"))
    ergebnis = projekte.loeschen(con, "eins")
    assert ergebnis["geloeschte_dateien"] == []
    assert ergebnis["nicht_geloescht"] == []
    assert con.execute("SELECT COUNT(*) FROM projekt").fetchone()[0] == 0


def test_der_bestand_eines_projekts_nennt_was_verschwindet(con, laufwerk):
    eigen = _rohdatei(laufwerk, "eigen.docx", b"a" * 4000)
    geteilt = _rohdatei(laufwerk, "geteilt.docx", b"b" * 600)
    _projekt(con, "eins", str(eigen))
    _projekt(con, "zwei", str(geteilt))
    with con:
        con.execute(
            "INSERT INTO quelle (id, projekt_id, quellformat, pfad, eingelesen_am) "
            "VALUES ('q2', 'eins', 'literaturexzerpt', ?, '2026-01-01')",
            (str(geteilt),),
        )
    _export(laufwerk, "eins", 9000)

    z = projekte.dateien_eines_projekts(con, "eins")

    assert [d["name"] for d in z["rohdateien"]] == ["eigen.docx"]
    assert [d["name"] for d in z["rohdateien_geteilt"]] == ["geteilt.docx"]
    assert z["export"]["dateien"] == 2
    # Nur das Eigene plus der Export — die geteilte Datei zählt nicht mit.
    assert z["bytes_gesamt"] == 4000 + 9100


def test_bestand_eines_unbekannten_projekts_wirft(con, laufwerk):
    with pytest.raises(projekte.ProjektFehler) as fehler:
        projekte.dateien_eines_projekts(con, "gibtsnicht")
    assert fehler.value.code == "projekt_nicht_gefunden"
