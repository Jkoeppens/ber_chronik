"""
dev_server.py — lokaler Entwicklungs-Server

Endpoints:
  POST /overrides              — overrides.json speichern
  POST /recompute              — interpolate → export als SSE
  GET  /preview                — preview.html ausliefern
  GET  /taxonomy               — Taxonomy-Editor HTML
  GET  /taxonomy/data          — taxonomy_proposal.json
  POST /taxonomy/save          — Taxonomie speichern
  POST /taxonomy/propose       — propose_taxonomy.py als SSE
  GET  /ingest                 — Ingest-Wizard HTML
  POST /ingest/upload          — Dateien nach data/raw/ speichern
  POST /ingest/analyze         — parse + LLM-Analyse, gibt JSON zurück
  POST /ingest/propose_taxonomy — propose_taxonomy.py auf aktuellen Segmenten, SSE
  POST /ingest/save_config     — project_config.json schreiben
  POST /ingest/run             — vollständige Pipeline als SSE

Starten:
  uvicorn src.generalized.dev_server:app --port 8001 --reload
"""

import asyncio
import json
import os
import random
import re
import sys
import uuid
from pathlib import Path
from typing import List

from src.generalized.llm import get_provider, TASK_ANALYZE
import shutil

from src.generalized.db import (
    init_db, create_project, get_project, list_projects as db_list_projects,
    update_project, delete_project, token_valid,
)
from src.generalized.utils import render_template as _render_template
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

ROOT               = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH        = ROOT / "data" / "interim" / "generalized" / "project_config.json"
PROJECTS_DIR       = ROOT / "data" / "projects"
RAW_DIR            = ROOT / "data" / "raw"

PARSE_SCRIPT               = ROOT / "src" / "generalized" / "parse_document.py"
DETECT_SCRIPT              = ROOT / "src" / "generalized" / "detect_anchors.py"
INTERPOLATE_SCRIPT         = ROOT / "src" / "generalized" / "interpolate_anchors.py"
CLASSIFY_SCRIPT            = ROOT / "src" / "generalized" / "classify_segments.py"
EXPORT_SCRIPT              = ROOT / "src" / "generalized" / "export_preview.py"
EXPORT_EXPLORATION_SCRIPT  = ROOT / "src" / "generalized" / "export_exploration.py"
PROPOSE_SCRIPT             = ROOT / "src" / "generalized" / "propose_taxonomy.py"
EXTRACT_ENTITIES_SCRIPT    = ROOT / "src" / "generalized" / "extract_entities_v2.py"
EXTRACT_ENTITIES_FULL_SCRIPT = EXTRACT_ENTITIES_SCRIPT  # selbes Skript, anderer --mode
MATCH_ENTITIES_SCRIPT      = ROOT / "src" / "generalized" / "match_entities.py"

app = FastAPI(title="Generalized Dev Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup():
    await init_db()


# ── Token-Prüfung ──────────────────────────────────────────────────────────────

async def _require_token(request: Request, project: str | None = None) -> JSONResponse | None:
    """
    Liest Token aus ?token= oder X-Project-Token Header.
    project: explizit übergeben > ?project= Query-Param > project_config.json Fallback.
    Gibt None zurück wenn OK, JSONResponse(403) wenn nicht.
    """
    token = (
        request.query_params.get("token")
        or request.headers.get("X-Project-Token")
    )
    if not token:
        return JSONResponse({"ok": False, "error": "Token fehlt"}, status_code=403)
    proj_id = project or request.query_params.get("project") or get_current_project()
    db_proj = await get_project(proj_id)
    if not db_proj:
        return JSONResponse({"ok": False, "error": "Projekt nicht gefunden"}, status_code=403)
    if not token_valid(db_proj, token):
        return JSONResponse({"ok": False, "error": "Token ungültig oder abgelaufen"}, status_code=403)
    return None


# ── Projekt-Hilfsfunktionen ────────────────────────────────────────────────────

def get_current_project() -> str:
    """Liest den aktuellen Projektnamen aus project_config.json."""
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if cfg.get("project"):
                return cfg["project"]
        except Exception:
            pass
    return "ber"   # Fallback


def get_current_document() -> str | None:
    """Liest die aktuelle Dokument-ID aus project_config.json."""
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return cfg.get("document") or None
        except Exception:
            pass
    return None


def _slugify(name: str) -> str:
    """Menschlicher Projektname → technische ID (lowercase, Leerzeichen→_, Sonderzeichen weg)."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    s = s.strip("_")
    return s or "projekt"


def _save_config_pointer(project: str, document: str | None = None) -> None:
    """Schreibt project (+ optional document) in project_config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ptr: dict = {}
    if CONFIG_PATH.exists():
        try:
            ptr = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    ptr["project"] = project
    if document is not None:
        ptr["document"] = document
    CONFIG_PATH.write_text(json.dumps(ptr, ensure_ascii=False, indent=2), encoding="utf-8")


def get_project_dir(project: str) -> Path:
    return PROJECTS_DIR / project


def get_doc_dir(project: str, doc_id: str) -> Path:
    return PROJECTS_DIR / project / "documents" / doc_id


# ── Shared SSE helper ──────────────────────────────────────────────────────────

async def run_script_sse(script_path: Path, args: list[str] = ()):
    label = script_path.name
    yield f"data: ▶ Starte {label}…\n\n"
    try:
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script_path), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
        )
        # Read raw chunks so \r-only lines (e.g. tqdm) are also forwarded
        buf = b""
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"\r|\n", buf)
            buf = parts.pop()          # keep last incomplete segment
            for part in parts:
                line = part.decode("utf-8", errors="replace").strip()
                if line:
                    yield f"data: {line}\n\n"
        if buf:
            line = buf.decode("utf-8", errors="replace").strip()
            if line:
                yield f"data: {line}\n\n"
        await proc.wait()
        if proc.returncode != 0:
            yield f"data: __error__ {label} Exit-Code {proc.returncode}\n\n"
            return
        yield f"data: ✓ {label} abgeschlossen\n\n"
    except Exception as exc:
        yield f"data: __error__ {exc}\n\n"
        return
    yield "data: __ok__\n\n"


