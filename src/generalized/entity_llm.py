"""
entity_llm.py — LLM-basierte Entity-Extraktion und Bereinigung.

Aktiv genutzt (4-Schritte-Pipeline):
  - Schritt 1: _llm_sample_iteration
  - Schritt 2: _llm_full_extract
  - Schritt 3: _llm_dedup
  - Schritt 4: _llm_task1_normalize
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

from src.generalized.entity_utils import (
    VALID_TYPES,
    _normalize_entity,
    _build_few_shot_block,
    _save_checkpoint,
)

SYSTEM_PROMPT   = "Du klassifizierst Kandidaten aus historischen Texten. Antworte ausschließlich als JSON."
NORMALIZE_BATCH = 20
SAMPLE_SEGS     = 50
ITER1_BATCH     = 10
SAVE_INTERVAL   = 10

ITER1_PROMPT = """\
{few_shot_block}Erkenne alle Eigennamen in diesem Text.
Für jeden Namen:
- normalform: genau wie im Text, Großschreibung bereinigt
- typ: Person / Ort / Organisation / Konzept
- aliases: alle Schreibweisen die du in DIESEM Text siehst

Wichtig:
- Ein Name = eine Entity, nicht zusammenfassen
- Titel (Pasha, Bey, Sultan, Effendi, Pascha) sind keine Normalform,
  nur Alias: "Enver" nicht "Enver Pasha"
- Keine Beschreibungen als Normalform:
  RICHTIG: "Syrien"
  FALSCH: "Staat in der Region Nahost"
- Monatsnamen und generische Begriffe weglassen

JSON: [{{"normalform": "...", "typ": "Person|Organisation|Ort|Konzept", "aliases": [...]}}]

Text:
{text}"""

NORMALIZE_PROMPT = """\
{few_shot_block}Bereinige diese Entitäts-Kandidaten aus einem historischen Text.
Für jeden Kandidaten:
- normalform: Eigenname bereinigt (Großschreibung, OCR-Fehler korrigiert)
- typ: Person / Organisation / Ort / Konzept — nutze Hinweis als Orientierung
- aliases: alle bekannten Schreibweisen inkl. Titeln als Aliases

Regeln:
- Normalform = Name selbst, KEINE Beschreibung
  RICHTIG: "Ismail Enver", "Damaskus", "CUP"
  FALSCH: "türkischer Offizier", "Hauptstadt Syriens"
- Titel (Pasha, Bey, Pascha, Sultan, Effendi, Vizier, Emir, Khedive) in aliases, nicht in normalform
- OCR-Fehler korrigieren wenn offensichtlich
- Weglassen wenn kein Eigenname (Monatsnamen, generische Begriffe, alleinstehende Titel)
- typ MUSS exakt: Person, Organisation, Ort oder Konzept

Antworte als JSON-Array ([] wenn alles verworfen):
[{{"normalform": "...", "typ": "Person|Organisation|Ort|Konzept", "aliases": [...]}}]

Kandidaten:
{kandidaten}"""

EXTRACT_TEMPLATE = """\
{few_shot_block}Extrahiere alle Eigennamen aus diesem historischen Text.

Regeln:
- Normalform = der Name selbst, KEINE Beschreibung
- Titel (Pasha, Bey, Effendi usw.) nicht zur Normalform
- aliases = alle Schreibweisen wie der Name im Text vorkommt
- Nur eindeutige Eigennamen, keine generischen Begriffe

Antworte als JSON-Array (leer [] wenn keine Eigennamen):
[{{"normalform": "...", "typ": "Person|Organisation|Ort|Konzept", "aliases": [...]}}]

