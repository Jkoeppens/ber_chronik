"""
entity_llm.py — LLM-basierte Entity-Extraktion und Bereinigung.

Aktiv genutzt (4-Schritte-Pipeline):
  - Schritt 1: _llm_sample_iteration
  - Schritt 2: _llm_full_extract
  - Schritt 3: _llm_group  (Schreibvarianten zusammenführen, Batches à 30)
  - Schritt 4: _llm_task1_normalize
"""

import random
import sys
from pathlib import Path

from src.generalized.entity_utils import (
    VALID_TYPES,
    _normalize_entity,
    _build_few_shot_block,
    _save_checkpoint,
    _merge,
)

SYSTEM_PROMPT   = "Du extrahierst Eigennamen aus historischen Texten."
NORMALIZE_BATCH = 20
SAMPLE_SEGS     = 50
ITER1_BATCH     = 5
SAVE_INTERVAL   = 10

# D-E1: Plaintext-Listenformat — kein JSON
_PLAINTEXT_FORMAT_EXAMPLE = """\
Ausgabe-Format:
- Gruppiert nach Typ: # Personen, # Organisationen, # Orte, # Konzepte
- JEDE ENTITY AUF EINER EIGENEN ZEILE
- Kommas trennen Schreibvarianten DESSELBEN Namens (nicht verschiedene Entities)
- Erste Schreibweise = Normalform, Rest = Synonyme

Beispiel:
# Personen
Mustafa Kemal, Kemal Pascha, Atatürk
Enver Pascha

# Organisationen
CUP, Komitee für Einheit und Fortschritt

# Orte
Damaskus, Damascus

(Leere Abschnitte weglassen. Nur die Aufzählung ausgeben, kein JSON, kein Kommentar.)

=== BEISPIEL ENDE ==="""

ITER1_PROMPT = """\
{few_shot_block}Erkenne alle Eigennamen in diesem Text.

Der Text kann mehrsprachig sein — Deutsch, Englisch, Arabisch, Osmanisch-Türkisch.
Eigennamen in allen Sprachen erkennen. Arabische Namen: lateinische Transliteration
als Normalform, arabische Schrift als Synonym (z.B. "Damaskus, Damascus, الشام").

Regeln:
- Normalform = der Name selbst, Großschreibung bereinigt, KEINE Beschreibung
  RICHTIG: "Syrien", "Ismail Enver"   FALSCH: "Staat in Nahost", "türk. Offizier"
- Personen: Vor- UND Nachname wenn im Text erkennbar — nicht nur "Talat" wenn
  "Mehmed Talat" oder "Talat Pascha" im Text steht. Einzelwort nur wenn kein
  vollständiger Name aus dem Kontext ableitbar ist.
- Titel (Pasha, Bey, Sultan, Effendi, Pascha) nicht zur Normalform — als Synonym
- Monatsnamen und generische Begriffe weglassen
- Synonyme = alle Schreibweisen aus DIESEM Text, kommasepariert

{format_example}
Jetzt extrahiere Entities aus folgendem Text:
=== TEXT ===
{text}
=== ENDE ==="""

NORMALIZE_PROMPT = """\
{few_shot_block}Bereinige diese Entitäts-Kandidaten aus einem historischen Text.

Regeln:
- Normalform = Eigenname bereinigt (Großschreibung, OCR-Fehler korrigiert), KEINE Beschreibung
  RICHTIG: "Ismail Enver", "Damaskus", "CUP"   FALSCH: "türk. Offizier", "Hauptstadt Syriens"
- Titel (Pasha, Bey, Pascha, Sultan, Effendi, Vizier, Emir, Khedive) als Synonyme, nicht Normalform
- OCR-Fehler korrigieren wenn offensichtlich
- Weglassen wenn kein Eigenname (Monatsnamen, generische Begriffe, alleinstehende Titel)
- Typ-Hinweis als Orientierung nutzen, aber korrigieren wenn falsch

{format_example}
Jetzt bereinige folgende Kandidaten:
=== KANDIDATEN ===
{kandidaten}
=== ENDE ==="""

