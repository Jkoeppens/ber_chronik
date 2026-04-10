"""
entity_llm.py — LLM-basierte Entity-Extraktion und Bereinigung.

Aktiv genutzt (4-Schritte-Pipeline):
  - Schritt 1: _llm_sample_iteration
  - Schritt 2: _llm_full_extract
  - Schritt 3: _llm_dedup
  - Schritt 4: _llm_task1_normalize

DEPRECATED (Altpipeline Stufe B/2b, nicht mehr aufgerufen):
  - _llm_task2_validate_aliases
  - _llm_task3_clarify_types
  - _llm_extract_uncovered
  - _select_uncovered_stratified
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
SEGMENT_BATCH    = 5   # DEPRECATED – nicht mehr verwendet
SAMPLE_SEGS      = 50
ITER1_BATCH      = 10
SAMPLE_UNCOVERED = 30  # DEPRECATED – nicht mehr verwendet
SAVE_INTERVAL    = 10

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

# DEPRECATED – nicht mehr verwendet
ALIAS_VALIDATE_PROMPT = """\
Sind diese Namen Varianten DESSELBEN Individuums oder verschiedene Personen/Orte?

Kandidat: "{normalform}" (Typ: {typ})
Bekannte Schreibweisen: {aliases}

Wichtig: Muhammad und Mahmud sind verschiedene Namen – nur zusammenführen wenn
eindeutig dieselbe Person/derselbe Ort gemeint ist (z.B. verschiedene Schreibweisen
desselben Namens, Kurzform + Vollform, oder Transliterationsvarianten).
Im Zweifel: split.

Kontext (Sätze aus dem Text):
{context}

Antworte als JSON:
- Alle gleich (eine Entity): {{"action": "keep", "normalform": "...", "typ": "...", "aliases": [...]}}
- Verschiedene Entities: {{"action": "split", "entities": [{{"normalform": "...", "typ": "...", "aliases": [...]}}]}}"""

# DEPRECATED – nicht mehr verwendet
CLARIFY_TYPE_PROMPT = """\
Bestimme den Typ dieser Entität in diesem historischen Kontext.
Typ MUSS exakt einer von: Person, Organisation, Ort, Konzept

Kandidat: "{normalform}"
Bisheriger Typ (unsicher): {current_typ}

Kontext:
{context}