Text:
{text}"""


def _find_context_sentences(token: str, content_segs: list[dict], max_n: int = 3) -> list[str]:
    token_lc = token.lower()
    hits: list[str] = []
    for seg in content_segs:
        if token_lc in seg.get("text", "").lower():
            hits.append(seg["text"])
            if len(hits) >= max_n:
                break
    return hits


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
    batches      = [sample[i:i + ITER1_BATCH] for i in range(0, len(sample), ITER1_BATCH)]
    few_shot     = _build_few_shot_block(seed)

    print(f"Iteration 1: {len(sample)} Segmente in {len(batches)} Batches …")
    results: list[dict] = []

    for idx, batch in enumerate(batches):
        text   = "\n---\n".join(s.get("text", "") for s in batch)
        prompt = ITER1_PROMPT.format(few_shot_block=few_shot, text=text)
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)
        try:
            out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  JSON-Fehler: {e}", file=sys.stderr)
            out = None

        # Ollama mit format:json gibt manchmal einzelnes Objekt statt Array
        if isinstance(out, dict) and "normalform" in out:
            out = [out]
        if isinstance(out, list):
            for ent in out:
                if isinstance(ent, dict):
                    n = _normalize_entity(ent, "llm_iter1", rejected_lc)
                    if n is not None:
                        results.append(n)
        elif out is not None:
            print(f"  Batch {idx + 1}: kein Array ({type(out).__name__})", file=sys.stderr)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {"iter1_entities": results})

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
        prompt = NORMALIZE_PROMPT.format(few_shot_block=few_shot, kandidaten=kandidaten)
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)

        out = None
        for attempt in range(2):   # einmal versuchen, einmal wiederholen
            try:
                out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"  JSON-Fehler Batch {idx + 1} (Versuch {attempt + 1}): {e}",
                      file=sys.stderr)
                out = None
            if isinstance(out, list):
                break
            if attempt == 0:
                print(f"  Retry Batch {idx + 1} …", flush=True)

        # Ollama mit format:json gibt manchmal einzelnes Objekt statt Array
        if isinstance(out, dict) and "normalform" in out:
            out = [out]
        if isinstance(out, list):
            for ent in out:
                if isinstance(ent, dict):
                    norm_lc = (ent.get("normalform") or "").lower()
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
                n = _normalize_entity(dict(c), "llm_task1", rejected_lc)
                if n is not None:
                    accumulated.append(n)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {
                "stageB1_batch": idx + 1,
                "stageB1_entities": accumulated,
            })

    print(f"  {len(accumulated)} Entities nach Task B1")
    return accumulated


# ══════════════════════════════════════════════════════════════════════════════
# Neue Pipeline (Schritte 2–3)
# ══════════════════════════════════════════════════════════════════════════════

DEDUP_BATCH_PROMPT = """\
Prüfe diese {n} Kandidatenpaare aus einem historischen Text.
Sind A und B jeweils dieselbe Entity (Schreibvariante, Kurzform, Transliteration)?

{pairs_block}

Regeln:
- Nur zusammenführen wenn eindeutig gleich. Im Zweifel: keep.
- Bei merge: "winner" = "a" wenn A die bessere Normalform ist, sonst "b".

JSON-Array, ein Eintrag pro Paar in gleicher Reihenfolge:
[
  {{"pair": 1, "action": "keep"}},
  {{"pair": 2, "action": "merge", "winner": "a"}}
]"""


def _levenshtein(a: str, b: str) -> int:
    """Einfache Levenshtein-Distanz ohne externe Abhängigkeit."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for ca in a:
        curr = [prev[0] + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j] + (0 if ca == cb else 1),
                            curr[j] + 1, prev[j + 1] + 1))
        prev = curr
    return prev[-1]


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
    batches      = [content_segs[i:i + batch_size]
                    for i in range(0, len(content_segs), batch_size)]
    few_shot     = _build_few_shot_block(seed)   # begrenzt intern auf seed[:10]
    results      = list(accumulated) if accumulated else []

    print(f"Schritt 2 (Vollextraktion): {len(content_segs)} Segmente "
          f"in {len(batches)} Batches à {batch_size} …")
    if resume_from:
        print(f"  Resume ab Batch {resume_from + 1}")

    for idx, batch in enumerate(batches):
        if idx < resume_from:
            continue

        text   = "\n---\n".join(s.get("text", "") for s in batch)
        prompt = EXTRACT_TEMPLATE.format(few_shot_block=few_shot, text=text)
        print(f"  Batch {idx + 1}/{len(batches)} …", flush=True)
        try:
            out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  JSON-Fehler Batch {idx + 1}: {e}", file=sys.stderr)
            out = None

        if isinstance(out, list):
            for ent in out:
                if isinstance(ent, dict):
                    n = _normalize_entity(ent, "llm_full", rejected_lc)
                    if n is not None:
                        results.append(n)
        elif out is not None:
            print(f"  Batch {idx + 1}: kein Array", file=sys.stderr)

        if checkpoint_path and (idx + 1) % SAVE_INTERVAL == 0:
            _save_checkpoint(checkpoint_path, {
                "step2_batch":    idx + 1,
                "step2_entities": results,
            })

    print(f"  {len(results)} Entities aus Vollextraktion")
    return results


