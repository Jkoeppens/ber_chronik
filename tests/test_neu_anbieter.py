"""
tests/test_neu_anbieter.py — src/neu/anbieter.py und anbieter.toml

Kein Netz, kein Modell, kein Schlüssel: jeder Test setzt die Umgebung selbst.
Geladen wird nie etwas — geprüft wird, was das Modul über Anbieter *weiß*,
nicht was es damit rechnet.

Ausführen:
  python3 -m pytest tests/test_neu_anbieter.py -v
"""

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.neu import anbieter  # noqa: E402

ANBIETER_VARIABLEN = (
    "EMBEDDING_PROVIDER", "LLM_PROVIDER",
    "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
    "ANTHROPIC_MODEL_ANALYZE", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "OLLAMA_BASE_URL",
    "GLINER_MODEL",
)


@pytest.fixture(autouse=True)
def leere_umgebung(monkeypatch):
    """Keine Anbietervariablen, und die eingecheckte anbieter.toml."""
    for name in ANBIETER_VARIABLEN:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(anbieter, "DATEI", ROOT / "anbieter.toml")
    anbieter.einstellungen(neu_lesen=True)
    yield
    anbieter._einstellungen = None


# ── Die Datei ─────────────────────────────────────────────────────────────────

def test_fehlende_datei_ist_ein_fehler(monkeypatch, tmp_path):
    """Kein eingebauter Ersatz — sonst rechnete eine kaputte Installation
    stillschweigend mit etwas anderem als die vollständige."""
    monkeypatch.setattr(anbieter, "DATEI", tmp_path / "gibtsnicht.toml")
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.einstellungen(neu_lesen=True)
    assert fehler.value.code == "anbieter_datei_fehlt"
    assert "gibtsnicht.toml" in str(fehler.value)


def test_unlesbare_datei_wird_benannt(monkeypatch, tmp_path):
    kaputt = tmp_path / "anbieter.toml"
    kaputt.write_text("[wahl\nembedding =", encoding="utf-8")
    monkeypatch.setattr(anbieter, "DATEI", kaputt)
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.einstellungen(neu_lesen=True)
    assert fehler.value.code == "anbieter_datei_unlesbar"


def test_die_eingecheckte_wahl_ist_leer():
    """Variante A: die Wahl wird je Installation ausdrücklich getroffen.

    Ein falsch gewähltes Modell fällt erst Wochen später auf, an Zahlen, die
    niemand mehr nachrechnet. Ein Lauf, der nicht startet, ist der günstigere
    Fehler — deshalb steht hier nichts, und das ist kein Versäumnis.
    """
    with (ROOT / "anbieter.toml").open("rb") as f:
        datei = tomllib.load(f)
    assert datei["wahl"] == {"embedding": "", "llm": ""}


# ── Die Wahl ──────────────────────────────────────────────────────────────────

def test_ohne_umgebung_bricht_es_ab():
    for aufruf, code in [
        (lambda: anbieter.embedding_modellname("themen"), "embedding_anbieter_fehlt"),
        (lambda: anbieter.llm_modellname(), "llm_anbieter_fehlt"),
    ]:
        with pytest.raises(anbieter.AnbieterFehler) as fehler:
            aufruf()
        assert fehler.value.code == code
        assert "PROVIDER" in str(fehler.value)


