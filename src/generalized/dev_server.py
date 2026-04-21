"""
dev_server.py — lokaler Entwicklungs-Server

Endpoints:
  POST /overrides              — overrides.json speichern
  POST /recompute              — interpolate → export als SSE
  GET  /preview                — preview.html ausliefern
  GET  /taxonomy               — Taxonomy-Editor HTML
  GET  /taxonomy/data          — config.json["taxonomy"]
  POST /taxonomy/save          — Taxonomie speichern
  GET  /ingest                 — Ingest-Wizard HTML
  POST /ingest/upload          — Dateien nach data/raw/ speichern
  POST /ingest/analyze         — parse + LLM-Analyse, gibt JSON zurück
  POST /ingest/propose_taxonomy — propose_taxonomy.py auf aktuellen Segmenten, SSE
  POST /ingest/save_config     — project_config.json schreiben
  POST /ingest/run             — vollständige Pipeline als SSE
  GET  /viz/                   — Exploration-Viz (StaticFiles aus viz/)
  GET  /data/projects/         — Projektdaten (StaticFiles, für viz/DATA_BASE)

Starten:
  uvicorn src.generalized.dev_server:app --port 8001 --reload
"""

import asyncio
import html
import json
import os
import random
import re
import sys
import uuid
from pathlib import Path
from typing import List
from urllib.parse import urlencode

from src.generalized.llm import get_provider, TASK_ANALYZE
import shutil

from src.generalized.db import (
    init_db, create_project, get_project, list_projects as db_list_projects,
    update_project, delete_project, token_valid,
)
from src.generalized.utils import render_template as _render_template
from src.generalized.invite_auth import invite_required, invite_valid, invite_info
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.generalized.config import ROOT, DATA_ROOT
PROJECTS_DIR       = DATA_ROOT / "projects"
RAW_DIR            = DATA_ROOT / "raw"
VIZ_DIR            = ROOT / "viz"

PARSE_SCRIPT               = ROOT / "src" / "generalized" / "parse_document.py"
DETECT_SCRIPT              = ROOT / "src" / "generalized" / "detect_anchors.py"
INTERPOLATE_SCRIPT         = ROOT / "src" / "generalized" / "interpolate_anchors.py"
CLASSIFY_SCRIPT            = ROOT / "src" / "generalized" / "classify_segments.py"
EXPORT_SCRIPT              = ROOT / "src" / "generalized" / "export_preview.py"
EXPORT_EXPLORATION_SCRIPT  = ROOT / "src" / "generalized" / "export_exploration.py"
PROPOSE_SCRIPT             = ROOT / "src" / "generalized" / "propose_taxonomy.py"
EXTRACT_ENTITIES_SCRIPT    = ROOT / "src" / "generalized" / "extract_entities_v2.py"
MATCH_ENTITIES_SCRIPT      = ROOT / "src" / "generalized" / "match_entities.py"

