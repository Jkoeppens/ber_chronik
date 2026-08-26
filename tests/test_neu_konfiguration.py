"""
tests/test_neu_konfiguration.py — src/neu/konfiguration.py und die Ollama-Frist

Kein Netz, kein Modell, keine echte .env: jeder Test setzt die Umgebung selbst
und biegt den Pfad der .env auf einen tmp_path um.

Ausführen:
  python3 -m pytest tests/test_neu_konfiguration.py -v
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu import konfiguration  # noqa: E402
from src.neu.anbieter import (  # noqa: E402
    AnbieterFehler,
    llm_funktion,
    ollama_frist,
)


ANBIETER_VARIABLEN = (
    "EMBEDDING_PROVIDER", "LLM_PROVIDER",
    "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
    "ANTHROPIC_MODEL_ANALYZE", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "OLLAMA_BASE_URL",
)


@pytest.fixture
def leere_umgebung(monkeypatch, tmp_path):
    """Keine Anbietervariablen, keine .env."""
    for name in ANBIETER_VARIABLEN:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(konfiguration, "ENV_DATEI", tmp_path / "keine.env")
    return tmp_path


# ── .env laden ────────────────────────────────────────────────────────────────

def test_env_laden_ohne_datei(leere_umgebung):
    assert konfiguration.env_laden(leere_umgebung / "keine.env") is False


def test_env_laden_setzt_was_fehlt(leere_umgebung, monkeypatch):
    datei = leere_umgebung / ".env"
    datei.write_text("EMBEDDING_PROVIDER=local\n", encoding="utf-8")
    assert konfiguration.env_laden(datei) is True
    import os
    assert os.environ["EMBEDDING_PROVIDER"] == "local"


def test_umgebung_schlaegt_datei(leere_umgebung, monkeypatch):
    """override=False: was in der Umgebung steht, gewinnt — sonst bräche Railway."""
    import os
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    datei = leere_umgebung / ".env"
    datei.write_text("EMBEDDING_PROVIDER=local\n", encoding="utf-8")
    konfiguration.env_laden(datei)
    assert os.environ["EMBEDDING_PROVIDER"] == "voyage"


# ── Lage ──────────────────────────────────────────────────────────────────────

def test_ohne_anbieter_ist_nichts_einsatzbereit(leere_umgebung):
    z = konfiguration.lage()
    assert z.env_datei is None
    assert z.embedding.anbieter is None and z.embedding.einsatzbereit is False
    assert "EMBEDDING_PROVIDER" in z.embedding.hinweis
    assert z.llm.anbieter is None and z.llm.einsatzbereit is False
    assert z.schwelle_akteure is None and z.band_akteure is None


def test_local_braucht_keinen_schluessel(leere_umgebung, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    z = konfiguration.lage()
    assert z.embedding.einsatzbereit is True
    assert z.embedding.schluessel_name is None
    assert z.embedding.schluessel_vorhanden is None
    assert z.schwelle_akteure == 0.92
    assert z.band_akteure == (0.79, 0.91)


def test_voyage_ohne_schluessel_ist_nicht_einsatzbereit(leere_umgebung, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    z = konfiguration.lage()
    assert z.embedding.schluessel_name == "VOYAGE_API_KEY"
    assert z.embedding.schluessel_vorhanden is False
    assert z.embedding.einsatzbereit is False
    # Die Schwelle hängt am Modell, nicht an der Einsatzbereitschaft.
    assert z.schwelle_akteure == 0.78
    assert z.band_akteure == (0.65, 0.77)


def test_voyage_mit_schluessel(leere_umgebung, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-geheim")
    z = konfiguration.lage()
    assert z.embedding.einsatzbereit is True
    assert z.embedding.schluessel_vorhanden is True


def test_unbekannter_anbieter_wird_benannt(leere_umgebung, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    z = konfiguration.lage()
    assert z.embedding.bekannt is False
    assert "openai" in z.embedding.hinweis


def test_anthropic_ohne_schluessel(leere_umgebung, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    z = konfiguration.lage()
    assert z.llm.schluessel_name == "ANTHROPIC_API_KEY"
    assert z.llm.einsatzbereit is False
    assert z.ollama_frist_sekunden is None


def test_ollama_meldet_seine_frist(leere_umgebung, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "45")
    z = konfiguration.lage()
    assert z.llm.einsatzbereit is True
    assert z.ollama_frist_sekunden == 45


# ── Protokollzeilen ───────────────────────────────────────────────────────────

def test_protokoll_nennt_kein_geheimnis(leere_umgebung, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("VOYAGE_API_KEY", "pa-streng-geheim-1234")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-streng-geheim-5678")
    text = "\n".join(konfiguration.protokollzeilen())
    assert "pa-streng-geheim-1234" not in text
    assert "sk-ant-streng-geheim-5678" not in text
    assert "voyage" in text and "anthropic" in text


def test_protokoll_sagt_was_fehlt(leere_umgebung):
    text = "\n".join(konfiguration.protokollzeilen())
    assert "EMBEDDING_PROVIDER ist nicht gesetzt" in text
    assert "503" in text        # der Hinweis, dass der Server trotzdem läuft


# ── Ollama-Frist ──────────────────────────────────────────────────────────────

def test_frist_vorgabe(leere_umgebung):
    """Die Vorgabe steht in anbieter.toml, nicht als Konstante im Modul."""
    assert ollama_frist() == 120


@pytest.mark.parametrize("wert,erwartet", [
    ("30", 30), ("30.9", 30), ("", 120), ("viel", 120), ("0", 120), ("-5", 120),
])
def test_frist_aus_der_umgebung(leere_umgebung, monkeypatch, wert, erwartet):
    monkeypatch.setenv("OLLAMA_TIMEOUT", wert)
    assert ollama_frist() == erwartet


def test_stille_wird_als_lesefrist_gesetzt(leere_umgebung, monkeypatch):
    """Die Frist gilt der Lücke zwischen zwei Bruchstücken, nicht der Gesamtdauer."""
    import requests

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "7")
    gesehen = {}

    def wirft(*args, **kwargs):
        gesehen["timeout"] = kwargs["timeout"]
        gesehen["stream"] = kwargs["stream"]
        raise requests.Timeout("zu lang")

    monkeypatch.setattr(requests, "post", wirft)
    frage, modell = llm_funktion()

    with pytest.raises(AnbieterFehler) as exc:
        frage("Was?", "System")
    assert gesehen["timeout"] == (10, 7)      # (Verbinden, Stille)
    assert gesehen["stream"] is True
    assert exc.value.code == "ollama_zeitueberschreitung"
    assert "Ollama" in str(exc.value)
    assert modell in str(exc.value)
    assert "7 s still" in str(exc.value)
    assert "es kam nie ein Zeichen an" in str(exc.value)
    assert "OLLAMA_TIMEOUT" in str(exc.value)


class _Antwort:
    """Attrappe für eine Strom-Antwort von Ollama."""

    def __init__(self, zeilen):
        self._zeilen = zeilen
        self.ok = True

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def raise_for_status(self): pass
    def iter_lines(self, decode_unicode=False): return iter(self._zeilen)


def _strom(monkeypatch, zeilen):
    import requests
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Antwort(zeilen))
    return llm_funktion()


def test_strom_wird_zusammengesetzt(leere_umgebung, monkeypatch):
    import json as _json
    frage, _ = _strom(monkeypatch, [
        _json.dumps({"response": "## Gruppe 1\n"}),
        "",                                        # Leerzeilen werden übergangen
        _json.dumps({"response": "Titel\n"}),
        _json.dumps({"response": "Beschreibung"}),
        _json.dumps({"done": True, "prompt_eval_count": 6100, "eval_count": 420}),
    ])
    antwort, ein, aus = frage("Prompt", "System")
    assert antwort == "## Gruppe 1\nTitel\nBeschreibung"
    # Die Vorlage gab (text, 0, 0) zurück; der Strom nennt die Zahlen.
    assert (ein, aus) == (6100, 420)


def test_fehlerfeld_im_strom_wird_gemeldet(leere_umgebung, monkeypatch):
    import json as _json
    frage, _ = _strom(monkeypatch, [_json.dumps({"error": "model not found"})])
    with pytest.raises(AnbieterFehler) as exc:
        frage("Prompt", "System")
    assert exc.value.code == "ollama_fehler"
    assert "model not found" in str(exc.value)


def test_unlesbare_zeile_wird_gemeldet(leere_umgebung, monkeypatch):
    frage, _ = _strom(monkeypatch, ["kein json"])
    with pytest.raises(AnbieterFehler) as exc:
        frage("Prompt", "System")
    assert exc.value.code == "ollama_antwort_ungueltig"


def test_strom_ohne_text_ist_ein_fehler(leere_umgebung, monkeypatch):
    import json as _json
    frage, _ = _strom(monkeypatch, [_json.dumps({"done": True})])
    with pytest.raises(AnbieterFehler) as exc:
        frage("Prompt", "System")
    assert exc.value.code == "ollama_antwort_leer"


def test_lage_meldet_einen_nicht_laufenden_dienst(leere_umgebung, monkeypatch):
    import requests
    from src.neu.anbieter import ollama_lage

    def wirft(*a, **k):
        raise requests.ConnectionError("kein Anschluss")

    monkeypatch.setattr(requests, "get", wirft)
    lage = ollama_lage("http://localhost:11434")
    assert lage["erreichbar"] is False
    assert "ConnectionError" in lage["fehler"]
    assert lage["modelle"] == [] and lage["geladen"] == []


def test_ollama_nicht_erreichbar(leere_umgebung, monkeypatch):
    import requests

    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    def wirft(*args, **kwargs):
        raise requests.ConnectionError("kein Anschluss")

    monkeypatch.setattr(requests, "post", wirft)
    frage, _ = llm_funktion()

    with pytest.raises(AnbieterFehler) as exc:
        frage("Was?", "System")
    assert exc.value.code == "ollama_nicht_erreichbar"