def test_unbekannter_anbieter_wird_benannt(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.embedding_modellname("themen")
    assert fehler.value.code == "embedding_anbieter_unbekannt"
    assert "openai" in str(fehler.value)
    assert "local" in str(fehler.value) and "voyage" in str(fehler.value)


def test_die_umgebung_schlaegt_die_datei(monkeypatch, tmp_path):
    """Kein neues Schema: es bleibt bei EMBEDDING_PROVIDER."""
    datei = tmp_path / "anbieter.toml"
    quelle = (ROOT / "anbieter.toml").read_text(encoding="utf-8")
    datei.write_text(quelle.replace('embedding = ""', 'embedding = "local"'),
                     encoding="utf-8")
    monkeypatch.setattr(anbieter, "DATEI", datei)
    anbieter.einstellungen(neu_lesen=True)

    assert anbieter.embedding_modellname("themen") == "BAAI/bge-m3"
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    assert anbieter.embedding_modellname("themen") == "voyage-4"


# ── Modell je Aufgabe ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("anbietername,themen,akteure", [
    ("local", "BAAI/bge-m3", "paraphrase-multilingual-MiniLM-L12-v2"),
    ("voyage", "voyage-4", "voyage-4"),
])
def test_modell_haengt_an_der_aufgabe(monkeypatch, anbietername, themen, akteure):
    """bge-m3 für lange Texte, MiniLM für kurze Namen.

    Die zwei zu verwechseln war lange möglich: die Taxonomiefläche schrieb
    MiniLM an den Kopf, wo bge-m3 rechnete. Seit der Modellname der Schlüssel
    des Vektorspeichers ist, ist das kein Schönheitsfehler mehr.
    """
    monkeypatch.setenv("EMBEDDING_PROVIDER", anbietername)
    assert anbieter.embedding_modellname("themen") == themen
    assert anbieter.embedding_modellname("akteure") == akteure


def test_unbekannte_aufgabe_wird_benannt(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.embedding_modellname("stimmung")
    assert fehler.value.code == "aufgabe_unbekannt"


def test_der_modellname_verlangt_keinen_schluessel(monkeypatch):
    """Unter welchem Schlüssel die Vektoren liegen, ist beantwortbar, ohne
    dass gerechnet werden darf — und ohne ein Modell zu laden."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    assert anbieter.embedding_modellname("themen") == "voyage-4"


# ── Schwellen ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("anbietername,schwelle", [("local", 0.92), ("voyage", 0.78)])
def test_schwelle_haengt_am_modell(monkeypatch, anbietername, schwelle):
    """Mit der MiniLM-Zahl führte ein Voyage-Lauf praktisch nichts zusammen."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", anbietername)
    assert anbieter.embedding_schwelle() == schwelle


def test_gliner_schwelle_kommt_aus_der_datei():
    assert anbieter.gliner_schwelle() == 0.7


def test_der_kern_fuehrt_die_gliner_werte_nicht_mehr():
    """Sie sagen, WOMIT erkannt wird — das ist Anbieterwissen."""
    from src.neu.akteure import kern

    assert not hasattr(kern, "GLINER_MODELL")
    assert not hasattr(kern, "GLINER_SCHWELLE")
    # Was fachlich ist, bleibt: Labels, Abbildung, Stückgröße.
    assert kern.GLINER_MAX_ZEICHEN == 2000
    assert "Person" in kern.LABEL_ZU_TYP


# ── Schlüssel ─────────────────────────────────────────────────────────────────

