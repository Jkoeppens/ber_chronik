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

import os
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
    Ollama zählt keine Token und meldet (text, 0, 0) — wie in der Vorlage.
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

    def frage_ollama(prompt: str, system: str) -> tuple[str, int, int]:
        r = requests.post(
            f"{basis}/api/generate",
            json={"model": m, "prompt": prompt, "stream": False, "system": system,
                  "options": {"num_ctx": 8192, "temperature": 0}},
            timeout=300,
        )
        r.raise_for_status()
        daten = r.json()
        if "response" not in daten:
            raise AnbieterFehler(f"Ollama antwortet ohne response-Feld: {daten}",
                                 "ollama_antwort_ungueltig")
        return daten["response"].strip(), 0, 0

    return frage_ollama, m


def kosten(modell: str, in_tokens: int, out_tokens: int) -> float:
    """Kosten in Dollar. Für Ollama null, weil lokal gerechnet wird."""
    if modell not in ANTHROPIC_PREISE:
        return 0.0
    p_in, p_out = ANTHROPIC_PREISE[modell]
    return in_tokens * p_in / 1_000_000 + out_tokens * p_out / 1_000_000