JSON: {{"typ": "Person|Organisation|Ort|Konzept"}}"""

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


# DEPRECATED – nicht mehr verwendet
def _llm_task2_validate_aliases(
    candidates: list[dict],
    provider,
    content_segs: list[dict],
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    """Task B2: Alias-Validierung für Kandidaten mit ≥2 Aliases."""
    to_validate = [c for c in candidates if len(c.get("aliases", [])) >= 2]
    other       = [c for c in candidates if len(c.get("aliases", [])) < 2]

    if not to_validate:
        print("Task B2 (Alias-Validierung): keine Kandidaten mit ≥2 Aliases")
        return candidates

    print(f"Task B2 (Alias-Validierung): {len(to_validate)} Kandidaten (≥2 Aliases) …")
    result = list(other)

    for cand in to_validate:
        ctx   = _find_context_sentences(cand["normalform"], content_segs)
        ctx_s = "\n".join(f"- {s}" for s in ctx) if ctx else "(kein Kontext gefunden)"
        prompt = ALIAS_VALIDATE_PROMPT.format(
            normalform=cand["normalform"],
            typ=cand.get("typ", "?"),
            aliases=", ".join(f'"{a}"' for a in cand["aliases"]),
            context=ctx_s,
        )
        try:
            out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Fehler bei {cand['normalform']!r}: {e}", file=sys.stderr)
            result.append(cand)
            continue

        if not isinstance(out, dict):
            result.append(cand)
            continue

        if out.get("action") == "split":
            for ent in out.get("entities", []):
                if isinstance(ent, dict):
                    n = _normalize_entity(ent, "llm_task2", rejected_lc)
                    if n:
                        result.append(n)
        else:
            cand["normalform"] = out.get("normalform", cand["normalform"])
            cand["aliases"]    = out.get("aliases",    cand["aliases"])
            if out.get("typ") in VALID_TYPES:
                cand["typ"] = out["typ"]
            result.append(cand)

    print(f"  {len(result)} Entities nach Task B2")
    return result


# DEPRECATED – nicht mehr verwendet
def _llm_task3_clarify_types(
    candidates: list[dict],
    provider,
    content_segs: list[dict],
) -> list[dict]:
    """Task B3: Typ klären für mBERT-Kandidaten mit Konfidenz < CLASSIFIER_CONF."""
    CLASSIFIER_CONF = 0.6  # ehemals aus entity_classifier importiert
    uncertain = [
        c for c in candidates
        if c.get("_confidence") is not None and c["_confidence"] < CLASSIFIER_CONF
    ]
    if not uncertain:
        print("Task B3 (Typ klären): keine unsicheren Kandidaten")
        return candidates

    print(f"Task B3 (Typ klären): {len(uncertain)} unsichere Kandidaten …")
    uncertain_lc = {c["normalform"].lower() for c in uncertain}

    updated: list[dict] = []
    for cand in candidates:
        if cand.get("normalform", "").lower() not in uncertain_lc:
            updated.append(cand)
            continue
        ctx   = _find_context_sentences(cand["normalform"], content_segs)
        ctx_s = "\n".join(f"- {s}" for s in ctx) if ctx else "(kein Kontext)"
        prompt = CLARIFY_TYPE_PROMPT.format(
            normalform=cand["normalform"],
            current_typ=cand.get("typ", "?"),
            context=ctx_s,
        )
        try:
            out = provider.complete_json(prompt, system=SYSTEM_PROMPT)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Fehler bei {cand['normalform']!r}: {e}", file=sys.stderr)
            updated.append(cand)
            continue

        if isinstance(out, dict) and out.get("typ") in VALID_TYPES:
            cand["typ"] = out["typ"]
        updated.append(cand)

    print(f"  Task B3 abgeschlossen")
    return updated


# DEPRECATED – nicht mehr verwendet
def _select_uncovered_stratified(
    uncovered: list[dict],
    max_segs: int,
    seed: list[dict],
    found_by_type: dict[str, int],
) -> list[dict]:
    UNDERREP_THRESHOLD = 0.90

    seed_dist  = Counter(e.get("typ", "?") for e in seed)
    total_seed = sum(seed_dist.values()) or 1
    total_found = sum(found_by_type.values()) or 1

    underrep = [
        t for t in VALID_TYPES
        if seed_dist.get(t, 0) > 0
        and found_by_type.get(t, 0) / total_found
            < seed_dist[t] / total_seed * UNDERREP_THRESHOLD
    ]

    if not underrep:
        return random.sample(uncovered, min(max_segs, len(uncovered)))

    print(f"  Stage 2b stratifiziert: unterrepräsentiert = {underrep}")

    aliases_by_type: dict[str, list[str]] = {t: [] for t in underrep}
    for ent in seed:
        t = ent.get("typ", "")
        if t not in aliases_by_type:
            continue
        names = [ent.get("normalform", "")] + list(ent.get("aliases") or [])
        for n in names:
            n = n.strip()
            if n:
                aliases_by_type[t].append(n.lower())

    scored:   list[tuple[dict, int]] = []
    unscored: list[dict]             = []
    for seg in uncovered:
        text_lc = seg.get("text", "").lower()
        score = sum(
            1 for t in underrep
            for alias in aliases_by_type[t]
            if alias and alias in text_lc
        )
        (scored if score > 0 else unscored).append(
            (seg, score) if score > 0 else seg
        )

    scored.sort(key=lambda x: -x[1])

    n_scored  = min(len(scored), max(1, max_segs // 2))
    selected  = [s for s, _ in scored[:n_scored]]
    remaining = max_segs - len(selected)
    if remaining > 0 and unscored:
        selected += random.sample(unscored, min(remaining, len(unscored)))

    type_hits = Counter(
        t for seg, _ in scored[:n_scored]
        for t in underrep
        if any(a in seg.get("text", "").lower() for a in aliases_by_type[t])
    )
    print(f"  Scored Pool: {n_scored} Segmente  "
          + "  ".join(f"{t}:{type_hits.get(t,0)}" for t in underrep))
    return selected


# DEPRECATED – nicht mehr verwendet
def _llm_extract_uncovered(
    segments: list[dict],
    uncovered_idx: set[int],
    provider,
    seed: list[dict],
    checkpoint_path: Path | None,
    max_segs: int | None,
    found_by_type: dict[str, int] | None = None,
    rejected_lc: set[str] = frozenset(),
) -> list[dict]:
    uncovered = [s for i, s in enumerate(segments)
                 if i in uncovered_idx and s.get("type") == "content"]
    if max_segs is not None:
        if found_by_type is not None:
            uncovered = _select_uncovered_stratified(
                uncovered, max_segs, seed, found_by_type
            )
        else:
            uncovered = random.sample(uncovered, min(max_segs, len(uncovered)))

    batches  = [uncovered[i:i + SEGMENT_BATCH]
                for i in range(0, len(uncovered), SEGMENT_BATCH)]
    few_shot = _build_few_shot_block(seed)

    print(f"Stufe 2b: {len(uncovered)} Segmente ohne Treffer "
          f"in {len(batches)} Batches à {SEGMENT_BATCH} …")
    results: list[dict] = []

    for idx, batch in enumerate(batches):
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
                    n = _normalize_entity(ent, "llm_uncovered", rejected_lc)
                    if n is not None:
                        results.append(n)
        elif out is not None:
            print(f"  Batch {idx + 1}: kein Array", file=sys.stderr)

    print(f"  {len(results)} Entities aus nicht abgedeckten Segmenten")
    return results


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
