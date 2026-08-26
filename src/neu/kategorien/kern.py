"""
kern.py — Kategorien vorschlagen und zuordnen

Reine Funktionen: Text und Zahlen rein, Entscheidungen raus. Keine Datenbank,
keine Dateien, kein Netz, kein print. Der LLM-Aufruf kommt als Funktion von
außen herein, damit auch dieser Weg ohne Netz prüfbar bleibt.

Die Fachlogik ist unverändert übernommen aus
src/generalized/classify_segments.py:
    normalize_category, build_categories_block, classify_one samt Prompt,
    die BGE-Schwellwerte (0,5 / 0,35) und die Argmax-Zuordnung
und aus src/generalized/propose_taxonomy_pipeline.py:
    _parse_taxonomy

Ein Unterschied im Ergebnis, keiner in der Regel: wo die Vorlage die Zeichenkette
"(unbekannt)" in das Kategoriefeld schrieb, gibt der Kern hier None zurück. Der
Wert war nie eine Kategorie, sondern das Eingeständnis, keine gefunden zu haben —
in der Datenbank ist das kategorie_id NULL bei gesetzter Herkunft.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

# ── Wertevorräte ──────────────────────────────────────────────────────────────

# Aus src/neu/vokabular.py. HERKUENFTE hieß hier wie in datierung/kern.py und
# akteure/kern.py, meinte aber etwas anderes.
from src.neu.vokabular import (  # noqa: E402
    KONFIDENZEN,
    UnbekannterWert,
    pruefen,
)
from src.neu.vokabular import KATEGORIE_HERKUENFTE as HERKUENFTE  # noqa: E402
from src.neu.vokabular import VORSCHLAG_HERKUENFTE as KATEGORIE_HERKUENFTE  # noqa: E402

__all_vokabular__ = (HERKUENFTE, KATEGORIE_HERKUENFTE, KONFIDENZEN)

# Zeichen-Limit beim Embedden — wie in der Vorlage
SEG_CHARS = 500

# Schwellwerte auf der Kosinusähnlichkeit (BGE-M3)
SCHWELLE_HIGH = 0.5
SCHWELLE_MEDIUM = 0.35


UnbekannteHerkunft = UnbekannterWert


def herkunft_pruefen(wert: str) -> str:
    return pruefen(wert, HERKUENFTE, "Herkunft")


# ── Ergebnis einer Zuordnung ──────────────────────────────────────────────────

@dataclass(frozen=True)
class Zuordnung:
    """Eine Kategorie-Entscheidung für eine Einheit.

    kategorie ist None, wenn keine Kategorie zugeordnet werden konnte — in der
    Vorlage war das die Zeichenkette "(unbekannt)".
    """

    kategorie: str | None
    konfidenz: str | None
    herkunft: str


# ── Taxonomie: Vorschlag parsen ───────────────────────────────────────────────
# Unverändert aus propose_taxonomy_pipeline._parse_taxonomy übernommen.

def parse_taxonomie(text: str) -> list[dict]:
    """Parst ## Name / Beschreibung / Keywords: … Format."""
    results: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("##"):
            if current and current.get("name"):
                results.append(current)
            name = re.sub(r"\*+", "", line.lstrip("#").strip())
            name = re.sub(r"^Gruppe\s+\d+[:\.\-–]\s*", "", name).strip()
            current = {"name": name, "description": "", "keywords": []}
        elif current is not None:
            if line.lower().startswith("keywords:"):
                kws = line[len("keywords:"):].strip()
                current["keywords"] = [k.strip() for k in kws.split(",") if k.strip()][:3]
                results.append(current)
                current = None
            elif not current["description"]:
                current["description"] = line
    if current and current.get("name"):
        results.append(current)
    return [c for c in results if c.get("name")]


# ── Taxonomie: Namen normalisieren ────────────────────────────────────────────
# Unverändert aus classify_segments.normalize_category übernommen; nur der
# Rückgabewert für den Fehlschlag ist None statt "(unbekannt)".

def normalisiere_kategorie(raw: str | None, gueltige_namen: list[str]) -> str | None:
    """Normalisiert die LLM-Kategorie gegen die gültige Taxonomie-Liste.

    1. Exakter Match → nehmen
    2. Kein exakter Match → längsten gültigen Namen der als Substring vorkommt nehmen
    3. Kein Substring-Match → None
    """
    if not isinstance(raw, str):
        return None
    # 1. Exakt
    if raw in gueltige_namen:
        return raw
    # 2. Substring — längsten Match bevorzugen (z.B. "Außenpolitik" vor "Politik")
    raw_lower = raw.lower()
    matches = [n for n in gueltige_namen if n.lower() in raw_lower]
    if matches:
        return max(matches, key=len)
    return None


