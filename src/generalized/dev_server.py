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

from src.generalized.llm import get_provider, TASK_ANALYZE, TASK_CHAT
import shutil

from src.generalized.db import (
    init_db, create_project, get_project,
    list_projects as db_list_projects,
    update_project, delete_project, token_valid,
    upsert_document, get_latest_doc_id,
)
from src.generalized.utils import render_template as _render_template, read_json_safe, validate_doc_id
from src.generalized.invite_auth import invite_required, invite_valid, invite_info
from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.generalized.config import ROOT, DATA_ROOT
load_dotenv(ROOT / ".env")
PROJECTS_DIR          = DATA_ROOT / "projects"
RAW_DIR               = DATA_ROOT / "raw"
DROPBOX_TOKENS_PATH   = DATA_ROOT / "dropbox_tokens.json"
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
INGEST_OBSIDIAN_SCRIPT     = ROOT / "src" / "generalized" / "ingest_obsidian.py"

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
    from src.generalized.seed_ber import seed_ber
    await seed_ber()
    try:
        from src.generalized.entity_gliner import _load_gliner
        from src.generalized.config import GLINER_MODEL
        import asyncio
        await asyncio.get_event_loop().run_in_executor(None, _load_gliner, GLINER_MODEL)
    except Exception as exc:
        print(f"[startup] GLiNER konnte nicht geladen werden: {exc}", file=__import__("sys").stderr)


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


