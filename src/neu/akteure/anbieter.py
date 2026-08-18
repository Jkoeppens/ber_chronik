"""
anbieter.py — Erkenner und Embedding für den Akteursschritt auswählen

Wie src/neu/taxonomie/anbieter.py: der Anbieter bestimmt, WOMIT gerechnet wird,
nicht OB. Fehlt eine Angabe, wird abgebrochen — kein stiller Rückfall.

Der Unterschied zum Taxonomieschritt ist das lokale Modell. Dort BGE-M3 für
lange Texte, hier MiniLM für kurze Namen; die Vergleichsmessung vom 17.05. hält
BGE-M3 für Entity-Clustering ausdrücklich für ungeeignet.

Und die Schwelle hängt am Modell, nicht am Verfahren. 0,92 ist die Zahl für
MiniLM. src/generalized/embeddings.py nennt für Voyage-4 ~0,78, aber
entity_gliner.py rechnet mit einer Konstante — ein Lauf mit
EMBEDDING_PROVIDER=voyage führt dort praktisch nichts mehr zusammen. Deshalb
kommt die Schwelle hier aus derselben Hand wie das Modell.
"""

from __future__ import annotations

import os
from typing import Callable

import numpy as np

from src.neu.akteure.kern import GLINER_MODELL
from src.neu.taxonomie.anbieter import AnbieterFehler

EMBEDDING_ANBIETER = ("local", "voyage")

# Schwelle für das Zusammenführen, je Modell. Beide Werte stammen aus dem
# Bestand: 0,92 aus entity_gliner.EMB_THRESHOLD, 0,78 aus
# embeddings.VoyageProvider.THRESHOLD_CLUSTER.
SCHWELLE_MINILM = 0.92
SCHWELLE_VOYAGE = 0.78

MODELL_MINILM = "paraphrase-multilingual-MiniLM-L12-v2"
MODELL_VOYAGE = "voyage-4"


# ── Embedding ─────────────────────────────────────────────────────────────────

def embedding_funktion(
    name: str | None = None,
) -> tuple[Callable[[list[str]], np.ndarray], str, float]:
    """Gibt (embed, bezeichnung, schwelle) zurück. Bricht ab, wenn etwas fehlt."""
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
        return (lambda texte: provider.encode(list(texte))), MODELL_VOYAGE, SCHWELLE_VOYAGE

    from src.generalized.embeddings import MiniLMProvider

    provider = MiniLMProvider()
    return (lambda texte: provider.encode(list(texte))), MODELL_MINILM, SCHWELLE_MINILM


# ── Erkenner ──────────────────────────────────────────────────────────────────

_gliner_modell = None
_gliner_name: str | None = None


def gliner_funktion(
    modell: str | None = None,
) -> tuple[Callable[[str, list[str], float], list[dict]], str]:
    """Gibt (vorhersage, modellname) zurück.

    vorhersage(stueck, labels, schwelle) -> [{"text": …, "label": …}, …].
    Das Modell wird einmal geladen und für alle Aufrufe wiederverwendet.
    """
    global _gliner_modell, _gliner_name

    name = modell or os.environ.get("GLINER_MODEL") or GLINER_MODELL
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

    return vorhersage, name
