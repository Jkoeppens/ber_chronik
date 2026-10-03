"""
test_neu_invites_uebernehmen.py — die alten Einladungstoken in zugang holen

Das alte System prüfte vor zugang ein eigenes Gate: Token im Kopf
X-Invite-Token, Liste als JSON auf dem Laufwerk. Seit der neue Server läuft,
gibt es das Gate nicht mehr, und wer so einen Token hat, steht vor der Tür.

Zwei Dinge gehen hier still kaputt, und beide haben einen Test:

  · Überschreiben statt Überspringen. Hinter einer vorhandenen Zeile kann ein
    anderer Mensch stehen als hinter dem gleichnamigen Eintrag in der Datei.
  · Erfundene Angaben. Die Liste kennt kein Ablaufdatum und keine Rolle; wer
    hier eines einsetzt, behauptet etwas, das nie dastand.
"""

import json
import sqlite3

import pytest

from src.neu.invites_uebernehmen import einlesen, main, uebernehmen, vorgabe_datei


@pytest.fixture
def con(tmp_path, monkeypatch):
    from src.neu.db import anlegen_wenn_noetig, verbindung_schreibend

    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "laufwerk"))
    monkeypatch.delenv("NEU_DB", raising=False)
    anlegen_wenn_noetig()
    verbindung = verbindung_schreibend()
    yield verbindung
    verbindung.close()


def _liste(tmp_path, inhalt: dict):
    pfad = tmp_path / "invites.json"
    pfad.write_text(json.dumps(inhalt, ensure_ascii=False), encoding="utf-8")
    return pfad


BEISPIEL = {
    "a1b2c3d4e5f60718": {"name": "Anna Beispiel", "org": "Uni Bonn"},
    "0f1e2d3c4b5a6978": {"name": "", "org": ""},
    "deadbeefcafe0001": {"name": "Carl Muster", "org": ""},
}


# ── Die Übernahme ─────────────────────────────────────────────────────────────

def test_jeder_eintrag_wird_eine_zeile(con, tmp_path):
    z = uebernehmen(con, BEISPIEL)
    assert z["gelesen"] == 3
    assert z["uebernommen"] == 3
    assert z["uebersprungen"] == 0
    assert z["zugang_gesamt"] == 3


def test_der_token_bleibt_unveraendert(con):
    """Er ist das Geheimnis, das Menschen in der Hand haben. Kein Umbau."""
    uebernehmen(con, BEISPIEL)
    in_db = {z[0] for z in con.execute("SELECT token FROM zugang")}
    assert in_db == set(BEISPIEL)


def test_name_und_organisation_kommen_aus_der_datei(con):
    uebernehmen(con, BEISPIEL)
    zeile = con.execute(
        "SELECT name, organisation FROM zugang WHERE token = ?",
        ("a1b2c3d4e5f60718",),
    ).fetchone()
    assert tuple(zeile) == ("Anna Beispiel", "Uni Bonn")


def test_leer_bleibt_leer(con):
    """Keine Platzhalter. 'Unbekannt 7' wäre eine Angabe, die niemand gemacht hat."""
    uebernehmen(con, BEISPIEL)
    zeile = con.execute(
        "SELECT name, organisation FROM zugang WHERE token = ?",
        ("0f1e2d3c4b5a6978",),
    ).fetchone()
    assert tuple(zeile) == ("", "")


def test_alle_bekommen_die_rolle_nutzer(con):
    """Die Liste kannte keine Rolle. Verwalter wird niemand durch eine Übernahme."""
    uebernehmen(con, BEISPIEL)
    rollen = {z[0] for z in con.execute(
        "SELECT rolle FROM zugang WHERE token IN (?, ?, ?)", tuple(BEISPIEL)
    )}
    assert rollen == {"nutzer"}


def test_angelegt_am_ist_der_zeitpunkt_der_uebernahme(con):
    """Ein echtes Datum gibt es nicht — die Liste führte keines."""
    from datetime import datetime, timezone

    uebernehmen(con, BEISPIEL)
    roh = con.execute(
        "SELECT angelegt_am FROM zugang WHERE token = ?", ("deadbeefcafe0001",)
    ).fetchone()[0]
    wann = datetime.fromisoformat(roh)
    assert abs((datetime.now(timezone.utc) - wann).total_seconds()) < 60


def test_es_wird_nichts_erfunden(con):
    """Kein Ablaufdatum, keine Kennzeichnung — die Tabelle hat dafür kein Feld,
    und ein Vermerk im Namen wäre eine Angabe, die niemand gemacht hat."""
    uebernehmen(con, BEISPIEL)
    for name, org in con.execute("SELECT name, organisation FROM zugang"):
        for wert in (name, org):
            assert "Einladung" not in wert
            assert "invite" not in wert.lower()


# ── Was NICHT passieren darf ──────────────────────────────────────────────────

def test_eine_kollision_wird_uebersprungen_nicht_ueberschrieben(con):
    """Hinter der vorhandenen Zeile kann ein anderer Mensch stehen.

    Der Fall, der still kaputtgeht: ein UPDATE sähe genauso erfolgreich aus und
    nähme jemandem den Zugang weg, ohne dass irgendwo etwas scheitert.
    """
    with con:
        con.execute(
            "INSERT INTO zugang (token, name, organisation, rolle, angelegt_am) "
            "VALUES ('a1b2c3d4e5f60718', 'Schon da', 'Archiv', 'verwalter', "
            "'2026-01-01')"
        )

    z = uebernehmen(con, BEISPIEL)

    assert z["uebernommen"] == 2
    assert z["uebersprungen"] == 1
    zeile = con.execute(
        "SELECT name, organisation, rolle FROM zugang WHERE token = ?",
        ("a1b2c3d4e5f60718",),
    ).fetchone()
    assert tuple(zeile) == ("Schon da", "Archiv", "verwalter"), \
        "Die vorhandene Zeile wurde überschrieben"


