"""
tests/test_neu_server.py — Leseserver src/neu/server/

Läuft ohne Server: TestClient ruft die App im Prozess auf.

Ausführen:
  python3 -m pytest tests/test_neu_server.py -v

Braucht data/neu.db. Fehlt sie:
  python3 -m src.neu.ingest.cli --projekt damaskus --titel Damaskus --anlegen --pfad "data/raw/Damakus Notizen.docx" --quellformat literaturexzerpt
"""

import json
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
    """Ein Projekt gibt es nur noch über /kennzahlen.

    GET /api/projekt/{id} ist weggefallen — die Fläche hat es nie gerufen,
    und was es lieferte, steht in /kennzahlen mit drin.
    """
    r = client.get("/api/projekt/damaskus/kennzahlen")
    assert r.status_code == 200
    body = r.json()
    assert body["projekt_id"] == "damaskus"
    assert body["titel"] == "Damaskus"


def test_projekt_unbekannt_gibt_404_in_fehlergestalt(client: TestClient) -> None:
    r = client.get("/api/projekt/gibtsnicht/kennzahlen")
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


# ── GET /api/konfiguration ────────────────────────────────────────────────────

def test_konfiguration_liefert_die_lage(client: TestClient) -> None:
    r = client.get("/api/konfiguration")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "env_datei", "embedding", "llm", "schwelle_akteure", "band_akteure",
        "schwellen_kategorien", "ollama_frist_sekunden",
    }
    for teil in ("embedding", "llm"):
        assert set(body[teil]) == {
            "anbieter", "bekannt", "modell", "modell_akteure", "modelle",
            "schluessel_name", "schluessel_vorhanden", "einsatzbereit", "hinweis",
        }


def test_konfiguration_nennt_je_aufgabe_ein_modell(client: TestClient,
                                                   monkeypatch) -> None:
    """Die Auskunft muss aufgelöst sein, nicht bloß abgeschrieben.

    Wo kein modell_{aufgabe} in anbieter.toml steht, hat hier die Vorgabe zu
    stehen — sonst müsste die Fläche die Vorrangregel nachbauen, um zu sagen,
    womit gerechnet wird.
    """
    from src.neu.anbieter import LLM_AUFGABEN

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "irgendwas")
    monkeypatch.delenv("ANTHROPIC_MODEL_ANALYZE", raising=False)
    for aufgabe in LLM_AUFGABEN:
        monkeypatch.delenv(f"ANTHROPIC_MODEL_{aufgabe.upper()}", raising=False)

    llm = client.get("/api/konfiguration").json()["llm"]
    assert set(llm["modelle"]) == set(LLM_AUFGABEN)
    # Für Anthropic weicht in anbieter.toml nichts ab: alle drei = Vorgabe.
    assert set(llm["modelle"].values()) == {llm["modell"]}


def test_konfiguration_zeigt_das_abweichende_chatmodell(client: TestClient,
                                                        monkeypatch) -> None:
    """Ollama weicht beim Chat ab — genau das soll die Auskunft sichtbar machen."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL_CHAT", raising=False)

    llm = client.get("/api/konfiguration").json()["llm"]
    assert llm["modelle"]["chat"] == "llama3.1:8b"
    assert llm["modelle"]["taxonomie"] == llm["modell"] == "llama3.2:3b"
    assert llm["modelle"]["zusammenfassungen"] == "llama3.2:3b"


def test_umgebung_je_aufgabe_schlaegt_die_datei(client: TestClient,
                                                monkeypatch) -> None:
    """OLLAMA_MODEL_CHAT hat seine Wirkung zurück.

    Im alten Server steuerte die Variable TASK_CHAT; nach dem Anbieter-Umbau
    stand sie wirkungslos in .env herum.
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL_CHAT", "mistral:7b")

    llm = client.get("/api/konfiguration").json()["llm"]
    assert llm["modelle"]["chat"] == "mistral:7b"
    assert llm["modelle"]["taxonomie"] != "mistral:7b"


