"""
anbieter.py — Embedding und Sprachmodell auswählen

Der Anbieter bestimmt, WOMIT gerechnet wird, nicht OB gerechnet wird. Das
Verfahren ist in beiden Fällen dasselbe; nur das Modell wechselt.

Fehlt eine Angabe, wird abgebrochen — kein stiller Rückfall. Das ist der
Unterschied zu src/generalized/embeddings.get_embedding_provider(), das bei
fehlendem EMBEDDING_PROVIDER auf 'local' zurückfällt, und zu llm.get_provider(),
das außerhalb von Railway auf 'ollama' zurückfällt. Beide Rückfälle sind hier
nicht gewollt: ein Lauf, der versehentlich mit einem anderen Modell rechnet,
ist schlimmer als ein Lauf, der gar nicht startet.

Die Modell-Umsetzungen selbst kommen aus src/generalized/ und werden nicht
verändert — nur unter Umgehung der zurückfallenden Fabriken instanziiert.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable

import numpy as np

EMBEDDING_ANBIETER = ("local", "voyage")
LLM_ANBIETER = ("anthropic", "ollama")

# Preise je Million Token, wie in der Vorlage hinterlegt
ANTHROPIC_PREISE = {
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
}
MODELL_ANTHROPIC = "claude-haiku-4-5-20251001"
MODELL_OLLAMA = "llama3.2:3b"
OLLAMA_BASIS = "http://localhost:11434"

# Frist je Ollama-Aufruf. Sie zählt die **Stille**, nicht die Gesamtdauer: ein
# Aufruf darf lange rechnen, solange er dabei Zeichen liefert. Erst wenn so
# lange nichts kommt, gilt er als hängen geblieben.
#
# Die Vorlage stand auf 300 Sekunden Gesamtdauer — lang genug, dass ein
# hängender Aufruf wie ein arbeitender aussieht. Eine feste Gesamtfrist ist
# aber auch das falsche Maß: sie bricht einen Aufruf ab, der ordentlich
# arbeitet, nur langsam. Genau das ist beim ersten Taxonomielauf passiert.
OLLAMA_STILLE = 120

# Wie oft der Puls schlägt, solange auf ein Modell gewartet wird.
PULS_SEKUNDEN = 10

# Obergrenze für die Antwortlänge, in Token.
#
# Der Anthropic-Weg hat sie seit jeher (max_tokens=2048), der Ollama-Weg nicht —
# weder hier noch in der Vorlage (src/generalized/llm.py:151 setzt nur num_ctx).
# Ohne Deckel läuft ein kleines Modell in eine Endlosausgabe: beim ersten
# Taxonomielauf über nahda lieferte llama3.2:3b in Runde 1 ordentliche 2 277
# Zeichen und in Runde 2 nach über sieben Minuten immer noch stetig Text,
# 22 000 Zeichen und kein Ende. Das ist kein Hänger, sondern ein Weglaufen —
# und ohne Grenze hätte kein Zeitmaß es je gestoppt.
ANTWORT_TOKEN = 2048


def ollama_frist() -> int:
    """Erlaubte Stille je Ollama-Aufruf in Sekunden, aus OLLAMA_TIMEOUT."""
    roh = (os.environ.get("OLLAMA_TIMEOUT") or "").strip()
    if not roh:
        return OLLAMA_STILLE
    try:
        wert = int(float(roh))
    except ValueError:
        return OLLAMA_STILLE
    return wert if wert > 0 else OLLAMA_STILLE


# ── Überwachung ───────────────────────────────────────────────────────────────

protokoll = logging.getLogger("ber.neu.anbieter")


def ollama_lage(basis: str | None = None) -> dict:
    """Antwortet der Dienst, und welches Modell liegt geladen im Speicher?

    Billig und ohne Modellaufruf — gedacht als Blick vor einem langen Lauf,
    damit ein nicht laufender Dienst nicht als 'rechnet noch' erscheint.
    """
    import requests

    adresse = basis or os.environ.get("OLLAMA_BASE_URL") or OLLAMA_BASIS
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
    abgestürzten Dienst nicht zu unterscheiden: in beiden Fällen kommt minutenlang
    nichts. Der Puls trennt die beiden Fälle, weil er sagt, wann das letzte
    Zeichen ankam.
    """

    def __init__(self, was: str, intervall: int = PULS_SEKUNDEN):
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


class AnbieterFehler(RuntimeError):
    def __init__(self, meldung: str, code: str = "anbieter_fehler"):
        super().__init__(meldung)
        self.code = code


# ── Embedding ─────────────────────────────────────────────────────────────────