def _require_admin_or_invite(request: Request) -> JSONResponse | None:
    """ADMIN_KEY ODER gültiger invite-Token reicht. Ohne ADMIN_KEY: immer erlaubt."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return None
    auth = request.headers.get("Authorization", "")
    provided = auth.removeprefix("Bearer ").strip() or request.query_params.get("admin_key", "")
    if provided == admin_key:
        return None
    if invite_valid(_get_invite(request)):
        return None
    return JSONResponse({"ok": False, "error": "Admin-Key oder Einladungstoken erforderlich"}, status_code=403)


def _is_admin(request: Request) -> bool:
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return True
    auth = request.headers.get("Authorization", "")
    provided = auth.removeprefix("Bearer ").strip() or request.query_params.get("admin_key", "")
    return provided == admin_key


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
    owner = db_proj.get("owner_token")
    is_public = db_proj.get("is_public", 0)
    if owner and not is_public and not _is_admin(request) and owner != _get_invite(request):
        return JSONResponse({"ok": False, "error": "Kein Zugriff auf dieses Projekt"}, status_code=403)
    return None


# ── Projekt-Hilfsfunktionen ────────────────────────────────────────────────────

# Locks für config.json-Writes: verhindert Race Conditions wenn mehrere Requests
# gleichzeitig taxonomy, entities oder andere Felder in dieselbe Datei schreiben.
_project_locks: dict[str, asyncio.Lock] = {}

def _project_lock(project: str) -> asyncio.Lock:
    if project not in _project_locks:
        _project_locks[project] = asyncio.Lock()
    return _project_locks[project]


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
    if not validate_doc_id(doc_id):
        return JSONResponse({"error": "invalid document id"}, status_code=400)
    if err := await _require_token(request, project): return err
    body = await request.json()
    if not isinstance(body, list):
        return JSONResponse({"ok": False, "error": "Body muss ein JSON-Array sein"}, status_code=400)
    doc_dir  = get_doc_dir(project, doc_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    overrides_p = doc_dir / "overrides.json"
    overrides_p.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return sse_response(recompute_sse(project, doc_id))


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
        taxonomy = read_json_safe(config_p).get("taxonomy") or None
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
    return JSONResponse(read_json_safe(config_p).get("taxonomy") or [])


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
    async with _project_lock(project):
        cfg = read_json_safe(config_p)
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
    raw_project  = project_name or body.get("project", "")
    project      = _slugify(raw_project) if raw_project else None
    if not project:
        return JSONResponse({"ok": False, "error": "project_name oder project im Body erforderlich"}, status_code=400)
    doc_id   = body.get("document") or str(uuid.uuid4())[:8]
    if not validate_doc_id(doc_id):
        return JSONResponse({"ok": False, "error": "invalid document id"}, status_code=400)

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

    # 3. Analyse: presseartikel → aus segments.json, buchnotizen → LLM
    if doc_type == "presseartikel":
        time_froms = [
            s["time_from"] for s in segments
            if s.get("type") == "content" and isinstance(s.get("time_from"), (int, float))
        ]
        if time_froms:
            yr_min = int(min(time_froms))
            yr_max = int(max(time_froms))
        else:
            yr_min, yr_max = None, None
        analysis: dict = {"year_min": yr_min, "year_max": yr_max, "events": [], "language": "de"}
    else:
        load_dotenv(ROOT / ".env")
        try:
            provider = get_provider(task=TASK_ANALYZE)
        except RuntimeError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

        prompt = (
            "Analysiere diese Dokument-Ausschnitte und erkenne:\n"
            "1. Zeitraum des Materials (year_min, year_max als Integer)\n"
            "2. Wichtige historische Perioden mit Jahreszahlen – mindestens 3, maximal 8.\n"
            "   Jedes Ereignis MUSS dieses Format haben: {\"name\": \"...\", \"year_from\": 1234, \"year_to\": 1234}\n"
            "   year_from und year_to sind Integer-Jahreszahlen. Kein Fließtext, keine Sätze als name.\n"
            "   Gib konkrete Perioden aus dem Material zurück, keine leere Liste.\n"
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
    project    = request.query_params.get("project")
    doc_id     = request.query_params.get("document")
    method     = request.query_params.get("method", "llm")
    n_clusters = request.query_params.get("n_clusters")   # None wenn nicht gesetzt
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if method not in ("llm", "kmeans", "bge"):
        return JSONResponse({"error": "method muss 'llm', 'kmeans' oder 'bge' sein"}, status_code=400)
    if err := await _require_token(request, project): return err
    async def gen():
        args = ["--project", project, "--document", doc_id, "--method", method]
        if method == "kmeans" and n_clusters:
            args += ["--n-clusters", n_clusters]
        elif method == "bge" and n_clusters:
            args += ["--n-clusters", n_clusters]
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
    if not validate_doc_id(doc_id):
        return JSONResponse({"ok": False, "error": "invalid document id"}, status_code=400)

    # Token-Check: wenn das Projekt bereits in der DB existiert, muss ein gültiger
    # Token mitgeschickt werden. Beim ersten Aufruf (Neuanlage) gibt es noch keinen
    # Token — dort ist kein Check möglich.
    existing = await get_project(project)
    if existing is not None:
        if err := await _require_token(request, project): return err

    # ── Projektebene: title, year_min/max, taxonomy, entities ──────────────────
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    proj_cfg_path = project_dir / "config.json"
    async with _project_lock(project):
        proj_cfg = read_json_safe(proj_cfg_path)
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
    doc_cfg = read_json_safe(doc_cfg_path)
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

    await upsert_document(
        doc_id            = doc_id,
        project_id        = project,
        ingested_at       = doc_cfg.get("ingested_at", ""),
        doc_type          = doc_cfg.get("doc_type", ""),
        ingest_source     = doc_cfg.get("obsidian_source") or doc_cfg.get("ingest_source") or "docx",
        original_filename = doc_cfg.get("original_filename"),
    )

    return {"ok": True, "token": db_proj["token"]}


@app.post("/ingest/run")
async def ingest_run(request: Request):
    body         = await request.json()
    filename     = body.get("filename", "")
    project      = body.get("project") or request.query_params.get("project")
    doc_id       = body.get("document") or request.query_params.get("document")
    no_summaries = body.get("no_summaries", True)
    if not project or not doc_id:
        return JSONResponse({"error": "project und document erforderlich"}, status_code=400)
    if not validate_doc_id(doc_id):
        return JSONResponse({"error": "invalid document id"}, status_code=400)
    if err := await _require_token(request, project): return err
    input_file = RAW_DIR / filename if filename else None

    parse_args = ["--project", project, "--document", doc_id] + ([str(input_file)] if input_file else [])
    d_args     = ["--project", project, "--document", doc_id]
    p_args     = ["--project", project] + (["--no-summaries"] if no_summaries else [])

    doc_dir       = get_doc_dir(project, doc_id)
    has_segments  = (doc_dir / "segments.json").exists()
    has_anchors   = (doc_dir / "anchors_interpolated.json").exists()

    steps = []
    if not has_segments:
        steps.append((PARSE_SCRIPT, parse_args))
    if not has_anchors:
        steps += [
            (DETECT_SCRIPT,      d_args),
            (INTERPOLATE_SCRIPT, d_args),
        ]
    steps += [
        (CLASSIFY_SCRIPT,        d_args),
        (MATCH_ENTITIES_SCRIPT,  d_args),
    ]
    if not has_anchors:
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
        exploration_ok = True
        async for chunk in run_script_sse(EXPORT_EXPLORATION_SCRIPT, p_args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                exploration_ok = False
                break
        if exploration_ok:
            yield f"data: __link__:/viz/?project={project}\n\n"
        else:
            yield "data: ⚠ Explorer-Export fehlgeschlagen — Viz-Link nicht verfügbar\n\n"
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

    method        = body.get("method", "llm")
    input_file    = RAW_DIR / filename if filename else None
    parse_args    = ["--project", project, "--document", doc_id] + ([str(input_file)] if input_file else [])
    d_args        = ["--project", project, "--document", doc_id]
    p_args        = ["--project", project]
    classify_args = d_args + (["--force"] if force else []) + (["--method", method] if method != "llm" else [])

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
    if not validate_doc_id(doc_id):
        return JSONResponse({"error": "invalid document id"}, status_code=400)
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
    config_p = get_project_dir(project) / "config.json"
    if config_p.exists():
        try:
            cfg_entities = json.loads(config_p.read_text(encoding="utf-8")).get("entities") or []
        except (json.JSONDecodeError, OSError):
            cfg_entities = []
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
    # Einzige Quelle: config.json["entities"] (D-P4)
    project_dir = get_project_dir(project)
    project_dir.mkdir(parents=True, exist_ok=True)
    config_p = project_dir / "config.json"
    async with _project_lock(project):
        cfg = read_json_safe(config_p)
        cfg["entities"] = clean
        config_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "count": len(clean)}




@app.get("/ingest/entities/near-duplicates")
async def get_near_duplicates(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if err := await _require_token(request, project): return err
    config_p = get_project_dir(project) / "config.json"
    entities = read_json_safe(config_p).get("entities") or []
    if len(entities) < 2:
        return JSONResponse([])
    try:
        from src.generalized.embeddings import EMB_TASK_CLUSTER, get_embedding_provider
        import numpy as np
        texts = [e.get("normalform", "") for e in entities]
        embs  = get_embedding_provider(EMB_TASK_CLUSTER).encode(texts)
        sim   = embs @ embs.T
        LOW, HIGH = 0.80, 0.91
        all_pairs = []
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                s = float(sim[i, j])
                if LOW <= s <= HIGH:
                    all_pairs.append({
                        "i": i, "j": j, "sim": round(s, 3),
                        "norm_i": entities[i].get("normalform", ""),
                        "typ_i":  entities[i].get("typ", ""),
                        "norm_j": entities[j].get("normalform", ""),
                        "typ_j":  entities[j].get("typ", ""),
                    })
        # Greedy: jede Entity erscheint in maximal einem Paar (höchste Similarity gewinnt)
        used: set[int] = set()
        pairs = []
        for p in sorted(all_pairs, key=lambda x: -x["sim"]):
            if p["i"] not in used and p["j"] not in used:
                pairs.append(p)
                used.add(p["i"])
                used.add(p["j"])
        return JSONResponse(pairs)
    except ImportError:
        return JSONResponse({"error": "sentence-transformers nicht installiert"}, status_code=503)


@app.post("/ingest/entities/reject")
async def reject_entity(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Body muss ein Objekt sein"}, status_code=400)
    project = body.get("project") or request.query_params.get("project")
    doc_id  = body.get("document") or request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"ok": False, "error": "project und document Parameter erforderlich"}, status_code=400)
    if not validate_doc_id(doc_id):
        return JSONResponse({"ok": False, "error": "invalid document id"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir       = get_doc_dir(project, doc_id)
    rejected_path = doc_dir / "entities_rejected.json"
    rejected      = json.loads(rejected_path.read_text(encoding="utf-8")) if rejected_path.exists() else []
    norm_lc       = (body.get("normalform") or "").lower()
    if norm_lc and not any((e.get("normalform") or "").lower() == norm_lc for e in rejected):
        rejected.append({"normalform": body["normalform"], "aliases": body.get("aliases") or []})
        rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/ingest/doc_status")
async def get_doc_status(request: Request):
    project = request.query_params.get("project")
    doc_id  = request.query_params.get("document")
    if not project or not doc_id:
        return JSONResponse({"error": "project und document Parameter erforderlich"}, status_code=400)
    if not validate_doc_id(doc_id):
        return JSONResponse({"error": "invalid document id"}, status_code=400)
    if err := await _require_token(request, project): return err
    doc_dir        = get_doc_dir(project, doc_id)
    anchors_p      = doc_dir / "anchors_interpolated.json"
    year_min, year_max = None, None
    if anchors_p.exists():
        anchors_segs = read_json_safe(anchors_p, default=[])
        if isinstance(anchors_segs, list):
            years = [
                int(s["time_from"]) for s in anchors_segs
                if s.get("type") == "content" and isinstance(s.get("time_from"), (int, float))
            ]
            if years:
                year_min, year_max = min(years), max(years)
    return JSONResponse({
        "segments":   (doc_dir / "segments.json").exists(),
        "anchors":    anchors_p.exists(),
        "classified": (doc_dir / "classified.json").exists(),
        "preview":    (doc_dir / "preview.html").exists(),
        "year_min":   year_min,
        "year_max":   year_max,
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


async def _get_latest_doc_id(project_id: str) -> str | None:
    return await get_latest_doc_id(project_id)


@app.post("/api/projects")
async def create_project_endpoint(request: Request):
    if err := _require_admin_or_invite(request): return err
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return JSONResponse({"ok": False, "error": "title erforderlich"}, status_code=400)
    doc_type   = body.get("doc_type", "buchnotizen")
    project_id = _slugify(title)
    proj_dir   = PROJECTS_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = proj_dir / "config.json"
    async with _project_lock(project_id):
        if not cfg_path.exists():
            cfg_path.write_text(json.dumps({"title": title, "doc_type": doc_type},
                                           ensure_ascii=False, indent=2), encoding="utf-8")
    invite_tok = _get_invite(request)
    db_proj = await get_project(project_id)
    if db_proj is None:
        db_proj = await create_project(
            project_id, title=title, doc_type=doc_type,
            owner_token=invite_tok or None,
        )
        db_proj = await get_project(project_id)
    return JSONResponse({"ok": True, "id": project_id, "token": db_proj["token"]})


@app.get("/api/projects")
async def list_projects_endpoint(request: Request):
    invite_tok = _get_invite(request)
    db_rows = await db_list_projects(invite_token=invite_tok or None)
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
            "doc_id":      await _get_latest_doc_id(row["id"]),
        })
    return JSONResponse(result)


@app.get("/api/projects/{project_id}")
async def get_project_endpoint(project_id: str):
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Nicht gefunden"}, status_code=404)
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    cfg = read_json_safe(cfg_path)
    oc = cfg.get("obsidian") or {}
    obsidian_info = None
    if oc.get("dropbox_folder"):
        obsidian_info = {
            "dropbox_folder": oc.get("dropbox_folder", ""),
            "doc_type":       oc.get("doc_type", "presseartikel"),
            "connected":      _dropbox_connected(),
        }
    return JSONResponse({
        "ok":       True,
        "id":       proj["id"],
        "title":    proj["title"],
        "doc_type": proj["doc_type"],
        "doc_id":   cfg.get("doc_id"),
        "year_min": cfg.get("year_min"),
        "year_max": cfg.get("year_max"),
        "events":   cfg.get("events") or [],
        "taxonomy": cfg.get("taxonomy") or [],
        "obsidian": obsidian_info,
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
    async with _project_lock(project_id):
        if cfg_path.exists():
            cfg = read_json_safe(cfg_path)
            cfg["title"] = title
            try:
                cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as e:
                print(f"Warnung: config.json für {project_id} konnte nicht aktualisiert werden: {e}",
                      file=sys.stderr)
    return JSONResponse({"ok": True, "id": project_id, "title": title})


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str, request: Request):
    if project_id == "ber":
        return JSONResponse({"ok": False, "error": "Das BER-Demoprojekt kann nicht gelöscht werden"}, status_code=403)
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
    if err := _require_admin_or_invite(request): return err
    proj = await get_project(project_id)
    if not proj:
        return JSONResponse({"ok": False, "error": "Projekt nicht gefunden"}, status_code=404)
    owner = proj.get("owner_token")
    is_public = proj.get("is_public", 0)
    if owner and not is_public and not _is_admin(request) and owner != _get_invite(request):
        return JSONResponse({"ok": False, "error": "Kein Zugriff auf dieses Projekt"}, status_code=403)
    doc_id = await _get_latest_doc_id(project_id)
    return JSONResponse({"ok": True, "id": proj["id"], "token": proj["token"],
                         "created_at": proj["created_at"], "doc_id": doc_id})


# ── Obsidian / Dropbox OAuth2 + Ingest ───────────────────────────────────────

# In-memory-Store: csrf_token → {project_id, session}
_obsidian_oauth_states: dict[str, dict] = {}
_CSRF_SESSION_KEY = "dropbox_csrf"


def _dropbox_env_ok() -> bool:
    import src.generalized.ingest_obsidian as _obs
    return bool(_obs.DROPBOX_APP_KEY and _obs.DROPBOX_APP_SECRET)


def _dropbox_connected() -> bool:
    if not DROPBOX_TOKENS_PATH.exists():
        return False
    try:
        return bool(json.loads(DROPBOX_TOKENS_PATH.read_text(encoding="utf-8")).get("refresh_token"))
    except (json.JSONDecodeError, OSError):
        return False


@app.get("/api/obsidian/dropbox/status")
async def obsidian_dropbox_status():
    return JSONResponse({"connected": _dropbox_connected()})


@app.get("/api/obsidian/oauth/start")
async def obsidian_oauth_start(request: Request, project_id: str = ""):
    if not _dropbox_env_ok():
        return JSONResponse({"ok": False, "error": "DROPBOX_APP_KEY / DROPBOX_APP_SECRET fehlen in .env"}, status_code=500)
    import src.generalized.ingest_obsidian as _obs
    from dropbox.oauth import DropboxOAuth2Flow
    session: dict = {}
    flow = DropboxOAuth2Flow(
        consumer_key=_obs.DROPBOX_APP_KEY,
        consumer_secret=_obs.DROPBOX_APP_SECRET,
        redirect_uri=_obs.DROPBOX_REDIRECT_URL,
        session=session,
        csrf_token_session_key=_CSRF_SESSION_KEY,
        token_access_type="offline",
    )
    auth_url = flow.start()
    csrf = session[_CSRF_SESSION_KEY]
    _obsidian_oauth_states[csrf] = {"session": session, "project_id": project_id}
    return JSONResponse({"ok": True, "auth_url": auth_url})


@app.get("/api/obsidian/oauth/callback")
async def obsidian_oauth_callback(code: str = "", state: str = ""):
    if not state or state not in _obsidian_oauth_states:
        return JSONResponse({"ok": False, "error": "Ungültiger OAuth-State"}, status_code=400)
    entry = _obsidian_oauth_states.pop(state)
    import src.generalized.ingest_obsidian as _obs
    from dropbox.oauth import DropboxOAuth2Flow
    flow = DropboxOAuth2Flow(
        consumer_key=_obs.DROPBOX_APP_KEY,
        consumer_secret=_obs.DROPBOX_APP_SECRET,
        redirect_uri=_obs.DROPBOX_REDIRECT_URL,
        session=entry["session"],
        csrf_token_session_key=_CSRF_SESSION_KEY,
        token_access_type="offline",
    )
    project_id = entry.get("project_id", "")
    try:
        result = flow.finish({"code": code, "state": state})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    tokens = {"access_token": result.access_token, "refresh_token": result.refresh_token}
    if project_id:
        cfg_path = PROJECTS_DIR / project_id / "config.json"
        async with _project_lock(project_id):
            cfg = read_json_safe(cfg_path)
            cfg.setdefault("obsidian", {})["tokens"] = tokens
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        _obsidian_oauth_states["pending"] = tokens
    return HTMLResponse(
        "<html><head><title>Dropbox verbunden</title></head>"
        "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
        "<h2>&#10003; Dropbox verbunden</h2>"
        "<p>Dieses Fenster schlie&szlig;t sich automatisch&hellip;</p>"
        "<script>window.close();</script></body></html>"
    )


@app.get("/api/obsidian/oauth/pending")
async def obsidian_oauth_pending():
    pending = _obsidian_oauth_states.get("pending")
    return JSONResponse({"connected": bool(pending), "has_pending": bool(pending)})


@app.post("/api/projects/{project_id}/obsidian/config")
async def save_obsidian_config(project_id: str, request: Request):
    if err := await _require_token(request, project_id): return err
    body = await request.json()
    folder = body.get("dropbox_folder", "").strip()
    if folder and not folder.startswith("/"):
        folder = "/" + folder
    if not folder:
        return JSONResponse({"ok": False, "error": "Ordner-Pfad darf nicht leer sein"}, status_code=400)
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    async with _project_lock(project_id):
        cfg = read_json_safe(cfg_path)
        oc = cfg.get("obsidian") or {}
        oc["dropbox_folder"] = folder
        oc["doc_type"]       = body.get("doc_type", "presseartikel")
        pending = _obsidian_oauth_states.pop("pending", None)
        if pending and not oc.get("tokens", {}).get("refresh_token"):
            oc["tokens"] = pending
        cfg["obsidian"] = oc
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return JSONResponse({"ok": True})


@app.get("/api/projects/{project_id}/obsidian/test")
async def test_obsidian_config(project_id: str, request: Request):
    if err := await _require_token(request, project_id): return err
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    if not cfg_path.exists():
        return JSONResponse({"ok": False, "error": "config.json nicht gefunden"}, status_code=404)
    cfg = read_json_safe(cfg_path)
    oc  = cfg.get("obsidian") or {}
    folder = oc.get("dropbox_folder", "")
    if folder and not folder.startswith("/"):
        folder = "/" + folder
    tokens = oc.get("tokens") or {}
    if not tokens.get("refresh_token"):
        return JSONResponse({"ok": False, "error": "Dropbox nicht verbunden — OAuth erforderlich"}, status_code=400)
    if not folder:
        return JSONResponse({"ok": False, "error": "dropbox_folder nicht konfiguriert"}, status_code=400)
    import asyncio
    def _check():
        try:
            import src.generalized.ingest_obsidian as _obs
            dbx = _obs._get_client(tokens)
            entries = _obs._list_md_files(dbx, folder)
            return {"ok": True, "count": len(entries)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(loop.run_in_executor(None, _check), timeout=10.0)
    except asyncio.TimeoutError:
        return JSONResponse({"ok": False, "error": "Dropbox-Timeout"}, status_code=504)
    return JSONResponse(result)


@app.get("/api/projects/{project_id}/obsidian/debug")
async def obsidian_debug(project_id: str, request: Request):
    """Temporärer Diagnose-Endpoint: Dropbox-Listing + Checkpoint-Stand."""
    if err := await _require_token(request, project_id): return err
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    if not cfg_path.exists():
        return JSONResponse({"error": "config.json nicht gefunden"}, status_code=404)
    cfg = read_json_safe(cfg_path)
    obs = cfg.get("obsidian") or {}
    tokens = obs.get("tokens") or {}
    folder = obs.get("dropbox_folder") or ""
    if not folder:
        return JSONResponse({"error": "dropbox_folder nicht konfiguriert"}, status_code=400)
    if not folder.startswith("/"):
        folder = "/" + folder
    if not tokens.get("refresh_token"):
        return JSONResponse({"error": "Kein refresh_token — OAuth fehlt"}, status_code=400)

    try:
        import dropbox, dropbox.files as dbx_files
        dbx = dropbox.Dropbox(
            oauth2_refresh_token=tokens["refresh_token"],
            app_key=os.environ.get("DROPBOX_APP_KEY", ""),
            app_secret=os.environ.get("DROPBOX_APP_SECRET", ""),
        )
        acc = dbx.users_get_current_account()
        result = dbx.files_list_folder(folder, recursive=True)
        entries = list(result.entries)
        while result.has_more:
            result = dbx.files_list_folder_continue(result.cursor)
            entries.extend(result.entries)
        md_files = [e.path_display for e in entries
                    if isinstance(e, dbx_files.FileMetadata) and e.name.endswith(".md")]
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    cp_path = PROJECTS_DIR / project_id / "obsidian_checkpoint.json"
    checkpoint = read_json_safe(cp_path) or {"done": []}

    return JSONResponse({
        "account":    acc.name.display_name,
        "folder":     folder,
        "md_count":   len(md_files),
        "md_files":   md_files,
        "checkpoint": checkpoint,
    })


@app.post("/api/projects/{project_id}/obsidian/sync")
async def obsidian_sync(project_id: str, request: Request):
    if err := await _require_token(request, project_id): return err
    cfg_path = PROJECTS_DIR / project_id / "config.json"
    if not cfg_path.exists():
        return JSONResponse({"ok": False, "error": "config.json nicht gefunden"}, status_code=404)
    cfg = read_json_safe(cfg_path)
    oc  = cfg.get("obsidian") or {}
    if not (oc.get("tokens") or {}).get("refresh_token"):
        return JSONResponse({"ok": False, "error": "Dropbox nicht verbunden — OAuth erforderlich"}, status_code=400)
    args = ["--project", project_id, "--source", "dropbox",
            "--doc-type", oc.get("doc_type", "presseartikel")]
    async def gen():
        async for chunk in run_script_sse(INGEST_OBSIDIAN_SCRIPT, args):
            if chunk == "data: __ok__\n\n":
                break
            yield chunk
            if "__error__" in chunk:
                break
        yield "data: __done__\n\n"
    return sse_response(gen())


# ── Chat ──────────────────────────────────────────────────────────────────────

_CHAT_SYSTEM = """\
Du beantwortest Fragen auf Basis von Auszügen aus historischem Quellmaterial.

