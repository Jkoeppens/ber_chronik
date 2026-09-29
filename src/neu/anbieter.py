"""
anbieter.py — die eine Stelle, die etwas über Anbieter weiß

Welches Modell je Aufgabe, welche Schwelle, welche Frist, welcher Schlüssel,
welcher Preis. Alles davon steht in anbieter.toml; dieses Modul liest sie,
lässt die Umgebung sie überschreiben und gibt fertige Funktionen zurück.

Vorher stand es an zwei Stellen: src/neu/taxonomie/anbieter.py wusste von
bge-m3, Anthropic und Ollama, src/neu/akteure/anbieter.py von MiniLM, Voyage
und GLiNER — und beide von Voyage, mit verschiedenen Schwellen. Wer die
Ausnahme AnbieterFehler brauchte, importierte aus der Taxonomie, auch der
Dropbox-Ingest, der mit Taxonomie nichts zu tun hat.

Zwei Regeln, die geblieben sind:

  1. Der Anbieter bestimmt, WOMIT gerechnet wird, nicht OB. Das Verfahren ist
     dasselbe; nur das Modell wechselt.
  2. Kein stiller Rückfall. Fehlt die Wahl, wird abgebrochen — anders als
     src/generalized/embeddings.get_embedding_provider(), das auf 'local'
     zurückfällt, und llm.get_provider(), das auf 'ollama' zurückfällt. Ein
     Lauf, der versehentlich mit einem anderen Modell rechnet, ist schlimmer
     als ein Lauf, der gar nicht startet: das falsche Modell fällt erst
     Wochen später auf, an Zahlen, die niemand mehr nachrechnen kann.

Die Modell-Umsetzungen selbst kommen aus src/generalized/ und werden nicht
verändert — nur unter Umgehung der zurückfallenden Fabriken instanziiert.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

WURZEL = Path(__file__).resolve().parent.parent.parent
DATEI = WURZEL / "anbieter.toml"

EMBEDDING_ANBIETER = ("local", "voyage")
LLM_ANBIETER = ("anthropic", "ollama")

# Wofür embeddet wird. Die zwei Aufgaben nehmen bei 'local' verschiedene
# Modelle: bge-m3 für lange Texte, MiniLM für kurze Namen. Sie zu verwechseln
# war lange möglich — die Taxonomiefläche schrieb MiniLM an den Kopf, wo
# bge-m3 rechnete.
AUFGABEN = ("themen", "akteure")

# Wofür das Sprachmodell gefragt wird. Dieselbe Achse wie oben, aus demselben
# Grund: llama3.2:3b taugt für Kategorienamen und Kurzfassungen, schreibt im
# Chat aber keine einzige Fußnote — 446 Textstücke, keine eckige Klammer. Ein
# Modell je Anbieter hieß, dass die Quellenangaben lokal tot sind.
#
# Die Aufrufprofile gehen ohnehin auseinander: Taxonomie sind vier Aufrufe je
# Lauf, Zusammenfassungen einer je Akteur (bei nahda-durchlauf 70 mit 85 000
# Eingabe-Token), Chat genau einer — und der einzige, bei dem jemand wartet.
LLM_AUFGABEN = ("taxonomie", "zusammenfassungen", "chat")

# Unter welchem Namen die Umgebung ein Modell überschreibt. Die allgemeine
# Variable je Anbieter ist die bestehende; je Aufgabe kommt der Aufgabenname
# dahinter. OLLAMA_MODEL_CHAT und ANTHROPIC_MODEL_CHAT bekommen damit die
# Wirkung zurück, die sie im alten Server hatten.
_LLM_VARIABLE = {"anthropic": "ANTHROPIC_MODEL_ANALYZE", "ollama": "OLLAMA_MODEL"}
_LLM_PRAEFIX = {"anthropic": "ANTHROPIC_MODEL", "ollama": "OLLAMA_MODEL"}

protokoll = logging.getLogger("ber.neu.anbieter")


class AnbieterFehler(RuntimeError):
    def __init__(self, meldung: str, code: str = "anbieter_fehler"):
        super().__init__(meldung)
        self.code = code


# ── Die Datei ─────────────────────────────────────────────────────────────────

_einstellungen: dict | None = None


def einstellungen(neu_lesen: bool = False) -> dict:
    """anbieter.toml, einmal gelesen und gemerkt.

    Fehlt die Datei, ist das ein Fehler und kein Anlass für eingebaute
    Ersatzwerte: sonst rechnete eine kaputte Installation stillschweigend mit
    etwas anderem als die vollständige.
    """
    global _einstellungen
    if _einstellungen is not None and not neu_lesen:
        return _einstellungen

    if not DATEI.exists():
        raise AnbieterFehler(
            f"{DATEI} fehlt. Ohne sie ist nicht bekannt, mit welchen Modellen "
            "gerechnet wird — die Datei gehört zum Quellbestand wie schema.sql.",
            "anbieter_datei_fehlt",
        )
    try:
        with DATEI.open("rb") as f:
            gelesen = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise AnbieterFehler(
            f"{DATEI} ist nicht lesbar: {exc}", "anbieter_datei_unlesbar"
        ) from exc

    _einstellungen = gelesen
    return gelesen


def _abschnitt(*pfad: str) -> dict:
    """Ein Abschnitt aus der Datei, mit einer Meldung, die den Pfad nennt."""
    stelle: dict = einstellungen()
    gegangen: list[str] = []
    for teil in pfad:
        gegangen.append(teil)
        if not isinstance(stelle, dict) or teil not in stelle:
            raise AnbieterFehler(
                f"In {DATEI.name} fehlt der Abschnitt [{'.'.join(gegangen)}].",
                "anbieter_abschnitt_fehlt",
            )
        stelle = stelle[teil]
    return stelle


def _umgebung(name: str) -> str | None:
    """Eine Umgebungsvariable, leer wie nicht gesetzt behandelt."""
    wert = (os.environ.get(name) or "").strip()
    return wert or None


# ── Die Wahl ──────────────────────────────────────────────────────────────────
# Umgebung schlägt Datei, unter den bestehenden Namen. Kein neues Schema:
# .env und Railway führen EMBEDDING_PROVIDER und LLM_PROVIDER seit jeher.

def _wahl(art: str, name: str | None = None) -> str:
    variable = {"embedding": "EMBEDDING_PROVIDER", "llm": "LLM_PROVIDER"}[art]
    vorrat = {"embedding": EMBEDDING_ANBIETER, "llm": LLM_ANBIETER}[art]

    roh = name or _umgebung(variable) or (_abschnitt("wahl").get(art) or "")
    gewaehlt = roh.strip().lower()

    if not gewaehlt:
        raise AnbieterFehler(
            f"{variable} ist nicht gesetzt. Erlaubt: " + " | ".join(vorrat),
            f"{art}_anbieter_fehlt",
        )
    if gewaehlt not in vorrat:
        raise AnbieterFehler(
            f"Unbekannter {variable} '{gewaehlt}'. Erlaubt: " + " | ".join(vorrat),
            f"{art}_anbieter_unbekannt",
        )
    return gewaehlt


def _schluessel_pruefen(anbieter: str, block: dict) -> None:
    """Bricht ab, wenn der Anbieter einen Schlüssel braucht, der nicht da ist."""
    variable = (block.get("schluessel") or "").strip()
    if variable and not _umgebung(variable):
        raise AnbieterFehler(
            f"{variable} ist nicht gesetzt, gewählt ist aber '{anbieter}'.",
            f"{anbieter}_schluessel_fehlt",
        )


# ── Embedding ─────────────────────────────────────────────────────────────────

def _embedding_block(name: str | None = None) -> tuple[str, dict]:
    anbieter = _wahl("embedding", name)
    return anbieter, _abschnitt("embedding", anbieter)


def embedding_modellname(aufgabe: str, name: str | None = None) -> str:
    """Welches Modell für diese Aufgabe gilt — ohne es zu laden.

    Wer nur wissen will, unter welchem Schlüssel die Vektoren liegen, soll
    dafür kein halbes Gigabyte in den Speicher holen. Der Schlüssel wird auch
    nicht geprüft: die Frage ist beantwortbar, ohne dass gerechnet werden darf.
    """
    if aufgabe not in AUFGABEN:
        raise AnbieterFehler(
            f"Unbekannte Aufgabe '{aufgabe}'. Erlaubt: " + " | ".join(AUFGABEN),
            "aufgabe_unbekannt",
        )
    anbieter, block = _embedding_block(name)
    schluessel = f"modell_{aufgabe}"
    if schluessel not in block:
        raise AnbieterFehler(
            f"In {DATEI.name} fehlt [embedding.{anbieter}].{schluessel}.",
            "anbieter_abschnitt_fehlt",
        )
    return str(block[schluessel])


def embedding_schwelle(name: str | None = None) -> float:
    """Ab welcher Ähnlichkeit zwei Akteursnamen als derselbe gelten.

    Die Schwelle hängt am Modell, nicht am Verfahren: 0,92 gilt für MiniLM,
    0,78 für Voyage-4. Mit der MiniLM-Zahl führte ein Voyage-Lauf praktisch
    nichts mehr zusammen — deshalb kommt sie aus derselben Hand wie das Modell.
    """
    _, block = _embedding_block(name)
    return float(block["schwelle_akteure"])


def embedding_tempo(name: str | None = None) -> float | None:
    """Einheiten je Sekunde beim Einbetten, oder None, wenn nicht gemessen.

    Eine Eigenschaft des Modells, keine des Browsers: die Zahl stand vorher als
    32 in themen/+page.svelte und hätte bei jedem Modellwechsel eine falsche
    Dauer angekündigt, ohne dass es jemandem aufgefallen wäre.
    """
    _, block = _embedding_block(name)
    wert = block.get("einheiten_je_sekunde")
    return float(wert) if wert else None


def embedding_stapel(name: str | None = None) -> int | None:
    """Wie viele Texte höchstens in EINE Anfrage gehen — oder None, wenn egal.

    None für die lokalen Modelle: sie stapeln selbst und kennen keine Grenze je
    Aufruf, nur Arbeitsspeicher. Voyage weist eine zu große Anfrage ab.
    """
    _, block = _embedding_block(name)
    wert = block.get("stapel_grenze")
    return int(wert) if wert else None


def _gestapelt(
    embed: Callable[[list[str]], np.ndarray], grenze: int
) -> Callable[[list[str]], np.ndarray]:
    """Zerlegt eine Anfrage in Stapel und setzt sie in der Reihenfolge zusammen.

    Der Aufrufer merkt nichts davon: hinein gehen n Texte, heraus kommen n
    Zeilen in derselben Reihenfolge. Genau daran hängt alles — der Vektor an
    Platz i muss zum Text an Platz i gehören, und wenn das verrutscht, ist das
    Ergebnis nicht falsch aussehend, sondern still falsch: jeder Akteur bekäme
    die Ähnlichkeit eines anderen, und niemand sähe einen Fehler.

    vstack über aufeinanderfolgende Scheiben hält die Reihenfolge von selbst;
    es gibt keine Sortierung, die danebengehen könnte. Nacheinander und nicht
    nebenläufig: die Anfragen kosten Geld, und eine Begrenzung je Zeit hat
    Voyage auch — ein Fächer aus zehn gleichzeitigen Anfragen liefe dort hinein.

    Dass sich die Werte durch das Zerlegen nicht ändern, liegt an der
    Normalisierung: VoyageProvider teilt jede Zeile durch ihre eigene Länge.
    Eine zeilenweise Rechnung kennt ihre Nachbarn nicht, und ein Stapel von 500
    ergibt darum dieselben Zahlen wie einer von 1000.
    """
    def embed_in_stapeln(texte: list[str]) -> np.ndarray:
        texte = list(texte)
        if not texte:
            # Kein Aufruf über das Netz für nichts. Die Form bleibt zweistufig,
            # damit ein vstack darüber nicht an der Dimensionszahl scheitert.
            return np.empty((0, 0), dtype=np.float32)
        if len(texte) <= grenze:
            return embed(texte)
        teile = [embed(texte[i:i + grenze]) for i in range(0, len(texte), grenze)]
        zusammen = np.vstack(teile)
        # Eine Behauptung über fremden Code, und darum geprüft: käme ein Stapel
        # kürzer zurück als hineingegeben, verschöbe sich ab dort jede Zuordnung.
        if len(zusammen) != len(texte):
            raise AnbieterFehler(
                f"Das Einbettungsmodell gab {len(zusammen)} Vektoren für "
                f"{len(texte)} Texte zurück.",
                "stapel_unvollstaendig",
            )
        return zusammen

    return embed_in_stapeln


def embedding_funktion(
    aufgabe: str, name: str | None = None
) -> tuple[Callable[[list[str]], np.ndarray], str]:
    """Gibt (embed, Modellname) zurück. Bricht ab, wenn etwas fehlt.

    Die eine Stelle für beide Aufgaben: Themen und Akteure holen ihre
    Einbettungsfunktion hier. Was hier gilt — etwa die Stapelgrenze —, gilt
    darum für beide, ohne dass es zweimal dastehen müsste.
    """
    anbieter, block = _embedding_block(name)
    modell = embedding_modellname(aufgabe, name)
    _schluessel_pruefen(anbieter, block)

    if anbieter == "voyage":
        from src.generalized.embeddings import VoyageProvider

        provider = VoyageProvider()
        embed = lambda texte: provider.encode(list(texte))  # noqa: E731
        grenze = embedding_stapel(name)
        return (_gestapelt(embed, grenze) if grenze else embed), modell

    if aufgabe == "akteure":
        from src.generalized.embeddings import MiniLMProvider

        provider = MiniLMProvider()
    else:
        from src.generalized.embeddings import BGEProvider

        # Die Vorlage embeddet mit batch_size=16, BGEProvider mit 32.
        # Rechnerisch identisch, nur andere Stapelgröße.
        provider = BGEProvider()
    return (lambda texte: provider.encode(list(texte))), modell


# ── Erkenner ──────────────────────────────────────────────────────────────────

_gliner_modell = None
_gliner_name: str | None = None


def gliner_schwelle() -> float:
    return float(_abschnitt("gliner")["schwelle"])


def gliner_funktion(
    modell: str | None = None,
) -> tuple[Callable[[str, list[str], float], list[dict]], str, float]:
    """Gibt (vorhersage, Modellname, Schwelle) zurück.

    vorhersage(stueck, labels, schwelle) -> [{"text": …, "label": …}, …].
    Das Modell wird einmal geladen und für alle Aufrufe wiederverwendet.
    """
    global _gliner_modell, _gliner_name

    block = _abschnitt("gliner")
    name = modell or _umgebung("GLINER_MODEL") or str(block["modell"])

    if _gliner_modell is None or _gliner_name != name:
        try:
            from gliner import GLiNER
        except ImportError as exc:
            raise AnbieterFehler(
                "gliner ist nicht installiert: pip install gliner", "gliner_fehlt"
            ) from exc
        _gliner_modell = GLiNER.from_pretrained(name)
        _gliner_name = name

    geladen = _gliner_modell

    def vorhersage(stueck: str, labels: list[str], schwelle: float) -> list[dict]:
        return geladen.predict_entities(stueck, labels, threshold=schwelle)

    return vorhersage, name, float(block["schwelle"])


# ── Sprachmodell: Fristen und Überwachung ─────────────────────────────────────

def ollama_frist() -> int:
    """Erlaubte Stille je Ollama-Aufruf in Sekunden.

    Datei, dann OLLAMA_TIMEOUT. Ein unbrauchbarer Wert (leer, keine Zahl,
    null, negativ) wird still auf den Wert aus der Datei zurückgesetzt —
    hier ist Rückfall richtig, weil es um eine Frist geht und nicht darum,
    womit gerechnet wird.
    """
    vorgabe = int(_abschnitt("llm", "ollama")["stille_sekunden"])
    roh = _umgebung("OLLAMA_TIMEOUT")
    if not roh:
        return vorgabe
    try:
        wert = int(float(roh))
    except ValueError:
        return vorgabe
    return wert if wert > 0 else vorgabe


def ollama_basis() -> str:
    return _umgebung("OLLAMA_BASE_URL") or str(_abschnitt("llm", "ollama")["basis"])


def ollama_lage(basis: str | None = None) -> dict:
    """Antwortet der Dienst, und welches Modell liegt geladen im Speicher?

    Billig und ohne Modellaufruf — gedacht als Blick vor einem langen Lauf,
    damit ein nicht laufender Dienst nicht als 'rechnet noch' erscheint.
    """
    import requests

    adresse = basis or ollama_basis()
    lage: dict = {"basis": adresse, "erreichbar": False, "modelle": [],
                  "geladen": [], "fehler": None}
    try:
        tags = requests.get(f"{adresse}/api/tags", timeout=5)
        tags.raise_for_status()
        lage["erreichbar"] = True
        lage["modelle"] = sorted(m.get("name", "") for m in tags.json().get("models", []))
        ps = requests.get(f"{adresse}/api/ps", timeout=5)
        if ps.ok:
            lage["geladen"] = [
                {"modell": m.get("name"),
                 "kontext": m.get("context_length"),
                 "im_speicher": m.get("size_vram", 0) > 0}
                for m in ps.json().get("models", [])
            ]
    except Exception as exc:
        lage["fehler"] = f"{type(exc).__name__}: {exc}"
    return lage


class _Puls:
    """Meldet im Takt, dass gewartet wird — und worauf.

    Ohne das ist ein Aufruf, der die Prompt-Auswertung durchläuft, von einem
    abgestürzten Dienst nicht zu unterscheiden: in beiden Fällen kommt
    minutenlang nichts. Der Puls trennt die beiden Fälle, weil er sagt, wann
    das letzte Zeichen ankam.
    """

    def __init__(self, was: str, intervall: int):
        self.was = was
        self.intervall = intervall
        self.zeichen = 0
        self.letztes = time.monotonic()
        self._start = time.monotonic()
        self._ende = threading.Event()
        self._faden = threading.Thread(target=self._schlagen, daemon=True)

    def __enter__(self) -> "_Puls":
        self._faden.start()
        return self

    def __exit__(self, *_) -> None:
        self._ende.set()
        protokoll.info(
            "%s: fertig nach %.0f s, %d Zeichen",
            self.was, time.monotonic() - self._start, self.zeichen,
        )

    def empfangen(self, zeichen: int) -> None:
        self.zeichen += zeichen
        self.letztes = time.monotonic()

    def _schlagen(self) -> None:
        while not self._ende.wait(self.intervall):
            gelaufen = time.monotonic() - self._start
            still = time.monotonic() - self.letztes
            if self.zeichen == 0:
                protokoll.info(
                    "%s: %.0f s, noch kein Zeichen — der Prompt wird gelesen",
                    self.was, gelaufen,
                )
            else:
                protokoll.info(
                    "%s: %.0f s, %d Zeichen (%.0f/s), letztes vor %.0f s",
                    self.was, gelaufen, self.zeichen,
                    self.zeichen / max(gelaufen, 1e-9), still,
                )


# ── Sprachmodell ──────────────────────────────────────────────────────────────

def llm_modellname(
    aufgabe: str | None = None,
    name: str | None = None,
    modell: str | None = None,
) -> str:
    """Welches Sprachmodell für diese Aufgabe gilt — ohne Schlüsselprüfung.

    aufgabe=None heißt 'die Vorgabe', nicht 'irgendeine'. Wer keine Aufgabe
    nennt, bekommt modell aus dem Anbieterblock.

    Was gewinnt, von oben nach unten:

      1. ein ausdrücklich übergebenes modell
      2. die Umgebung je Aufgabe        OLLAMA_MODEL_CHAT
      3. der Aufgabeneintrag in der Datei  [llm.ollama].modell_chat
      4. die Umgebung, allgemein        OLLAMA_MODEL
      5. modell in der Datei            [llm.ollama].modell

    Das Genauere schlägt das Allgemeinere, gleich woher es kommt: wer
    modell_chat einträgt, will die Abweichung auch dann, wenn in der Umgebung
    ein OLLAMA_MODEL für alles andere steht. Sonst wäre eine gesetzte
    Umgebungsvariable eine stille Rücknahme der Datei.
    """
    if modell:
        return modell
    anbieter = _wahl("llm", name)
    block = _abschnitt("llm", anbieter)

    if aufgabe is not None:
        if aufgabe not in LLM_AUFGABEN:
            raise AnbieterFehler(
                f"Unbekannte Aufgabe '{aufgabe}'. Erlaubt: " + " | ".join(LLM_AUFGABEN),
                "aufgabe_unbekannt",
            )
        je_aufgabe = _umgebung(f"{_LLM_PRAEFIX[anbieter]}_{aufgabe.upper()}")
        if je_aufgabe:
            return je_aufgabe
        if f"modell_{aufgabe}" in block:
            return str(block[f"modell_{aufgabe}"])

    return _umgebung(_LLM_VARIABLE[anbieter]) or str(block["modell"])


def llm_modelle_je_aufgabe(name: str | None = None) -> dict[str, str]:
    """Was für jede Aufgabe tatsächlich gälte — für die Auskunft.

    Aufgelöst, nicht bloß abgeschrieben: wo kein Aufgabeneintrag steht, steht
    hier die Vorgabe. Die Fläche soll sagen können, womit gerechnet wird, ohne
    die Vorrangregel nachzubauen.
    """
    return {aufgabe: llm_modellname(aufgabe, name) for aufgabe in LLM_AUFGABEN}


def llm_funktion(
    aufgabe: str | None = None,
    name: str | None = None,
    modell: str | None = None,
) -> tuple[Callable[[str, str], tuple[str, int, int]], str]:
    """Gibt (frage_modell, Modellname) zurück.

    frage_modell(prompt, system) -> (antwort, in_tokens, out_tokens).

    aufgabe wählt das Modell (siehe llm_modellname); None nimmt die Vorgabe.

    Der Ollama-Weg läuft im Strom und protokolliert dabei mit (siehe _Puls),
    damit ein langer Aufruf von einem hängenden zu unterscheiden ist. Er meldet
    auch die Tokenzahlen, die die Vorlage als (text, 0, 0) wegwarf.
    """
    anbieter = _wahl("llm", name)
    block = _abschnitt("llm", anbieter)
    _schluessel_pruefen(anbieter, block)
    m = llm_modellname(aufgabe, name, modell)
    antwort_token = int(block["antwort_token"])

    if anbieter == "anthropic":
        import anthropic

        client = anthropic.Anthropic()

        def frage_anthropic(prompt: str, system: str) -> tuple[str, int, int]:
            antwort = client.messages.create(
                model=m, max_tokens=antwort_token, temperature=0,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return (antwort.content[0].text.strip(),
                    antwort.usage.input_tokens, antwort.usage.output_tokens)

        return frage_anthropic, m

    import requests

    basis = ollama_basis()
    frist = ollama_frist()
    puls_takt = int(block["puls_sekunden"])

    def frage_ollama(prompt: str, system: str) -> tuple[str, int, int]:
        """Fragt Ollama im Strom, damit man beim Warten etwas sieht.

        stream=True ist hier keine Bequemlichkeit, sondern die Überwachung: die
        Frist gilt für die Lücke zwischen zwei Bruchstücken. Ein Aufruf, der
        langsam aber stetig liefert, läuft durch; einer, der stehen bleibt,
        fliegt nach `frist` Sekunden Stille heraus — und die Meldung sagt, wie
        weit er gekommen war.

        Ollama liefert erst nach der Prompt-Auswertung das erste Zeichen. Genau
        diese Stille am Anfang hat den ersten Taxonomielauf abgebrochen, obwohl
        das Modell arbeitete.
        """
        was = f"Ollama {m}"
        stuecke: list[str] = []
        in_tokens = out_tokens = 0

        try:
            with requests.post(
                f"{basis}/api/generate",
                json={"model": m, "prompt": prompt, "stream": True, "system": system,
                      "options": {"num_ctx": 8192, "temperature": 0,
                                  "num_predict": antwort_token}},
                timeout=(10, frist),
                stream=True,
            ) as r:
                r.raise_for_status()
                protokoll.info("%s: Anfrage gestellt, %d Zeichen Prompt", was, len(prompt))
                with _Puls(was, puls_takt) as puls:
                    for zeile in r.iter_lines(decode_unicode=True):
                        if not zeile:
                            continue
                        try:
                            teil = json.loads(zeile)
                        except json.JSONDecodeError as exc:
                            raise AnbieterFehler(
                                f"Ollama liefert eine unlesbare Zeile: {zeile[:200]}",
                                "ollama_antwort_ungueltig",
                            ) from exc
                        if teil.get("error"):
                            raise AnbieterFehler(
                                f"Ollama meldet einen Fehler: {teil['error']}",
                                "ollama_fehler",
                            )
                        bruch = teil.get("response") or ""
                        if bruch:
                            stuecke.append(bruch)
                            puls.empfangen(len(bruch))
                        if teil.get("done"):
                            in_tokens = int(teil.get("prompt_eval_count") or 0)
                            out_tokens = int(teil.get("eval_count") or 0)
                            if teil.get("done_reason") == "length":
                                # Abgeschnitten statt zu Ende gedacht — sichtbar
                                # machen, nicht stillschweigend weiterparsen.
                                protokoll.warning(
                                    "%s: bei %d Token abgeschnitten (antwort_token=%d). "
                                    "Die Antwort ist unvollständig.",
                                    was, out_tokens, antwort_token,
                                )
                            break
        except requests.Timeout as exc:
            bisher = "".join(stuecke)
            stand = (f"{len(bisher)} Zeichen waren angekommen"
                     if bisher else "es kam nie ein Zeichen an")
            raise AnbieterFehler(
                f"Ollama ({m} auf {basis}) war {frist} s still — {stand}. "
                "Erlaubte Stille über OLLAMA_TIMEOUT ändern, ein kleineres "
                "Modell wählen, oder mit LLM_PROVIDER=anthropic rechnen.",
                "ollama_zeitueberschreitung",
            ) from exc
        except requests.ConnectionError as exc:
            raise AnbieterFehler(
                f"Ollama ist unter {basis} nicht erreichbar. Läuft der Dienst?",
                "ollama_nicht_erreichbar",
            ) from exc

        antwort = "".join(stuecke).strip()
        if not antwort:
            raise AnbieterFehler(
                f"Ollama ({m}) hat den Aufruf beendet, ohne Text zu liefern.",
                "ollama_antwort_leer",
            )
        # Anders als die Vorlage, die (text, 0, 0) zurückgab: der Strom nennt
        # die Tokenzahlen, und damit wird ein Lauf vergleichbar.
        return antwort, in_tokens, out_tokens

    return frage_ollama, m


def llm_strom_funktion(
    aufgabe: str | None = None,
    name: str | None = None,
    modell: str | None = None,
) -> tuple[Callable[[str, str], Iterator[str]], str]:
    """Gibt (strom, Modellname) zurück. strom(prompt, system) liefert Textstücke.

    Dasselbe wie llm_funktion(), nur stückweise. Zwei Aufgaben, zwei Formen:
    ein Klassifikationslauf will eine fertige Antwort und die Tokenzahlen, eine
    Chatantwort will man beim Entstehen lesen. Eine Funktion für beides hieße,
    dass eine Seite immer wartet.

    Die Stücke sind roher Text, nichts weiter — keine Steuerwörter dazwischen.
    Wer daraus Ereignisse macht, tut das eine Schicht weiter oben.

    Anthropic streamt über messages.stream, Ollama über denselben Weg wie
    llm_funktion(); dort ist der Strom schon da, es wird nur nicht mehr am Ende
    zusammengeklebt. Die Frist gilt in beiden Fällen für die Stille zwischen
    zwei Stücken, nicht für die Gesamtdauer.
    """
    anbieter = _wahl("llm", name)
    block = _abschnitt("llm", anbieter)
    _schluessel_pruefen(anbieter, block)
    m = llm_modellname(aufgabe, name, modell)
    antwort_token = int(block["antwort_token"])

    if anbieter == "anthropic":
        import anthropic

        client = anthropic.Anthropic()

        def strom_anthropic(prompt: str, system: str) -> Iterator[str]:
            with client.messages.stream(
                model=m, max_tokens=antwort_token, temperature=0,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as lauf:
                yield from lauf.text_stream

        return strom_anthropic, m

    import requests

    basis = ollama_basis()
    frist = ollama_frist()
    puls_takt = int(block["puls_sekunden"])

    def strom_ollama(prompt: str, system: str) -> Iterator[str]:
        was = f"Ollama {m} (Strom)"
        gesehen = 0
        try:
            with requests.post(
                f"{basis}/api/generate",
                json={"model": m, "prompt": prompt, "stream": True, "system": system,
                      "options": {"num_ctx": 8192, "temperature": 0,
                                  "num_predict": antwort_token}},
                timeout=(10, frist),
                stream=True,
            ) as r:
                r.raise_for_status()
                protokoll.info("%s: Anfrage gestellt, %d Zeichen Prompt", was, len(prompt))
                with _Puls(was, puls_takt) as puls:
                    for zeile in r.iter_lines(decode_unicode=True):
                        if not zeile:
                            continue
                        try:
                            teil = json.loads(zeile)
                        except json.JSONDecodeError as exc:
                            raise AnbieterFehler(
                                f"Ollama liefert eine unlesbare Zeile: {zeile[:200]}",
                                "ollama_antwort_ungueltig",
                            ) from exc
                        if teil.get("error"):
                            raise AnbieterFehler(
                                f"Ollama meldet einen Fehler: {teil['error']}",
                                "ollama_fehler",
                            )
                        bruch = teil.get("response") or ""
                        if bruch:
                            gesehen += len(bruch)
                            puls.empfangen(len(bruch))
                            yield bruch
                        if teil.get("done"):
                            if teil.get("done_reason") == "length":
                                protokoll.warning(
                                    "%s: bei antwort_token=%d abgeschnitten. "
                                    "Die Antwort ist unvollständig.", was, antwort_token,
                                )
                            break
        except requests.Timeout as exc:
            stand = (f"{gesehen} Zeichen waren angekommen" if gesehen
                     else "es kam nie ein Zeichen an")
            raise AnbieterFehler(
                f"Ollama ({m} auf {basis}) war {frist} s still — {stand}. "
                "Erlaubte Stille über OLLAMA_TIMEOUT ändern, ein kleineres "
                "Modell wählen, oder mit LLM_PROVIDER=anthropic rechnen.",
                "ollama_zeitueberschreitung",
            ) from exc
        except requests.ConnectionError as exc:
            raise AnbieterFehler(
                f"Ollama ist unter {basis} nicht erreichbar. Läuft der Dienst?",
                "ollama_nicht_erreichbar",
            ) from exc

        if gesehen == 0:
            raise AnbieterFehler(
                f"Ollama ({m}) hat den Aufruf beendet, ohne Text zu liefern.",
                "ollama_antwort_leer",
            )

    return strom_ollama, m


def kosten(modell: str, in_tokens: int, out_tokens: int) -> float:
    """Kosten in Dollar, aus [llm.anthropic.preise].

    Für ein Modell ohne Preis null — die Zahl ist dann unbekannt, nicht
    gratis. Lokal gerechnete Läufe fallen darunter, und das ist richtig.
    """
    try:
        preise = _abschnitt("llm", "anthropic", "preise")
    except AnbieterFehler:
        return 0.0
    if modell not in preise:
        return 0.0
    p_in, p_out = preise[modell]
    return in_tokens * p_in / 1_000_000 + out_tokens * p_out / 1_000_000


# ── Was eingestellt ist ───────────────────────────────────────────────────────
# Beantwortet, ohne zu laden, ohne zu rechnen und ohne einen Schlüssel gegen
# den Anbieter zu prüfen: nur Datei und Umgebung. Das darf beim Hochfahren
# keine Sekunde kosten und kein Modell aus dem Netz holen.

@dataclass
class Anbieterlage:
    """Was für einen Anbieter eingestellt ist und was ihm fehlt."""

    anbieter: str | None            # None = nicht gesetzt
    bekannt: bool                   # steht im Wertevorrat
    modell: str | None
    schluessel_name: str | None     # welche Variable gebraucht wird, oder None
    schluessel_vorhanden: bool | None   # None = wird keiner gebraucht
    einsatzbereit: bool
    hinweis: str | None = None      # was fehlt, in einem Satz
    # Beim Embedding sind 'local' zwei Modelle mit zwei Aufgaben: bge-m3 für
    # Themen und Zuordnung, MiniLM für das Zusammenführen von Akteuren. Seit
    # der Modellname der Schlüssel des Vektorspeichers ist
    # (src/neu/vektoren.py), ist die Verwechslung kein Schönheitsfehler mehr.
    # `modell` ist das der Themen; hier steht das andere.
    modell_akteure: str | None = None
    # Aufgabe → Modell, aufgelöst. Beim Sprachmodell die drei aus LLM_AUFGABEN,
    # beim Embedding die zwei aus AUFGABEN. Aufgelöst und nicht abgeschrieben:
    # wo kein Aufgabeneintrag steht, steht hier die Vorgabe, damit niemand die
    # Vorrangregel nachbauen muss, um zu wissen, womit gerechnet wird.
    modelle: dict[str, str] = field(default_factory=dict)


def _fehlt(fehler: AnbieterFehler, anbieter: str | None = None) -> Anbieterlage:
    return Anbieterlage(
        anbieter=anbieter, bekannt=False, modell=None,
        schluessel_name=None, schluessel_vorhanden=None, einsatzbereit=False,
        hinweis=str(fehler),
    )


def embedding_lage() -> tuple[Anbieterlage, float | None]:
    """(Lage, Schwelle fürs Zusammenführen). Die Schwelle hängt am Modell.

    Sie steht auch dann, wenn der Schlüssel fehlt: welche Zahl gälte, ist eine
    andere Frage als, ob gerechnet werden darf.
    """
    roh = _umgebung("EMBEDDING_PROVIDER")
    try:
        anbieter = _wahl("embedding")
    except AnbieterFehler as exc:
        return _fehlt(exc, roh), None

    block = _abschnitt("embedding", anbieter)
    variable = (block.get("schluessel") or "").strip() or None
    da = bool(_umgebung(variable)) if variable else None
    schwelle = float(block["schwelle_akteure"])

    return Anbieterlage(
        anbieter=anbieter,
        bekannt=True,
        modell=str(block["modell_themen"]),
        modell_akteure=str(block["modell_akteure"]),
        modelle={a: str(block[f"modell_{a}"]) for a in AUFGABEN
                 if f"modell_{a}" in block},
        schluessel_name=variable,
        schluessel_vorhanden=da,
        einsatzbereit=da is not False,
        hinweis=None if da is not False else f"{variable} fehlt.",
    ), schwelle


def llm_lage() -> tuple[Anbieterlage, int | None]:
    """(Lage, Ollama-Frist). Die Frist ist None, wenn Ollama nicht gewählt ist."""
    roh = _umgebung("LLM_PROVIDER")
    try:
        anbieter = _wahl("llm")
    except AnbieterFehler as exc:
        return _fehlt(exc, roh), None

    block = _abschnitt("llm", anbieter)
    variable = (block.get("schluessel") or "").strip() or None
    da = bool(_umgebung(variable)) if variable else None

    return Anbieterlage(
        anbieter=anbieter,
        bekannt=True,
        modell=llm_modellname(),
        modelle=llm_modelle_je_aufgabe(),
        schluessel_name=variable,
        schluessel_vorhanden=da,
        einsatzbereit=da is not False,
        hinweis=None if da is not False else f"{variable} fehlt.",
    ), (ollama_frist() if anbieter == "ollama" else None)
