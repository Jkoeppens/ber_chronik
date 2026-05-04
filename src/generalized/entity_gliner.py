"""
entity_gliner.py — NER-Extraktion via GLiNER für mehrsprachige historische Texte.

Modell:  urchade/gliner_multi  (multilingual, läuft lokal ohne GPU)
Labels:  GLINER_LABELS aus config.py  (verfeinerte Kategorien)
Threshold: GLINER_THRESHOLD (default 0.7)

Pipeline:
  Phase 1: GLiNER-Erkennung pro Segment (chunked, mit Modell-Cache)
  Phase 2: _normalize_entity() pro Entity
  Phase 3: _merge() — programmatische Dedup
  Phase 4: _llm_group() — LLM fasst Schreibvarianten + Aliase zusammen
  Phase 5: _llm_task1_normalize() — LLM bereinigt Normalformen, validiert Typen

Schnittstelle identisch zu entity_spacy.extract_with_spacy().
"""

import sys

from src.generalized.config import (
    GLINER_LABELS,
    GLINER_MAX_CHARS,
    GLINER_MODEL,
    GLINER_THRESHOLD,
)
from src.generalized.entity_utils import _merge, _normalize_entity
from src.generalized.entity_llm import _llm_group, _llm_task1_normalize

# Label-Mapping: verfeinerte GLiNER-Labels → VALID_TYPES
_LABEL_TO_TYPE: dict[str, str] = {
    "Person":                   "Person",
    "Organisation":             "Organisation",
    "geographischer Ort":       "Ort",
    "politische Bewegung":      "Organisation",
    "religiöse Institution":    "Organisation",
    "Zeitung oder Publikation": "Organisation",
}

# Modell-Cache: einmal laden, für alle Aufrufe wiederverwenden
_gliner_model = None
_gliner_model_name: str | None = None


def _load_gliner(model_name: str):
    global _gliner_model, _gliner_model_name
    if _gliner_model is not None and _gliner_model_name == model_name:
        return _gliner_model
    try:
        from gliner import GLiNER
    except ImportError:
        print(
            "FEHLER: gliner nicht installiert.\n"
            "  pip install gliner",
            file=sys.stderr,
        )
        raise
    print(f"GLiNER: {model_name} wird geladen …")
    _gliner_model = GLiNER.from_pretrained(model_name)
    _gliner_model_name = model_name
    print("GLiNER: Modell geladen")
    return _gliner_model


def _chunk(text: str, max_chars: int = GLINER_MAX_CHARS) -> list[str]:
    """Teilt Text an Satzgrenzen in Stücke à max_chars Zeichen."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        split = text.rfind(". ", 0, max_chars)
        split = (split + 1) if split != -1 else max_chars
        chunks.append(text[:split].strip())
        text = text[split:].strip()
    return [c for c in chunks if c]


def extract_with_gliner(
    segments: list[dict],
    rejected_lc: set[str],
    provider,
) -> list[dict]:
    """Extrahiert Entities aus Segmenten via GLiNER NER.

    provider wird für _llm_group (Phase 4) und _llm_task1_normalize (Phase 5)
    genutzt. Gibt eine deduplizierte Entity-Liste im Standard-Format zurück.
    """
    model = _load_gliner(GLINER_MODEL)

    def _skip(s: dict) -> bool:
        if s.get("item_type") == "videoRecording":
            return True
        # Alte Segmente ohne item_type: bei sehr langem Text überspringen
        if s.get("item_type") is None and len(s.get("text", "")) > 20_000:
            return True
        return False

    content_segs = [s for s in segments
                    if s.get("type") == "content" and not _skip(s)]
    skipped_video = sum(1 for s in segments
                        if s.get("type") == "content"
                        and s.get("item_type") == "videoRecording")
    skipped_long  = sum(1 for s in segments
                        if s.get("type") == "content"
                        and s.get("item_type") is None
                        and len(s.get("text", "")) > 20_000)
    if skipped_video:
        print(f"  {skipped_video} videoRecording-Segment(e) übersprungen")
    if skipped_long:
        print(f"  {skipped_long} Segment(e) übersprungen (kein item_type, >20k Zeichen)")
    print(f"GLiNER NER: {len(content_segs)} Segmente  (θ={GLINER_THRESHOLD}) …")

    raw_entities: list[dict] = []

    for seg in content_segs:
        text = seg.get("text", "")
        if not text:
            continue
        for chunk in _chunk(text):
            try:
                entities = model.predict_entities(
                    chunk, GLINER_LABELS, threshold=GLINER_THRESHOLD
                )
            except Exception as exc:
                print(
                    f"  WARNING: GLiNER Fehler in Segment "
                    f"{seg.get('segment_id', '?')}: {exc}",
                    file=sys.stderr,
                )
                continue
            for ent in entities:
                typ  = _LABEL_TO_TYPE.get(ent["label"], "Konzept")
                norm = ent["text"].strip()
                if not norm:
                    continue
                n = _normalize_entity(
                    {"normalform": norm, "typ": typ, "aliases": [],
                     "score": round(ent["score"], 3)},
                    "gliner", rejected_lc,
                )
                if n is not None:
                    raw_entities.append(n)

    print(f"  {len(raw_entities)} Roh-Entities aus GLiNER")

    # Phase 3: Programmatische Dedup
    deduped = _merge([raw_entities])
    print(f"  {len(deduped)} nach _merge()")

    # Phase 4: Schreibvarianten via LLM zusammenführen
    grouped = _llm_group(deduped, provider, rejected_lc)
    print(f"  {len(grouped)} nach _llm_group()")

    # Phase 5: Normalformen bereinigen + Typen validieren
    normalized = _llm_task1_normalize(
        grouped, provider, seed=[], checkpoint_path=None, rejected_lc=rejected_lc
    )
    print(f"  {len(normalized)} nach _llm_task1_normalize()")
    return normalized