def test_voyage_ohne_schluessel_bricht_ab(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.embedding_funktion("themen")
    assert fehler.value.code == "voyage_schluessel_fehlt"
    assert "VOYAGE_API_KEY" in str(fehler.value)


def test_anthropic_ohne_schluessel_bricht_ab(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    with pytest.raises(anbieter.AnbieterFehler) as fehler:
        anbieter.llm_funktion()
    assert fehler.value.code == "anthropic_schluessel_fehlt"


def test_local_braucht_keinen_schluessel(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    lage, schwelle = anbieter.embedding_lage()
    assert lage.einsatzbereit is True
    assert lage.schluessel_name is None
    assert lage.schluessel_vorhanden is None
    assert schwelle == 0.92


# ── Was eingestellt ist ───────────────────────────────────────────────────────

def test_lage_meldet_den_fehlenden_schluessel_beim_hochfahren(monkeypatch):
    """'voyage' ohne VOYAGE_API_KEY soll beim Hochfahren auffallen, nicht beim
    ersten Klick — und ohne dass dafür ein Modell geladen wird."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "voyage")
    lage, schwelle = anbieter.embedding_lage()
    assert lage.anbieter == "voyage" and lage.bekannt is True
    assert lage.schluessel_name == "VOYAGE_API_KEY"
    assert lage.schluessel_vorhanden is False
    assert lage.einsatzbereit is False
    assert "VOYAGE_API_KEY" in lage.hinweis
    # Die Schwelle steht trotzdem: welche Zahl gälte, ist eine andere Frage
    # als, ob gerechnet werden darf.
    assert schwelle == 0.78


def test_lage_ohne_wahl(monkeypatch):
    lage, schwelle = anbieter.embedding_lage()
    assert lage.anbieter is None and lage.einsatzbereit is False
    assert "EMBEDDING_PROVIDER" in lage.hinweis
    assert schwelle is None


def test_lage_nennt_beide_embedding_modelle(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    lage, _ = anbieter.embedding_lage()
    assert lage.modell == "BAAI/bge-m3"
    assert lage.modell_akteure == "paraphrase-multilingual-MiniLM-L12-v2"


def test_llm_lage_meldet_die_frist_nur_bei_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    lage, frist = anbieter.llm_lage()
    assert lage.modell == "llama3.2:3b" and frist == 120

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    lage, frist = anbieter.llm_lage()
    assert lage.modell == "claude-haiku-4-5-20251001" and frist is None


def test_modell_ueberschreibbar_unter_bestehendem_namen(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral:7b")
    assert anbieter.llm_modellname() == "mistral:7b"

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL_ANALYZE", "claude-sonnet-4-6")
    assert anbieter.llm_modellname() == "claude-sonnet-4-6"


# ── Preise ────────────────────────────────────────────────────────────────────

def test_kosten_kommen_aus_der_datei():
    assert anbieter.kosten("claude-haiku-4-5-20251001", 1_000_000, 0) == pytest.approx(0.80)
    assert anbieter.kosten("claude-haiku-4-5-20251001", 0, 1_000_000) == pytest.approx(4.00)


def test_unbekanntes_modell_kostet_null():
    """Lokal gerechnet fällt darunter, und das ist richtig."""
    assert anbieter.kosten("llama3.2:3b", 10_000, 10_000) == 0.0


# ── Eine Stelle ───────────────────────────────────────────────────────────────

def test_die_beiden_alten_module_sind_weg():
    assert not (ROOT / "src" / "neu" / "akteure" / "anbieter.py").exists()
    assert not (ROOT / "src" / "neu" / "taxonomie" / "anbieter.py").exists()


def test_ingest_importiert_nicht_mehr_aus_der_taxonomie():
    """Der Dropbox-Ingest hat mit Taxonomie nichts zu tun — er importierte von
    dort nur, weil AnbieterFehler dort wohnte."""
    for datei in (ROOT / "src" / "neu" / "ingest").glob("*.py"):
        text = datei.read_text(encoding="utf-8")
        assert "taxonomie" not in text, f"{datei.name} importiert aus taxonomie"


def test_kein_modellname_steht_noch_einmal_im_code():
    """Modellnamen stehen in anbieter.toml, sonst nirgends.

    Geprüft werden Zeichenketten im Code, nicht Erwähnungen in Kommentaren:
    dass llama3.2:3b '**Gruppe 1**' schreibt, gehört in die Begründung des
    Taxonomiekerns und ist keine zweite Einstellung.
    """
    import ast

    werte = {"BAAI/bge-m3", "paraphrase-multilingual-MiniLM-L12-v2",
             "urchade/gliner_multi", "llama3.2:3b",
             "claude-haiku-4-5-20251001", "http://localhost:11434"}
    treffer: list[str] = []
    for datei in (ROOT / "src" / "neu").rglob("*.py"):
        baum = ast.parse(datei.read_text(encoding="utf-8"))
        # Docstrings sind Erklärung, keine Einstellung: eine Zeichenkette, die
        # für sich allein als Anweisung dasteht, wird nicht verwendet.
        allein = {id(k.value) for k in ast.walk(baum)
                  if isinstance(k, ast.Expr) and isinstance(k.value, ast.Constant)}
        for knoten in ast.walk(baum):
            if (isinstance(knoten, ast.Constant)
                    and isinstance(knoten.value, str)
                    and knoten.value in werte
                    and id(knoten) not in allein):
                treffer.append(
                    f"{datei.relative_to(ROOT)}:{knoten.lineno} {knoten.value!r}"
                )
    assert treffer == [], treffer
