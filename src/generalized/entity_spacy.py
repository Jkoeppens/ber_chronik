"""
entity_spacy.py — NER-Extraktion via spaCy für englischsprachige Segmente.

Lädt en_core_web_trf wenn vorhanden, sonst en_core_web_sm als Fallback.
Typ-Mapping: PERSON→Person, ORG→Organisation, GPE/LOC/FAC→Ort, sonst→Konzept.
Am Ende: _merge() (programmatische Dedup) + _llm_group() (Schreibvarianten, Stufe 3).
"""

import sys

from src.generalized.entity_utils import _merge, _normalize_entity
from src.generalized.entity_llm import _llm_group

_SPACY_TYPE_MAP: dict[str, str] = {
    "PERSON": "Person",
    "ORG":    "Organisation",
    "GPE":    "Ort",
    "LOC":    "Ort",
    "FAC":    "Ort",
    "NORP":   "Konzept",
    "EVENT":  "Konzept",
    "LAW":    "Konzept",
    "WORK_OF_ART": "Konzept",
    "PRODUCT": "Konzept",
}


def _load_nlp():
    import spacy
    try:
        nlp = spacy.load("en_core_web_trf")
        print("spaCy: en_core_web_trf geladen")
        return nlp
    except OSError:
        nlp = spacy.load("en_core_web_sm")
        print("spaCy: en_core_web_sm geladen (Fallback)")
        return nlp


def extract_with_spacy(
    segments: list[dict],
    rejected_lc: set[str],
    provider,
) -> list[dict]:
    """Extrahiert Entities aus Segmenten via spaCy NER.

    provider wird für _llm_group (Stufe 3, Schreibvarianten zusammenführen) genutzt.
    Gibt eine deduplizierte Entity-Liste im Standard-Format zurück.
    """
    nlp = _load_nlp()
    content_segs = [s for s in segments if s.get("type") == "content"]
    print(f"spaCy NER: {len(content_segs)} Segmente …")

    raw_entities: list[dict] = []

    for seg in content_segs:
        text = seg.get("text", "")
        if not text:
            continue
        try:
            doc = nlp(text)
        except Exception as exc:
            print(f"  WARNING: spaCy Fehler in Segment {seg.get('segment_id', '?')}: {exc}",
                  file=sys.stderr)
            continue
        for ent in doc.ents:
            typ = _SPACY_TYPE_MAP.get(ent.label_)
            if typ is None:
                continue
            norm = ent.text.strip()
            if not norm:
                continue
            n = _normalize_entity({"normalform": norm, "typ": typ, "aliases": []},
                                  "spacy", rejected_lc)
            if n is not None:
                raw_entities.append(n)

    print(f"  {len(raw_entities)} Roh-Entities aus spaCy")

    # Programmatische Dedup vor dem LLM-Gruppierungsschritt
    deduped = _merge([raw_entities])
    print(f"  {len(deduped)} nach _merge()")

    # Stufe 3: Schreibvarianten via LLM zusammenführen
    grouped = _llm_group(deduped, provider, rejected_lc)
    return grouped
