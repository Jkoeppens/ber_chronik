"""
test_neu_zugang.py — der Riegel, und das Loch im Ordnerpfad

Zwei Löcher werden hier zugehalten, und beide waren erst im Netz gefährlich:

  · Der Dienst stand offen. Jede Anfrage geht jetzt durch HTTP Basic — die
    Fläche, die API, /viz/ und die Exportdateien.
  · POST /api/projekt/{id}/quelle nahm bei quellformat=pressesammlung jeden
    absoluten Pfad und las alles darunter an .md-Dateien ein. Am Schreibtisch
    bequem, hinter einer öffentlichen Adresse eine Leseprimitive für alles, was
    der Prozess lesen darf.

Der zweite Teil prüft nicht 'wird .. abgewiesen', sondern 'liegt das ZIEL unter
der Wurzel'. Ein Symlink führt ohne jedes '..' hinaus.
"""

import base64

import pytest
from fastapi.testclient import TestClient

from src.neu import zugang
from src.neu.server import app
from tests.conftest import TEST_PASSWORT, basic_kopf


@pytest.fixture(scope="module")
def offen() -> TestClient:
    """Ein Client OHNE Anmeldung. Für alles, was 401 bekommen soll."""
    return TestClient(app)


@pytest.fixture(scope="module")
def angemeldet() -> TestClient:
    return TestClient(app, headers=basic_kopf())


# ── Der Start ─────────────────────────────────────────────────────────────────

def test_ohne_passwort_startet_der_server_nicht(monkeypatch):
    """Keine Vorgabe: eine Vorgabe würde behaupten, das darf offen stehen."""
    monkeypatch.delenv("ZUGANG_PASSWORT", raising=False)
    with pytest.raises(zugang.ZugangFehlt) as fehler:
        zugang.passwort()
    # Die Meldung muss die Variable nennen — sonst sucht man im Code danach.
    assert "ZUGANG_PASSWORT" in str(fehler.value)


def test_nur_blanks_gelten_als_nicht_gesetzt(monkeypatch):
    """ZUGANG_PASSWORT=" " in einer .env ist ein Versehen, kein Geheimnis."""
    monkeypatch.setenv("ZUGANG_PASSWORT", "   ")
    with pytest.raises(zugang.ZugangFehlt):
        zugang.passwort()


def test_kein_pfad_ist_ausgenommen():
    """Was hier stünde, stünde offen. Geprüft, damit es nicht unbemerkt wächst.

    Railway fragt nichts über HTTP ab — railway.toml setzt kein
    healthcheckPath —, also gibt es nichts auszunehmen. Wer später eines
    einträgt, muss diesen Test ändern und dabei nachdenken.
    """
    assert zugang.OHNE_RIEGEL == ()


# ── 401 ohne, 200 mit ─────────────────────────────────────────────────────────

# Die vier Flächen, die getrennt eingehängt sind: SvelteKit unter /, die API,
# der viz-Mount und die Exportdateien. Eine Abhängigkeit je Route hätte bei einer
# davon vergessen werden können, deshalb wird jede einzeln geprüft.
GESCHUETZT = [
    "/",
    "/api/projekte",
    "/api/konfiguration",
    "/viz/",
    "/viz/boot.js",
    "/data/exporte/pruefstueck/data.json",
]

# Alles davon außer '/': die SvelteKit-Fläche hängt an frontend/build, und der
# pytest-Lauf der CI baut das Frontend nicht (eigener Job). Ohne Build antwortet
# '/' mit 503 statt 200 — was diesen Test angeht ist das dasselbe, denn die
# Aussage lautet 'der Riegel hat durchgelassen', nicht 'die Seite steht'.
IMMER_DA = [p for p in GESCHUETZT if p != "/"]


@pytest.mark.parametrize("pfad", GESCHUETZT)
def test_ohne_anmeldung_401(offen: TestClient, pfad: str):
    r = offen.get(pfad)
    assert r.status_code == 401, f"{pfad} stand offen"


@pytest.mark.parametrize("pfad", GESCHUETZT)
def test_mit_anmeldung_kein_401(angemeldet: TestClient, pfad: str):
    """Durchgelassen. Was dahinter antwortet, ist eine andere Frage."""
    assert angemeldet.get(pfad).status_code != 401, f"{pfad} wies ab"


@pytest.mark.parametrize("pfad", IMMER_DA)
def test_mit_anmeldung_200(angemeldet: TestClient, pfad: str):
    r = angemeldet.get(pfad)
    assert r.status_code == 200, f"{pfad} gab {r.status_code}"


def test_der_401_fordert_basic_an(offen: TestClient):
    """Ohne WWW-Authenticate fragt der Browser nicht von selbst."""
    r = offen.get("/api/projekte")
    kopf = r.headers["www-authenticate"]
    assert kopf.startswith("Basic ")
    assert 'realm="BER Chronik"' in kopf


def test_der_401_hat_die_eine_fehlergestalt(offen: TestClient):
    """Dieselbe Form wie jeder andere Fehler — die Fläche kennt nur eine."""
    d = offen.get("/api/projekte").json()
    assert set(d) == {"fehler"}
    assert set(d["fehler"]) == {"code", "meldung", "status"}
    assert d["fehler"]["code"] == "zugang_verweigert"
    assert d["fehler"]["status"] == 401


