"""
ingest_zotero.py — Zotero-Collection als neues Dokument einlesen

Ablauf:
  1. Alle Items der Collection via pyzotero laden
  2. Checkpoint prüfen — bereits verarbeitete Keys überspringen
  3. Pro neuem Item: HTML-Attachment laden → trafilatura-Volltext
     Fallback: Abstract (mit Warnung). Kein Text → Item überspringen.
  4. Segmente schreiben (neues Dokument, neue doc_id)
  5. Pipeline ausführen: detect_anchors → interpolate_anchors →
     classify_segments → match_entities → export_exploration
  6. Checkpoint aktualisieren

Aufruf:
  python3 -m src.generalized.ingest_zotero \
    --project mein_projekt \
    --api-key KEY \
    --user-id 12345 \
    --collection ABCDEF

API-Key / User-ID können auch als Umgebungsvariablen gesetzt werden:
  ZOTERO_API_KEY, ZOTERO_USER_ID
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pyzotero import zotero
import trafilatura

from src.generalized.config import ROOT, PROJECTS_DIR

CHECKPOINT_NAME = "zotero_checkpoint.json"

PIPELINE = [
    "src/generalized/detect_anchors.py",
    "src/generalized/interpolate_anchors.py",
    "src/generalized/classify_segments.py",
    "src/generalized/match_entities.py",
]


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("WARNING: Checkpoint ungültig — starte von vorn", file=sys.stderr)
    return {"done": []}


def _save_checkpoint(path: Path, done_keys: list[str]) -> None:
    existing = _load_checkpoint(path)
    merged = list(dict.fromkeys(existing.get("done", []) + done_keys))
    path.write_text(
        json.dumps({"done": merged, "last_run": datetime.now(timezone.utc).isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Datum-Extraktion ──────────────────────────────────────────────────────────

def _extract_date(data: dict) -> str | None:
    """Gibt das beste verfügbare Datum zurück und loggt welches Feld genutzt wurde."""
    title = data.get("title", "(ohne Titel)")
    for field in ("issued", "date"):
        raw = data.get(field)
        if not raw:
            continue
        # issued kommt als {"date-parts": [[2021, 3, 15]]} oder als String
        if isinstance(raw, dict):
            parts = raw.get("date-parts", [[]])[0]
            if parts:
                year = str(parts[0])
                print(f"  Datum [{field}/date-parts]: {year}  — {title}")
                return year
        elif isinstance(raw, str) and raw.strip():
            print(f"  Datum [{field}]: {raw.strip()}  — {title}")
            return raw.strip()
    print(f"  Datum [keins]: None  — {title}")
    return None


# ── Volltext-Extraktion ───────────────────────────────────────────────────────

def _fetch_fulltext(zot: zotero.Zotero, item_key: str, title: str,
                    url: str | None = None) -> str | None:
    """HTML-Attachment laden und via trafilatura extrahieren.
    Fallback: URL direkt fetchen. Gibt None zurück wenn kein Text gefunden."""
    try:
        children = zot.children(item_key)
    except Exception as exc:
        print(f"  WARNING: children({item_key}) fehlgeschlagen: {exc}", file=sys.stderr)
        return None

    html_key = None
    for child in children:
        cdata = child.get("data", {})
        if cdata.get("contentType") == "text/html" and cdata.get("itemType") == "attachment":
            html_key = child["key"]
            break

    if html_key is not None:
        try:
            raw = zot.file(html_key)
        except Exception as exc:
            print(f"  WARNING: file({html_key}) fehlgeschlagen: {exc}", file=sys.stderr)
            return None
        html = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        return text or None

    # Kein HTML-Snapshot — URL direkt fetchen
    if url:
        print(f"  INFO: {title} — kein Snapshot, fetche URL direkt")
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False,
                                           include_tables=False)
                if text:
                    return text
        except Exception as exc:
            print(f"  WARNING: fetch_url fehlgeschlagen: {exc}", file=sys.stderr)

    return None


# ── Segment-Bau ───────────────────────────────────────────────────────────────

def _build_segment(idx: int, text: str, title: str, date: str | None,
                   item_key: str, doc_type: str, item_type: str = "",
                   url: str = "") -> dict:
    return {
        "segment_id": f"s{idx:04d}",
        "level":      3,
        "type":       "content",
        "source":     title,
        "text":       text,
        "page":       None,
        "doc_type":   doc_type,
        "date":       date,
        "zotero_key": item_key,
        "item_type":  item_type,
        "url":        url,
    }


# ── Pipeline-Ausführung ───────────────────────────────────────────────────────

def _run(script: str, args: list[str]) -> bool:
    name = Path(script).name
    print(f"\n▶ {name} …")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, str(ROOT / script), *args],
        cwd=str(ROOT),
        env=env,
    )
    if result.returncode != 0:
        print(f"✗ {name} Exit-Code {result.returncode}", file=sys.stderr)
        return False
    print(f"✓ {name}")
    return True


# ── Hauptlogik ────────────────────────────────────────────────────────────────

def main() -> None:
    load_dotenv(ROOT / ".env")

    ap = argparse.ArgumentParser(description="Zotero-Collection als Dokument einlesen")
    ap.add_argument("--project",    required=True)
    ap.add_argument("--api-key",    default=os.environ.get("ZOTERO_API_KEY"))
    ap.add_argument("--user-id",    default=os.environ.get("ZOTERO_USER_ID"))
    ap.add_argument("--collection", required=True)
    ap.add_argument("--doc-type",   default="presseartikel",
                    help="Dokumenttyp für classify_segments (default: presseartikel)")
    args = ap.parse_args()

    if not args.api_key:
        print("Fehler: --api-key oder ZOTERO_API_KEY erforderlich", file=sys.stderr)
        sys.exit(1)
    if not args.user_id:
        print("Fehler: --user-id oder ZOTERO_USER_ID erforderlich", file=sys.stderr)
        sys.exit(1)

    project_dir  = PROJECTS_DIR / args.project
    cp_path      = project_dir / CHECKPOINT_NAME

    if not project_dir.exists():
        print(f"Fehler: Projekt nicht gefunden: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # ── 1. Zotero-Items laden ─────────────────────────────────────────────────
    print(f"Verbinde mit Zotero (user={args.user_id}, collection={args.collection}) …")
    zot = zotero.Zotero(args.user_id, "user", args.api_key)
    try:
        items = zot.everything(zot.collection_items(args.collection))
    except Exception as exc:
        print(f"Fehler beim Laden der Collection: {exc}", file=sys.stderr)
        sys.exit(1)

    # Nur reguläre Items, keine Attachments/Notes auf oberster Ebene
    items = [
        it for it in items
        if it.get("data", {}).get("itemType") not in ("attachment", "note")
    ]
    print(f"{len(items)} Items in Collection")

    # ── 2. Checkpoint ─────────────────────────────────────────────────────────
    cp = _load_checkpoint(cp_path)
    done_set = set(cp.get("done", []))
    new_items = [it for it in items if it["key"] not in done_set]
    print(f"{len(new_items)} neue Items (bereits verarbeitet: {len(done_set)})")

    if not new_items:
        print("Nichts zu tun.")
        return

    # ── 3. Segmente bauen ─────────────────────────────────────────────────────
    segments: list[dict] = []
    processed_keys: list[str] = []

    for it in new_items:
        data  = it.get("data", {})
        key   = it["key"]
        title = data.get("title") or key
        print(f"\n── {title} ({key})")

        # Datum
        date = _extract_date(data)

        # Volltext
        text = _fetch_fulltext(zot, key, title, url=data.get("url"))

        if text is None:
            # Fallback: Abstract
            abstract = (data.get("abstractNote") or "").strip()
            if abstract:
                print(f"  WARNING: {title} hat kein Snapshot/URL-Text, nutze Abstract",
                      file=sys.stderr)
                text = abstract
            else:
                print(f"  WARNING: {title} hat weder Snapshot noch URL-Text noch Abstract — übersprungen",
                      file=sys.stderr)
                continue

        seg = _build_segment(
            idx=len(segments) + 1,
            text=text,
            title=title,
            date=date,
            item_key=key,
            doc_type=args.doc_type,
            item_type=data.get("itemType", ""),
            url=data.get("url", ""),
        )
        segments.append(seg)
        processed_keys.append(key)
        print(f"  → Segment s{len(segments):04d}  ({len(text)} Zeichen)")

    if not segments:
        print("\nKeine verwertbaren Segmente — Abbruch.")
        return

    # ── 4. Dokument schreiben ─────────────────────────────────────────────────
    doc_id  = uuid.uuid4().hex[:8]
    doc_dir = project_dir / "documents" / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    segments_path = doc_dir / "segments.json"
    segments_path.write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    doc_config = {
        "doc_type":          args.doc_type,
        "original_filename": f"zotero:{args.collection}",
        "ingested_at":       datetime.now(timezone.utc).isoformat(),
        "zotero_collection": args.collection,
    }
    (doc_dir / "config.json").write_text(
        json.dumps(doc_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n→ {segments_path}  ({len(segments)} Segmente, doc_id={doc_id})")

    # ── 5. Pipeline ───────────────────────────────────────────────────────────
    d_args = ["--project", args.project, "--document", doc_id]
    p_args = ["--project", args.project]

    # Taxonomie prüfen — bei neuem Projekt leer → propose_taxonomy vorschalten
    cfg_path = project_dir / "config.json"
    cfg = {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    if not cfg.get("taxonomy"):
        print("\nKeine Taxonomie in config.json — starte propose_taxonomy …")
        if not _run("src/generalized/propose_taxonomy.py", d_args):
            print("Fehler: propose_taxonomy fehlgeschlagen — Pipeline abgebrochen.",
                  file=sys.stderr)
            sys.exit(1)

    for script in PIPELINE:
        if not _run(script, d_args):
            print("Pipeline abgebrochen.", file=sys.stderr)
            sys.exit(1)

    # ── 5b. Entity-Extraktion (nur wenn config["entities"] leer) ─────────────
    # config neu lesen — propose_taxonomy kann taxonomy geschrieben haben
    cfg = {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass

    if not cfg.get("entities"):
        print("\nKeine Entities in config.json — starte extract_entities_v2 (sample) …")
        extract_ok = _run(
            "src/generalized/extract_entities_v2.py",
            d_args + ["--mode", "sample"],
        )
        proposal_path = project_dir / "documents" / doc_id / "entities_proposal.json"
        if extract_ok and proposal_path.exists():
            try:
                entities = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                entities = []
            if entities:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["entities"] = entities
                cfg_path.write_text(
                    json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"  {len(entities)} Entities → config.json gespiegelt")
                if not _run("src/generalized/match_entities.py", d_args):
                    print("WARNING: match_entities (2. Lauf) fehlgeschlagen",
                          file=sys.stderr)
            else:
                print("  Keine Entities in entities_proposal.json — übersprungen",
                      file=sys.stderr)
        else:
            print("  extract_entities_v2 fehlgeschlagen oder kein Proposal — übersprungen",
                  file=sys.stderr)
    else:
        print(f"\n{len(cfg['entities'])} Entities bereits in config.json — "
              "Entity-Extraktion übersprungen")

    if not _run("src/generalized/export_exploration.py", p_args):
        print("WARNING: export_exploration fehlgeschlagen (nicht fatal)", file=sys.stderr)

    # ── 6. Checkpoint speichern ───────────────────────────────────────────────
    _save_checkpoint(cp_path, processed_keys)
    print(f"\nCheckpoint aktualisiert: {len(processed_keys)} neue Keys gespeichert")
    print(f"✓ Zotero-Ingest abgeschlossen  (project={args.project}, doc_id={doc_id})")


if __name__ == "__main__":
    main()
