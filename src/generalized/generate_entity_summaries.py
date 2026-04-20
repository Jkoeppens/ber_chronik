"""
generate_entity_summaries.py — KI-Zusammenfassungen für Entities

Portiert aus src/berchronik/export_viz.py --summaries (Commit b7d1740a).

Input:
  data/projects/{project}/exploration/data.json   — Einträge mit actors-Feld
  data/projects/{project}/config.json["entities"] — Normalformen + Aliases

Output:
  data/projects/{project}/exploration/entities_summary.json
  Format: {"Normalform": {"summary": "...", "paragraph_ids": [...], "count": N}}

Features:
  - Nur Entities mit >= min_mentions Nennungen (default 3)
  - Max 30 Paragraphen pro Entity samplen (round-robin über event_type)
  - Resume-Support: bereits erzeugte Einträge überspringen
  - Schreibt nach jeder Entity — überlebt Abbrüche
  - LLM via get_provider() (Anthropic oder Ollama)

CLI:
  python -m src.generalized.generate_entity_summaries --project osmanisch
  python -m src.generalized.generate_entity_summaries --project ber --min-mentions 5
  python -m src.generalized.generate_entity_summaries --project ber --force
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

from src.generalized.config import ROOT, PROJECTS_DIR
from src.generalized.llm import get_provider, TASK_ANALYZE

MAX_PARAGRAPHS = 30

SUMMARY_PROMPT = """\
Du fasst die Rolle einer Person oder Organisation in diesem historischen Text zusammen, \
auf Basis von Auszügen aus einer Chronik.

Person/Organisation: {name}

Relevante Auszüge ({count} gesamt, {shown} gezeigt):
{paragraphs}

Schreibe eine Zusammenfassung auf Deutsch mit genau dieser Struktur \
(drei Absätze, keine Überschriften, kein JSON):

Absatz 1 – Wer: Wer ist diese Person oder Organisation? \
Welchen Hintergrund und welche Funktion hatten sie allgemein?

Absatz 2 – Rolle: Welche konkreten Aufgaben, Entscheidungen und Beiträge \
hatten sie in diesem Kontext? \
Nenne mindestens drei konkrete Jahreszahlen aus den Auszügen. \
Nenne mindestens zwei andere beteiligte Personen oder Organisationen \
mit denen sie zusammenarbeiteten oder in Beziehung standen.

Absatz 3 – Konflikte und Wendepunkte: Welche Konflikte, Krisen oder \
Kursänderungen waren mit dieser Person/Organisation verbunden? \
Was hat sich durch ihr Handeln verändert oder verschlechtert?

