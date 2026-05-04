import os
from pathlib import Path

ROOT         = Path(__file__).resolve().parent.parent.parent
DATA_ROOT    = Path(os.environ["DATA_ROOT"]) if "DATA_ROOT" in os.environ else ROOT / "data"
PROJECTS_DIR = DATA_ROOT / "projects"
RAW_DIR      = DATA_ROOT / "raw"
DEFAULTS_DIR = ROOT / "data" / "defaults"  # read-only defaults stay in repo

# ── GLiNER-Konfiguration (D-E4) ───────────────────────────────────────────────

GLINER_MODEL     = "urchade/gliner_multi"
GLINER_THRESHOLD = 0.7
GLINER_MAX_CHARS = 2000   # Chunk-Größe für GLiNER (Satzgrenzen-Split)

# Verfeinerte Labels für bessere Typ-Distinktion gegenüber einfachen 4 Klassen.
# Mapping auf VALID_TYPES in entity_gliner._LABEL_TO_TYPE.
GLINER_LABELS: list[str] = [
    "Person",
    "Organisation",
    "geographischer Ort",
    "politische Bewegung",
    "religiöse Institution",
    "Zeitung oder Publikation",
    "politische Bewegung oder Ideologie",
    "religiöse Strömung oder Konzept",
]

# ── NER-Backend-Routing ───────────────────────────────────────────────────────
# "gliner" → entity_gliner.py  (Standard, multilingual, lokal)
# "llm"    → entity_llm.py     (Fallback für Setups ohne GLiNER)
# "spacy"  → entity_spacy.py   (Legacy, englischsprachige Pressetexte)
NER_BACKEND: dict[str, str] = {
    "presseartikel":     "gliner",
    "forschungsnotizen": "gliner",
    "buchnotizen":       "gliner",
}
# Default für unbekannte doc_types: "gliner"
