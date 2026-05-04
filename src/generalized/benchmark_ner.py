"""
benchmark_ner.py — LLM-Pipeline vs. GLiNER NER-Vergleich auf Projekt-Segmenten.

System A: bestehende LLM-Pipeline (Schritt 1 Sample + Schritt 3 Group + Schritt 4 Normalize)
System B: GLiNER urchade/gliner_multi (multilingual)

Beide Systeme laufen auf denselben N zufälligen Segmenten.
Kein Schreiben in Projekt-Dateien — nur stdout.

CLI:
  python -m src.generalized.benchmark_ner \\
    --project <id> --document <doc_id> \\
    [--n 30] [--threshold 0.5] [--seed 42]
"""

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from src.generalized.config import PROJECTS_DIR, ROOT
from src.generalized.entity_utils import VALID_TYPES, _merge

LABELS    = ["Person", "Organisation", "Ort", "Konzept"]
MAX_CHARS = 2000


# ── Chunking (analog entity_llm.py) ──────────────────────────────────────────

def _chunk(text: str, max_chars: int = MAX_CHARS) -> list[str]:
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


# ── Dedup: case-insensitive, höchster Score gewinnt ──────────────────────────

def _dedup(raw: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in raw:
        key = (e.get("normalform") or "").strip().lower()
        if not key:
            continue
        if key not in seen:
            seen[key] = dict(e)
        else:
            if (e.get("score") or 0.0) > (seen[key].get("score") or 0.0):
                seen[key]["score"] = e["score"]
            existing_lc = {a.lower() for a in seen[key].get("aliases", [])}
            for a in e.get("aliases", []):
                if a and a.lower() not in existing_lc:
                    seen[key].setdefault("aliases", []).append(a)
                    existing_lc.add(a.lower())
    return list(seen.values())


# ── Seed + Rejected laden (analog extract_entities_v2.py) ────────────────────

def _load_seed_and_rejected(doc_dir: Path) -> tuple[list[dict], set[str]]:
    seed: list[dict] = []
    config_p = doc_dir.parent.parent / "config.json"
    if config_p.exists():
        try:
            cfg_entities = json.loads(config_p.read_text(encoding="utf-8")).get("entities") or []
            if cfg_entities:
                seed = [dict(e, _source="seed") for e in cfg_entities]
                print(f"  Seed: {len(seed)} bestätigte Entities aus config.json")
        except (json.JSONDecodeError, OSError):
            pass
    if not seed:
        print("  Kein Seed gefunden — Few-Shot ohne Beispiele")

    rejected_lc: set[str] = set()
    rejected_p = doc_dir / "entities_rejected.json"
    if rejected_p.exists():
        for e in json.loads(rejected_p.read_text(encoding="utf-8")):
            norm = (e.get("normalform") or "").lower()
            if norm:
                rejected_lc.add(norm)
        print(f"  Rejected: {len(rejected_lc)} Normalformen gefiltert")

    return seed, rejected_lc


# ── System A: LLM-Pipeline (Schritte 1 + 3 + 4) ──────────────────────────────

def run_llm(
    segments: list[dict],
    seed: list[dict],
    rejected_lc: set[str],
) -> tuple[list[dict], float]:
    from src.generalized.llm import get_provider, TASK_EXTRACT
    from src.generalized.entity_llm import (
        _llm_sample_iteration,
        _llm_group,
        _llm_task1_normalize,
    )

    load_dotenv(ROOT / ".env")
    try:
        provider = get_provider(task=TASK_EXTRACT)
    except Exception as exc:
        print(f"  FEHLER: Provider konnte nicht geladen werden: {exc}", file=sys.stderr)
        return [], 0.0

    t0 = time.perf_counter()

    # Schritt 1: Stichprobe (läuft auf genau den übergebenen Segmenten)
    print(f"  Schritt 1: Sample-Iteration …")
    step1 = _llm_sample_iteration(segments, provider, seed, None, rejected_lc)

    # Schritt 3: Schreibvarianten gruppieren
    print(f"  Schritt 3: Gruppieren …")
    step3 = _llm_group(step1, provider, rejected_lc)

    # Schritt 4: Normalform bereinigen
    print(f"  Schritt 4: Normalisieren …")
    step4 = _llm_task1_normalize(step3, provider, seed, None, rejected_lc=rejected_lc)

    elapsed = time.perf_counter() - t0

    # Score-Felder für einheitliche Ausgabe ergänzen (LLM liefert keinen Score)
    for e in step4:
        e.setdefault("score", None)

    return _dedup(step4), elapsed


# ── System B: GLiNER ──────────────────────────────────────────────────────────

def run_gliner(segments: list[dict], threshold: float) -> tuple[list[dict], float]:
    try:
        from gliner import GLiNER
    except ImportError:
        print("  FEHLER: gliner nicht installiert.\n"
              "  pip install gliner --break-system-packages", file=sys.stderr)
        return [], 0.0

    print("  Modell: urchade/gliner_multi (lädt …)")
    load_start = time.perf_counter()
    model = GLiNER.from_pretrained("urchade/gliner_multi")
    print(f"  Modell geladen in {time.perf_counter() - load_start:.1f}s")

    t0  = time.perf_counter()
    raw: list[dict] = []

    for seg in segments:
        text = seg.get("text", "")
        if not text:
            continue
        for chunk in _chunk(text):
            try:
                entities = model.predict_entities(chunk, LABELS, threshold=threshold)
            except Exception as exc:
                print(f"  WARNING: GLiNER Fehler: {exc}", file=sys.stderr)
                continue
            for ent in entities:
                typ  = ent["label"] if ent["label"] in VALID_TYPES else "Konzept"
                norm = ent["text"].strip()
                if norm:
                    raw.append({
                        "normalform": norm,
                        "typ":        typ,
                        "aliases":    [],
                        "score":      round(ent["score"], 3),
                    })

    elapsed = time.perf_counter() - t0
    return _dedup(raw), elapsed


# ── Ausgabe ───────────────────────────────────────────────────────────────────

def _fmt_score(score) -> str:
    return f"{score:.3f}" if score is not None else "  N/A"


def _type_conflicts(entities: list[dict]) -> list[tuple[str, str, str]]:
    seen: dict[str, str] = {}
    conflicts = []
    for e in entities:
        key = (e.get("normalform") or "").lower()
        typ = e.get("typ", "")
        if key in seen and seen[key] != typ:
            conflicts.append((e.get("normalform", ""), seen[key], typ))
        else:
            seen[key] = typ
    return conflicts


def print_system_report(label: str, entities: list[dict], elapsed: float) -> None:
    W = 64
    print(f"\n{'═' * W}")
    print(f"  System {label}")
    print(f"{'═' * W}")
    print(f"  Gefunden : {len(entities)} Entities   Laufzeit: {elapsed:.1f}s")

    dist  = Counter(e.get("typ", "?") for e in entities)
    parts = [f"{t}: {dist.get(t, 0)}" for t in ["Person", "Organisation", "Ort", "Konzept"]]
    print(f"  Typen    : {' | '.join(parts)}")

    conflicts = _type_conflicts(entities)
    if conflicts:
        print(f"\n  Typ-Konflikte ({len(conflicts)}):")
        for name, t1, t2 in conflicts:
            print(f"    ⚠  {name}  →  {t1} / {t2}")

    print(f"\n  {'Normalform':<38} {'Typ':<16} Score")
    print(f"  {'-'*38} {'-'*16} {'-'*5}")
    for e in sorted(entities, key=lambda x: (x.get("typ", ""), x.get("normalform", "").lower())):
        name = (e.get("normalform") or "")[:37]
        print(f"  {name:<38} {e.get('typ', ''):<16} {_fmt_score(e.get('score'))}")


def print_comparison(
    a_ents: list[dict], b_ents: list[dict],
    name_a: str, name_b: str,
) -> None:
    W = 64
    a_map = {(e.get("normalform") or "").lower(): e for e in a_ents}
    b_map = {(e.get("normalform") or "").lower(): e for e in b_ents}

    only_a = [e for k, e in a_map.items() if k not in b_map]
    only_b = [e for k, e in b_map.items() if k not in a_map]
    both_a = [e for k, e in a_map.items() if k in b_map]

    print(f"\n{'═' * W}")
    print(f"  Vergleich")
    print(f"{'═' * W}")
    print(f"  Beide gefunden : {len(both_a):3d}")
    print(f"  Nur {name_a:<10}: {len(only_a):3d}")
    print(f"  Nur {name_b:<10}: {len(only_b):3d}")

    if both_a:
        print(f"\n  ✓ Beide ({len(both_a)}):")
        for e in sorted(both_a, key=lambda x: x.get("normalform", "").lower()):
            key     = (e.get("normalform") or "").lower()
            b_e     = b_map[key]
            typ_a   = e.get("typ", "")
            typ_b   = b_e.get("typ", "")
            conflict = f"  ⚠ {name_a}={typ_a} / {name_b}={typ_b}" if typ_a != typ_b else ""
            name    = (e.get("normalform") or "")[:37]
            gliner_score = _fmt_score(b_e.get("score"))
            print(f"    {name:<38} {typ_a:<16} {name_b}={gliner_score}{conflict}")

    if only_a:
        print(f"\n  → Nur {name_a} ({len(only_a)}):")
        for e in sorted(only_a, key=lambda x: x.get("normalform", "").lower()):
            name = (e.get("normalform") or "")[:37]
            print(f"    {name:<38} {e.get('typ', '')}")

    if only_b:
        print(f"\n  → Nur {name_b} ({len(only_b)}):")
        for e in sorted(only_b, key=lambda x: x.get("normalform", "").lower()):
            name = (e.get("normalform") or "")[:37]
            print(f"    {name:<38} {e.get('typ', ''):<16} score={_fmt_score(e.get('score'))}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LLM-Pipeline vs. GLiNER NER-Benchmark auf Projekt-Segmenten"
    )
    ap.add_argument("--project",   required=True,               help="Projekt-ID")
    ap.add_argument("--document",  required=True,               help="Dokument-ID")
    ap.add_argument("--n",         type=int,   default=30,      help="Anzahl Segmente (default: 30)")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="GLiNER Confidence-Schwelle (default: 0.5)")
    ap.add_argument("--seed",      type=int,   default=42,      help="Random-Seed (default: 42)")
    args = ap.parse_args()

    doc_dir  = PROJECTS_DIR / args.project / "documents" / args.document
    seg_path = doc_dir / "segments.json"

    if not seg_path.exists():
        print(f"FEHLER: {seg_path} nicht gefunden", file=sys.stderr)
        sys.exit(1)

    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    content  = [s for s in segments
                if s.get("type") == "content" and (s.get("text") or "").strip()]
    if not content:
        print("FEHLER: Keine content-Segmente gefunden", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)
    sample = random.sample(content, min(args.n, len(content)))

    seed, rejected_lc = _load_seed_and_rejected(doc_dir)

    print()
    print("NER-Benchmark: LLM-Pipeline vs. GLiNER")
    print(f"  Projekt   : {args.project}/{args.document}")
    print(f"  Segmente  : {len(sample)} von {len(content)} content-Segmenten")
    print(f"  Threshold : {args.threshold}  (nur GLiNER)")
    print(f"  Seed      : {args.seed}")

    print(f"\n[System A: LLM-Pipeline (Schritte 1 + 3 + 4)]")
    a_ents, a_time = run_llm(sample, seed, rejected_lc)

    print(f"\n[System B: GLiNER  threshold={args.threshold}]")
    b_ents, b_time = run_gliner(sample, args.threshold)

    print_system_report("A  (LLM)",                     a_ents, a_time)
    print_system_report(f"B  (GLiNER θ={args.threshold})", b_ents, b_time)
    print_comparison(a_ents, b_ents, "LLM", "GLiNER")
    print()


if __name__ == "__main__":
    main()