EXTRACT_TEMPLATE = """\
{few_shot_block}Extrahiere alle Eigennamen aus diesem historischen Text.

Der Text kann mehrsprachig sein — Deutsch, Englisch, Arabisch, Osmanisch-Türkisch.
Eigennamen in allen Sprachen erkennen. Arabische Namen: lateinische Transliteration
als Normalform, arabische Schrift als Synonym (z.B. "Damaskus, Damascus, الشام").

Regeln:
- Normalform = der Name selbst, KEINE Beschreibung
- Personen: Vor- UND Nachname wenn im Text erkennbar — nicht nur "Talat" wenn
  "Mehmed Talat" oder "Talat Pascha" im Text steht. Einzelwort nur wenn kein
  vollständiger Name aus dem Kontext ableitbar ist.
- Titel (Pasha, Bey, Effendi usw.) nicht zur Normalform, aber als Synonym
- Synonyme = alle Schreibweisen wie der Name im Text vorkommt
- Nur eindeutige Eigennamen, keine generischen Begriffe

{format_example}
Jetzt extrahiere Entities aus folgendem Text:
=== TEXT ===
{text}
=== ENDE ==="""


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Teilt Text in Chunks à max_chars Zeichen auf, Schnitt an Satzgrenzen wenn möglich."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    while len(text) > max_chars:
        split_pos = text.rfind(". ", 0, max_chars)
        if split_pos == -1:
            split_pos = max_chars
        else:
            split_pos += 1  # Punkt behalten
        chunks.append(text[:split_pos].strip())
        text = text[split_pos:].lstrip()
    if text:
        chunks.append(text)
    return chunks


# D-E1: Parser für Plaintext-Listenformat
_PLAINTEXT_TYPE_MAP: dict[str, str] = {
    "personen":      "Person",
    "person":        "Person",
    "organisationen": "Organisation",
    "organisation":  "Organisation",
    "orte":          "Ort",
    "ort":           "Ort",
    "konzepte":      "Konzept",
    "konzept":       "Konzept",
}


def _parse_plaintext_entities(text: str) -> list[dict]:
    """Parst das D-E1-Plaintext-Format in eine Liste von Entity-Dicts."""
    results: list[dict] = []
    current_type: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            header = line.lstrip("#").strip().lower()
            current_type = _PLAINTEXT_TYPE_MAP.get(header)
            continue
        if current_type is None:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        results.append({
            "normalform": parts[0],
            "typ":        current_type,
            "aliases":    parts[1:],
        })
    return results


def _format_candidate_for_task1(cand: dict) -> str:
    name = cand.get("normalform", "")
    hint = cand.get("typ") or cand.get("_type_hint", "")
    if hint:
        conf = cand.get("_confidence")
        suffix = f", Konfidenz: {conf:.0%}" if conf is not None else ""
        name += f" (Hinweis: {hint}{suffix})"
    aliases = [a for a in cand.get("aliases", []) if a]
    if aliases:
        name += " [auch: " + ", ".join(str(a) for a in aliases[:4]) + "]"
    return name