app = FastAPI(title="Generalized Dev Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _get_invite(request: Request) -> str:
    return (
        request.query_params.get("invite")
        or request.headers.get("X-Invite-Token")
        or request.cookies.get("invite_token")
        or ""
    )


@app.middleware("http")
async def invite_gate_middleware(request: Request, call_next):
    """Invite-Token-Gate: aktiv sobald invites.json existiert und Einträge hat."""
    if not invite_required():
        return await call_next(request)
    # Validation endpoint immer freigeben
    if request.url.path == "/api/check_invite":
        return await call_next(request)
    # Admin-Bypass (nur wenn ADMIN_KEY konfiguriert)
    admin_key = os.environ.get("ADMIN_KEY")
    if admin_key:
        auth     = request.headers.get("Authorization", "")
        provided = auth.removeprefix("Bearer ").strip() or request.query_params.get("admin_key", "")
        if provided == admin_key:
            return await call_next(request)
    if invite_valid(_get_invite(request)):
        return await call_next(request)
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        gate_html = _render_template("invite_gate.html")
        return HTMLResponse(gate_html, status_code=401)
    return JSONResponse({"error": "Einladungstoken fehlt oder ungültig"}, status_code=401)


@app.on_event("startup")
async def startup():
    await init_db()


# ── Invite-Token Validation ────────────────────────────────────────────────────

@app.get("/api/check_invite")
async def check_invite(request: Request):
    token = _get_invite(request)
    if invite_valid(token):
        info = invite_info(token) or {}
        return JSONResponse({"ok": True, "name": info.get("name", "")})
    return JSONResponse({"ok": False}, status_code=401)


# ── Projekt-Token-Prüfung ──────────────────────────────────────────────────────

def _require_admin_key(request: Request) -> JSONResponse | None:
    """
    Prüft optionalen ADMIN_KEY aus .env.
    Wenn nicht gesetzt: immer erlaubt (lokaler Dev-Modus).
    Wenn gesetzt: muss als 'Authorization: Bearer <key>' oder ?admin_key= übergeben werden.
    """
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return None
    auth = request.headers.get("Authorization", "")
    provided = auth.removeprefix("Bearer ").strip() or request.query_params.get("admin_key", "")
    if provided != admin_key:
        return JSONResponse({"ok": False, "error": "Admin-Key fehlt oder ungültig"}, status_code=403)
    return None


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
    proj_id = project or request.query_params.get("project")
    db_proj = await get_project(proj_id)
    if not db_proj:
        return JSONResponse({"ok": False, "error": "Projekt nicht gefunden"}, status_code=403)
    if not token_valid(db_proj, token):
        return JSONResponse({"ok": False, "error": "Token ungültig oder abgelaufen"}, status_code=403)
    return None


# ── Projekt-Hilfsfunktionen ────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Menschlicher Projektname → technische ID (lowercase, Leerzeichen→_, Sonderzeichen weg)."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "_", s)
    s = s.strip("_")
    return s or "projekt"


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
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document Parameter erforderlich"}, status_code=400)
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
        # D-P1: einzige Quelle ist config.json["taxonomy"] — kein Fallback mehr
        taxonomy = None
        if config_p.exists():
            taxonomy = json.loads(config_p.read_text(encoding="utf-8")).get("taxonomy") or None
        classifications = {r["segment_id"]: r for r in classified if r.get("segment_id")}
        return build_quality_report(list(classifications.values()), classifications, taxonomy)
    except Exception as e:
        print(f"_compute_quality_report fehlgeschlagen: {e}", file=sys.stderr)
        return None


async def recompute_sse(project: str, doc_id: str):
    d_args = ["--project", project, "--document", doc_id]
    # I7: match_entities nach interpolate → actors nach manuellen Zeitkorrekturen aktuell
    steps  = [(INTERPOLATE_SCRIPT, d_args), (MATCH_ENTITIES_SCRIPT, d_args), (EXPORT_SCRIPT, d_args)]
    async for chunk in run_pipeline_sse(steps):
        if chunk == "data: __done__\n\n":
            report = _compute_quality_report(project, doc_id)
            if report:
                yield f"data: __report__:{json.dumps(report, ensure_ascii=False)}\n\n"
        yield chunk


@app.post("/recompute")
async def recompute(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    return sse_response(recompute_sse(project, doc_id))


# ── GET /preview ───────────────────────────────────────────────────────────────

@app.get("/preview")
async def get_preview(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    preview_p = get_doc_dir(project, doc_id) / "preview.html"
    if not preview_p.exists():
        return HTMLResponse("<p>preview.html nicht gefunden.</p>", status_code=404)
    return HTMLResponse(content=preview_p.read_text(encoding="utf-8"))


# ── Taxonomy endpoints ─────────────────────────────────────────────────────────

@app.get("/taxonomy/data")
async def get_taxonomy_data(request: Request):
    project = request.query_params.get("project")
    if not project:
        return JSONResponse({"error": "project Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    config_p = get_project_dir(project) / "config.json"
    # D-P1: einzige Quelle ist config.json["taxonomy"] — kein Fallback mehr
    if config_p.exists():
        taxonomy = json.loads(config_p.read_text(encoding="utf-8")).get("taxonomy") or []
        return JSONResponse(taxonomy)
    return JSONResponse([])


@app.post("/taxonomy/save")
async def save_taxonomy(request: Request):
    project = request.query_params.get("project")
    if not project:
        return JSONResponse({"ok": False, "error": "project Parameter erforderlich"}, status_code=400)
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
        except (json.JSONDecodeError, OSError):
            pass
    cfg["taxonomy"] = body
    config_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(body)}


@app.get("/taxonomy")
async def get_taxonomy_editor():
    return HTMLResponse(content=_render_template("taxonomy_editor.html"))


# ── Ingest endpoints ───────────────────────────────────────────────────────────

@app.post("/ingest/upload")
async def ingest_upload(files: List[UploadFile] = File(...)):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        content = await f.read()
        safe_name = Path(f.filename).name
        if not safe_name:
            continue
        dest = RAW_DIR / safe_name
        dest.write_bytes(content)
        saved.append({"name": safe_name, "size": len(content)})
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
    project  = _slugify(project_name) if project_name else body.get("project")
    if not project:
        return JSONResponse({"ok": False, "error": "project_name oder project im Body erforderlich"}, status_code=400)
    doc_id   = body.get("document") or str(uuid.uuid4())[:8]

    input_file = RAW_DIR / filename
    doc_dir    = get_doc_dir(project, doc_id)
    segments_p = doc_dir / "segments.json"

    if not input_file.exists():
        return JSONResponse({"ok": False, "error": f"Datei nicht gefunden: {filename}"}, status_code=404)

    # 1. parse_document → documents/{doc_id}/segments.json
    parse_args = ["--project", project, "--document", doc_id, str(input_file)]
    if doc_type:
        parse_args += ["--doc-type", doc_type]
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(PARSE_SCRIPT), *parse_args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
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

    seen_sources: dict[str, None] = {}
    for s in segments:
        src = s.get("source")
        if s.get("type") == "content" and src:
            seen_sources[src] = None
    organizer_headings = list(seen_sources.keys())

    bibliography_keywords = [
        s["text"][:60] for s in segments
        if s.get("type") == "bibliography" and s.get("text")
    ][:10]

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
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
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
    project = body.get("project") or request.query_params.get("project")
    doc_id  = body.get("document") or request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document erforderlich"}, status_code=400)

    # ── Projektebene: title, year_min/max, taxonomy, entities ──────────────────
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    proj_cfg_path = project_dir / "config.json"
    proj_cfg: dict = {}
    if proj_cfg_path.exists():
        try:
            proj_cfg = json.loads(proj_cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    for field in ("title", "year_min", "year_max", "taxonomy", "entities"):
        if field in body:
            proj_cfg[field] = body[field]
    if "time_config" in body:
        tc = body["time_config"]
        if isinstance(tc, dict):
            if "year_min" in tc:
                proj_cfg["year_min"] = tc["year_min"]
            if "year_max" in tc:
                proj_cfg["year_max"] = tc["year_max"]
            if "events" in tc:
                proj_cfg["events"] = tc["events"]
    proj_cfg_path.write_text(json.dumps(proj_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Dokumentebene: doc_type, original_filename ──────────────────────────────
    doc_dir = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_cfg_path = doc_dir / "config.json"
    doc_cfg: dict = {}
    if doc_cfg_path.exists():
        try:
            doc_cfg = json.loads(doc_cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    for field in ("doc_type", "original_filename"):
        if field in body:
            doc_cfg[field] = body[field]
    doc_cfg_path.write_text(json.dumps(doc_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

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
    project  = body.get("project") or request.query_params.get("project")
    doc_id   = body.get("document") or request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    input_file = RAW_DIR / filename if filename else None

    parse_args = ["--project", project, "--document", doc_id] + ([str(input_file)] if input_file else [])
    d_args     = ["--project", project, "--document", doc_id]
    p_args     = ["--project", project]  # project-only (for exploration export)

    # Zeitanker-Schritte überspringen wenn anchors_interpolated.json neuer als segments.json
    doc_dir        = get_doc_dir(project, doc_id)
    anchors_path   = doc_dir / "anchors_interpolated.json"
    segments_path  = doc_dir / "segments.json"
    anchors_fresh  = (
        anchors_path.exists() and segments_path.exists() and
        anchors_path.stat().st_mtime > segments_path.stat().st_mtime
    )

    steps = [
        (PARSE_SCRIPT,           parse_args),
    ]
    if not anchors_fresh:
        steps += [
            (DETECT_SCRIPT,      d_args),
            (INTERPOLATE_SCRIPT, d_args),
        ]
    steps += [
        (CLASSIFY_SCRIPT,        d_args),
        (MATCH_ENTITIES_SCRIPT,  d_args),
    ]
    if not anchors_fresh:
        steps.append((EXPORT_SCRIPT, d_args))

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
        yield f"data: __link__:/viz/?project={project}\n\n"
        yield "data: __done__\n\n"

    return sse_response(gen())


@app.post("/ingest/run/step")
async def ingest_run_step(request: Request):
    body     = await request.json()
    step     = body.get("step", "")
    filename = body.get("filename", "")
    force    = body.get("force", False)
    project  = body.get("project") or request.query_params.get("project")
    doc_id   = body.get("document") or request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err

    input_file    = RAW_DIR / filename if filename else None
    parse_args    = ["--project", project, "--document", doc_id] + ([str(input_file)] if input_file else [])
    d_args        = ["--project", project, "--document", doc_id]
    p_args        = ["--project", project]
    classify_args = d_args + (["--force"] if force else [])

    _STEP_MAP = {
        "parse_document.py":       (PARSE_SCRIPT,              parse_args),
        "detect_anchors.py":       (DETECT_SCRIPT,             d_args),
        "interpolate_anchors.py":  (INTERPOLATE_SCRIPT,        d_args),
        "classify_segments.py":    (CLASSIFY_SCRIPT,           classify_args),
        "match_entities.py":       (MATCH_ENTITIES_SCRIPT,     d_args),
        "export_preview.py":       (EXPORT_SCRIPT,             d_args),
        "export_exploration.py":   (EXPORT_EXPLORATION_SCRIPT, p_args),
    }
    if step not in _STEP_MAP:
        return JSONResponse({"ok": False, "error": f"Unbekannter Schritt: {step}"}, status_code=400)

    script, args = _STEP_MAP[step]

    async def gen():
        had_error = False
        async for chunk in run_script_sse(script, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                had_error = True
                break
        # D-P3: nach classify immer match_entities nachschalten
        if not had_error and step == "classify_segments.py":
            async for chunk in run_script_sse(MATCH_ENTITIES_SCRIPT, d_args):
                if chunk == "data: __ok__\n\n":
                    break
                yield chunk
                if "__error__" in chunk:
                    break
        yield "data: __done__\n\n"

    return sse_response(gen())


@app.post("/ingest/extract_entities")
async def ingest_extract_entities(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    body = {}
    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        pass
    mode = body.get("mode", "sample")
    if mode not in ("sample", "full"):
        return JSONResponse({"error": "mode muss 'sample' oder 'full' sein"}, status_code=400)
    async def gen():
        args = ["--project", project, "--document", doc_id, "--mode", mode]
        async for chunk in run_script_sse(EXTRACT_ENTITIES_SCRIPT, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                return
        yield "data: __done__\n\n"
    return sse_response(gen())


@app.get("/ingest/entities/data")
async def get_entities_data(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir      = get_doc_dir(project, doc_id)
    proposal_path = doc_dir / "entities_proposal.json"
    if proposal_path.exists():
        data = json.loads(proposal_path.read_text(encoding="utf-8"))
        return JSONResponse([dict(**{k: v for k, v in e.items() if not k.startswith("_")},
                                  _status="confirmed") for e in data])
    # Kein frischer Extraction-Run: config.json["entities"] als Fallback
    config_p = get_project_dir(project) / "config.json"
    if config_p.exists():
        cfg_entities = json.loads(config_p.read_text(encoding="utf-8")).get("entities") or []
        if cfg_entities:
            return JSONResponse([dict(**{k: v for k, v in e.items() if not k.startswith("_")},
                                      _status="confirmed") for e in cfg_entities])
    return JSONResponse([])


@app.post("/ingest/entities/save")
async def save_entities(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    body = await request.json()
    if not isinstance(body, list):
        return JSONResponse({"ok": False, "error": "Body muss ein JSON-Array sein"}, status_code=400)
    # Strip internal fields (_status, _source, etc.) before writing
    clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in body]
    # Kanonische Quelle: entities_proposal.json (doc-level)
    doc_dir = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "entities_proposal.json").write_text(
        json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # Spiegel in config.json["entities"] für Pipeline-Schritte (classify, match_entities)
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    config_p = project_dir / "config.json"
    cfg: dict = {}
    if config_p.exists():
        try:
            cfg = json.loads(config_p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    cfg["entities"] = clean
    config_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(clean)}




@app.post("/ingest/entities/reject")
async def reject_entity(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Body muss ein Objekt sein"}, status_code=400)
    project = body.get("project") or request.query_params.get("project")
    doc_id  = body.get("document") or request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir       = get_doc_dir(project, doc_id)
    rejected_path = doc_dir / "entities_rejected.json"
    rejected      = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
    norm_lc       = (body.get("normalform") or "").lower()
    if norm_lc and not any((e.get("normalform") or "").lower() == norm_lc for e in rejected):
        rejected.append({"normalform": body["normalform"], "aliases": body.get("aliases") or []})
        rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    # Remove from entities_proposal.json immediately so editor reflects change
    proposal_path = doc_dir / "entities_proposal.json"
    if proposal_path.exists():
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal = [e for e in proposal if (e.get("normalform") or "").lower() != norm_lc]
        proposal_path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/ingest/doc_status")
async def get_doc_status(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir = get_doc_dir(project, doc_id)
    return JSONResponse({
        "segments":   (doc_dir / "segments.json").exists(),
        "anchors":    (doc_dir / "anchors_interpolated.json").exists(),
        "classified": (doc_dir / "classified.json").exists(),
        "preview":    (doc_dir / "preview.html").exists(),
    })


@app.post("/ingest/classified/update")
async def update_classified(request: Request):
    body       = await request.json()
    project    = request.query_params.get("project")
    doc_id     = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    segment_id = body.get("segment_id")
    category   = body.get("category") or ""
    if not segment_id:
        return JSONResponse({"ok": False, "error": "segment_id fehlt"}, status_code=400)
    doc_dir = get_doc_dir(project, doc_id)
    classified_path = doc_dir / "classified.json"
    if not classified_path.exists():
        return JSONResponse({"ok": False, "error": "classified.json nicht gefunden"}, status_code=404)
    rows = json.loads(classified_path.read_text(encoding="utf-8"))
    updated = False
    for row in rows:
        if row.get("segment_id") == segment_id:
            row["category"] = category
            updated = True
            break
    if not updated:
        return JSONResponse({"ok": False, "error": "segment_id nicht gefunden"}, status_code=404)
    classified_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/ingest/segments/data")
async def get_segments_data(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir = get_doc_dir(project, doc_id)
    segs_path = doc_dir / "segments.json"
    if segs_path.exists():
        return JSONResponse(json.loads(segs_path.read_text(encoding="utf-8")))
    return JSONResponse([])


@app.get("/ingest/entities")
async def get_entity_editor():
    return HTMLResponse(content=_render_template("entity_editor.html"))


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
            except (json.JSONDecodeError, OSError):
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
        except (json.JSONDecodeError, OSError):
            pass
    return JSONResponse({
        "ok":       True,
        "id":       proj["id"],
        "title":    proj["title"],
        "doc_type": proj["doc_type"],
        "year_min": cfg.get("year_min"),
        "year_max": cfg.get("year_max"),
        "events":   cfg.get("events") or [],
        "taxonomy": cfg.get("taxonomy") or [],
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
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warnung: config.json für {project_id} konnte nicht aktualisiert werden: {e}",
                  file=sys.stderr)
    return JSONResponse({"ok": True, "id": project_id, "title": title})


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str, request: Request):
    body = await request.json()
    if not body.get("confirm"):
        return JSONResponse({"ok": False, "error": "confirm: true erforderlich"}, status_code=400)
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    if ".." in project_id or "/" in project_id:
        return JSONResponse({"error": "Ungültige project_id"}, status_code=400)
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        shutil.rmtree(project_dir)
    await delete_project(project_id)
    return JSONResponse({"ok": True})


@app.get("/editor")
async def get_editor(request: Request):
    project_id = request.query_params.get("project")
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
                    except (json.JSONDecodeError, OSError):
                        pass
                candidates.append((ingested_at, doc_dir.name, doc_dir))
        if candidates:
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best = candidates[0][2]
            preview_html = (best / "preview.html").read_text(encoding="utf-8")
            doc_id = best.name
    if not preview_html:
        return HTMLResponse(f"<p>Keine Preview f\u00fcr Projekt \"{title}\" gefunden.</p>", status_code=404)
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
        f'<span>{html.escape(title)}</span>'
        f'<a href="{preview_url}" style="margin-left:auto;padding:5px 12px;background:#2563eb;'
        f'color:#fff;border-radius:4px;text-decoration:none;font-size:11px;font-weight:600;">'
        f'Zeitanker bearbeiten \u2192</a></div>'
    )
    html = preview_html.replace("<body>", f"<body>{header}", 1)
    return HTMLResponse(content=html)


@app.get("/api/projects/{project_id}/token")
async def get_project_token(project_id: str, request: Request):
    if err := _require_admin_key(request): return err
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
                    except (json.JSONDecodeError, OSError):
                        pass
                candidates.append((ingested_at, d.name))
        if candidates:
            candidates.sort(reverse=True)
            doc_id = candidates[0][1]
    return JSONResponse({"ok": True, "id": proj["id"], "token": proj["token"],
                         "created_at": proj["created_at"], "doc_id": doc_id})


@app.get("/ingest")
async def get_ingest_wizard():
    return HTMLResponse(content=_render_template("ingest_wizard.html"))


# ── Static file mounts (after all route handlers) ─────────────────────────────
# /viz/ → viz/ (Exploration-Visualisierung)
# /data/projects/ → data/projects/ (exploration/*.json für boot.js via DATA_BASE)
if VIZ_DIR.exists():
    app.mount("/viz", StaticFiles(directory=VIZ_DIR, html=True), name="viz")
if PROJECTS_DIR.exists():
    app.mount("/data/projects", StaticFiles(directory=PROJECTS_DIR), name="projects_data")

