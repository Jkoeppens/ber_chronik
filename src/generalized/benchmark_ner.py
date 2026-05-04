"""
benchmark_ner.py — LLM-Pipeline vs. GLiNER vs. Hybrid NER-Vergleich.

System A: LLM-Pipeline (Schritt 1 Sample + Schritt 3 Group + Schritt 4 Normalize)
System B: GLiNER urchade/gliner_multi  (θ=args.threshold, breite Labels)
System C: GLiNER θ=0.7 + verfeinerte Labels → _llm_group() Deduplizierung

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

LABELS        = ["Person", "Organisation", "Ort", "Konzept"]
MAX_CHARS     = 2000

# System C: spezifischere Labels → bessere Distinktion
HYBRID_LABELS = [
    "Person",
    "Organisation",
    "geographischer Ort",
    "politische Bewegung",
    "religiöse Institution",
    "Zeitung oder Publikation",
]

# Mapping der verfeinerten Labels auf VALID_TYPES
_HYBRID_LABEL_MAP: dict[str, str] = {
    "Person":                   "Person",
    "Organisation":             "Organisation",
    "geographischer Ort":       "Ort",
    "politische Bewegung":      "Organisation",
    "religiöse Institution":    "Organisation",
    "Zeitung oder Publikation": "Organisation",
}
HYBRID_THRESHOLD = 0.7


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


# ── Seed + Rejected laden ─────────────────────────────────────────────────────

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


# ── GLiNER Modell laden (einmalig, für B + C gemeinsam) ──────────────────────

def _load_gliner_model():
    try:
        from gliner import GLiNER
    except ImportError:
        print("  FEHLER: gliner nicht installiert.\n"
              "  pip install gliner --break-system-packages", file=sys.stderr)
        return None, 0.0
    print("  GLiNER-Modell: urchade/gliner_multi (lädt …)")
    t0    = time.perf_counter()
    model = GLiNER.from_pretrained("urchade/gliner_multi")
    load_time = time.perf_counter() - t0
    print(f"  Modell geladen in {load_time:.1f}s")
    return model, load_time


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

    print("  Schritt 1: Sample-Iteration …")
    step1 = _llm_sample_iteration(segments, provider, seed, None, rejected_lc)

    print("  Schritt 3: Gruppieren …")
    step3 = _llm_group(step1, provider, rejected_lc)

    print("  Schritt 4: Normalisieren …")
    step4 = _llm_task1_normalize(step3, provider, seed, None, rejected_lc=rejected_lc)

    elapsed = time.perf_counter() - t0
    for e in step4:
        e.setdefault("score", None)
    return _dedup(step4), elapsed


# ── System B: GLiNER (breite Labels, variabler Threshold) ────────────────────

def run_gliner(
    segments: list[dict],
    threshold: float,
    model,
) -> tuple[list[dict], float]:
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

    return _dedup(raw), time.perf_counter() - t0


# ── System C: GLiNER (verfeinerte Labels, θ=0.7) + LLM-Group ────────────────

def run_hybrid(
    segments: list[dict],
    rejected_lc: set[str],
    model,
) -> tuple[list[dict], list[dict], float, float]:
    """
    Gibt zurück: (vor_group, nach_group, gliner_time, group_time)
    """
    from src.generalized.llm import get_provider, TASK_EXTRACT
    from src.generalized.entity_llm import _llm_group

    load_dotenv(ROOT / ".env")
    try:
        provider = get_provider(task=TASK_EXTRACT)
    except Exception as exc:
        print(f"  FEHLER: Provider konnte nicht geladen werden: {exc}", file=sys.stderr)
        return [], [], 0.0, 0.0

    # Phase 1: GLiNER mit verfeinerten Labels
    t0  = time.perf_counter()
    raw: list[dict] = []

    for seg in segments:
        text = seg.get("text", "")
        if not text:
            continue
        for chunk in _chunk(text):
            try:
                entities = model.predict_entities(chunk, HYBRID_LABELS, threshold=HYBRID_THRESHOLD)
            except Exception as exc:
                print(f"  WARNING: GLiNER Fehler: {exc}", file=sys.stderr)
                continue
            for ent in entities:
                label = ent["label"]
                typ   = _HYBRID_LABEL_MAP.get(label, "Konzept")
                norm  = ent["text"].strip()
                if norm:
                    raw.append({
                        "normalform": norm,
                        "typ":        typ,
                        "aliases":    [],
                        "score":      round(ent["score"], 3),
                        "_gliner_label": label,
                    })

    before_group = _dedup(raw)
    gliner_time  = time.perf_counter() - t0

    # Phase 2: LLM-Group für Deduplizierung + Synonyme
    print(f"  LLM-Group: {len(before_group)} Entities → gruppieren …")
    t1          = time.perf_counter()
    after_group = _llm_group(before_group, provider, rejected_lc)
    group_time  = time.perf_counter() - t1

    # Score aus GLiNER-Phase auf gruppierte Entities übertragen
    before_map = {(e.get("normalform") or "").lower(): e for e in before_group}
    for e in after_group:
        key = (e.get("normalform") or "").lower()
        if key in before_map:
            e.setdefault("score", before_map[key].get("score"))
        else:
            e.setdefault("score", None)

    return before_group, after_group, gliner_time, group_time


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


def _print_entity_table(entities: list[dict]) -> None:
    print(f"\n  {'Normalform':<38} {'Typ':<16} Score")
    print(f"  {'-'*38} {'-'*16} {'-'*5}")
    for e in sorted(entities, key=lambda x: (x.get("typ", ""), x.get("normalform", "").lower())):
        name = (e.get("normalform") or "")[:37]
        print(f"  {name:<38} {e.get('typ', ''):<16} {_fmt_score(e.get('score'))}")


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

    _print_entity_table(entities)


def print_hybrid_report(
    before: list[dict],
    after:  list[dict],
    gliner_time: float,
    group_time:  float,
) -> None:
    W = 64
    print(f"\n{'═' * W}")
    print(f"  System C  (Hybrid: GLiNER θ={HYBRID_THRESHOLD} + LLM-Group)")
    print(f"{'═' * W}")
    print(f"  GLiNER   : {len(before):3d} Entities   Laufzeit: {gliner_time:.1f}s")
    reduction = len(before) - len(after)
    print(f"  LLM-Group: {len(after):3d} Entities   Laufzeit: {group_time:.1f}s"
          f"   ({'-' if reduction >= 0 else '+'}{abs(reduction)} nach Gruppierung)")
    print(f"  Gesamt   :                  {gliner_time + group_time:.1f}s")

    dist  = Counter(e.get("typ", "?") for e in after)
    parts = [f"{t}: {dist.get(t, 0)}" for t in ["Person", "Organisation", "Ort", "Konzept"]]
    print(f"  Typen    : {' | '.join(parts)}")

    conflicts = _type_conflicts(after)
    if conflicts:
        print(f"\n  Typ-Konflikte ({len(conflicts)}):")
        for name, t1, t2 in conflicts:
            print(f"    ⚠  {name}  →  {t1} / {t2}")

    # Zeige vor/nach Gruppierung nebeneinander
    before_map = {(e.get("normalform") or "").lower(): e for e in before}
    after_keys = {(e.get("normalform") or "").lower() for e in after}
    collapsed = [e for k, e in before_map.items() if k not in after_keys]

    print(f"\n  Nach LLM-Group ({len(after)} Entities):")
    _print_entity_table(after)

    if collapsed:
        print(f"\n  Von LLM-Group zusammengeführt / entfernt ({len(collapsed)}):")
        for e in sorted(collapsed, key=lambda x: x.get("normalform", "").lower()):
            name = (e.get("normalform") or "")[:37]
            print(f"    {name:<38} {e.get('typ', ''):<16} {_fmt_score(e.get('score'))}")


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
    print(f"  Vergleich: {name_a} vs. {name_b}")
    print(f"{'═' * W}")
    print(f"  Beide gefunden : {len(both_a):3d}")
    print(f"  Nur {name_a:<10}: {len(only_a):3d}")
    print(f"  Nur {name_b:<10}: {len(only_b):3d}")

    if both_a:
        print(f"\n  ✓ Beide ({len(both_a)}):")
        for e in sorted(both_a, key=lambda x: x.get("normalform", "").lower()):
            key      = (e.get("normalform") or "").lower()
            b_e      = b_map[key]
            typ_a    = e.get("typ", "")
            typ_b    = b_e.get("typ", "")
            conflict = f"  ⚠ {name_a}={typ_a} / {name_b}={typ_b}" if typ_a != typ_b else ""
            name     = (e.get("normalform") or "")[:37]
            sc_b     = _fmt_score(b_e.get("score"))
            print(f"    {name:<38} {typ_a:<16} {name_b}={sc_b}{conflict}")

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


def print_speed_summary(
    a_time: float,
    b_time: float,
    gliner_load: float,
    c_gliner: float,
    c_group: float,
    threshold: float,
) -> None:
    W = 64
    print(f"\n{'═' * W}")
    print(f"  Geschwindigkeit & Kosten")
    print(f"{'═' * W}")
    print(f"  {'System':<28} {'Zeit':<10} {'Kosten'}")
    print(f"  {'-'*28} {'-'*10} {'-'*14}")
    print(f"  {'A  LLM-Pipeline':<28} {a_time:>6.1f}s    API (Sonnet)")
    print(f"  {'B  GLiNER θ='+str(threshold):<28} {b_time:>6.1f}s    lokal, kostenlos")
    print(f"  {'C  GLiNER θ=0.7 (Extract)':<28} {c_gliner:>6.1f}s    lokal")
    print(f"  {'C  LLM-Group':<28} {c_group:>6.1f}s    API (Sonnet)")
    print(f"  {'C  Gesamt':<28} {c_gliner+c_group:>6.1f}s")
    print(f"  {'GLiNER Ladezeit (einmalig)':<28} {gliner_load:>6.1f}s    (nicht mitgerechnet)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LLM-Pipeline vs. GLiNER vs. Hybrid NER-Benchmark"
    )
    ap.add_argument("--project",   required=True,             help="Projekt-ID")
    ap.add_argument("--document",  required=True,             help="Dokument-ID")
    ap.add_argument("--n",         type=int,   default=30,    help="Anzahl Segmente (default: 30)")
    ap.add_argument("--threshold", type=float, default=0.5,
                    help="GLiNER Confidence-Schwelle für System B (default: 0.5)")
    ap.add_argument("--seed",      type=int,   default=42,    help="Random-Seed (default: 42)")
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
    print("NER-Benchmark: LLM-Pipeline vs. GLiNER vs. Hybrid")
    print(f"  Projekt         : {args.project}/{args.document}")
    print(f"  Segmente        : {len(sample)} von {len(content)} content-Segmenten")
    print(f"  Threshold B     : {args.threshold}  (System B)")
    print(f"  Threshold C     : {HYBRID_THRESHOLD}  (System C, fest)")
    print(f"  Hybrid-Labels   : {', '.join(HYBRID_LABELS)}")
    print(f"  Seed            : {args.seed}")

    # ── System A ──
    print(f"\n[System A: LLM-Pipeline (Schritte 1 + 3 + 4)]")
    a_ents, a_time = run_llm(sample, seed, rejected_lc)

    # ── GLiNER einmalig laden ──
    print(f"\n[GLiNER-Modell laden (für B + C)]")
    gliner_model, gliner_load = _load_gliner_model()
    if gliner_model is None:
        sys.exit(1)

    # ── System B ──
    print(f"\n[System B: GLiNER θ={args.threshold}  Labels={LABELS}]")
    b_ents, b_time = run_gliner(sample, args.threshold, gliner_model)

    # ── System C ──
    print(f"\n[System C: GLiNER θ={HYBRID_THRESHOLD} + LLM-Group  Labels={HYBRID_LABELS}]")
    c_before, c_after, c_gliner_time, c_group_time = run_hybrid(
        sample, rejected_lc, gliner_model
    )

    # ── Reports ──
    print_system_report("A  (LLM)",                       a_ents, a_time)
    print_system_report(f"B  (GLiNER θ={args.threshold})", b_ents, b_time)
    print_hybrid_report(c_before, c_after, c_gliner_time, c_group_time)

    # ── Vergleiche ──
    print_comparison(a_ents, b_ents, "LLM", f"GLiNER-B")
    print_comparison(a_ents, c_after, "LLM", "Hybrid-C")

    # ── Speed-Summary ──
    print_speed_summary(a_time, b_time, gliner_load, c_gliner_time, c_group_time, args.threshold)
    print()


if __name__ == "__main__":
    main()
