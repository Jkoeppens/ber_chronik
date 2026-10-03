"""
test_neu_zugang_tabelle.py — der Riegel prüft gegen zugang, nicht gegen ein Wort

Vorher galt ein gemeinsames ZUGANG_PASSWORT für alle. Jetzt wird das eingegebene
Passwort in der Tabelle nachgeschlagen, ein Token je Person; das gemeinsame
Geheimnis gilt zusätzlich weiter, damit eine leere Tabelle auf einem frischen
Laufwerk niemanden aussperrt.

Der Punkt der Übung ist Widerrufbarkeit. Deshalb prüft hier ein Test, dass ein
entzogener Token OHNE Neustart nicht mehr hereinlässt — ein Zwischenspeicher
wäre genau an dieser Stelle still falsch.

Der letzte Test im Modul ist der eigentliche: er bindet einen Satz aus der
Oberfläche an das Verhalten, das er behauptet.
"""

import base64
import io
import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.neu import zugang
from src.neu.server import app
from tests.conftest import TEST_PASSWORT


def _kopf(passwort: str, benutzer: str = "wer") -> dict:
    roh = f"{benutzer}:{passwort}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(roh).decode("ascii")}


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Eine eigene Datenbank mit drei Zugängen. Nicht die Arbeitsdatenbank."""
    from src.neu.db import anlegen_wenn_noetig, verbindung_schreibend

    monkeypatch.setenv("NEU_DB", str(tmp_path / "zugang.db"))
    anlegen_wenn_noetig()
    con = verbindung_schreibend()
    token = {}
    for name, rolle in (("Jakob", "verwalter"), ("Gast", "nutzer"), ("Weg", "nutzer")):
        _, token[name] = zugang.anlegen(con, name, "Uni", rolle)
    yield con, token
    con.close()


@pytest.fixture
def client(db) -> TestClient:
    return TestClient(app)


# ── Wer hereinkommt ───────────────────────────────────────────────────────────

def test_ein_gueltiger_token_kommt_durch(client, db):
    _, token = db
    r = client.get("/api/projekte", headers=_kopf(token["Jakob"]))
    assert r.status_code == 200


def test_der_benutzername_bleibt_ungeprueft(client, db):
    _, token = db
    for benutzer in ("", "jakob", "irgendwer"):
        r = client.get("/api/projekte", headers=_kopf(token["Gast"], benutzer))
        assert r.status_code == 200, f"Benutzer {benutzer!r} wurde abgewiesen"


def test_zugang_passwort_kommt_weiter_durch(client):
    """Sonst sperrte eine leere Tabelle auf dem Laufwerk den Betreiber aus."""
    assert client.get("/api/projekte",
                      headers=_kopf(TEST_PASSWORT)).status_code == 200


def test_ein_unbekannter_token_kommt_nicht_durch(client):
    assert client.get("/api/projekte",
                      headers=_kopf("gibtsnicht")).status_code == 401


def test_ein_leeres_passwort_kommt_nicht_durch(client):
    """Weder als leere Zeichenkette noch als fehlender Kopf."""
    assert client.get("/api/projekte", headers=_kopf("")).status_code == 401
    assert client.get("/api/projekte").status_code == 401


def test_ein_entzogener_token_kommt_nicht_mehr_durch_ohne_neustart(client, db):
    """Der Grund für 'kein Zwischenspeicher'. Derselbe laufende Server.

    Ein Speicher, der nur bei unbekanntem Token neu lädt, ließe den entzogenen
    weitergelten — und genau das soll die Änderung verhindern.
    """
    con, token = db
    assert client.get("/api/projekte", headers=_kopf(token["Weg"])).status_code == 200

    zugang.entziehen(con, "Weg")

    assert client.get("/api/projekte", headers=_kopf(token["Weg"])).status_code == 401
    # Die übrigen bleiben unberührt.
    assert client.get("/api/projekte", headers=_kopf(token["Jakob"])).status_code == 200


def test_der_vergleich_benutzt_compare_digest():
    """Ein abbrechender Vergleich verriete über die Dauer, wie weit er kam.

    Geprüft wird der AUFRUF, nicht das Wort. Die erste Fassung dieses Tests
    suchte 'compare_digest' im Quelltext und fand es im Docstring, der es
    erklärt — ein == im Code daneben fiel ihr nicht auf. Gegenprobe gemacht.
    """
    import ast
    import inspect
    import textwrap

    for was in (zugang.Riegel._wer, zugang.nachschlagen):
        baum = ast.parse(textwrap.dedent(inspect.getsource(was)))
        gerufen = {
            k.func.attr for k in ast.walk(baum)
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
        } | {
            k.func.id for k in ast.walk(baum)
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
        }
        assert "compare_digest" in gerufen, f"{was.__name__} ruft es nicht auf"
        # Und kein == auf Bytes daneben: das wäre der Vergleich, den es ersetzt.
        for knoten in ast.walk(baum):
            if isinstance(knoten, ast.Compare) and any(
                isinstance(o, (ast.Eq, ast.NotEq)) for o in knoten.ops
            ):
                quelle = ast.unparse(knoten)
                assert "token" not in quelle and "geheimnis" not in quelle, (
                    f"{was.__name__} vergleicht ein Geheimnis mit ==: {quelle}"
                )


def test_nachgeschlagen_wird_ohne_where_auf_den_wert():
    """Der geheime Wert soll die Middleware nicht verlassen.

    Ein WHERE token = ? schriebe ihn in jede Abfragestatistik und in jedes
    Protokoll, das SQL mitschneidet — und SQLite verglicht ihn abbrechend.
    """
    import ast
    import inspect
    import textwrap

    baum = ast.parse(textwrap.dedent(inspect.getsource(zugang.nachschlagen)))
    funktion = baum.body[0]
    # Den Docstring überspringen: er ERKLÄRT das Verbot und zitiert es dabei.
    # Sonst prüfte der Test seine eigene Begründung und wäre nie grün zu kriegen.
    for anweisung in funktion.body[1:]:
        for knoten in ast.walk(anweisung):
            if isinstance(knoten, ast.Constant) and isinstance(knoten.value, str):
                assert "WHERE token" not in knoten.value


# ── Was nicht im Protokoll steht ──────────────────────────────────────────────

def _mitschrift():
    """Fängt alles ab, was irgendein Logger ausgibt — Stufe DEBUG.

    Der Handler hängt NUR an der Wurzel. An 'ber' und 'ber.neu' daneben gehängt
    fing er dieselbe Meldung dreimal, weil sie durch alle Vorfahren steigt —
    und ein Test, der einmaliges Melden prüft, sah dann drei Zeilen. Die Stufen
    werden trotzdem überall gesenkt: ein Logger filtert seine eigenen Aufrufe,
    bevor sie nach oben kommen.
    """
    puffer = io.StringIO()
    ausgang = logging.StreamHandler(puffer)
    ausgang.setLevel(logging.DEBUG)
    namen = ("", "ber", "ber.neu", "uvicorn", "uvicorn.access", "uvicorn.error")
    alt = [(logging.getLogger(n), logging.getLogger(n).level) for n in namen]
    for lg, _ in alt:
        lg.setLevel(logging.DEBUG)
    wurzel = logging.getLogger("")
    wurzel.addHandler(ausgang)
    return puffer, (ausgang, alt)


def _mitschrift_ende(zustand):
    ausgang, alt = zustand
    logging.getLogger("").removeHandler(ausgang)
    for lg, stufe in alt:
        lg.setLevel(stufe)


def test_der_eingegebene_wert_steht_in_keinem_protokoll(client, db):
    """Weder der gültige Token noch ein falsch geratener."""
    _, token = db
    puffer, zustand = _mitschrift()
    try:
        client.get("/api/projekte", headers=_kopf(token["Jakob"]))
        client.get("/api/projekte", headers=_kopf("falsch-geraten-xyz"))
    finally:
        _mitschrift_ende(zustand)

    text = puffer.getvalue()
    assert token["Jakob"] not in text
    assert "falsch-geraten-xyz" not in text
    assert "Basic " not in text
    assert "Authorization" not in text


def test_der_zugang_wird_einmal_gemeldet_und_nicht_je_anfrage(db):
    """/viz/ lädt rund zwanzig Dateien je Aufruf — zwanzig Zeilen wären Rauschen.

    Ein eigener Riegel und nicht der der App: deren Set lebt so lange wie der
    Prozess und ist von früheren Tests längst gefüllt. Der Test prüfte sonst,
    dass GAR NICHTS gemeldet wird.
    """
    _, token = db

    async def leer(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    eigener = TestClient(zugang.Riegel(leer, geheimnis="egal"))
    puffer, zustand = _mitschrift()
    try:
        for _ in range(5):
            eigener.get("/", headers=_kopf(token["Jakob"]))
    finally:
        _mitschrift_ende(zustand)

    zeilen = [z for z in puffer.getvalue().splitlines() if "Zugang: Jakob" in z]
    assert len(zeilen) == 1, f"{len(zeilen)} Meldungen statt einer"
    assert "verwalter" in zeilen[0]


# ── Die erkannte Person ───────────────────────────────────────────────────────

def test_scope_traegt_die_richtige_zeile(db):
    """Die Fläche, auf der projekt_zugang später steht."""
    con, token = db
    gesehen = []

    async def horcher(scope, receive, send):
        gesehen.append(scope.get("zugang"))
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    riegel = zugang.Riegel(horcher, geheimnis="egal")
    TestClient(riegel).get("/", headers=_kopf(token["Jakob"]))

    wer = gesehen[0]
    assert isinstance(wer, zugang.Person)
    assert wer.name == "Jakob"
    assert wer.rolle == "verwalter"
    assert wer.id == con.execute(
        "SELECT id FROM zugang WHERE name = 'Jakob'").fetchone()[0]


def test_das_gemeinsame_geheimnis_gehoert_niemandem(db):
    """id=None zwingt den, der projekt_zugang verdrahtet, diesen Fall zu bedenken."""
    gesehen = []

    async def horcher(scope, receive, send):
        gesehen.append(scope.get("zugang"))
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    riegel = zugang.Riegel(horcher, geheimnis="das-geheimnis")
    TestClient(riegel).get("/", headers=_kopf("das-geheimnis"))
    assert gesehen[0].id is None


def test_ohne_riegel_gibt_die_abhaengigkeit_nicht_nach(db):
    """Kein Rückfall auf 'irgendwer': das wäre eine stille Umgehung."""
    class OhneScope:
        scope: dict = {}

    with pytest.raises(RuntimeError, match="nicht hinter"):
        zugang.wer_fragt(OhneScope())


# ── Die Reichweite ist unverändert ────────────────────────────────────────────

GESCHUETZT = ["/", "/api/projekte", "/viz/",
              "/data/exporte/pruefstueck/data.json", "/gibtsnicht"]


@pytest.mark.parametrize("pfad", GESCHUETZT)
def test_ohne_anmeldung_kommt_niemand_durch(client, pfad):
    """401 für Programmpfade, 302 zur Anmeldeseite für Seitenaufrufe.

    Seit Oktober 2026 — vorher war alles 401. Die Reichweite ist dieselbe
    geblieben, nur die Art der Abweisung hängt jetzt am Pfad.
    """
    r = client.get(pfad, follow_redirects=False)
    assert r.status_code in (401, 302), f"{pfad} stand offen"
    if pfad.startswith(("/api/", "/data/")):
        assert r.status_code == 401, f"{pfad} wurde umgeleitet statt abgewiesen"


@pytest.mark.parametrize("pfad", GESCHUETZT)
def test_mit_token_kein_401(client, db, pfad):
    """Durchgelassen. '/' kann 503 geben, wenn frontend/build fehlt (CI)."""
    _, token = db
    r = client.get(pfad, headers=_kopf(token["Jakob"]), follow_redirects=False)
    assert r.status_code != 401
    assert r.status_code != 302, "wurde zur Anmeldung geschickt trotz Token"


def test_keine_zusaetzliche_ausnahme(db):
    """Genau die Anmeldeseite und ihr Gegenstück, kein Pfad mehr."""
    assert zugang.OHNE_RIEGEL == ("/anmelden", "/abmelden")


# ── Das Verwaltungsskript ─────────────────────────────────────────────────────

def test_anlegen_geht_ohne_projekt(db):
    """Die Kopplung in ingest/cli.py war der Fehler, nicht das Vorbild."""
    con, _ = db
    kennung, token = zugang.anlegen(con, "Neue Person", "Archiv", "nutzer")

    assert len(token) > 30
    zeile = con.execute(
        "SELECT name, organisation, rolle FROM zugang WHERE id = ?", (kennung,)
    ).fetchone()
    assert tuple(zeile) == ("Neue Person", "Archiv", "nutzer")
    # Kein Projekt ist dabei entstanden.
    assert con.execute(
        "SELECT COUNT(*) FROM projekt WHERE eigentuemer_id = ?", (kennung,)
    ).fetchone()[0] == 0


def test_der_tokenwert_entsteht_an_einer_stelle():
    """Sonst vergäben zwei Befehle verschieden viel Zufall."""
    import ast
    from pathlib import Path

    for datei in ("src/neu/ingest/cli.py", "src/neu/zugang_cli.py"):
        baum = ast.parse(Path(datei).read_text(encoding="utf-8"))
        rufe = [
            k.func.attr for k in ast.walk(baum)
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
        ]
        assert "token_urlsafe" not in rufe, f"{datei} erzeugt selbst einen Token"


def test_ein_zugang_ohne_namen_wird_abgewiesen(db):
    con, _ = db
    with pytest.raises(ValueError, match="Namen"):
        zugang.anlegen(con, "   ")


def test_eine_unbekannte_rolle_wird_abgewiesen(db):
    con, _ = db
    with pytest.raises(Exception):
        zugang.anlegen(con, "X", rolle="chef")


def test_entziehen_geht_ueber_id_und_ueber_namen(db):
    con, _ = db
    kennung, _ = zugang.anlegen(con, "Einer")
    assert zugang.entziehen(con, str(kennung))["name"] == "Einer"

    zugang.anlegen(con, "Zweiter")
    assert zugang.entziehen(con, "Zweiter")["name"] == "Zweiter"


def test_entziehen_verlangt_nicht_den_tokenwert(db):
    """Wer entzieht, hat den Token gerade nicht zur Hand — das ist der Anlass."""
    con, token = db
    with pytest.raises(ValueError, match="Kein Zugang"):
        zugang.entziehen(con, token["Gast"])


def test_ein_eigentuemer_laesst_sich_nicht_einfach_entziehen(db):
    """Sonst bräche der Fremdschlüssel. Die Meldung sagt, was zu tun ist."""
    con, _ = db
    kennung, _ = zugang.anlegen(con, "Besitzer")
    with con:
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES ('p', 'P', ?, '2026-01-01')", (kennung,)
        )
    with pytest.raises(ValueError, match="UPDATE projekt SET eigentuemer_id"):
        zugang.entziehen(con, "Besitzer")
    assert con.execute("SELECT COUNT(*) FROM zugang WHERE id = ?",
                       (kennung,)).fetchone()[0] == 1


def test_die_liste_zeigt_nie_einen_token(db):
    con, token = db
    text = repr(zugang.auflisten(con))
    for wert in token.values():
        assert wert not in text
    assert "token" not in text


def test_die_liste_zaehlt_die_besessenen_projekte(db):
    con, _ = db
    kennung, _ = zugang.anlegen(con, "Mit Projekt")
    with con:
        con.execute(
            "INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
            "VALUES ('p', 'P', ?, '2026-01-01')", (kennung,)
        )
    nach_id = {z["id"]: z for z in zugang.auflisten(con)}
    assert nach_id[kennung]["projekte"] == 1


# ── Der Satz, der ans Verhalten gebunden ist ──────────────────────────────────

def test_der_satz_unter_der_liste_stimmt_noch(db):
    """Die feste Zeile aus --auflisten behauptet etwas über den Code.

    Sie sagt, dass projekt_zugang von keiner Zeile gelesen wird und darum jeder
    Zugang alle Projekte sieht. Solange das stimmt, ist sie richtig; sobald
    jemand die Tabelle verdrahtet, ist sie eine Lüge — und zwar eine stille,
    weil nichts daran scheitert.

    Dieser Test lässt sie nicht still werden: er bricht in dem Augenblick, in
    dem projekt_zugang irgendwo in src/neu/ auftaucht. Wer sie verdrahtet, muss
    hier vorbei und den Satz mitnehmen.

    Beim letzten Abgleich lagen alle zwölf Abweichungen in der Prosa und keine
    im Code. Ein Satz, den ein Test hält, veraltet nicht still.
    """
    import ast
    from pathlib import Path

    fundstellen = []
    for datei in sorted(Path("src/neu").rglob("*.py")):
        baum = ast.parse(datei.read_text(encoding="utf-8"))

        # Docstrings erst einsammeln und dann übergehen: ein Text, der die
        # Tabelle erklärt, verdrahtet sie nicht. Über den Syntaxbaum und nicht
        # über Zeilenanfänge — die Zeile mitten in einem Docstring sieht aus
        # wie Code.
        erklaerend = set()
        for knoten in ast.walk(baum):
            if isinstance(knoten, (ast.Module, ast.FunctionDef,
                                   ast.AsyncFunctionDef, ast.ClassDef)):
                erster = (knoten.body or [None])[0]
                if (isinstance(erster, ast.Expr)
                        and isinstance(erster.value, ast.Constant)
                        and isinstance(erster.value.value, str)):
                    erklaerend.add(id(erster.value))

        # Der Satz selbst nennt die Tabelle — er ist die Aussage über sie und
        # nicht ihr Gebrauch. Sonst schlüge der Test wegen seines eigenen
        # Gegenstands an.
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Assign)
                    and any(isinstance(z, ast.Name) and z.id == "KEINE_PROJEKTRECHTE"
                            for z in knoten.targets)):
                for teil in ast.walk(knoten.value):
                    if isinstance(teil, ast.Constant):
                        erklaerend.add(id(teil))

        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Constant)
                    and isinstance(knoten.value, str)
                    and id(knoten) not in erklaerend
                    and "projekt_zugang" in knoten.value):
                fundstellen.append(
                    f"{datei}:{knoten.lineno}: {knoten.value.strip()[:70]}"
                )

    assert not fundstellen, (
        "projekt_zugang wird jetzt gelesen oder geschrieben:\n  "
        + "\n  ".join(fundstellen)
        + "\n\nDamit stimmt der Satz unter --auflisten nicht mehr. "
          "zugang.KEINE_PROJEKTRECHTE anpassen und diesen Test mit ihm."
    )
    assert "jeder Zugang sieht alle Projekte" in zugang.KEINE_PROJEKTRECHTE
    assert "projekt_zugang" in zugang.KEINE_PROJEKTRECHTE


def test_die_liste_schreibt_den_satz_wirklich_hin(db, capsys):
    """Der Satz nützt nur, wenn er auch erscheint."""
    from src.neu.zugang_cli import main

    assert main(["--auflisten"]) == 0
    assert zugang.KEINE_PROJEKTRECHTE in capsys.readouterr().out


def test_die_lokal_zeile_bleibt_unberuehrt(db):
    """Sie ist der Eigentümer von allem, was über die Fläche entsteht."""
    from src.neu import projekte

    con, _ = db
    kennung = projekte.lokaler_zugang(con)
    zeile = con.execute(
        "SELECT token, name, rolle FROM zugang WHERE id = ?", (kennung,)
    ).fetchone()
    assert zeile["token"] == projekte.LOKALER_TOKEN
    assert zeile["rolle"] == "verwalter"


def test_auch_der_lokale_token_laesst_herein(db):
    """Er steht in der Tabelle, also gilt er — das ist keine Ausnahme, sondern
    die Regel, und es soll auffallen, dass 'lokal' ein schwaches Wort ist."""
    assert zugang.nachschlagen("lokal") is None   # erst anlegen
    con, _ = db
    from src.neu import projekte

    projekte.lokaler_zugang(con)
    wer = zugang.nachschlagen("lokal")
    assert wer is not None and wer.rolle == "verwalter"


def test_ohne_datenbank_gilt_nur_das_gemeinsame_geheimnis(tmp_path, monkeypatch):
    """Ein frisches Laufwerk darf niemanden aussperren."""
    monkeypatch.setenv("NEU_DB", str(tmp_path / "gibtsnicht.db"))
    assert zugang.nachschlagen("irgendwas") is None
    assert zugang.anzahl_token() == 0


def test_eine_kaputte_tabelle_laesst_niemanden_herein(tmp_path, monkeypatch):
    """Ein sqlite3.Error darf nicht zu 'dann eben alle' werden."""
    kaputt = tmp_path / "kaputt.db"
    con = sqlite3.connect(kaputt)
    con.execute("CREATE TABLE zugang (unsinn TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("NEU_DB", str(kaputt))
    assert zugang.nachschlagen("irgendwas") is None