def test_das_genauere_schlaegt_das_allgemeinere(client: TestClient,
                                                monkeypatch) -> None:
    """Ein gesetztes OLLAMA_MODEL nimmt modell_chat nicht still zurück."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen:4b")
    monkeypatch.delenv("OLLAMA_MODEL_CHAT", raising=False)

    llm = client.get("/api/konfiguration").json()["llm"]
    assert llm["modell"] == "qwen:4b"                    # Vorgabe kommt aus der Umgebung
    assert llm["modelle"]["taxonomie"] == "qwen:4b"
    assert llm["modelle"]["chat"] == "llama3.1:8b"       # die Abweichung bleibt


def test_lokales_embedding_nennt_beide_modelle(client: TestClient, monkeypatch) -> None:
    """'local' sind zwei Modelle mit zwei Aufgaben; modell ist das der Kategorien.

    Diese Stelle nannte lange nur MiniLM, und die Taxonomiefläche schrieb es an
    den Kopf, wo bge-m3 rechnete. Seit der Modellname der Schlüssel des
    Vektorspeichers ist, wäre das eine falsche Auskunft über den Speicher.
    """
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    e = client.get("/api/konfiguration").json()["embedding"]
    assert e["modell"] == "BAAI/bge-m3"
    assert e["modell_akteure"] == "paraphrase-multilingual-MiniLM-L12-v2"


def test_konfiguration_verraet_keine_schluessel(client: TestClient, monkeypatch) -> None:
    """Nur ob ein Schlüssel gesetzt ist — nie sein Wert."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-streng-geheim-1234")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-streng-geheim-5678")

    roh = client.get("/api/konfiguration").text
    assert "pa-streng-geheim-1234" not in roh
    assert "sk-ant-streng-geheim-5678" not in roh
    assert "dropbox_token" not in roh

    body = client.get("/api/konfiguration").json()
    assert body["embedding"]["schluessel_vorhanden"] is True
    assert body["llm"]["schluessel_vorhanden"] is True