Schreibe ausschließlich was explizit in den Auszügen steht. \
Wenn du unsicher bist ob ein Detail in den Auszügen vorkommt, lass es weg.\
"""


def _sample_paragraphs(rows: list[dict], max_n: int) -> list[dict]:
    """Samplet bis zu max_n Einträge, round-robin über event_type für Diversität."""
    if len(rows) <= max_n:
        return rows
    by_type: dict[str, list] = defaultdict(list)
    for r in rows:
        by_type[r.get("event_type") or "?"].append(r)
    result, buckets = [], list(by_type.values())
    i = 0
    while len(result) < max_n:
        bucket = buckets[i % len(buckets)]
        if bucket:
            result.append(bucket.pop(0))
        i += 1
        if all(not b for b in buckets):
            break
    result.sort(key=lambda r: r.get("id") or 0)
    return result


def _build_alias_map(entities: list[dict]) -> dict[str, str]:
    """Alias → Normalform Mapping aus config.json["entities"]."""
    alias_map: dict[str, str] = {}
    for ent in entities:
        nf = ent.get("normalform", "")
        if not nf:
            continue
        alias_map[nf.lower()] = nf
        for alias in ent.get("aliases", []):
            if alias:
                alias_map[alias.lower()] = nf
    return alias_map


def build_summaries(
    entries: list[dict],
    entities: list[dict],
    out_path: Path,
    min_mentions: int = 3,
    force: bool = False,
) -> None:
    """Erzeugt entities_summary.json für alle qualifizierten Entities."""

    # Alias-Map: jeder Actor-String → kanonische Normalform
    alias_map = _build_alias_map(entities)
    known_normalforms = {ent.get("normalform", "") for ent in entities if ent.get("normalform")}

    # Paragraphen pro Normalform sammeln (actors können Aliases sein)
    actor_paragraphs: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        for actor in entry.get("actors") or []:
            nf = alias_map.get(actor.lower(), actor)  # auf Normalform mappen
            actor_paragraphs[nf].append(entry)

    # Nur Entities aus config.json, mit >= min_mentions
    candidates = sorted(
        [
            (nf, actor_paragraphs[nf])
            for nf in known_normalforms
            if len(actor_paragraphs.get(nf, [])) >= min_mentions
        ],
        key=lambda x: -len(x[1]),
    )
    print(f"  {len(candidates)} Entities mit >= {min_mentions} Nennungen")

    # Bestehende Summaries laden (Resume)
    existing: dict = {}
    if out_path.exists() and not force:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            skipped = sum(1 for nf, _ in candidates if nf in existing)
            if skipped:
                print(f"  Resume: {skipped} bereits vorhanden, werden übersprungen")
        except json.JSONDecodeError:
            pass

    results = dict(existing)
    provider = get_provider(task=TASK_ANALYZE)
    print(f"  Modell: {provider.model}\n")

    for nf, paragraphs in candidates:
        if nf in results and not force:
            continue

        shown = _sample_paragraphs(paragraphs, MAX_PARAGRAPHS)
        para_block = "\n\n".join(
            f"[{p.get('doc_anchor', '?')}, {p.get('year', '?')}] {p.get('text', '')}"
            for p in shown
        )
        prompt = SUMMARY_PROMPT.format(
            name=nf,
            count=len(paragraphs),
            shown=len(shown),
            paragraphs=para_block,
        )

        print(f"  {nf}  ({len(paragraphs)} Nennungen) …", flush=True)
        summary = provider.complete(prompt)
        if not summary:
            print(f"    → fehlgeschlagen, übersprungen", file=sys.stderr)
            summary = None

        results[nf] = {
            "summary":       summary,
            "paragraph_ids": [p.get("doc_anchor") for p in paragraphs if p.get("doc_anchor")],
            "count":         len(paragraphs),
        }

        # Nach jeder Entity schreiben — überlebt Abbrüche
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    done    = sum(1 for v in results.values() if v.get("summary"))
    missing = sum(1 for v in results.values() if not v.get("summary"))
    print(f"\n→ {out_path}  ({done} Summaries, {missing} fehlgeschlagen)")


def main() -> None:
    load_dotenv(ROOT / ".env")

    ap = argparse.ArgumentParser(
        description="KI-Zusammenfassungen für Entities aus exploration/data.json"
    )
    ap.add_argument("--project",      required=True, help="Projektname")
    ap.add_argument("--document",     default=None,  help="Nicht verwendet (für Konsistenz)")
    ap.add_argument("--min-mentions", type=int, default=3,
                    help="Mindest-Nennungen für eine Zusammenfassung (default: 3)")
    ap.add_argument("--force",        action="store_true",
                    help="Alle Summaries neu generieren (ignoriert bestehende)")
    args = ap.parse_args()

    project_dir     = PROJECTS_DIR / args.project
    exploration_dir = project_dir / "exploration"
    data_path       = exploration_dir / "data.json"
    config_path     = project_dir / "config.json"
    out_path        = exploration_dir / "entities_summary.json"

    # D-P5: Input-Prüfung
    if not data_path.exists():
        print(f"Fehler: {data_path} nicht gefunden — bitte zuerst export_exploration laufen lassen.",
              file=sys.stderr)
        sys.exit(1)
    if not config_path.exists():
        print(f"Fehler: {config_path} nicht gefunden.", file=sys.stderr)
        sys.exit(1)

    data_obj = json.loads(data_path.read_text(encoding="utf-8"))
    entries  = data_obj.get("entries", [])
    config   = json.loads(config_path.read_text(encoding="utf-8"))
    entities = config.get("entities") or []

    if not entities:
        print("Warnung: config.json enthält keine Entities — keine Summaries möglich.",
              file=sys.stderr)
        sys.exit(0)

    print(f"Projekt:  {args.project}")
    print(f"Einträge: {len(entries)}  |  Entities: {len(entities)}")

    build_summaries(entries, entities, out_path, args.min_mentions, args.force)


if __name__ == "__main__":
    main()