def _llm_dedup(
    entities: list[dict],
    provider,
    content_segs: list[dict],
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Schritt 3: Duplikat-Erkennung – alle verdächtigen Paare in einem LLM-Request."""

    def _names(e: dict) -> set[str]:
        result = {(e.get("normalform") or "").lower()}
        for a in (e.get("aliases") or []):
            if a:
                result.add(a.lower())
        return result - {""}

    # Kandidatenpaare finden: Levenshtein < 3 auf Normalformen oder Alias-Überschneidung
    pairs: list[tuple[int, int]] = []
    for i in range(len(entities)):
        na       = (entities[i].get("normalform") or "").lower()
        aliases_i = _names(entities[i])
        for j in range(i + 1, len(entities)):
            nb = (entities[j].get("normalform") or "").lower()
            if _levenshtein(na, nb) < 3 or (aliases_i & _names(entities[j])):
                pairs.append((i, j))

    if not pairs:
        print("Schritt 3 (Dedup): keine Kandidatenpaare gefunden")
        return entities

    print(f"Schritt 3 (Dedup): {len(pairs)} Paare in einem LLM-Request …")

    # Alle Paare mit Kontext formatieren
    pair_blocks: list[str] = []
    for pair_idx, (i, j) in enumerate(pairs, 1):
        ea, eb    = entities[i], entities[j]
        ctx_a     = _find_context_sentences(ea["normalform"], content_segs, max_n=2)
        ctx_b     = _find_context_sentences(eb["normalform"], content_segs, max_n=2)
        ctx_a_str = " | ".join(ctx_a) if ctx_a else "(kein Kontext)"
        ctx_b_str = " | ".join(ctx_b) if ctx_b else "(kein Kontext)"
        pair_blocks.append(
            f"Paar {pair_idx}:\n"
            f"  A: \"{ea['normalform']}\" (Typ: {ea.get('typ', '?')})\n"
            f"  B: \"{eb['normalform']}\" (Typ: {eb.get('typ', '?')})\n"
            f"  Kontext A: {ctx_a_str}\n"
            f"  Kontext B: {ctx_b_str}"
        )

    prompt = DEDUP_BATCH_PROMPT.format(
        n=len(pairs),
        pairs_block="\n\n".join(pair_blocks),
    )
    try:
        out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"  JSON-Fehler Dedup: {e} — übersprungen", file=sys.stderr)
        return entities

    if not isinstance(out, list):
        print(f"  Dedup: kein Array zurück ({type(out).__name__}) — übersprungen",
              file=sys.stderr)
        return entities

    # Entscheidungen indexieren (pair-Nummer 1-basiert)
    decisions: dict[int, dict] = {
        dec["pair"]: dec
        for dec in out
        if isinstance(dec, dict) and isinstance(dec.get("pair"), int)
    }

    to_remove: set[int] = set()
    updated   = list(entities)
    n_merged  = 0

    for pair_idx, (i, j) in enumerate(pairs, 1):
        if i in to_remove or j in to_remove:
            continue
        dec = decisions.get(pair_idx, {})
        if dec.get("action") != "merge":
            continue

        ea, eb = updated[i], updated[j]

        # winner bestimmt welche Normalform/Typ gewinnt; Aliases aus beiden zusammenführen
        winner = dec.get("winner", "a")
        primary, secondary = (ea, eb) if winner != "b" else (eb, ea)

        all_aliases = list({
            *(primary.get("aliases")   or []),
            *(secondary.get("aliases") or []),
            secondary.get("normalform", ""),
        })
        all_aliases = [a for a in all_aliases if a and a != primary["normalform"]]

        updated[i] = {
            "normalform": primary["normalform"],
            "typ":        primary.get("typ", "Konzept"),
            "aliases":    all_aliases,
            "_source":    "llm_dedup",
        }
        to_remove.add(j)
        n_merged += 1
        print(f"  Merge {pair_idx}: {ea['normalform']!r} + {eb['normalform']!r} "
              f"→ {updated[i]['normalform']!r} (winner={winner})")

    result = [e for idx, e in enumerate(updated) if idx not in to_remove]
    print(f"  {len(entities)} → {len(result)} Entities nach Dedup "
          f"({n_merged} zusammengeführt)")
    return result