def test_konfiguration_schwelle_folgt_dem_anbieter(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    body = client.get("/api/konfiguration").json()
    assert body["schwelle_akteure"] == 0.92
    assert body["band_akteure"] == [0.79, 0.91]

    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    body = client.get("/api/konfiguration").json()
    assert body["schwelle_akteure"] == 0.78
    assert body["band_akteure"] == [0.65, 0.77]


def test_konfiguration_meldet_fehlenden_anbieter(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    body = client.get("/api/konfiguration").json()
    assert body["embedding"]["einsatzbereit"] is False
    assert "EMBEDDING_PROVIDER" in body["embedding"]["hinweis"]


# ── Akteure ───────────────────────────────────────────────────────────────────

def test_akteure_erkennen_unbekanntes_projekt(client: TestClient) -> None:
    r = client.post("/api/projekt/gibtsnicht/akteure/erkennen", json={})
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "projekt_nicht_gefunden"


def test_akteure_erkennen_ohne_anbieter_gibt_503(client: TestClient, monkeypatch) -> None:
    """Fehlt EMBEDDING_PROVIDER, bricht der Lauf ab — kein stiller Rückfall."""
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    r = client.post("/api/projekt/damaskus/akteure/erkennen", json={})
    assert r.status_code == 503
    fehler = fehlergestalt_pruefen(r.json(), 503)
    assert fehler["code"] == "embedding_anbieter_fehlt"


def test_akteure_erkennen_unbekannter_anbieter_gibt_503(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    r = client.post("/api/projekt/damaskus/akteure/erkennen", json={})
    assert r.status_code == 503
    fehler = fehlergestalt_pruefen(r.json(), 503)
    assert fehler["code"] == "embedding_anbieter_unbekannt"


def test_duplikatskandidaten_unbekanntes_projekt(client: TestClient) -> None:
    r = client.get("/api/projekt/gibtsnicht/akteure/duplikatskandidaten")
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "projekt_nicht_gefunden"


def test_duplikatskandidaten_liefert_die_liste(client: TestClient) -> None:
    r = client.get("/api/projekt/damaskus/akteure/duplikatskandidaten")
    assert r.status_code == 200
    body = r.json()
    assert body["projekt_id"] == "damaskus"
    assert body["anzahl"] == len(body["kandidaten"])
    for k in body["kandidaten"]:
        assert k["grund"] in ("alias", "schreibweise", "aehnlichkeit")
        assert k["akteur_a_id"] < k["akteur_b_id"]


def test_akteur_patch_unbekannt(client: TestClient) -> None:
    r = client.patch("/api/akteur/999999", json={"typ": "Person"})
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "akteur_nicht_gefunden"


def test_akteur_patch_unbekannter_typ(client: TestClient) -> None:
    """Werk steht nicht im Wertevorrat — die Validierung fängt es ab."""
    r = client.patch("/api/akteur/1", json={"typ": "Werk"})
    assert r.status_code == 422
    assert "detail" not in r.json()
    fehlergestalt_pruefen(r.json(), 422)


def test_verschmelzen_braucht_zwei_ids(client: TestClient) -> None:
    r = client.post("/api/akteure/verschmelzen", json={"ids": [1], "behalten_id": 1})
    assert r.status_code == 422
    fehlergestalt_pruefen(r.json(), 422)


def test_verschmelzen_unbekannter_akteur(client: TestClient) -> None:
    r = client.post(
        "/api/akteure/verschmelzen",
        json={"ids": [999998, 999999], "behalten_id": 999998},
    )
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "akteur_nicht_gefunden"


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


# ── PUT /api/projekt/{id}/kategorien ──────────────────────────────────────────

def _eigene_db(tmp_path, monkeypatch) -> tuple[TestClient, sqlite3.Connection]:
    """Eine frische Datenbank mit einem Projekt und zwei Kategorien.

    Nicht data/neu.db: dieser Test schreibt, und die echte Datenbank ist die
    Arbeitsgrundlage des Historikers.
    """
    pfad = tmp_path / "put.db"
    con = sqlite3.connect(pfad)
    con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    with con:
        con.execute("INSERT INTO zugang (token, angelegt_am, rolle) "
                    "VALUES ('t','2026-01-01','nutzer')")
        con.execute("INSERT INTO projekt (id, titel, eigentuemer_id, angelegt_am) "
                    "VALUES ('p','P',1,'2026-01-01')")
        con.execute("INSERT INTO quelle (id, projekt_id, quellformat, eingelesen_am) "
                    "VALUES ('q','p','literaturexzerpt','2026-01-01')")
        con.execute("INSERT INTO einheit (quelle_id, position, typ, text) "
                    "VALUES ('q', 1, 'content', 'Ein Text mit genug Zeichen darin.')")
        for name in ("Eins", "Zwei"):
            con.execute("INSERT INTO kategorie (projekt_id, name, beschreibung, "
                        "schlagworte, herkunft) VALUES ('p',?,'','','vorschlag')", (name,))
    monkeypatch.setenv("NEU_DB", str(pfad))
    return TestClient(app), con


def test_leere_liste_haengt_keinen_lauf_an(tmp_path, monkeypatch) -> None:
    """Alle Kategorien entfernen ist ein gültiger Sollzustand.

    Vorher scheiterte hier ein Klassifikationslauf mit 'keine_taxonomie',
    obwohl das Löschen gelungen war — die Fläche zeigte eine Fehlermeldung für
    eine Handlung, die geklappt hatte.
    """
    client, con = _eigene_db(tmp_path, monkeypatch)
    r = client.put("/api/projekt/p/kategorien", json={"kategorien": []})

    assert r.status_code == 202
    assert r.json() == {"projekt_id": "p", "anzahl": 0, "angelegt": 0,
                        "geaendert": 0, "geloescht": 2, "lauf_id": None}
    assert con.execute("SELECT COUNT(*) FROM kategorie").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM lauf").fetchone()[0] == 0
    con.close()


def test_nichtleere_liste_haengt_einen_lauf_an(tmp_path, monkeypatch) -> None:
    client, con = _eigene_db(tmp_path, monkeypatch)
    kats = [{"id": None, "name": "Neu", "beschreibung": "", "schlagworte": []}]
    r = client.put("/api/projekt/p/kategorien", json={"kategorien": kats})

    assert r.status_code == 202
    body = r.json()
    assert body["anzahl"] == 1 and body["angelegt"] == 1 and body["geloescht"] == 2
    assert isinstance(body["lauf_id"], int)
    con.close()


# ── Unbekannte Pfade unter /api/ ──────────────────────────────────────────────
# Der Ausweich-Mount auf '/' liefert die Svelte-Seite für jede Adresse, die
# keine Route getroffen hat — das ist für /projekt/damaskus/themen richtig und
# für /api/gibtsnicht falsch: die Fläche bekam dort 200 mit HTML und meldete
# "Unexpected token '<'" statt eines Fehlers, den man lesen kann.

@pytest.mark.parametrize("pfad", [
    "/api/gibtsnicht",
    "/api/projekt/damaskus/quatsch",
    "/api/akteur/999999/tut-nichts",
    "/api/",
])
def test_unbekannter_api_pfad_gibt_404_in_fehlergestalt(client: TestClient, pfad: str) -> None:
    r = client.get(pfad)
    assert r.status_code == 404, f"{pfad} gab {r.status_code}"
    assert r.headers["content-type"].startswith("application/json")
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "endpoint_nicht_gefunden"


@pytest.mark.parametrize("methode", ["get", "post", "put", "patch", "delete"])
def test_unbekannter_api_pfad_auch_bei_schreibenden_methoden(
    client: TestClient, methode: str
) -> None:
    """Nicht nur GET: ein POST auf einen Tippfehler darf keine HTML-Seite sein."""
    r = getattr(client, methode)("/api/gibtsnicht")
    assert r.status_code == 404
    assert r.json()["fehler"]["code"] == "endpoint_nicht_gefunden"


def test_bekannter_api_pfad_bleibt_unberuehrt(client: TestClient) -> None:
    """Der Auffangpfad steht hinter den Routen, nicht vor ihnen."""
    r = client.get("/api/projekte")
    assert r.status_code == 200
    assert "projekte" in r.json()


def test_unbekannter_pfad_ausserhalb_api_bleibt_die_svelte_seite(client: TestClient) -> None:
    """Adressen ohne /api/ gehören der Fläche: sie löst sie selbst auf."""
    r = client.get("/gibtsnichtmal")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


# ── Zusammenfassungen ─────────────────────────────────────────────────────────

def test_zusammenfassen_prueft_das_projekt(client: TestClient) -> None:
    r = client.post("/api/projekt/gibtsnicht/akteure/zusammenfassen", json={})
    assert r.status_code == 404
    assert fehlergestalt_pruefen(r.json(), 404)["code"] == "projekt_nicht_gefunden"


def test_zusammenfassen_ohne_sprachmodell_gibt_503(
    client: TestClient, monkeypatch
) -> None:
    """503 an der Stelle des Klicks, nicht als gescheiterter Lauf Minuten später."""
    monkeypatch.setenv("LLM_PROVIDER", "")
    r = client.post("/api/projekt/damaskus/akteure/zusammenfassen", json={})
    assert r.status_code == 503
    fehler = fehlergestalt_pruefen(r.json(), 503)
    assert fehler["code"] == "llm_anbieter_fehlt"


def test_akteurliste_nennt_den_zusammenfassungsstand(client: TestClient) -> None:
    r = client.get("/api/projekt/damaskus/akteure")
    assert r.status_code == 200
    body = r.json()
    for feld in ("anzahl_kandidaten", "anzahl_mit_zusammenfassung",
                 "anzahl_offen", "mindest_nennungen"):
        assert feld in body, feld
    assert body["anzahl_offen"] == (
        body["anzahl_kandidaten"] - body["anzahl_mit_zusammenfassung"]
    )
    assert "zusammenfassung" in body["akteure"][0]


# ── GET /data/exporte/{id}/{datei} ────────────────────────────────────────────
# Eigene Wurzel, nicht data/projects/{id}/exploration/. Dort schreibt der alte
# Wizard, und ber, nahda und osmanisch stehen in beiden Datenbanken.

def test_exportwurzel_liegt_neben_dem_alten_baum() -> None:
    from src.neu.projekte import export_verzeichnis

    pfad = export_verzeichnis("ber")
    assert pfad == ROOT / "data" / "exporte" / "ber"
    assert "projects" not in pfad.parts


def test_keine_route_fuehrt_mehr_nach_exploration() -> None:
    """Die alte Adresse gehört dem alten System — der neue Server kennt sie nicht."""
    pfade = [getattr(r, "path", "") for r in app.routes]
    assert not [p for p in pfade if "exploration" in p]
    assert "/data/exporte/{projekt_id}/{datei}" in pfade


def test_exportdatei_ausserhalb_der_fuenf_gibt_404(client: TestClient) -> None:
    r = client.get("/data/exporte/ber/segments.json")
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "datei_nicht_ausgeliefert"


def test_exportdatei_ohne_export_gibt_404(client: TestClient) -> None:
    r = client.get("/data/exporte/gibtsnichtundwirdesnie/data.json")
    assert r.status_code == 404
    fehler = fehlergestalt_pruefen(r.json(), 404)
    assert fehler["code"] == "exportdatei_fehlt"


def test_exportdatei_liefert_die_datei(client: TestClient, tmp_path, monkeypatch) -> None:
    from src.neu.server import export as export_router

    ziel = tmp_path / "probe"
    ziel.mkdir()
    (ziel / "data.json").write_text('{"count": 1}', encoding="utf-8")
    monkeypatch.setattr(export_router, "export_verzeichnis", lambda _: ziel)

    r = client.get("/data/exporte/probe/data.json")
    assert r.status_code == 200
    assert r.json() == {"count": 1}


@pytest.mark.parametrize("kennung", ["%2E%2E", "..%2E", "..;", "BER", "ber.", "-ber"])
def test_exportdatei_bleibt_unter_der_wurzel(client: TestClient, kennung: str) -> None:
    """Was keine Kennung ist, kommt nicht durch.

    '%2E%2E' erreicht die Route als '..' — Starlette entschlüsselt erst nach der
    Wegfindung, und '..' hat keinen Schrägstrich, den Path(...).name abschneiden
    könnte. Der Pfad wäre data/exporte/../data.json gewesen.
    """
    r = client.get(f"/data/exporte/{kennung}/data.json")
    assert r.status_code == 404
    assert fehlergestalt_pruefen(r.json(), 404)["code"] == "kennung_ungueltig"


def test_jede_kennung_in_neu_db_kommt_durch_den_riegel() -> None:
    """Der Riegel darf kein vorhandenes Projekt aussperren."""
    from src.neu.db import verbindung
    from src.neu.server.export import KENNUNG

    con = verbindung()
    try:
        ids = [z[0] for z in con.execute("SELECT id FROM projekt")]
    finally:
        con.close()
    assert ids
    assert [i for i in ids if not KENNUNG.fullmatch(i)] == []


# ── POST /api/projekt/{id}/chat ───────────────────────────────────────────────
# Der einzige Endpunkt, der streamt. Geprüft wird die Gestalt des Stroms, nicht
# die Antwort — das Modell bleibt hier draußen.

def test_chat_unbekanntes_projekt(client: TestClient) -> None:
    r = client.post("/api/projekt/gibtsnicht/chat", json={"frage": "Was war 2012?"})
    assert r.status_code == 404
    assert fehlergestalt_pruefen(r.json(), 404)["code"] == "projekt_nicht_gefunden"


def test_chat_leere_frage_wird_abgewiesen(client: TestClient) -> None:
    """Vor dem Strom, also mit Status — danach ginge das nicht mehr."""
    r = client.post("/api/projekt/damaskus/chat", json={"frage": ""})
    assert r.status_code == 422
    assert fehlergestalt_pruefen(r.json(), 422)["code"] == "ungueltiger_parameter"


def test_chat_liefert_benannte_ereignisse(client: TestClient, monkeypatch) -> None:
    from src.neu.chat.dienst import Fertig, Stueck
    from src.neu.server import chat as chat_router

    monkeypatch.setattr(chat_router, "antworten", lambda *_a, **_k: iter([
        Stueck("Erst "), Stueck("dann."),
        Fertig(quellen=["main-e1"], stichwoerter=["2012"], absaetze=3,
               wege=["stichwoerter"], modell="attrappe"),
    ]))
    r = client.post("/api/projekt/damaskus/chat", json={"frage": "Was war 2012?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    zeilen = [z for z in r.text.split("\n") if z]
    assert zeilen == [
        "event: stueck", 'data: {"text": "Erst "}',
        "event: stueck", 'data: {"text": "dann."}',
        "event: fertig",
        'data: {"quellen": ["main-e1"], "stichwoerter": ["2012"], "absaetze": 3, '
        '"wege": ["stichwoerter"], "modell": "attrappe"}',
    ]


def test_kein_steuerwort_steht_je_im_text(client: TestClient, monkeypatch) -> None:
    """Der Fehler des alten Wegs, hier festgenagelt.

    Dort standen __done__ und __error__ im selben Strom wie der Text. Ein Absatz,
    der so anfing, wurde als Steuerwort gelesen. Hier trägt die event-Zeile die
    Art, und ein Text, der wie ein Steuerwort aussieht, bleibt Text — samt
    Zeilenumbrüchen, die json.dumps schützt.
    """
    from src.neu.chat.dienst import Stueck
    from src.neu.server import chat as chat_router

    boesartig = "__done__\nevent: fertig\ndata: {}\n\n__error__"
    monkeypatch.setattr(chat_router, "antworten",
                        lambda *_a, **_k: iter([Stueck(boesartig)]))
    r = client.post("/api/projekt/damaskus/chat", json={"frage": "Test?"})

    zeilen = [z for z in r.text.split("\n") if z]
    assert len(zeilen) == 2, zeilen          # genau ein Ereignis, nicht drei
    assert zeilen[0] == "event: stueck"
    assert json.loads(zeilen[1][6:])["text"] == boesartig


def test_chat_abbruch_ist_ein_ereignis_und_kein_status(client: TestClient,
                                                       monkeypatch) -> None:
    """Ab dem ersten Stück ist die Antwort 200 — ein Fehler muss in den Strom."""
    from src.neu.chat.dienst import Abbruch, Stueck
    from src.neu.server import chat as chat_router

    monkeypatch.setattr(chat_router, "antworten", lambda *_a, **_k: iter([
        Stueck("Der Anfang"),
        Abbruch("ollama_zeitueberschreitung", "war 120 s still"),
    ]))
    r = client.post("/api/projekt/damaskus/chat", json={"frage": "Test?"})
    assert r.status_code == 200
    assert "event: abbruch" in r.text
    assert json.loads(r.text.split("event: abbruch\ndata: ")[1].split("\n")[0]) == {
        "code": "ollama_zeitueberschreitung", "meldung": "war 120 s still"}