def sse_response(gen):
    return StreamingResponse(gen, media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def run_pipeline_sse(steps: list[tuple]):
    """steps: [(script_path, [args]), ...]"""
    for script, args in steps:
        async for chunk in run_script_sse(script, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
    yield "data: __done__\n\n"


# ── POST /overrides ────────────────────────────────────────────────────────────

@app.post("/overrides")
async def save_overrides(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    body = await request.json()
    if not isinstance(body, list):
        return JSONResponse({"ok": False, "error": "Body muss ein JSON-Array sein"}, status_code=400)
    doc_dir  = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    overrides_p = doc_dir / "overrides.json"
    overrides_p.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(body)}


# ── POST /recompute ────────────────────────────────────────────────────────────

def _compute_quality_report(project: str, doc_id: str) -> dict | None:
    """Qualitätsbericht aus classified.json berechnen (nach Pipeline-Lauf)."""
    doc_dir      = get_doc_dir(project, doc_id)
    classified_p = doc_dir / "classified.json"
    project_dir  = get_project_dir(project)
    config_p     = project_dir / "config.json"
    if not classified_p.exists():
        return None
    try:
        from src.generalized.export_preview import build_quality_report
        classified = json.loads(classified_p.read_text(encoding="utf-8"))
        taxonomy   = None
        if config_p.exists():
            taxonomy = json.loads(config_p.read_text(encoding="utf-8")).get("taxonomy") or None
        if taxonomy is None:
            fallback = doc_dir / "taxonomy_proposal.json"
            if fallback.exists():
                taxonomy = json.loads(fallback.read_text(encoding="utf-8"))
        classifications = {r["segment_id"]: r for r in classified if r.get("segment_id")}
        return build_quality_report(list(classifications.values()), classifications, taxonomy)
    except Exception:
        return None


async def recompute_sse(project: str, doc_id: str):
    d_args = ["--project", project, "--document", doc_id]
    steps  = [(INTERPOLATE_SCRIPT, d_args), (EXPORT_SCRIPT, d_args)]
    async for chunk in run_pipeline_sse(steps):
        if chunk == "data: __done__\n\n":
            report = _compute_quality_report(project, doc_id)
            if report:
                yield f"data: __report__:{json.dumps(report, ensure_ascii=False)}\n\n"
        yield chunk


@app.post("/recompute")
async def recompute(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    return sse_response(recompute_sse(project, doc_id))


# ── GET /preview ───────────────────────────────────────────────────────────────

@app.get("/preview")
async def get_preview(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    preview_p = get_doc_dir(project, doc_id) / "preview.html"
    if not preview_p.exists():
        return HTMLResponse("<p>preview.html nicht gefunden.</p>", status_code=404)
    return HTMLResponse(content=preview_p.read_text(encoding="utf-8"))


# ── Taxonomy endpoints ─────────────────────────────────────────────────────────

@app.get("/taxonomy/data")
async def get_taxonomy_data(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    config_p = get_project_dir(project) / "config.json"
    if config_p.exists():
        cfg = json.loads(config_p.read_text(encoding="utf-8"))
        taxonomy = cfg.get("taxonomy") or []
        if taxonomy:
            return JSONResponse(taxonomy)
    # Fallback: per-doc taxonomy_proposal.json
    fallback = get_doc_dir(project, doc_id) / "taxonomy_proposal.json"
    if fallback.exists():
        return JSONResponse(json.loads(fallback.read_text(encoding="utf-8")))
    return JSONResponse([])


@app.post("/taxonomy/save")
async def save_taxonomy(request: Request):
    project = request.query_params.get("project") or get_current_project()
    if err := await _require_token(request, project): return err
    body = await request.json()
    if not isinstance(body, list):
        return JSONResponse({"ok": False, "error": "Body muss ein JSON-Array sein"}, status_code=400)
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    config_p    = project_dir / "config.json"
    cfg: dict = {}
    if config_p.exists():
        try:
            cfg = json.loads(config_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg["taxonomy"] = body
    config_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(body)}


@app.post("/taxonomy/propose")
async def propose_taxonomy(request: Request):
    if err := await _require_token(request): return err
    async def gen():
        async for chunk in run_script_sse(PROPOSE_SCRIPT):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
        yield "data: __done__\n\n"
    return sse_response(gen())


@app.get("/taxonomy")
async def get_taxonomy_editor():
    return HTMLResponse(content=_render_template("taxonomy_editor.html", APP_CSS=APP_CSS))


# ── Ingest endpoints ───────────────────────────────────────────────────────────

@app.post("/ingest/upload")
async def ingest_upload(files: List[UploadFile] = File(...)):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        content = await f.read()
        dest = RAW_DIR / f.filename
        dest.write_bytes(content)
        saved.append({"name": f.filename, "size": len(content)})
    return {"ok": True, "files": saved}


@app.post("/ingest/analyze")
async def ingest_analyze(request: Request):
    body     = await request.json()
    filename = body.get("filename", "")
    _DOC_TYPE_MAP = {
        "Forschungsnotizen": "buchnotizen",
        "Transkripte":       "buchnotizen",
        "Anderes":           "buchnotizen",
        "Presseartikel":     "presseartikel",
    }
    doc_type = body.get("doc_type", "")
    doc_type = _DOC_TYPE_MAP.get(doc_type, doc_type)  # Wizard-Label → interner Wert
    project_name = body.get("project_name", "").strip()
    project  = _slugify(project_name) if project_name else (body.get("project") or get_current_project())
    doc_id   = body.get("document") or str(uuid.uuid4())[:8]

    input_file = RAW_DIR / filename
    doc_dir    = get_doc_dir(project, doc_id)
    segments_p = doc_dir / "segments.json"

    if not input_file.exists():
        return JSONResponse({"ok": False, "error": f"Datei nicht gefunden: {filename}"}, status_code=404)

    # Store doc_id in project_config.json for subsequent requests
    _save_config_pointer(project, doc_id)

    # 1. parse_document → documents/{doc_id}/segments.json
    parse_args = ["--project", project, "--document", doc_id, str(input_file)]
    if doc_type:
        parse_args += ["--doc-type", doc_type]
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(PARSE_SCRIPT), *parse_args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        cwd=str(ROOT),
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return JSONResponse({"ok": False, "error": "parse_document fehlgeschlagen",
                             "detail": out.decode("utf-8", errors="replace")}, status_code=500)

    # 2. Segmente lesen und aufteilen
    segments = json.loads(segments_p.read_text(encoding="utf-8"))
    pool     = [s for s in segments if s.get("type") == "content" and len(s.get("text", "")) >= 60]
    sample   = random.sample(pool, min(30, len(pool)))
    sample_text = "\n\n".join(
        f"[{s.get('source', '?')}]\n{s['text']}" for s in sample
    )

    organizer_headings   = [s["text"] for s in segments if s.get("type") in ("heading", "source") and s.get("text")]
    bibliography_keywords = [s["text"] for s in segments if s.get("type") == "bibliography" and s.get("text")]

    # 3. LLM-Analyse (nur year_min, year_max, events, language)
    load_dotenv(ROOT / ".env")
    try:
        provider = get_provider(task=TASK_ANALYZE)
    except RuntimeError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    prompt = (
        "Analysiere diese Dokument-Ausschnitte und erkenne:\n"
        "1. Zeitraum des Materials (year_min, year_max als Integer)\n"
        "2. Wichtige historische Ereignisse oder Perioden mit Jahreszahlen – mindestens 3, maximal 8.\n"
        "   Jedes Ereignis MUSS dieses Format haben: {\"name\": \"...\", \"year_from\": 1234, \"year_to\": 1234}\n"
        "   year_from und year_to sind Integer-Jahreszahlen. Kein Fließtext, keine Sätze als name.\n"
        "   Gib konkrete Ereignisse aus dem Material zurück, keine leere Liste.\n"
        "3. Hauptsprache des Dokuments als Sprachcode (de/en/fr/tr/ar/andere) — "
        "beschreibe die Sprache des Quellmaterials, nicht die Sprache dieser Antwort.\n\n"
        "Wichtig: Antworte ausschließlich auf Deutsch. "
        "Antworte ausschließlich als JSON ohne Erklärungen, mit den Feldern:\n"
        "{\"year_min\": ..., \"year_max\": ..., \"events\": [...], \"language\": \"...\"}\n\n"
        f"Ausschnitte:\n---\n{sample_text}"
    )
    system = "Du bist ein Forschungsassistent der Notizen und Dokumente analysiert."
    try:
        analysis = await asyncio.to_thread(provider.complete_json, prompt, system)
    except (json.JSONDecodeError, ValueError):
        analysis = {}

    if not isinstance(analysis, dict):
        analysis = {}

    # Normalize events: drop entries that are not dicts with name+year_from+year_to
    raw_events = analysis.get("events", [])
    analysis["events"] = [
        e for e in raw_events
        if isinstance(e, dict) and e.get("name") and isinstance(e.get("year_from"), int)
    ] if isinstance(raw_events, list) else []

    analysis["organizer_headings"]    = organizer_headings
    analysis["bibliography_keywords"] = bibliography_keywords

    return {"ok": True, "project": project, "project_title": project_name or project,
            "document": doc_id, "analysis": analysis}


@app.post("/ingest/propose_taxonomy")
async def ingest_propose_taxonomy(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    async def gen():
        args = ["--project", project, "--document", doc_id]
        async for chunk in run_script_sse(PROPOSE_SCRIPT, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
        yield "data: __done__\n\n"
    return sse_response(gen())


@app.post("/ingest/save_config")
async def ingest_save_config(request: Request):
    body    = await request.json()
    project = body.get("project") or request.query_params.get("project") or get_current_project()
    doc_id  = body.get("document") or request.query_params.get("document") or get_current_document() or "main"

    # ── Projektebene: title, year_min/max, taxonomy, entities ──────────────────
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    proj_cfg_path = project_dir / "config.json"
    proj_cfg: dict = {}
    if proj_cfg_path.exists():
        try:
            proj_cfg = json.loads(proj_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    for field in ("title", "year_min", "year_max", "taxonomy", "entities"):
        if field in body:
            proj_cfg[field] = body[field]
    proj_cfg_path.write_text(json.dumps(proj_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Dokumentebene: doc_type, original_filename ──────────────────────────────
    doc_dir = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_cfg_path = doc_dir / "config.json"
    doc_cfg: dict = {}
    if doc_cfg_path.exists():
        try:
            doc_cfg = json.loads(doc_cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    for field in ("doc_type", "original_filename"):
        if field in body:
            doc_cfg[field] = body[field]
    doc_cfg_path.write_text(json.dumps(doc_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Pointer ────────────────────────────────────────────────────────────────
    _save_config_pointer(project, doc_id)

    # ── DB: Projekt anlegen oder Metadaten aktualisieren ───────────────────────
    db_proj = await get_project(project)
    if db_proj is None:
        db_proj = await create_project(
            project,
            title    = proj_cfg.get("title") or project,
            doc_type = doc_cfg.get("doc_type") or "",
        )
    else:
        await update_project(
            project,
            title    = proj_cfg.get("title") or db_proj["title"],
            doc_type = doc_cfg.get("doc_type") or db_proj["doc_type"],
        )
        db_proj = await get_project(project)

    return {"ok": True, "token": db_proj["token"]}


@app.post("/ingest/run")
async def ingest_run(request: Request):
    body     = await request.json()
    filename = body.get("filename", "")
    project  = body.get("project") or request.query_params.get("project") or get_current_project()
    doc_id   = body.get("document") or request.query_params.get("document") or get_current_document() or str(uuid.uuid4())[:8]
    if err := await _require_token(request, project): return err
    input_file = RAW_DIR / filename if filename else None

    # Ensure doc_id is persisted
    _save_config_pointer(project, doc_id)

    parse_args = ["--project", project, "--document", doc_id] + ([str(input_file)] if input_file else [])
    d_args     = ["--project", project, "--document", doc_id]
    p_args     = ["--project", project]  # project-only (for exploration export)

    steps = [
        (PARSE_SCRIPT,           parse_args),
        (DETECT_SCRIPT,          d_args),
        (INTERPOLATE_SCRIPT,     d_args),
        (CLASSIFY_SCRIPT,        d_args),
        (MATCH_ENTITIES_SCRIPT,  d_args),
        (EXPORT_SCRIPT,          d_args),
    ]

    async def gen():
        # Run main pipeline steps
        for script, args in steps:
            async for chunk in run_script_sse(script, args):
                if chunk == "data: __ok__\n\n":
                    break
                yield chunk
                if "__error__" in chunk:
                    yield "data: __done__\n\n"
                    return
        # Run exploration export as final step
        async for chunk in run_script_sse(EXPORT_EXPLORATION_SCRIPT, p_args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                break  # non-fatal: exploration failure doesn't abort
        yield f"data: __link__:http://localhost:8765/viz/?project={project}\n\n"
        yield "data: __done__\n\n"

    return sse_response(gen())


@app.post("/ingest/extract_entities")
async def ingest_extract_entities(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    async def gen():
        args = ["--project", project, "--document", doc_id, "--mode", "sample"]
        async for chunk in run_script_sse(EXTRACT_ENTITIES_SCRIPT, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
        yield "data: Merge…\n\n"
        try:
            _, stats = _do_merge(project, doc_id)
            yield (f"data: Merge: {stats['seed']} Seed + {stats['proposal']} Vorschläge "
                   f"→ {stats['prop_confirmed']} confirmed, {stats['prop_new']} NEU"
                   + (f", {stats['prop_skipped_rejected']} abgelehnt" if stats['prop_skipped_rejected'] else "")
                   + "\n\n")
        except Exception as exc:
            yield f"data: Merge-Fehler: {exc}\n\n"
        yield "data: __done__\n\n"
    return sse_response(gen())


@app.post("/ingest/extract_entities_full")
async def ingest_extract_entities_full(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    async def gen():
        args = ["--project", project, "--document", doc_id, "--mode", "full"]
        async for chunk in run_script_sse(EXTRACT_ENTITIES_FULL_SCRIPT, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
        yield "data: Merge…\n\n"
        try:
            _, stats = _do_merge(project, doc_id)
            yield (f"data: Merge: {stats['seed']} Seed + {stats['proposal']} Vorschläge "
                   f"→ {stats['prop_confirmed']} confirmed, {stats['prop_new']} NEU"
                   + (f", {stats['prop_skipped_rejected']} abgelehnt" if stats['prop_skipped_rejected'] else "")
                   + "\n\n")
        except Exception as exc:
            yield f"data: Merge-Fehler: {exc}\n\n"
        yield "data: __done__\n\n"
    return sse_response(gen())


@app.get("/ingest/entities/data")
async def get_entities_data(request: Request):
    if err := await _require_token(request): return err
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    doc_dir = get_doc_dir(project, doc_id)
    # Priority: merged (has _status) > seed (all confirmed) > proposal (all new)
    merged_path   = doc_dir / "entities_merged.json"
    seed_path     = doc_dir / "entities_seed.json"
    proposal_path = doc_dir / "entities_proposal.json"
    if merged_path.exists():
        return JSONResponse(json.loads(merged_path.read_text(encoding="utf-8")))
    if seed_path.exists():
        data = json.loads(seed_path.read_text(encoding="utf-8"))
        return JSONResponse([dict(**{k: v for k, v in e.items() if not k.startswith("_")},
                                  _status="confirmed") for e in data])
    if proposal_path.exists():
        data = json.loads(proposal_path.read_text(encoding="utf-8"))
        return JSONResponse([dict(**{k: v for k, v in e.items() if not k.startswith("_")},
                                  _status="new") for e in data])
    return JSONResponse([])


@app.post("/ingest/entities/save")
async def save_entities(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    body = await request.json()
    if not isinstance(body, list):
        return JSONResponse({"ok": False, "error": "Body muss ein JSON-Array sein"}, status_code=400)
    doc_dir = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    # Strip internal fields (_status, _source, etc.) before writing seed
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in body]
    (doc_dir / "entities_seed.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Delete stale merged file so next load reads fresh seed
    merged = doc_dir / "entities_merged.json"
    if merged.exists():
        merged.unlink()
    return {"ok": True, "count": len(clean)}


def _all_aliases_lc(ent: dict) -> set[str]:
    names = {(ent.get("normalform") or "").lower()}
    for a in ent.get("aliases") or []:
        if a:
            names.add(a.lower())
    return names - {""}


def _do_merge(project: str, doc_id: str) -> tuple[list[dict], dict]:
    """
    Mergt proposal + seed + rejected → entities_merged.json mit _status-Feldern.
    Gibt (result, stats) zurück. stats enthält Zählungen für Debug-Ausgabe.

    Hinweis: entities_proposal.json enthält seed-Entities (da extract_entities_v2
    intern merged), daher werden diese korrekt als confirmed erkannt sofern
    Alias-Überschneidung vorhanden ist.
    """
    doc_dir       = get_doc_dir(project, doc_id)
    seed_path     = doc_dir / "entities_seed.json"
    proposal_path = doc_dir / "entities_proposal.json"
    rejected_path = doc_dir / "entities_rejected.json"

    seed     = json.loads(seed_path.read_text(encoding="utf-8"))     if seed_path.exists()     else []
    proposal = json.loads(proposal_path.read_text(encoding="utf-8")) if proposal_path.exists() else []
    rejected = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []

    stats = {
        "seed": len(seed),
        "proposal": len(proposal),
        "rejected_file": len(rejected),
        "prop_confirmed": 0,
        "prop_new": 0,
        "prop_skipped_rejected": 0,
    }

    rejected_lc: set[str] = set()
    for e in rejected:
        rejected_lc |= _all_aliases_lc(e)

    # Seed → confirmed (strip internal fields from any previous run)
    result: list[dict] = [
        dict(**{k: v for k, v in e.items() if not k.startswith("_")}, _status="confirmed")
        for e in seed
    ]

    for prop in proposal:
        prop_lc = _all_aliases_lc(prop)
        if prop_lc & rejected_lc:
            stats["prop_skipped_rejected"] += 1
            continue
        match = next((e for e in result if _all_aliases_lc(e) & prop_lc), None)
        if match:
            # Merge any new aliases into the confirmed entry
            # Include normalform so it isn't re-added as an alias
            existing_lc = _all_aliases_lc(match)
            for a in prop.get("aliases") or []:
                if a and a.lower() not in existing_lc:
                    match.setdefault("aliases", []).append(a)
                    existing_lc.add(a.lower())
            stats["prop_confirmed"] += 1
        else:
            clean = {k: v for k, v in prop.items() if not k.startswith("_")}
            result.append(dict(**clean, _status="new"))
            stats["prop_new"] += 1

    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "entities_merged.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[merge] seed={stats['seed']} proposal={stats['proposal']} "
        f"→ confirmed={stats['prop_confirmed']} new={stats['prop_new']} "
        f"skipped(rejected)={stats['prop_skipped_rejected']} "
        f"total_result={len(result)}"
    )
    return result, stats


@app.post("/ingest/entities/merge")
async def merge_entities_endpoint(request: Request):
    if err := await _require_token(request): return err
    body    = {}
    try:
        body = await request.json()
    except Exception:
        pass
    project = body.get("project") or request.query_params.get("project") or get_current_project()
    doc_id  = body.get("document") or request.query_params.get("document") or get_current_document() or "main"
    result, _stats = _do_merge(project, doc_id)
    return JSONResponse(result)


@app.post("/ingest/entities/reject")
async def reject_entity(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Body muss ein Objekt sein"}, status_code=400)
    project = body.get("project") or request.query_params.get("project") or get_current_project()
    doc_id  = body.get("document") or request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    doc_dir       = get_doc_dir(project, doc_id)
    rejected_path = doc_dir / "entities_rejected.json"
    rejected      = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
    norm_lc       = (body.get("normalform") or "").lower()
    if norm_lc and not any((e.get("normalform") or "").lower() == norm_lc for e in rejected):
        rejected.append({"normalform": body["normalform"], "aliases": body.get("aliases") or []})
        rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    # Remove from merged.json immediately so editor reflects change
    merged_path = doc_dir / "entities_merged.json"
    if merged_path.exists():
        merged = json.loads(merged_path.read_text(encoding="utf-8"))
        merged = [e for e in merged if (e.get("normalform") or "").lower() != norm_lc]
        merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/ingest/segments/data")
async def get_segments_data(request: Request):
    project = request.query_params.get("project") or get_current_project()
    doc_id  = request.query_params.get("document") or get_current_document() or "main"
    if err := await _require_token(request, project): return err
    doc_dir = get_doc_dir(project, doc_id)
    segs_path = doc_dir / "segments.json"
    if segs_path.exists():
        return JSONResponse(json.loads(segs_path.read_text(encoding="utf-8")))
    return JSONResponse([])


@app.get("/ingest/entities")
async def get_entity_editor():
    return HTMLResponse(content=_render_template("entity_editor.html", APP_CSS=APP_CSS))


@app.get("/api/projects")
async def list_projects_endpoint():
    db_rows = await db_list_projects()
    result  = []
    for row in db_rows:
        entry_count = 0
        data_path = PROJECTS_DIR / row["id"] / "exploration" / "data.json"
        if data_path.exists():
            try:
                entry_count = json.loads(data_path.read_text(encoding="utf-8")).get("count", 0)
            except Exception:
                pass
        result.append({
            "id":          row["id"],
            "title":       row["title"],
            "doc_type":    row["doc_type"],
            "entry_count": entry_count,
        })
    return JSONResponse(result)


@app.get("/api/projects/{project_id}")
async def get_project_endpoint(project_id: str):
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    cfg: dict = {}
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return JSONResponse({
        "ok":       True,
        "id":       proj["id"],
        "title":    proj["title"],
        "doc_type": proj["doc_type"],
        "year_min": cfg.get("year_min"),
        "year_max": cfg.get("year_max"),
    })


@app.put("/api/projects/{project_id}")
async def update_project_endpoint(project_id: str, request: Request):
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title darf nicht leer sein"}, status_code=400)
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    await update_project(project_id, title=title)
    # Auch config.json auf Dateisystem aktualisieren
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg["title"] = title
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    return JSONResponse({"ok": True, "id": project_id, "title": title})


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str, request: Request):
    body = await request.json()
    if not body.get("confirm"):
        return JSONResponse({"ok": False, "error": "confirm: true erforderlich"}, status_code=400)
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir)
    await delete_project(project_id)
    return JSONResponse({"ok": True})


@app.get("/editor")
async def get_editor(request: Request):
    project_id = request.query_params.get("project") or get_current_project()
    if not project_id:
        return HTMLResponse("<p>Kein Projekt angegeben.</p>", status_code=400)
    proj = await get_project(project_id)
    title = (proj["title"] if proj else None) or project_id
    token = proj["token"] if proj else None
    # Neuestes Dokument mit preview.html finden (nach ingested_at; Fallback: alphabetisch letztes)
    project_dir = PROJECTS_DIR / project_id / "documents"
    preview_html = None
    doc_id = None
    if project_dir.exists():
        candidates = []
        for doc_dir in project_dir.iterdir():
            if (doc_dir / "preview.html").exists():
                ingested_at = ""
                cfg_p = doc_dir / "config.json"
                if cfg_p.exists():
                    try:
                        ingested_at = json.loads(cfg_p.read_text(encoding="utf-8")).get("ingested_at", "")
                    except Exception:
                        pass
                candidates.append((ingested_at, doc_dir.name, doc_dir))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best = candidates[0][2]
            preview_html = (best / "preview.html").read_text(encoding="utf-8")
            doc_id = best.name
    if not preview_html:
        return HTMLResponse(f"<p>Keine Preview f\u00fcr Projekt \"{title}\" gefunden.</p>", status_code=404)
    from urllib.parse import urlencode
    preview_params = {"project": project_id}
    if doc_id:
        preview_params["document"] = doc_id
    if token:
        preview_params["token"] = token
    preview_url = "/preview?" + urlencode(preview_params)
    header = (
        f'<div style="background:#1e293b;color:#fff;padding:10px 20px;font-size:13px;'
        f'font-family:system-ui,sans-serif;display:flex;align-items:center;gap:12px;">'
        f'<strong>Daten bearbeiten</strong><span style="color:#94a3b8;">–</span>'
        f'<span>{title}</span>'
        f'<a href="{preview_url}" style="margin-left:auto;padding:5px 12px;background:#2563eb;'
        f'color:#fff;border-radius:4px;text-decoration:none;font-size:11px;font-weight:600;">'
        f'Zeitanker bearbeiten \u2192</a></div>'
    )
    html = preview_html.replace("<body>", f"<body>{header}", 1)
    return HTMLResponse(content=html)


@app.get("/api/projects/{project_id}/token")
async def get_project_token(project_id: str):
    # TODO: Schütze diesen Endpoint mit Auth sobald der Server öffentlich erreichbar ist
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Projekt nicht gefunden"}, status_code=404)
    # Neuestes Dokument mit segments.json ermitteln (nach ingested_at, Fallback: alphabetisch letztes)
    doc_id = None
    doc_dir = PROJECTS_DIR / project_id / "documents"
    if doc_dir.exists():
        candidates = []
        for d in doc_dir.iterdir():
            if (d / "segments.json").exists():
                ingested_at = ""
                cfg_p = d / "config.json"
                if cfg_p.exists():
                    try:
                        ingested_at = json.loads(cfg_p.read_text(encoding="utf-8")).get("ingested_at", "")
                    except Exception:
                        pass
                candidates.append((ingested_at, d.name))
        if candidates:
            candidates.sort(reverse=True)
            doc_id = candidates[0][1]
    return JSONResponse({"ok": True, "id": proj["id"], "token": proj["token"],
                         "created_at": proj["created_at"], "doc_id": doc_id})


@app.get("/ingest")
async def get_ingest_wizard():
    return HTMLResponse(content=_render_template("ingest_wizard.html", APP_CSS=APP_CSS))


# ── Shared CSS (tokens + base classes, injected into every page) ───────────────

APP_CSS = """\
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{font-size:13px}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
     background:var(--c-bg);color:var(--c-text);min-height:100vh;display:flex;flex-direction:column}
:root{
  --c-bg:#f4f3f0;--c-surface:#fff;
  --c-border:#e5e2dc;--c-border-ui:#e0ddd8;
  --c-text:#1a1a1a;--c-text-2:#555;--c-text-3:#888;--c-text-4:#aaa;
  --c-primary:#6d28d9;--c-primary-h:#5b21b6;
  --c-primary-tint:#ede9fe;--c-primary-bg:#faf5ff;--c-primary-ring:#c4b5fd;
  --c-success:#16a34a;--c-danger:#dc2626;
  --c-danger-bg:#fef2f2;--c-danger-border:#fca5a5;
  --c-code-bg:#f8fafc;--c-code-border:#e2e8f0;
}
.app-header{background:var(--c-surface);border-bottom:1px solid var(--c-border-ui);
            padding:11px 24px;display:flex;align-items:center;gap:10px;
            position:sticky;top:0;z-index:10;flex-wrap:wrap}
.app-header h1{font-size:14px;font-weight:600;color:var(--c-text);flex:1;margin-right:auto}
.app-status{font-size:11px;color:var(--c-text-3)}
.btn{padding:5px 12px;border-radius:4px;font-size:12px;cursor:pointer;
     border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-text-2);
     transition:background .15s,color .15s,border-color .15s;white-space:nowrap;
     font-family:inherit;text-decoration:none;display:inline-flex;align-items:center}
.btn:hover:not(:disabled){background:#f3f4f6}
.btn:disabled{opacity:.4;cursor:default}
.btn-primary{background:var(--c-primary);border-color:var(--c-primary);color:#fff}
.btn-primary:hover:not(:disabled){background:var(--c-primary-h);border-color:var(--c-primary-h)}
.btn-outline{border-color:var(--c-primary);color:var(--c-primary)}
.btn-outline:hover:not(:disabled){background:var(--c-primary);color:#fff}
.btn-success{border-color:var(--c-success);color:var(--c-success)}
.btn-success:hover:not(:disabled){background:var(--c-success);color:#fff;border-color:var(--c-success)}
.btn-dashed{border:1px dashed var(--c-primary-ring);background:var(--c-primary-bg);color:var(--c-primary)}
.btn-dashed:hover:not(:disabled){background:var(--c-primary-tint)}
.btn-sm{padding:3px 9px;font-size:11px;border-radius:3px}
.card{background:var(--c-surface);border:1px solid var(--c-border);border-radius:6px}
.card:hover{border-color:var(--c-primary-ring)}
.input{padding:4px 8px;border:1px solid #d1d5db;border-radius:3px;font-size:12px;
       font-family:inherit;background:var(--c-surface)}
.input:hover:not(:focus){border-color:#9ca3af}
.input:focus{border-color:var(--c-primary);outline:none;background:var(--c-primary-bg)}
.log-box{font-size:11px;font-family:ui-monospace,monospace;white-space:pre-wrap;
         background:var(--c-code-bg);border:1px solid var(--c-code-border);
         border-radius:4px;padding:8px 12px;max-height:200px;overflow-y:auto;display:none}
.log-box.collapsed{max-height:40px;overflow:hidden;cursor:default}
.log-box.error{background:var(--c-danger-bg);border-color:var(--c-danger-border);color:var(--c-danger)}
.log-toggle{font-size:10px;cursor:pointer;color:var(--c-muted);user-select:none;
            margin-top:3px;display:none}
.log-toggle:hover{color:var(--c-text)}
.section-label{font-size:10px;font-weight:600;color:var(--c-text-3);
               text-transform:uppercase;letter-spacing:.06em}
.chip{display:inline-flex;align-items:center;gap:3px;background:var(--c-primary-tint);
      border-radius:10px;padding:2px 8px;font-size:11px;color:#4c1d95}
.chip-del{border:none;background:none;cursor:pointer;color:var(--c-primary);
          font-size:12px;line-height:1;padding:0 2px}
.chip-del:hover{color:var(--c-danger)}
"""