def test_ein_zweiter_lauf_aendert_nichts(con):
    """Mehrfach ausführbar: wer unsicher ist, soll ihn noch einmal laufen lassen."""
    uebernehmen(con, BEISPIEL)
    vorher = con.execute("SELECT COUNT(*) FROM zugang").fetchone()[0]

    z = uebernehmen(con, BEISPIEL)

    assert z["uebernommen"] == 0
    assert z["uebersprungen"] == 3
    assert con.execute("SELECT COUNT(*) FROM zugang").fetchone()[0] == vorher


def test_die_probe_schreibt_nichts(con):
    z = uebernehmen(con, BEISPIEL, probe=True)
    assert z["uebernommen"] == 3          # was geschähe
    assert con.execute("SELECT COUNT(*) FROM zugang").fetchone()[0] == 0


def test_die_zaehlung_nennt_keinen_token(con):
    """Sie wird gedruckt und steht danach im Protokoll des Terminals."""
    z = uebernehmen(con, BEISPIEL)
    text = repr(z)
    for token in BEISPIEL:
        assert token not in text


# ── Die Datei ─────────────────────────────────────────────────────────────────

def test_eine_kaputte_datei_bricht_ab_statt_halb_zu_uebernehmen(tmp_path):
    """Wer dreizehn erwartet und sieben bekommt, sucht lange."""
    pfad = _liste(tmp_path, {"abc": "keine Felder, sondern ein Text"})
    with pytest.raises(ValueError, match="erwartet wird ein Objekt"):
        einlesen(pfad)


def test_eine_liste_statt_eines_objekts_bricht_ab(tmp_path):
    pfad = tmp_path / "invites.json"
    pfad.write_text('["a", "b"]', encoding="utf-8")
    with pytest.raises(ValueError, match="kein Objekt"):
        einlesen(pfad)


def test_fehlende_felder_sind_in_ordnung(tmp_path):
    """gen_invite schrieb immer beide, aber ein Eintrag von Hand vielleicht nicht."""
    pfad = _liste(tmp_path, {"0123456789abcdef": {}})
    assert einlesen(pfad) == {"0123456789abcdef": {}}


def test_die_vorgabedatei_liegt_auf_der_datenwurzel(con, tmp_path, monkeypatch):
    """Im Container ist das /data/invites.json — dort las auch invite_auth.py."""
    assert vorgabe_datei() == tmp_path / "laufwerk" / "invites.json"


def test_eine_fehlende_datei_ist_ein_fehler_und_kein_schweigen(con, tmp_path, capsys):
    assert main(["--datei", str(tmp_path / "gibtsnicht.json")]) == 1
    assert "gibt es nicht" in capsys.readouterr().err


def test_eine_leere_liste_ist_kein_fehler(con, tmp_path, capsys):
    pfad = _liste(tmp_path, {})
    assert main(["--datei", str(pfad)]) == 0
    assert "leer" in capsys.readouterr().out


# ── Die Gestalt der echten Liste ──────────────────────────────────────────────

def test_die_gestalt_von_gen_invite_wird_verstanden(con):
    """Gegen das, was invite_auth.gen_invite() tatsächlich schreibt.

    Nachgebaut und nicht importiert: src/generalized/ bleibt lesend, und die
    Datei dort schreibt in einen Pfad, den dieser Test nicht anfassen soll.
    Die Gestalt ist seit dem ersten Commit vom 20. April unverändert —
    {token: {name, org}}, 16 Hexzeichen, sonst nichts.
    """
    import secrets

    nachgebaut = {secrets.token_hex(8): {"name": "X", "org": "Y"} for _ in range(3)}
    for token in nachgebaut:
        assert len(token) == 16
        assert set(token) <= set("0123456789abcdef")

    z = uebernehmen(con, nachgebaut)
    assert z["uebernommen"] == 3


def test_kurze_token_stehen_neben_langen(con):
    """64 Bit neben 256 Bit in einer Spalte. TEXT hat keine Längenprüfung.

    Der Riegel vergleicht mit compare_digest über Bytes — verschiedene Längen
    sind ihm gleichgültig, und das soll so bleiben.
    """
    from src.neu import zugang

    uebernehmen(con, BEISPIEL)
    zugang.anlegen(con, "Mit langem Token")

    laengen = {len(z[0]) for z in con.execute("SELECT token FROM zugang")}
    assert 16 in laengen and 43 in laengen


def test_ein_uebernommener_token_laesst_herein(con, monkeypatch):
    """Der eigentliche Zweck. Geprüft am Nachschlagen, nicht über HTTP."""
    from src.neu import zugang

    uebernehmen(con, BEISPIEL)
    wer = zugang.nachschlagen("a1b2c3d4e5f60718")
    assert wer is not None
    assert wer.name == "Anna Beispiel"
    assert wer.rolle == "nutzer"


def test_ein_namenloser_uebernommener_bekommt_einen_lesbaren_namen(con):
    """nachschlagen() setzt 'Zugang <id>', wenn name leer ist — fürs Protokoll.

    In der TABELLE bleibt er leer; erfunden wird nichts. Nur die Protokollzeile
    braucht etwas, das sich lesen lässt.
    """
    from src.neu import zugang

    uebernehmen(con, BEISPIEL)
    wer = zugang.nachschlagen("0f1e2d3c4b5a6978")
    assert wer.name.startswith("Zugang ")
    assert con.execute(
        "SELECT name FROM zugang WHERE token = ?", ("0f1e2d3c4b5a6978",)
    ).fetchone()[0] == ""
