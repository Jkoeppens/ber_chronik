"""
tests/test_neu_server.py — Leseserver src/neu/server.py

Läuft ohne Server: TestClient ruft die App im Prozess auf.

Ausführen:
  python3 -m pytest tests/test_neu_server.py -v

Braucht data/neu.db. Fehlt sie:
  python3 -m src.neu.ingest.cli --projekt damaskus --titel Damaskus --anlegen --pfad "data/raw/Damakus Notizen.docx" --quellformat literaturexzerpt
"""

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu.db import db_pfad          # noqa: E402
from src.neu.server import app          # noqa: E402

pytestmark = pytest.mark.skipif(
    not db_pfad().exists(),
    reason=f"{db_pfad()} fehlt — erst src.neu.ingest.cli laufen lassen",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def fehlergestalt_pruefen(body: dict, status: int) -> dict:
    """Jede Fehlerantwort hat genau diese Gestalt."""
    assert set(body) == {"fehler"}, f"Fremde Schlüssel: {set(body)}"
    fehler = body["fehler"]
    assert set(fehler) == {"code", "meldung", "status"}
    assert fehler["status"] == status
    assert isinstance(fehler["code"], str) and fehler["code"]
    assert isinstance(fehler["meldung"], str) and fehler["meldung"]
    return fehler


# ── GET /api/projekte ─────────────────────────────────────────────────────────

def test_projekte_liefert_damaskus(client: TestClient) -> None:
    r = client.get("/api/projekte")
    assert r.status_code == 200
    body = r.json()

    assert body["anzahl"] == len(body["projekte"])
    ids = [p["id"] for p in body["projekte"]]
    assert "damaskus" in ids

    damaskus = next(p for p in body["projekte"] if p["id"] == "damaskus")
    assert damaskus["titel"] == "Damaskus"
    assert damaskus["oeffentlich"] is False       # 0 → bool, nicht 0
    assert isinstance(damaskus["eigentuemer_id"], int)
    assert "dropbox_token" not in damaskus        # wird nie ausgeliefert


# ── GET /api/projekt/{id} ─────────────────────────────────────────────────────

def test_leere_datenbank_gibt_200_mit_leerer_liste(tmp_path, monkeypatch) -> None:
    """Kein Projekt in der Datenbank ist ein gültiges leeres Ergebnis."""
    leere_db = tmp_path / "leer.db"
    con = sqlite3.connect(leere_db)
    con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    con.close()

    monkeypatch.setenv("NEU_DB", str(leere_db))
    r = TestClient(app).get("/api/projekte")

    assert r.status_code == 200
    assert r.json() == {"anzahl": 0, "projekte": []}


def test_projekt_einzeln(client: TestClient) -> None:
    r = client.get("/api/projekt/damaskus")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "damaskus"
    assert body["titel"] == "Damaskus"
    # Kein fester Wert mehr: angelegt_am entsteht beim Anlegen des Projekts,
    # seit es nicht mehr aus projects.db übertragen wird.
    from datetime import datetime
    datetime.fromisoformat(body["angelegt_am"])


def test_projekt_unbekannt_gibt_404_in_fehlergestalt(client: TestClient) -> None:
    r = client.get("/api/projekt/gibtsnicht")
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "projekt_nicht_gefunden"
    assert "gibtsnicht" in fehler["meldung"]


# ── GET /api/projekt/{id}/einheiten ───────────────────────────────────────────

def test_einheiten_vollzaehlig(client: TestClient) -> None:
    r = client.get("/api/projekt/damaskus/einheiten")
    assert r.status_code == 200
    body = r.json()
    assert body["anzahl"] == 718
    assert len(body["einheiten"]) == 718
    assert body["typ_filter"] is None


def test_einheiten_filter_content(client: TestClient) -> None:
    r = client.get("/api/projekt/damaskus/einheiten", params={"typ": "content"})
    assert r.status_code == 200
    body = r.json()
    assert body["anzahl"] == 672
    assert body["typ_filter"] == "content"
    assert {e["typ"] for e in body["einheiten"]} == {"content"}


def test_einheiten_reihenfolge_folgt_position(client: TestClient) -> None:
    body = client.get("/api/projekt/damaskus/einheiten").json()
    einheiten = body["einheiten"]

    # Nach Quelle gruppiert, darin nach position aufsteigend
    schluessel = [(e["quelle_id"], e["position"]) for e in einheiten]
    assert schluessel == sorted(schluessel)

    # Innerhalb der einen Quelle lückenlos 1..718
    positionen = [e["position"] for e in einheiten]
    assert positionen == list(range(1, 719))


def test_einheiten_reihenfolge_gleich_datenbank(client: TestClient) -> None:
    """Gegenprobe unmittelbar an der Datenbank, nicht nur gegen sich selbst."""
    body = client.get("/api/projekt/damaskus/einheiten").json()

    con = sqlite3.connect(f"file:{db_pfad()}?mode=ro", uri=True)
    try:
        erwartet = con.execute(
            "SELECT e.id FROM einheit e JOIN quelle q ON q.id = e.quelle_id "
            "WHERE q.projekt_id = 'damaskus' ORDER BY e.quelle_id, e.position"
        ).fetchall()
    finally:
        con.close()

    assert [e["id"] for e in body["einheiten"]] == [z[0] for z in erwartet]


def test_einheiten_unbekanntes_projekt_gibt_404(client: TestClient) -> None:
    r = client.get("/api/projekt/gibtsnicht/einheiten")
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "projekt_nicht_gefunden"


def test_leeres_ergebnis_ist_200_mit_leerer_liste(client: TestClient) -> None:
    """damaskus hat keine heading-Einheiten.

    Das Projekt gibt es, der Filter trifft nur nichts — ein gültiges leeres
    Ergebnis, kein fehlender Gegenstand.
    """
    r = client.get("/api/projekt/damaskus/einheiten", params={"typ": "heading"})
    assert r.status_code == 200
    body = r.json()
    assert body["einheiten"] == []
    assert body["anzahl"] == 0
    assert body["projekt_id"] == "damaskus"
    assert body["typ_filter"] == "heading"


def test_ungueltiger_typ_nutzt_dieselbe_fehlergestalt(client: TestClient) -> None:
    """FastAPIs eigenes {'detail': [...]} darf nicht durchschlagen."""
    r = client.get("/api/projekt/damaskus/einheiten", params={"typ": "quatsch"})
    assert r.status_code == 422
    assert "detail" not in r.json()
    fehler = fehlergestalt_pruefen(r.json(), 422)
    assert fehler["code"] == "ungueltiger_parameter"


# ── POST /api/projekt/{id}/quelle ─────────────────────────────────────────────

def test_quelle_pfad_ausbruch_wird_abgewiesen(client: TestClient) -> None:
    """Ein Pfad aus dem Netz darf nicht aus data/raw/ herauszeigen."""
    for pfad in ("../../etc/passwd", "/etc/passwd", "unterordner/../../geheim"):
        r = client.post(
            "/api/projekt/damaskus/quelle",
            json={"pfad": pfad, "quellformat": "literaturexzerpt"},
        )
        assert r.status_code == 422, pfad
        fehler = fehlergestalt_pruefen(r.json(), 422)
        assert fehler["code"] == "pfad_unzulaessig", pfad


def test_quelle_unbekanntes_quellformat(client: TestClient) -> None:
    """buchnotizen ist der alte interne Wert und wird nicht durchgereicht."""
    r = client.post(
        "/api/projekt/damaskus/quelle",
        json={"pfad": "egal.docx", "quellformat": "buchnotizen"},
    )
    assert r.status_code == 422
    assert "detail" not in r.json()
    fehlergestalt_pruefen(r.json(), 422)


def test_quelle_unbekanntes_projekt(client: TestClient) -> None:
    r = client.post(
        "/api/projekt/gibtsnicht/quelle",
        json={"pfad": "Damakus Notizen.docx", "quellformat": "literaturexzerpt"},
    )
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "projekt_nicht_gefunden"


# ── Nur lesend ────────────────────────────────────────────────────────────────

def test_verbindung_ist_schreibgeschuetzt() -> None:
    from src.neu.db import verbindung

    con = verbindung()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("DELETE FROM einheit")
    finally:
        con.close()


def test_projects_db_wird_nie_geoeffnet() -> None:
    """Keine Zeichenkette im Code nennt die alte Datenbank.

    Geprüft werden echte String-Literale, nicht Doktexte und Kommentare —
    dort darf und soll stehen, dass projects.db unberührt bleibt.
    """
    import ast

    for datei in (ROOT / "src" / "neu").glob("*.py"):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        doktexte = {
            id(k.body[0].value)
            for k in ast.walk(baum)
            if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and k.body
            and isinstance(k.body[0], ast.Expr)
            and isinstance(k.body[0].value, ast.Constant)
        }
        for knoten in ast.walk(baum):
            if (
                isinstance(knoten, ast.Constant)
                and isinstance(knoten.value, str)
                and id(knoten) not in doktexte
            ):
                assert "projects.db" not in knoten.value, f"{datei}:{knoten.lineno}"