def embedding_funktion(name: str | None = None) -> tuple[Callable[[list[str]], np.ndarray], str]:
    """Gibt (embed, bezeichnung) zurück. Bricht ab, wenn etwas fehlt."""
    anbieter = (name or os.environ.get("EMBEDDING_PROVIDER") or "").lower()
    if not anbieter:
        raise AnbieterFehler(
            "EMBEDDING_PROVIDER ist nicht gesetzt. Erlaubt: "
            + " | ".join(EMBEDDING_ANBIETER),
            "embedding_anbieter_fehlt",
        )
    if anbieter not in EMBEDDING_ANBIETER:
        raise AnbieterFehler(
            f"Unbekannter EMBEDDING_PROVIDER '{anbieter}'. Erlaubt: "
            + " | ".join(EMBEDDING_ANBIETER),
            "embedding_anbieter_unbekannt",
        )

    if anbieter == "voyage":
        if not os.environ.get("VOYAGE_API_KEY"):
            raise AnbieterFehler(
                "VOYAGE_API_KEY ist nicht gesetzt, EMBEDDING_PROVIDER steht auf 'voyage'.",
                "voyage_schluessel_fehlt",
            )
        from src.generalized.embeddings import VoyageProvider

        provider = VoyageProvider()
        return (lambda texte: provider.encode(list(texte))), "voyage-4"

    from src.generalized.embeddings import BGEProvider

    provider = BGEProvider()
    # Die Vorlage embeddet mit batch_size=16, BGEProvider mit 32. Rechnerisch
    # identisch, nur andere Stapelgröße.
    return (lambda texte: provider.encode(list(texte))), "BAAI/bge-m3"


# ── Sprachmodell ──────────────────────────────────────────────────────────────

def llm_funktion(
    name: str | None = None, modell: str | None = None
) -> tuple[Callable[[str, str], tuple[str, int, int]], str]:
    """Gibt (frage_modell, modellname) zurück.

    frage_modell(prompt, system) -> (antwort, in_tokens, out_tokens).

    Der Ollama-Weg läuft im Strom und protokolliert dabei mit (siehe _Puls),
    damit ein langer Aufruf von einem hängenden zu unterscheiden ist. Er meldet
    jetzt auch die Tokenzahlen, die die Vorlage als (text, 0, 0) wegwarf.
    """
    anbieter = (name or os.environ.get("LLM_PROVIDER") or "").lower()
    if not anbieter:
        raise AnbieterFehler(
            "LLM_PROVIDER ist nicht gesetzt. Erlaubt: " + " | ".join(LLM_ANBIETER),
            "llm_anbieter_fehlt",
        )
    if anbieter not in LLM_ANBIETER:
        raise AnbieterFehler(
            f"Unbekannter LLM_PROVIDER '{anbieter}'. Erlaubt: " + " | ".join(LLM_ANBIETER),
            "llm_anbieter_unbekannt",
        )

    if anbieter == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise AnbieterFehler(
                "ANTHROPIC_API_KEY ist nicht gesetzt, LLM_PROVIDER steht auf 'anthropic'.",
                "anthropic_schluessel_fehlt",
            )
        import anthropic

        client = anthropic.Anthropic()
        m = modell or os.environ.get("ANTHROPIC_MODEL_ANALYZE") or MODELL_ANTHROPIC

        def frage_anthropic(prompt: str, system: str) -> tuple[str, int, int]:
            antwort = client.messages.create(
                model=m, max_tokens=2048, temperature=0,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return (antwort.content[0].text.strip(),
                    antwort.usage.input_tokens, antwort.usage.output_tokens)

        return frage_anthropic, m

    import requests

    m = modell or os.environ.get("OLLAMA_MODEL") or MODELL_OLLAMA
    basis = os.environ.get("OLLAMA_BASE_URL") or OLLAMA_BASIS

    frist = ollama_frist()

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
                                  "num_predict": ANTWORT_TOKEN}},
                timeout=(10, frist),
                stream=True,
            ) as r:
                r.raise_for_status()
                protokoll.info("%s: Anfrage gestellt, %d Zeichen Prompt", was, len(prompt))
                with _Puls(was) as puls:
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
                                    "%s: bei %d Token abgeschnitten (num_predict=%d). "
                                    "Die Antwort ist unvollständig.",
                                    was, out_tokens, ANTWORT_TOKEN,
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


def kosten(modell: str, in_tokens: int, out_tokens: int) -> float:
    """Kosten in Dollar. Für Ollama null, weil lokal gerechnet wird."""
    if modell not in ANTHROPIC_PREISE:
        return 0.0
    p_in, p_out = ANTHROPIC_PREISE[modell]
    return in_tokens * p_in / 1_000_000 + out_tokens * p_out / 1_000_000
