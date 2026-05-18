"""
ingest_obsidian.py — Obsidian-Vault via Dropbox als Dokument einlesen

Ablauf:
  1. Dropbox-Client via refresh_token initialisieren (oder lokaler Vault)
  2. Alle .md-Dateien im konfigurierten Ordner listen
  3. Checkpoint prüfen — bereits verarbeitete Pfade überspringen
  4. Pro neuer Datei: Frontmatter parsen → Segmente bauen
  5. segments.json schreiben (neues Dokument, neue doc_id)
  6. Pipeline ausführen: detect_anchors → interpolate_anchors →
     propose_taxonomy (wenn leer) → classify_segments →
     match_entities → export_exploration
  7. Checkpoint aktualisieren

Frontmatter-Mapping:
  title       → source (Artikel-Titel)
  source      → url   (ist die URL, nicht die Zeitung)
  author      → author (Obsidian [[Link]]-Format wird bereinigt)
  published   → date  (detect_anchors liest dieses Feld, D-P8)
  created     → date  (Fallback wenn published fehlt)
  description → abstract

Aufruf Dropbox:
  python3 -m src.generalized.ingest_obsidian \
    --project mein_projekt

Lokaler Modus (Tests ohne Dropbox-Auth):
  python3 -m src.generalized.ingest_obsidian \
    --project mein_projekt --source local --vault /pfad/zum/vault
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from src.generalized.config import ROOT, PROJECTS_DIR, DATA_ROOT

load_dotenv(ROOT / ".env")

DROPBOX_TOKENS_PATH = DATA_ROOT / "dropbox_tokens.json"

CHECKPOINT_NAME = "obsidian_checkpoint.json"

DROPBOX_APP_KEY    = os.environ.get("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET = os.environ.get("DROPBOX_APP_SECRET", "")
DROPBOX_REDIRECT_URL = os.environ.get(
    "DROPBOX_REDIRECT_URL",
    "http://localhost:8001/api/obsidian/oauth/callback",
)

PIPELINE = [
    "src/generalized/detect_anchors.py",
    "src/generalized/interpolate_anchors.py",
    "src/generalized/classify_segments.py",
    "src/generalized/match_entities.py",
    "src/generalized/export_exploration.py",
]


# ── Checkpoint ────────────────────────────────────────────────────────────────

def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("WARNING: Checkpoint ungültig — starte von vorn", file=sys.stderr)
    return {"done": []}


def _save_checkpoint(path: Path, done_paths: list[str]) -> None:
    existing = _load_checkpoint(path)
    merged = list(dict.fromkeys(existing.get("done", []) + done_paths))
    path.write_text(
        json.dumps({"done": merged, "last_run": datetime.now(timezone.utc).isoformat()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Dropbox-Client ────────────────────────────────────────────────────────────

def _get_client(tokens: dict):
    """Gibt einen Dropbox-Client mit refresh_token zurück."""
    import dropbox
    return dropbox.Dropbox(
        oauth2_refresh_token=tokens["refresh_token"],
        app_key=DROPBOX_APP_KEY,
        app_secret=DROPBOX_APP_SECRET,
    )


def _list_md_files(dbx, folder_path: str) -> list:
    """Listet alle .md-Dateien im Dropbox-Ordner."""
    import dropbox.files
    try:
        result = dbx.files_list_folder(folder_path, recursive=True)
    except Exception as exc:
        print(f"Fehler beim Auflisten von {folder_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    entries = list(result.entries)
    while result.has_more:
        result = dbx.files_list_folder_continue(result.cursor)
        entries.extend(result.entries)
    return [e for e in entries
            if isinstance(e, dropbox.files.FileMetadata) and e.name.endswith(".md")]


def _download_md(dbx, path: str) -> str:
    """Lädt eine .md-Datei aus Dropbox herunter."""
    try:
        _, response = dbx.files_download(path)
        return response.content.decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  WARNING: download({path}) fehlgeschlagen: {exc}", file=sys.stderr)
        return ""


# ── Frontmatter-Parsing ───────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Trennt YAML-Frontmatter vom Body. Gibt (meta, body) zurück."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, text[end + 4:].lstrip()
    return {}, text


def _clean_obsidian_links(v: str) -> str:
    """[[Name|Alias]] oder [[Name]] → Name."""
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", str(v))


def _extract_date(meta: dict) -> str | None:
    """published → created → None. Gibt YYYY-MM-DD oder YYYY zurück."""
    for field in ("published", "created"):
        v = meta.get(field)
        if not v:
            continue
        s = str(v).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        if re.match(r"^\d{4}$", s):
            return s
    return None


# ── Segment-Bau ───────────────────────────────────────────────────────────────

def _build_segments(start_idx: int, meta: dict, body: str,
                    doc_type: str, file_path: str) -> list[dict]:
    """Ein content-Segment pro .md-Datei (wie Zotero).

    Das date-Feld trägt das Erscheinungsdatum; detect_anchors liest es
    direkt am content-Segment (kein Heading-Umweg, keine Interpolation).
    """
    title    = str(meta.get("title") or Path(file_path).stem)
    date     = _extract_date(meta)
    url      = str(meta.get("source") or "")
    author   = _clean_obsidian_links(meta.get("author") or "")
    abstract = str(meta.get("description") or "")

    return [{
        "segment_id":    f"s{start_idx:04d}",
        "type":          "content",
        "source":        title,
        "text":          body.strip(),
        "page":          None,
        "doc_type":      doc_type,
        "date":          date,
        "url":           url,
        "author":        author,
        "abstract":      abstract,
        "ingest_source": "obsidian",
        "obsidian_path": file_path,
    }]


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

    ap = argparse.ArgumentParser(description="Obsidian-Vault via Dropbox einlesen")
    ap.add_argument("--project",  required=True)
    ap.add_argument("--source",   default="dropbox", choices=["dropbox", "local"],
                    help="dropbox (default) oder local (für Tests)")
    ap.add_argument("--vault",    default=None,
                    help="Lokaler Ordner-Pfad (nur bei --source local)")
    ap.add_argument("--doc-type", default="presseartikel",
                    help="Dokumenttyp (default: presseartikel)")
    args = ap.parse_args()

    project_dir = PROJECTS_DIR / args.project
    if not project_dir.exists():
        print(f"Fehler: Projekt nicht gefunden: {project_dir}", file=sys.stderr)
        sys.exit(1)

    cp_path = project_dir / CHECKPOINT_NAME

    # ── 1. Dateien laden ─────────────────────────────────────────────────────
    if args.source == "local":
        vault_path = Path(args.vault or (project_dir / "test_vault"))
        if not vault_path.exists():
            print(f"Fehler: Vault nicht gefunden: {vault_path}", file=sys.stderr)
            sys.exit(1)
        md_files = list(vault_path.rglob("*.md"))
        print(f"Lokaler Vault: {vault_path}  ({len(md_files)} .md-Dateien)")
        file_keys = [str(f.relative_to(vault_path)) for f in md_files]

        def read_file(i: int) -> str:
            return md_files[i].read_text(encoding="utf-8", errors="replace")

    else:
        cfg_path = project_dir / "config.json"
        if not cfg_path.exists():
            print("Fehler: config.json nicht gefunden", file=sys.stderr)
            sys.exit(1)
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        oc = cfg.get("obsidian") or {}
        folder_path = oc.get("dropbox_folder", "")
        doc_type_cfg = oc.get("doc_type", args.doc_type)
        args.doc_type = doc_type_cfg

        tokens = (oc.get("tokens") or {})
        if not tokens.get("refresh_token"):
            print("Fehler: Dropbox nicht verbunden — zuerst OAuth durchführen", file=sys.stderr)
            sys.exit(1)
        if not folder_path:
            print("Fehler: dropbox_folder nicht konfiguriert", file=sys.stderr)
            sys.exit(1)
        if not folder_path.startswith("/"):
            folder_path = "/" + folder_path

        print(f"Verbinde mit Dropbox (Ordner={folder_path}) …")
        dbx = _get_client(tokens)
        entries = _list_md_files(dbx, folder_path)
        print(f"{len(entries)} .md-Dateien in {folder_path}")
        file_keys = [e.path_display for e in entries]

        def read_file(i: int) -> str:
            return _download_md(dbx, entries[i].path_display)

    # ── 2. Checkpoint ─────────────────────────────────────────────────────────
    cp = _load_checkpoint(cp_path)
    # Normalisierung auf Dateiname: verträgt alte Einträge (nur Name) und neue
    # Dropbox-Einträge (absoluter path_display wie /Ordner/Artikel.md).
    done_set = {Path(k).name for k in cp.get("done", [])}
    new_indices = [i for i, k in enumerate(file_keys) if Path(k).name not in done_set]
    print(f"{len(new_indices)} neue Dateien (bereits verarbeitet: {len(done_set)})")

    if not new_indices:
        print("Nichts zu tun.")
        return

    # ── 3. Segmente bauen ─────────────────────────────────────────────────────
    segments: list[dict] = []
    processed_keys: list[str] = []

    for i in new_indices:
        key = file_keys[i]
        print(f"\n── {key}")
        raw = read_file(i)
        if not raw.strip():
            print(f"  WARNING: {key} leer — übersprungen", file=sys.stderr)
            continue

        meta, body = _parse_frontmatter(raw)
        if not body.strip():
            print(f"  WARNING: {key} hat keinen Textinhalt — übersprungen", file=sys.stderr)
            continue

        new_segs = _build_segments(
            start_idx=len(segments) + 1,
            meta=meta,
            body=body,
            doc_type=args.doc_type,
            file_path=key,
        )
        segments.extend(new_segs)

        n_content = sum(1 for s in new_segs if s["type"] == "content")
        processed_keys.append(key)
        print(f"  → 1 Heading + {n_content} Absatz-Segment(e)  ({len(body)} Zeichen)")

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

    source_label = (folder_path if args.source == "dropbox"
                    else str(args.vault or "local"))
    doc_config = {
        "doc_type":          args.doc_type,
        "original_filename": f"obsidian:{source_label}",
        "ingested_at":       datetime.now(timezone.utc).isoformat(),
        "obsidian_source":   args.source,
    }
    (doc_dir / "config.json").write_text(
        json.dumps(doc_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n→ {segments_path}  ({len(segments)} Segmente, doc_id={doc_id})")

    # ── 5. Pipeline ───────────────────────────────────────────────────────────
    d_args = ["--project", args.project, "--document", doc_id]
    p_args = ["--project", args.project]

    # Projekt-config.json mit aktuellem doc_id + doc_type aktualisieren
    cfg_path = project_dir / "config.json"
    cfg = {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    cfg["doc_id"]   = doc_id
    cfg["doc_type"] = args.doc_type
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    for script in PIPELINE:
        args_for_script = p_args if script.endswith("export_exploration.py") else d_args
        if not _run(script, args_for_script):
            print("Pipeline abgebrochen.", file=sys.stderr)
            sys.exit(1)

    # ── 5b. Entity-Extraktion (nur wenn config["entities"] leer) ─────────────
    cfg = {}
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass

    if not cfg.get("entities"):
        print("\nKeine Entities in config.json — starte extract_entities_v2 …")
        extract_ok = _run(
            "src/generalized/extract_entities_v2.py",
            d_args,
        )
        if not extract_ok:
            print("WARNUNG: Entity-Extraktion fehlgeschlagen", file=sys.stderr, flush=True)
        proposal_path = doc_dir / "entities_proposal.json"
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
    else:
        print(f"\n{len(cfg['entities'])} Entities bereits in config.json — "
              "Entity-Extraktion übersprungen")

    # ── 6. Checkpoint speichern ───────────────────────────────────────────────
    _save_checkpoint(cp_path, processed_keys)
    print(f"\nCheckpoint aktualisiert: {len(processed_keys)} neue Dateien gespeichert")

    from src.generalized.db import upsert_document
    asyncio.run(upsert_document(
        doc_id            = doc_id,
        project_id        = args.project,
        ingested_at       = doc_config["ingested_at"],
        doc_type          = args.doc_type,
        ingest_source     = "obsidian",
        original_filename = doc_config["original_filename"],
    ))
    print(f"✓ Obsidian-Ingest abgeschlossen  (project={args.project}, doc_id={doc_id})")


if __name__ == "__main__":
    main()