def test_auch_unbekannte_pfade_sind_verriegelt(offen: TestClient):
    """401 vor 404: sonst verrät der Dienst, welche Pfade es gibt."""
    assert offen.get("/gibtsnicht").status_code == 401
    assert offen.get("/api/gibtsnicht").status_code == 401


def test_schreibende_wege_ebenso(offen: TestClient):
    r = offen.post("/api/projekte", json={"titel": "Eingeschmuggelt"})
    assert r.status_code == 401


# ── Was nicht durchkommt ──────────────────────────────────────────────────────

def _kopf(roh: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(roh.encode()).decode()}


def test_falsches_passwort_kommt_nicht_durch(offen: TestClient):
    r = offen.get("/api/projekte", headers=_kopf("wer:falsch"))
    assert r.status_code == 401


def test_der_benutzername_wird_nicht_geprueft(offen: TestClient):
    """Das Geheimnis ist das Passwort. Eine zweite Variable wäre vor allem eine
    zweite Möglichkeit, sich auszusperren."""
    for benutzer in ("", "irgendwer", "admin"):
        r = offen.get("/api/projekte", headers=_kopf(f"{benutzer}:{TEST_PASSWORT}"))
        assert r.status_code == 200, f"Benutzer {benutzer!r} wurde abgewiesen"


def test_ein_passwort_mit_doppelpunkt_bleibt_ganz(monkeypatch):
    """split(':', 1) und nicht rsplit: ein Passwort darf Doppelpunkte enthalten."""
    kopfzeilen = [(b"authorization",
                   b"Basic " + base64.b64encode(b"wer:a:b:c").decode().encode())]
    assert zugang._angebotenes(kopfzeilen) == "a:b:c"


@pytest.mark.parametrize("wert", [
    b"Bearer abc",                    # falsches Verfahren
    b"Basic",                         # ohne Wert
    b"Basic !!!kein-base64!!!",       # nicht dekodierbar
    b"Basic " + base64.b64encode(b"ohnedoppelpunkt"),
    b"",
])
def test_kaputte_koepfe_geben_kein_passwort(wert: bytes):
    """Jeder davon muss None ergeben — nicht eine Ausnahme und nicht Durchlass."""
    assert zugang._angebotenes([(b"authorization", wert)]) is None


# Der Test auf compare_digest steht in test_neu_zugang_tabelle.py. Er hieß hier
# test_der_vergleich_laeuft_in_gleichbleibender_zeit und suchte das Wort im
# Quelltext — wo es auch im Docstring stand, der es erklärt. Ein == daneben fiel
# ihm nicht auf; die Gegenprobe hat das gezeigt. Die neue Fassung prüft den
# AUFRUF über den Syntaxbaum und zusätzlich, dass kein == auf ein Geheimnis
# daneben steht.


# ── Der Ordnerpfad ────────────────────────────────────────────────────────────

def test_ohne_obsidian_wurzel_ist_der_ordnerweg_zu(angemeldet: TestClient,
                                                   tmp_path, monkeypatch):
    """Geschlossen heißt geschlossen — kein Rückfall auf 'dann eben alles'."""
    monkeypatch.setenv("OBSIDIAN_WURZEL", "")
    tresor = tmp_path / "tresor"
    tresor.mkdir()
    (tresor / "a.md").write_text("---\npublished: 2026-01-01\n---\nText", encoding="utf-8")

    r = angemeldet.post("/api/projekt/damaskus/quelle",
                        json={"pfad": str(tresor), "quellformat": "pressesammlung"})
    assert r.status_code == 403
    d = r.json()["fehler"]
    assert d["code"] == "obsidian_wurzel_fehlt"
    # Die Meldung muss die Variable nennen und den anderen Weg.
    assert "OBSIDIAN_WURZEL" in d["meldung"]
    assert "Dropbox" in d["meldung"]


def test_mit_wurzel_geht_ein_ordner_darunter(tmp_path, monkeypatch):
    from src.neu.server.gemeinsam import pfad_in_obsidian

    wurzel = tmp_path / "tresore"
    (wurzel / "presse").mkdir(parents=True)
    monkeypatch.setenv("OBSIDIAN_WURZEL", str(wurzel))

    assert pfad_in_obsidian(str(wurzel / "presse")) == (wurzel / "presse").resolve()
    # Auch relativ zur Wurzel, damit die Fläche nicht den ganzen Pfad braucht.
    assert pfad_in_obsidian("presse") == (wurzel / "presse").resolve()