# ── LLM-Pfad ──────────────────────────────────────────────────────────────────
# Prompt und Ablauf unverändert aus classify_segments übernommen.

SYSTEM_PROMPT = (
    "Du klassifizierst Forschungsnotizen nach vorgegebenen Kategorien. "
    "Antworte ausschließlich als JSON."
)

USER_TEMPLATE = """\
Kategorien:
{categories}

Klassifiziere diese Notiz in genau eine Kategorie.
Antworte NUR mit diesem JSON-Objekt, kein Markdown, keine Erklärungen:
{{"category": "<Name>", "confidence": "<high|medium|low>"}}

Notiz:
{text}"""


def baue_kategorienblock(taxonomie: Sequence[dict]) -> str:
    return "\n".join(f"- {cat['name']} – {cat['description']}" for cat in taxonomie)


def baue_prompt(kategorienblock: str, text: str) -> str:
    return USER_TEMPLATE.format(categories=kategorienblock, text=text)


def zuordnung_aus_antwort(roh: str, gueltige_namen: list[str]) -> Zuordnung | None:
    """Wertet eine LLM-Antwort aus. None heißt: unlesbar, bitte wiederholen.

    Der Markdown-Zaun wird entfernt wie in der Vorlage.
    """
    text = roh.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return Zuordnung(
        kategorie=normalisiere_kategorie(parsed.get("category"), gueltige_namen),
        konfidenz=parsed.get("confidence", "low"),
        herkunft="automatisch",
    )


def klassifiziere_eine(
    text: str,
    kategorienblock: str,
    gueltige_namen: list[str],
    frage_modell: Callable[[str, str], str],
) -> Zuordnung:
    """Klassifiziert einen Text. Bei unlesbarer Antwort: einmal wiederholen.

    frage_modell(user_prompt, system_prompt) -> Antworttext. Kommt von außen,
    damit der Kern kein Netz kennt.
    """
    prompt = baue_prompt(kategorienblock, text)
    for versuch in range(2):
        zuordnung = zuordnung_aus_antwort(frage_modell(prompt, SYSTEM_PROMPT), gueltige_namen)
        if zuordnung is not None:
            return zuordnung
        if versuch == 0:
            continue
    # Zweimal unlesbar — wie in der Vorlage: keine Kategorie, keine Konfidenz.
    return Zuordnung(kategorie=None, konfidenz=None, herkunft="automatisch")


# ── BGE-Pfad ──────────────────────────────────────────────────────────────────
# Schwellwerte und Argmax unverändert aus classify_segments._classify_bge.

def taxonomie_texte(taxonomie: Sequence[dict]) -> list[str]:
    """Die Zeichenketten, die für die Taxonomie embeddet werden."""
    return [
        f"{c['name']}. {c.get('description', '')}. {' '.join(c.get('keywords', []))}"
        for c in taxonomie
    ]


def einheit_texte(texte: Sequence[str]) -> list[str]:
    """Segmenttexte, auf SEG_CHARS gekürzt — wie in der Vorlage."""
    return [t[:SEG_CHARS] for t in texte]


def konfidenz_aus_aehnlichkeit(aehnlichkeit: float) -> str:
    if aehnlichkeit > SCHWELLE_HIGH:
        return "high"
    if aehnlichkeit > SCHWELLE_MEDIUM:
        return "medium"
    return "low"


def zuordnungen_aus_embeddings(
    einheit_embeddings: np.ndarray,
    taxonomie_embeddings: np.ndarray,
    gueltige_namen: list[str],
) -> list[Zuordnung]:
    """Argmax über das Skalarprodukt, Konfidenz aus den Schwellwerten.

    Der BGE-Pfad ordnet immer zu: es gibt kein 'keine Kategorie'. Bei niedriger
    Ähnlichkeit ist die Zuordnung schwach, nicht leer — deshalb konfidenz 'low'
    und nicht kategorie None.
    """
    zuordnungen: list[Zuordnung] = []
    for i in range(einheit_embeddings.shape[0]):
        sims = einheit_embeddings[i] @ taxonomie_embeddings.T
        best_idx = int(sims.argmax())
        best_sim = float(sims[best_idx])
        zuordnungen.append(Zuordnung(
            kategorie=gueltige_namen[best_idx],
            konfidenz=konfidenz_aus_aehnlichkeit(best_sim),
            herkunft="automatisch",
        ))
    return zuordnungen