def _llm_sample_iteration(
    segments: list[dict],
    provider,
    seed: list[dict],
    checkpoint_path: Path | None,
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Iteration 1: LLM extrahiert Eigennamen aus 50 zufälligen Segmenten."""
    content_segs = [s for s in segments if s.get("type") == "content"]
    sample       = random.sample(content_segs, min(SAMPLE_SEGS, len(content_segs)))
    few_shot     = _build_few_shot_block(seed)

    max_chars = provider.max_chars_per_chunk
    pseudo_segs: list[dict] = []
    for seg in sample:
        text = seg.get("text", "")
        if len(text) <= max_chars:
            pseudo_segs.append(seg)
        else:
            for chunk in _chunk_text(text, max_chars):
                pseudo_segs.append({"type": "content", "text": chunk})

    batches = [pseudo_segs[i:i + ITER1_BATCH] for i in range(0, len(pseudo_segs), ITER1_BATCH)]
    print(f"Iteration 1: {len(sample)} Segmente → {len(pseudo_segs)} Chunks "
          f"in {len(batches)} Batches …")
    results: list[dict] = []

    for idx, batch in enumerate(batches):
        text   = "\n---\n".join(s.get("text", "") for s in batch)
        prompt = ITER1_PROMPT.format(
            few_shot_block=few_shot,
            format_example=_PLAINTEXT_FORMAT_EXAMPLE,
            text=text,
        )
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)
        raw = provider.complete(prompt, system=SYSTEM_PROMPT)
        parsed = _parse_plaintext_entities(raw)
        if not parsed and raw.strip():
            print(f"  Batch {idx + 1}: Plaintext-Parser: 0 Entities aus nicht-leerem Output",
                  file=sys.stderr)
        for ent in parsed:
            n = _normalize_entity(ent, "llm_iter1", rejected_lc)
            if n is not None:
                results.append(n)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {"iter1_entities": results})

    results = _merge([results])
    print(f"  {len(results)} Entities aus Iteration 1")
    return results


def _llm_task1_normalize(
    candidates: list[dict],
    provider,
    seed: list[dict],
    checkpoint_path: Path | None,
    resume_from: int = 0,
    accumulated: list[dict] | None = None,
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Task B1: Normalform bereinigen + Typ zuweisen für alle Kandidaten."""
    batches    = [candidates[i:i + NORMALIZE_BATCH]
                  for i in range(0, len(candidates), NORMALIZE_BATCH)]
    few_shot   = _build_few_shot_block(seed)
    if accumulated is None:
        accumulated = []

    print(f"Task B1 (Normalize): {len(candidates)} Kandidaten in "
          f"{len(batches)} Batches à {NORMALIZE_BATCH} …")
    if resume_from:
        print(f"  Resume: ab Batch {resume_from + 1}")

    for idx, batch in enumerate(batches):
        if idx < resume_from:
            continue
        kandidaten = "\n".join(
            f"{i + 1}. {_format_candidate_for_task1(c)}" for i, c in enumerate(batch)
        )
        prompt = NORMALIZE_PROMPT.format(
            few_shot_block=few_shot,
            format_example=_PLAINTEXT_FORMAT_EXAMPLE,
            kandidaten=kandidaten,
        )
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)

        raw    = provider.complete(prompt, system=SYSTEM_PROMPT)
        parsed = _parse_plaintext_entities(raw)

        if parsed:
            for ent in parsed:
                norm_lc = ent["normalform"].lower()
                orig = next(
                    (c for c in batch if (c.get("normalform") or "").lower() == norm_lc),
                    None,
                )
                if orig and orig.get("_confidence") is not None:
                    ent["_confidence"] = orig["_confidence"]
                n = _normalize_entity(ent, "llm_task1", rejected_lc)
                if n is not None:
                    accumulated.append(n)
        else:
            # Fallback: Original-Kandidaten des Batches unverändert übernehmen
            print(f"  Batch {idx + 1}: Fallback — {len(batch)} Original-Kandidaten übernommen",
                  file=sys.stderr)
            for c in batch:
                n = _normalize_entity(c, "llm_task1", rejected_lc)
                if n is not None:
                    accumulated.append(n)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {
                "stageB1_batch": idx + 1,
                "stageB1_entities": accumulated,
            })

    print(f"  {len(accumulated)} Entities nach Task B1")
    return accumulated