def test_ein_ordner_darueber_geht_nicht(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from src.neu.server.gemeinsam import pfad_in_obsidian

    wurzel = tmp_path / "tresore"
    wurzel.mkdir()
    daneben = tmp_path / "geheim"
    daneben.mkdir()
    monkeypatch.setenv("OBSIDIAN_WURZEL", str(wurzel))

    with pytest.raises(HTTPException) as fehler:
        pfad_in_obsidian(str(daneben))
    assert fehler.value.status_code == 403
    assert fehler.value.detail[0] == "pfad_ausserhalb_obsidian"


def test_ueber_punktpunkt_mogelt_sich_keiner_hinaus(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from src.neu.server.gemeinsam import pfad_in_obsidian

    wurzel = tmp_path / "tresore"
    wurzel.mkdir()
    (tmp_path / "geheim").mkdir()
    monkeypatch.setenv("OBSIDIAN_WURZEL", str(wurzel))

    for versuch in (
        str(wurzel / ".." / "geheim"),
        str(wurzel / "a" / ".." / ".." / "geheim"),
        "../geheim",
        "../../etc",
    ):
        with pytest.raises(HTTPException) as fehler:
            pfad_in_obsidian(versuch)
        assert fehler.value.status_code == 403, versuch


def test_ein_symlink_hinaus_wird_erkannt(tmp_path, monkeypatch):
    """Der Fall, den eine Prüfung auf '..' nicht sieht.

    Geprüft wird das aufgelöste Ziel, nicht die geschriebene Form: hier steht
    kein '..' und keine absolute Angabe, und trotzdem zeigt der Pfad hinaus.
    """
    from fastapi import HTTPException
    from src.neu.server.gemeinsam import pfad_in_obsidian

    wurzel = tmp_path / "tresore"
    wurzel.mkdir()
    geheim = tmp_path / "geheim"
    geheim.mkdir()
    (wurzel / "harmlos").symlink_to(geheim)
    monkeypatch.setenv("OBSIDIAN_WURZEL", str(wurzel))

    with pytest.raises(HTTPException) as fehler:
        pfad_in_obsidian("harmlos")
    assert fehler.value.detail[0] == "pfad_ausserhalb_obsidian"


def test_ein_praefix_ist_kein_unterverzeichnis(tmp_path, monkeypatch):
    """'/…/tresoreboese' beginnt mit '/…/tresore' und ist doch daneben.

    Der Fall, den startswith durchließ — in pfad_in_rohdaten stand er bis
    September 2026 so.
    """
    from fastapi import HTTPException
    from src.neu.server.gemeinsam import pfad_in_obsidian

    (tmp_path / "tresore").mkdir()
    (tmp_path / "tresoreboese").mkdir()
    monkeypatch.setenv("OBSIDIAN_WURZEL", str(tmp_path / "tresore"))

    with pytest.raises(HTTPException):
        pfad_in_obsidian(str(tmp_path / "tresoreboese"))


def test_dasselbe_gilt_in_rohdaten(tmp_path, monkeypatch):
    """Der Symlink-Weg aus data/raw/ heraus, jetzt ebenfalls zu."""
    from fastapi import HTTPException
    from src.neu.server.gemeinsam import pfad_in_rohdaten

    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "laufwerk"))
    monkeypatch.delenv("NEU_DB", raising=False)
    roh = tmp_path / "laufwerk" / "raw"
    roh.mkdir(parents=True)
    geheim = tmp_path / "geheim"
    geheim.mkdir()
    (geheim / "beute.docx").write_bytes(b"x")
    (roh / "harmlos").symlink_to(geheim)

    with pytest.raises(HTTPException) as fehler:
        pfad_in_rohdaten("harmlos/beute.docx")
    assert fehler.value.detail[0] == "pfad_unzulaessig"


def test_der_dropbox_weg_bleibt_unberuehrt(angemeldet: TestClient, monkeypatch):
    """Ohne OBSIDIAN_WURZEL muss der andere Weg weiter gehen.

    Geprüft an der Route, die der Dropbox-Weg nimmt: sie darf nicht 403
    'obsidian_wurzel_fehlt' antworten. Dass sie ohne verbundenes Konto scheitert,
    ist in Ordnung — sie scheitert dann an Dropbox und nicht am Riegel.
    """
    monkeypatch.setenv("OBSIDIAN_WURZEL", "")
    r = angemeldet.post("/api/projekt/damaskus/quelle/dropbox")
    assert r.status_code != 403 or \
        r.json()["fehler"]["code"] != "obsidian_wurzel_fehlt"


def test_ein_docx_pfad_bleibt_an_rohdaten_gebunden(angemeldet: TestClient):
    """Die zweite Wurzel gilt weiter für alles, was keine Sammlung ist."""
    r = angemeldet.post("/api/projekt/damaskus/quelle",
                        json={"pfad": "/etc/passwd",
                              "quellformat": "literaturexzerpt"})
    assert r.status_code == 422
    assert r.json()["fehler"]["code"] == "pfad_unzulaessig"


def test_die_lage_nennt_die_obsidian_wurzel(monkeypatch):
    """Damit /api/konfiguration und die Startmeldung sie zeigen können."""
    from src.neu import pfade

    monkeypatch.setenv("OBSIDIAN_WURZEL", "")
    assert pfade.lage()["obsidian_wurzel"] == ""
    monkeypatch.setenv("OBSIDIAN_WURZEL", "/tmp")
    assert pfade.lage()["obsidian_wurzel"].endswith("tmp")