Antworte auf Deutsch. Gliedere deine Antwort nach relevanten thematischen Kategorien \
die sich aus den Auszügen ergeben. Nenne konkrete Daten, Personen und Beschlüsse. \
Halte dich strikt an die Auszüge, erfinde keine Fakten. \
Falls die Auszüge nicht genug Information enthalten, sage das kurz.

Zitierregeln (strikt einzuhalten):
- Jeder Auszug beginnt mit einer ID in eckigen Klammern, z.B. [PREFIX-s0012]. Nutze exakt diese ID als Quellenangabe — kopiere sie Zeichen für Zeichen, kürze den Prefix nicht ab.
- Schreibe niemals "doc_anchor" oder Platzhalter — nur echte IDs aus den Auszügen.
- Kein "source:", keine doppelten Klammern [[...]], kein Zusatztext in den Klammern.
- Setze die Quellenangabe DIREKT nach der Aussage, die du damit belegst — niemals alle Quellen am Ende sammeln.
- Mehrere Quellen für eine Aussage: direkt hintereinander ohne Komma, z.B. [ID1][ID2].

Antworte mit Fließtext und kurzen Überschriften (##), keine JSON-Ausgabe.\
"""

_CHAT_USER = """\
Frage: {question}

Auszüge ({count} gesamt):
{paragraphs}\
"""

_CHAT_STOPWORDS = {
    "aber", "alle", "allem", "allen", "aller", "alles", "also", "als", "am",
    "an", "auch", "auf", "aus", "bei", "beim", "bin", "bis", "bitte", "da",
    "damit", "dann", "dass", "dem", "den", "denn", "der", "des", "die", "dies",
    "dieser", "dieses", "doch", "dort", "durch", "ein", "eine", "einem", "einen",
    "einer", "eines", "er", "es", "etwa", "gibt", "haben", "hatte", "hier",
    "ihm", "ihn", "ihnen", "ihr", "ihre", "im", "immer", "ist", "kann", "kein",
    "keine", "mal", "man", "mehr", "mich", "mir", "mit", "nach", "nicht", "noch",
    "nun", "nur", "oder", "ohne", "sehr", "sein", "sich", "sie", "sind", "soll",
    "sowie", "über", "um", "und", "unter", "uns", "vom", "von", "vor", "war",
    "waren", "warum", "was", "weil", "wenn", "wer", "werden", "wie", "wird",
    "wir", "wann", "worden", "wurde", "wurden", "zu", "zum", "zur", "zwischen",
}


def _chat_keywords(question: str, max_kw: int = 6) -> list[str]:
    tokens = re.findall(r"[A-Za-zÄÖÜäöüß]+", question)
    return [t.lower() for t in tokens
            if len(t) >= 4 and t.lower() not in _CHAT_STOPWORDS][:max_kw]


def _chat_search(entries: list[dict], keywords: list[str], top_n: int = 20) -> list[dict]:
    if not keywords:
        return []
    hits = []
    for e in entries:
        score = sum(1 for kw in keywords if kw in (e.get("text") or "").lower())
        if score > 0:
            hits.append((score, e))
    hits.sort(key=lambda x: -x[0])
    return [e for _, e in hits[:top_n]]


@app.post("/chat/stream")
async def chat_stream(request: Request):
    body       = await request.json()
    question   = (body.get("question") or "").strip()
    project_id = body.get("project_id") or body.get("project") or ""
    if not question:
        return JSONResponse({"error": "question darf nicht leer sein"}, status_code=400)

    # Daten laden
    if project_id:
        data_path = PROJECTS_DIR / project_id / "exploration" / "data.json"
    else:
        data_path = ROOT / "viz" / "data.json"
    if not data_path.exists():
        return JSONResponse({"error": f"data.json nicht gefunden: {data_path}"}, status_code=404)
    entries = read_json_safe(data_path, default={}).get("entries", [])

    keywords = _chat_keywords(question)
    hits     = _chat_search(entries, keywords)
    sources  = [e["doc_anchor"] for e in hits if e.get("doc_anchor")]

    def no_hits_gen():
        msg = "Zu dieser Frage wurden keine passenden Einträge im Material gefunden."
        yield f"data: {json.dumps(msg)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'sources': [], 'keywords': keywords})}\n\n"

    if not hits:
        return StreamingResponse(no_hits_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    para_block = "\n\n".join(
        f"[{e['doc_anchor']}] {e.get('year', '?')}: {e.get('text', '')}"
        for e in hits
    )
    user_prompt = _CHAT_USER.format(question=question, count=len(hits), paragraphs=para_block)

    def generate():
        try:
            provider = get_provider(task=TASK_CHAT)
            for token in provider.stream_complete(user_prompt, system=_CHAT_SYSTEM):
                yield f"data: {json.dumps(token)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'keywords': keywords})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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