def _llm_full_extract(
    segments: list[dict],
    provider,
    seed: list[dict],
    checkpoint_path: Path | None,
    batch_size: int = 10,
    resume_from: int = 0,
    accumulated: list[dict] | None = None,
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Schritt 2: Vollextraktion aller Segmente mit Few-Shot aus den ersten 10 Seed-Entities."""
    content_segs = [s for s in segments if s.get("type") == "content"]
    few_shot     = _build_few_shot_block(seed)   # begrenzt intern auf seed[:10]
    results      = list(accumulated) if accumulated else []

    max_chars = provider.max_chars_per_chunk
    pseudo_segs: list[dict] = []
    for seg in content_segs:
        text = seg.get("text", "")
        if len(text) <= max_chars:
            pseudo_segs.append(seg)
        else:
            for chunk in _chunk_text(text, max_chars):
                pseudo_segs.append({"type": "content", "text": chunk})

    batches = [pseudo_segs[i:i + batch_size]
               for i in range(0, len(pseudo_segs), batch_size)]
    print(f"Schritt 2 (Vollextraktion): {len(content_segs)} Segmente "
          f"→ {len(pseudo_segs)} Chunks in {len(batches)} Batches à {batch_size} …")
    if resume_from:
        print(f"  Resume ab Batch {resume_from + 1}")

    for idx, batch in enumerate(batches):
        if idx < resume_from:
            continue

        text   = "\n---\n".join(s.get("text", "") for s in batch)
        prompt = EXTRACT_TEMPLATE.format(
            few_shot_block=few_shot,
            format_example=_PLAINTEXT_FORMAT_EXAMPLE,
            text=text,
        )
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)
        raw    = provider.complete(prompt, system=SYSTEM_PROMPT)
        parsed = _parse_plaintext_entities(raw)
        if not parsed and raw.strip():
            print(f"  Batch {idx + 1}: Plaintext-Parser: 0 Entities aus nicht-leerem Output",
                  file=sys.stderr)
        for ent in parsed:
            n = _normalize_entity(ent, "llm_full", rejected_lc)
            if n is not None:
                results.append(n)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {
                "step2_batch":    idx + 1,
                "step2_entities": results,
            })

    results = _merge([results])
    print(f"  {len(results)} Entities aus Vollextraktion")
    return results


GROUP_BATCH  = 30

GROUP_PROMPT = """\
Hier ist eine Liste von Entity-Namen aus einem historischen Text.
Fasse zusammen, welche Einträge dieselbe Person, denselben Ort oder dieselbe Organisation bezeichnen
(Schreibvarianten, Kurzformen, Transliterationen).

Ausgabe — eine Zeile pro Gruppe:
Normalform zuerst, weitere Varianten kommasepariert dahinter.
Entities ohne Varianten: nur den Namen, keine Kommas.
Nur eindeutige Zusammenführungen. Im Zweifel: getrennt lassen.
Keine Kommentare, kein JSON, keine leeren Zeilen am Ende.

Eingabe:
{entities_block}

Ausgabe:"""


def _llm_group(
    entities: list[dict],
    provider,
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Schritt 3: Schreibvarianten gruppieren — Plaintext-Format, Batches à GROUP_BATCH."""
    # lookup: jeder bekannte Name (normalform + aliases) → entity dict
    lookup: dict[str, dict] = {}
    for ent in entities:
        norm_lc = (ent.get("normalform") or "").lower()
        if norm_lc:
            lookup[norm_lc] = ent
        for alias in ent.get("aliases", []):
            if alias:
                lookup[alias.lower()] = ent

    batches = [entities[i:i + GROUP_BATCH] for i in range(0, len(entities), GROUP_BATCH)]
    print(f"Schritt 3 (Gruppieren): {len(entities)} Entities in "
          f"{len(batches)} Batch(es) à {GROUP_BATCH} …")

    all_results: list[dict] = []

    for idx, batch in enumerate(batches):
        entities_block = "\n".join(
            ent["normalform"] for ent in batch if ent.get("normalform")
        )
        prompt = GROUP_PROMPT.format(entities_block=entities_block)
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)

        raw   = provider.complete(prompt, system=SYSTEM_PROMPT)
        lines = [ln.strip() for ln in raw.splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]

        if not lines:
            print(f"  Batch {idx + 1}: Gruppen-LLM lieferte 0 Zeilen "
                  f"— {len(batch)} Entities unverändert übernommen", file=sys.stderr)
            for ent in batch:
                n = _normalize_entity(ent, "llm_group", rejected_lc)
                if n is not None:
                    all_results.append(n)
            continue

        for line in lines:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if not parts:
                continue
            normalform    = parts[0]
            extra_aliases = parts[1:]

            # Typ aus ursprünglichem Entity ableiten
            orig = lookup.get(normalform.lower())
            if orig is None:
                for alias in extra_aliases:
                    orig = lookup.get(alias.lower())
                    if orig:
                        break
            typ = (orig.get("typ") if orig else None) or "Konzept"

            # Aliases: erst aus dem Original, dann LLM-Varianten
            seen_lc: set[str] = {normalform.lower()}
            grouped_aliases: list[str] = []
            for a in list(orig.get("aliases", []) if orig else []) + extra_aliases:
                if a and a.lower() not in seen_lc:
                    grouped_aliases.append(a)
                    seen_lc.add(a.lower())

            candidate = {"normalform": normalform, "typ": typ, "aliases": grouped_aliases}
            n = _normalize_entity(candidate, "llm_group", rejected_lc)
            if n is not None:
                all_results.append(n)

    print(f"  {len(entities)} → {len(all_results)} Entities nach Gruppierung")
    return all_results
