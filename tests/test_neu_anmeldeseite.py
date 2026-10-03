"""
test_neu_anmeldeseite.py — eine eigene Seite statt des Browserfensters

Das Anmeldefenster gehörte dem Browser: zwei Felder, von denen eines ignoriert
wurde, keine Gestaltung. Jetzt ein Feld auf einer eigenen Seite, und der Riegel
prüft drei Wege — Keks, Basic, gemeinsames Passwort.

Die Bauform des Kekses ist der Kern, und ein Test hält jeden ihrer Teile fest:

  · Er trägt NUR die zugang.id, kein Geheimnis. Also ist er für sich nicht
    gültig, und --entziehen beendet Sitzungen sofort.
  · Er ist signiert. Also lässt sich keine fremde id hineinschreiben.
  · Er läuft ab, der Token nicht. Ein verlorener Browser vergisst von selbst.
"""

import base64
import io
import logging
import time

import pytest
from fastapi.testclient import TestClient

from src.neu import zugang
from src.neu.server import app
from src.neu.server.anmeldung import ziel_pruefen
from tests.conftest import TEST_PASSWORT


def _basic(passwort: str) -> dict:
    roh = f"x:{passwort}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(roh).decode("ascii")}


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Eigene Datenbank mit zwei Zugängen. Nicht die Arbeitsdatenbank."""
    from src.neu.db import anlegen_wenn_noetig, verbindung_schreibend

    monkeypatch.setenv("NEU_DB", str(tmp_path / "anmelden.db"))
    anlegen_wenn_noetig()
    con = verbindung_schreibend()
    token = {}
    for name, rolle in (("Jakob", "verwalter"), ("Weg", "nutzer")):
        _, token[name] = zugang.anlegen(con, name, "Uni", rolle)
    yield con, token
    con.close()


@pytest.fixture
def client(db) -> TestClient:
    """Über https, weil der Keks Secure ist.

    Nicht kosmetisch: httpx schickt einen Secure-Keks über http gar nicht erst
    zurück, und der Test prüfte dann, dass man NICHT angemeldet bleibt. Im
    Betrieb läuft alles über https; lokal gilt localhost dem Browser als
    sicherer Ursprung, dort geht es ebenfalls.
    """
    return TestClient(app, base_url="https://testserver")


def _anmelden(client: TestClient, token: str, weiter: str = "/"):
    return client.post("/anmelden", data={"token": token, "weiter": weiter},
                       follow_redirects=False)


# ── Der gute Weg ──────────────────────────────────────────────────────────────

def test_richtiger_token_setzt_keks_und_leitet_weiter(client, db):
    _, token = db
    r = _anmelden(client, token["Jakob"])

    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert zugang.KEKS in r.cookies


def test_danach_kommt_man_ohne_weitere_anmeldung_durch(client, db):
    """Der eigentliche Zweck: einmal anmelden, dann ohne Kopfzeile arbeiten."""
    _, token = db
    _anmelden(client, token["Jakob"])

    # Der TestClient behält den Keks. Kein Authorization-Kopf dabei.
    r = client.get("/api/projekte", follow_redirects=False)
    assert r.status_code == 200
    assert "authorization" not in {k.lower() for k in r.request.headers}


def test_die_anmeldeseite_ist_ohne_anmeldung_erreichbar(client):
    """Sonst käme niemand zu ihr."""
    r = client.get("/anmelden", follow_redirects=False)
    assert r.status_code == 200
    assert "<form" in r.text
    assert 'name="token"' in r.text


def test_die_seite_hat_genau_ein_eingabefeld_fuer_den_token(client):
    """Kein Benutzernamenfeld — es gibt keinen. Genau das war der Anlass."""
    text = client.get("/anmelden").text
    assert text.count('<input id=') == 1
    assert 'name="user' not in text
    assert 'name="benutzer' not in text


def test_das_ziel_wird_durchgereicht(client, db):
    """Wer auf /projekt/x wollte, landet dort und nicht auf der Startseite."""
    _, token = db
    r = client.get("/viz/", follow_redirects=False)
    assert r.headers["location"] == "/anmelden?weiter=%2Fviz%2F"

    r = _anmelden(client, token["Jakob"], weiter="/viz/")
    assert r.headers["location"] == "/viz/"


# ── Der schlechte Weg ─────────────────────────────────────────────────────────

def test_falscher_token_gibt_die_seite_mit_meldung(client):
    """Kein 401 und damit kein Browserfenster."""
    r = _anmelden(client, "gibtsnicht")

    assert r.status_code == 200
    assert zugang.KEKS not in r.cookies
    assert "gilt nicht" in r.text
    assert "www-authenticate" not in {k.lower() for k in r.headers}


def test_leerer_token_setzt_keinen_keks(client):
    for wert in ("", "   "):
        r = _anmelden(client, wert)
        assert zugang.KEKS not in r.cookies


def test_der_eingegebene_token_steht_nicht_in_der_antwort(client, db):
    """Weder in der Meldung noch in einem Feldwert — sonst stünde er im Verlauf."""
    r = _anmelden(client, "geheim-geraten-12345")
    assert "geheim-geraten-12345" not in r.text


def test_das_gemeinsame_passwort_bekommt_keinen_keks(client):
    """Dahinter steht keine Zeile, also gibt es keine id für den Keks.

    Es bleibt über Basic gültig — nur eine Sitzung lässt sich darauf nicht
    ausstellen. Ein Keks ohne id wäre einer, den kein --entziehen beenden kann.
    """
    r = _anmelden(client, TEST_PASSWORT)
    assert zugang.KEKS not in r.cookies
    assert "gilt nicht" in r.text


# ── Der Keks ──────────────────────────────────────────────────────────────────

def test_ein_gefaelschter_keks_kommt_nicht_durch(client, db):
    con, _ = db
    echte_id = con.execute("SELECT id FROM zugang WHERE name='Jakob'").fetchone()[0]

    # Ohne Signatur, mit falscher Signatur, mit fremder Signatur.
    for wert in (f"{echte_id}.{int(time.time()) + 999}",
                 f"{echte_id}.{int(time.time()) + 999}.00ff",
                 zugang.keks_backen(echte_id, "ein anderes Geheimnis")):
        client.cookies.clear()
        client.cookies.set(zugang.KEKS, wert)
        assert client.get("/api/projekte").status_code == 401, wert[:30]


def test_ein_verfaelschter_keks_kommt_nicht_durch(client, db):
    """Ein Zeichen gedreht — die Signatur fällt."""
    con, token = db
    _anmelden(client, token["Jakob"])
    echt = client.cookies[zugang.KEKS]

    gedreht = echt[:-1] + ("0" if echt[-1] != "0" else "1")
    # Erst leeren: cookies.set legt sonst einen ZWEITEN Keks gleichen Namens an,
    # der echte bleibt daneben stehen, und der Test bestünde, ohne etwas zu
    # prüfen. Genau so ist er beim ersten Lauf durchgefallen.
    client.cookies.clear()
    client.cookies.set(zugang.KEKS, gedreht)
    assert client.get("/api/projekte").status_code == 401


def test_eine_fremde_id_laesst_sich_nicht_hineinschreiben(client, db):
    """Der Grund für die Signatur: sonst wäre '1.<frist>' ein Verwalterzugang."""
    con, token = db
    _anmelden(client, token["Weg"])
    echt = client.cookies[zugang.KEKS]
    _, rest = echt.split(".", 1)

    client.cookies.clear()
    client.cookies.set(zugang.KEKS, f"1.{rest}")
    assert client.get("/api/projekte").status_code == 401


def test_der_keks_einer_entzogenen_id_kommt_nicht_mehr_durch(client, db):
    """OHNE Neustart. Das ist der Grund für diese Bauform.

    Trüge der Keks den Token selbst, wäre er für sich gültig und überlebte
    jedes Entziehen bis zum Ablauf — bis zu dreißig Tage lang.
    """
    con, token = db
    _anmelden(client, token["Weg"])
    assert client.get("/api/projekte").status_code == 200

    zugang.entziehen(con, "Weg")

    assert client.get("/api/projekte").status_code == 401


def test_ein_abgelaufener_keks_kommt_nicht_durch(db):
    con, _ = db
    kennung = con.execute("SELECT id FROM zugang WHERE name='Jakob'").fetchone()[0]
    geheimnis = zugang.keks_geheimnis()

    alt = zugang.keks_backen(kennung, geheimnis, jetzt=time.time() - zugang.KEKS_DAUER - 10)
    assert zugang.keks_lesen(alt, geheimnis) is None

    frisch = zugang.keks_backen(kennung, geheimnis)
    assert zugang.keks_lesen(frisch, geheimnis) == kennung


def test_der_keks_wird_bei_gebrauch_nicht_verlaengert(client, db):
    """Er läuft ab, der Token nicht — das ist der Unterschied und er ist gewollt."""
    _, token = db
    _anmelden(client, token["Jakob"])
    vorher = client.cookies[zugang.KEKS]

    for _ in range(3):
        client.get("/api/projekte")

    assert client.cookies[zugang.KEKS] == vorher, "der Keks wurde erneuert"


def test_der_keks_traegt_kein_geheimnis(client, db):
    """Nur id, Frist, Signatur. Kein Token, kein Name, keine Rolle."""
    _, token = db
    _anmelden(client, token["Jakob"])
    wert = client.cookies[zugang.KEKS]

    assert token["Jakob"] not in wert
    assert "Jakob" not in wert
    assert "verwalter" not in wert
    kennung, frist, signatur = wert.split(".")
    assert kennung.isdigit() and frist.isdigit()
    assert len(signatur) == 64          # sha256 als hex


def test_die_kekseigenschaften(client, db):
    _, token = db
    r = _anmelden(client, token["Jakob"])
    satz = r.headers["set-cookie"].lower()

    assert "httponly" in satz
    assert "secure" in satz
    assert "samesite=lax" in satz
    assert "path=/" in satz
    assert f"max-age={zugang.KEKS_DAUER}" in satz


# ── Abmelden ──────────────────────────────────────────────────────────────────

def test_abmelden_loescht_den_keks(client, db):
    _, token = db
    _anmelden(client, token["Jakob"])
    assert client.get("/api/projekte").status_code == 200

    r = client.get("/abmelden", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/anmelden"
    assert client.get("/api/projekte").status_code == 401


def test_abmelden_geht_auch_ohne_gueltigen_keks(client):
    """Sonst wäre es eine Tür, die nur von innen zugeht."""
    assert client.get("/abmelden", follow_redirects=False).status_code == 303


def test_abmelden_macht_den_token_nicht_ungueltig(client, db):
    """Abgemeldet wird dieser Browser, nicht der Zugang."""
    _, token = db
    _anmelden(client, token["Jakob"])
    client.get("/abmelden")

    assert client.get("/api/projekte",
                      headers=_basic(token["Jakob"])).status_code == 200


# ── Die anderen beiden Wege bleiben ───────────────────────────────────────────

def test_basic_funktioniert_unveraendert(client, db):
    _, token = db
    assert client.get("/api/projekte",
                      headers=_basic(token["Jakob"])).status_code == 200


def test_zugang_passwort_funktioniert_unveraendert(client):
    assert client.get("/api/projekte",
                      headers=_basic(TEST_PASSWORT)).status_code == 200


def test_basic_schlaegt_einen_kaputten_keks(client, db):
    """Wer eine abgelaufene Sitzung hat und Basic mitschickt, kommt durch."""
    _, token = db
    client.cookies.set(zugang.KEKS, "kaputt.123.00ff")
    assert client.get("/api/projekte",
                      headers=_basic(token["Jakob"])).status_code == 200


# ── Das Signaturgeheimnis ─────────────────────────────────────────────────────

def test_das_geheimnis_steht_in_der_datenbank_und_nicht_in_der_umgebung(db):
    """Eine Variable mehr im Dashboard ist eine mehr, die jemand falsch setzt."""
    import os

    con, _ = db
    wert = zugang.keks_geheimnis()
    assert len(wert) > 30
    in_db = con.execute(
        "SELECT wert FROM einstellung WHERE schluessel = ?",
        (zugang.GEHEIMNIS_SCHLUESSEL,),
    ).fetchone()[0]
    assert in_db == wert
    assert "KEKS" not in " ".join(os.environ)


def test_das_geheimnis_entsteht_nur_einmal(db):
    assert zugang.keks_geheimnis() == zugang.keks_geheimnis()


def test_ein_geloeschtes_geheimnis_meldet_alle_ab_aber_entwertet_keinen_token(db):
    """Der Notausgang, falls ein Keks abhanden kommt."""
    con, token = db
    kennung = con.execute("SELECT id FROM zugang WHERE name='Jakob'").fetchone()[0]
    alter_keks = zugang.keks_backen(kennung, zugang.keks_geheimnis())

    with con:
        con.execute("DELETE FROM einstellung WHERE schluessel = ?",
                    (zugang.GEHEIMNIS_SCHLUESSEL,))

    neues = zugang.keks_geheimnis()
    assert zugang.keks_lesen(alter_keks, neues) is None
    # Der Token selbst bleibt gültig.
    assert zugang.nachschlagen(token["Jakob"]) is not None


# ── Die offene Weiterleitung ──────────────────────────────────────────────────

@pytest.mark.parametrize("roh", [
    "https://woanders.example/",     # fremde Adresse
    "//woanders.example/",           # für den Browser vollständig, für startswith('/') ein Pfad
    "/\\woanders.example",           # dasselbe mit Rückstrich
    "http://localhost:8002/x",
    "javascript:alert(1)",
    None,
    "",
    "kein-schraegstrich",
])
def test_fremde_ziele_fuehren_zur_startseite(roh):
    """Sonst wäre /anmelden?weiter=… eine offene Weiterleitung.

    Eine Adresse, die auf unserem Dienst beginnt und auf einem fremden endet —
    genau so etwas verschickt man in einer Mail.
    """
    assert ziel_pruefen(roh) == "/"


@pytest.mark.parametrize("roh", ["/", "/viz/", "/projekt/ber/export", "/viz/?project=x"])
def test_eigene_ziele_bleiben(roh):
    assert ziel_pruefen(roh) == roh


def test_ein_fremdes_ziel_kommt_auch_durch_das_formular_nicht_durch(client, db):
    _, token = db
    r = _anmelden(client, token["Jakob"], weiter="https://woanders.example/")
    assert r.headers["location"] == "/"


# ── Das Protokoll ─────────────────────────────────────────────────────────────

def test_der_eingegebene_token_steht_in_keinem_protokoll(client, db):
    _, token = db
    puffer = io.StringIO()
    ausgang = logging.StreamHandler(puffer)
    ausgang.setLevel(logging.DEBUG)
    wurzel = logging.getLogger("")
    alt = wurzel.level
    wurzel.addHandler(ausgang)
    wurzel.setLevel(logging.DEBUG)
    try:
        _anmelden(client, token["Jakob"])
        _anmelden(client, "falsch-geraten-abc")
        client.get("/api/projekte")
    finally:
        wurzel.removeHandler(ausgang)
        wurzel.setLevel(alt)

    text = puffer.getvalue()
    assert token["Jakob"] not in text
    assert "falsch-geraten-abc" not in text
    assert zugang.keks_geheimnis() not in text


# ── Die Seite selbst ──────────────────────────────────────────────────────────

def test_die_seite_haengt_an_keinem_bauschritt(client):
    """Alles inline: kein <script src>, kein <link href>, keine fremde Adresse.

    Sie wird vor der Anmeldung ausgeliefert und soll von nichts abhängen, was
    erst gebaut oder nachgeladen werden muss.
    """
    text = client.get("/anmelden").text
    assert "<script" not in text.lower()
    assert "<link" not in text.lower()
    assert "http://" not in text
    assert "https://" not in text
    assert "//cdn" not in text


def test_die_seite_liegt_nicht_im_frontend_bau():
    """Sie gehört dem Dienst, nicht SvelteKit — das war die Begründung."""
    from pathlib import Path

    from src.neu.server.anmeldung import SEITE

    assert SEITE.is_file()
    assert "frontend" not in SEITE.parts
    assert not list(Path("frontend/src").rglob("anmelde*"))


def test_die_seite_taucht_nicht_in_der_api_beschreibung_auf(client, db):
    """Sonst stünde sie in api-typen.ts, und das Frontend wüsste von ihr."""
    pfade = client.get("/openapi.json", headers=_basic(TEST_PASSWORT)).json()["paths"]
    assert "/anmelden" not in pfade
    assert "/abmelden" not in pfade


def test_die_seite_wird_nicht_zwischengespeichert(client):
    """Sie trägt ein Formular für ein Geheimnis."""
    assert "no-store" in client.get("/anmelden").headers["cache-control"]
