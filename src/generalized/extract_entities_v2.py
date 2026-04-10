"""
extract_entities_v2.py — Entity-Erkennung: 4 LLM-Schritte

Schritt 1 – Stichprobe (immer):
  50 zufällige Content-Segmente, LLM extrahiert Entities mit Typ.

Schritt 2 – Vollextraktion mit Few-Shot (nur full-Modus, nur wenn Seed vorhanden):
  Alle Segmente in Batches à BATCH_SIZE, erste 10 Seed-Entities als Beispiele.

Schritt 3 – Duplikat-Erkennung:
  Levenshtein < 3 oder Alias-Überschneidung → ein LLM-Request für alle Paare.

Schritt 4 – Normalform bereinigen:
  Titel entfernen, Großschreibung korrigieren. Batches à 20.

Modi:
  --mode sample  Schritt 1 + 3 + 4
  --mode full    Schritt 1 + 2 (wenn Seed) + 3 + 4

Resume: nur im full-Modus über _v2_checkpoint.json, jeder Schritt einzeln.

Output: entities_proposal.json
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.generalized.llm import get_provider, TASK_EXTRACT
from src.generalized.entity_utils import (
    _merge,
    _print_stats,
    _save_checkpoint,
)
from src.generalized.entity_llm import (
    _llm_sample_iteration,
    _llm_full_extract,
    _llm_dedup,
    _llm_task1_normalize,
)

ROOT            = Path(__file__).resolve().parent.parent.parent
BATCH_SIZE      = 10          # Segmente pro Batch in Schritt 2
CHECKPOINT_NAME = "_v2_checkpoint.json"


def _run_stage(
    name: str,
    key: str,
    cp: dict,
    cp_path: Path | None,
    fn,
) -> list[dict]:
    """Checkpoint-Helper: liest gecachtes Ergebnis oder führt fn() aus und speichert."""
    if cp.get(f"{key}_done"):
        result = cp[f"{key}_entities"]
        print(f"{name}: aus Checkpoint ({len(result)} Entities)")
        return result
    result = fn()
    if cp_path:
        _save_checkpoint(cp_path, {f"{key}_done": True, f"{key}_entities": result})
    return result


def _parse_args():
    ap = argparse.ArgumentParser(
        description="Entity-Extraktion v2 (4 LLM-Schritte)"
    )
    ap.add_argument("--project",  required=True)
    ap.add_argument("--document", required=True)
    ap.add_argument("--mode", choices=["sample", "full"], default="sample")
    args    = ap.parse_args()
    doc_dir = ROOT / "data" / "projects" / args.project / "documents" / args.document
    return args, doc_dir


def _load_seed_and_rejected(doc_dir: Path) -> tuple[list[dict], set[str]]:
    seed: list[dict] = []
    seed_path = doc_dir / "entities_seed.json"
    if seed_path.exists():
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        for ent in seed:
            ent["_source"] = "seed"
        print(f"Seed: {len(seed)} Entities")
    else:
        print("Kein entities_seed.json — nur Schritt 1 (Stichprobe)")

    rejected_lc: set[str] = set()
    rejected_path = doc_dir / "entities_rejected.json"
    if rejected_path.exists():
        for e in json.loads(rejected_path.read_text(encoding="utf-8")):
            rejected_lc.add((e.get("normalform") or "").lower())
            for a in e.get("aliases") or []:
                if a:
                    rejected_lc.add(a.lower())
        rejected_lc.discard("")
        print(f"Rejected: {len(rejected_lc)} Tokens gefiltert")

    return seed, rejected_lc


def main() -> None:
    args, doc_dir = _parse_args()

    segments_path   = doc_dir / "segments.json"
    output_path     = doc_dir / "entities_proposal.json"
    checkpoint_path = doc_dir / CHECKPOINT_NAME

    if not segments_path.exists():
        print(f"Nicht gefunden: {segments_path}", file=sys.stderr)
        sys.exit(1)

    load_dotenv(ROOT / ".env")
    provider = get_provider(task=TASK_EXTRACT)

    segments  = json.loads(segments_path.read_text(encoding="utf-8"))
    n_content = sum(1 for s in segments if s.get("type") == "content")
    print(f"Segmente: {len(segments)} gesamt, {n_content} content  |  Modus: {args.mode}")

    seed, rejected_lc = _load_seed_and_rejected(doc_dir)

    cp: dict = {}
    if args.mode == "full" and checkpoint_path.exists():
        try:
            cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            print("Checkpoint geladen")
        except (json.JSONDecodeError, KeyError):
            print("Checkpoint ungültig — starte von vorn", file=sys.stderr)
            cp = {}

    cp_path      = checkpoint_path if args.mode == "full" else None
    content_segs = [s for s in segments if s.get("type") == "content"]

    # ── Schritt 1: Stichprobe (immer) ─────────────────────────────────────────
    step1_entities = _run_stage(
        "Schritt 1", "step1", cp, cp_path,
        lambda: _llm_sample_iteration(
            segments, provider, seed, cp_path, rejected_lc
        ),
    )

    # ── Schritt 2: Vollextraktion (full-Modus + Seed vorhanden) ───────────────
    step2_entities: list[dict] = []
    if args.mode == "full" and seed:
        if cp.get("step2_done"):
            step2_entities = cp["step2_entities"]
            print(f"Schritt 2: aus Checkpoint ({len(step2_entities)} Entities)")
        else:
            resume_batch  = cp.get("step2_batch", 0)
            resume_accum  = cp.get("step2_entities", []) if resume_batch else []
            if resume_batch:
                print(f"Schritt 2: Resume ab Batch {resume_batch + 1}")
            step2_entities = _llm_full_extract(
                segments, provider, seed, cp_path,
                batch_size=BATCH_SIZE,
                resume_from=resume_batch,
                accumulated=resume_accum,
                rejected_lc=rejected_lc,
            )
            if cp_path:
                _save_checkpoint(cp_path, {
                    "step2_done":     True,
                    "step2_entities": step2_entities,
                })
    elif args.mode == "full":
        print("Schritt 2: übersprungen (kein Seed für Few-Shot)")

    # Schritt 1 + 2 zusammenführen
    combined = _merge([step1_entities, step2_entities]) if step2_entities \
               else step1_entities

    # ── Schritt 3: Duplikat-Erkennung ─────────────────────────────────────────
    step3_entities = _run_stage(
        "Schritt 3", "step3", cp, cp_path,
        lambda: _llm_dedup(combined, provider, content_segs, rejected_lc),
    )

    # ── Schritt 4: Normalform bereinigen ──────────────────────────────────────
    # checkpoint_path=None: _run_stage sichert das Gesamtergebnis von Schritt 4;
    # internes Batch-Checkpointing von _llm_task1_normalize wird nicht genutzt.
    step4_entities = _run_stage(
        "Schritt 4", "step4", cp, cp_path,
        lambda: _llm_task1_normalize(
            step3_entities, provider, seed,
            checkpoint_path=None,
            rejected_lc=rejected_lc,
        ),
    )

    # ── Merge mit Seed + Ausgabe ───────────────────────────────────────────────
    merged = _merge([seed, step4_entities])

    if cp_path and cp_path.exists():
        cp_path.unlink()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n→ {output_path}  ({len(merged)} Entities)")
    _print_stats(merged)


if __name__ == "__main__":
    main()
