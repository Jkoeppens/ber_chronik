"""
db.py — SQLite-Persistenz für Projekt-Metadaten via aiosqlite

Tabellen:
  projects   — Projekt-Identität, Auth, Token
  documents  — Dokument-Metadaten (ingested_at, ingest_source, original_filename)

Token-TTL: 30 Tage ab created_at
"""

import secrets
from datetime import datetime, timezone, timedelta
import aiosqlite

from src.generalized.config import DATA_ROOT
DB_PATH = DATA_ROOT / "projects.db"

TOKEN_TTL_DAYS = 30

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    doc_type    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    token       TEXT NOT NULL
);
"""


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_DDL)
        # Idempotente Migrationen
        for stmt in (
            "ALTER TABLE projects ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE projects ADD COLUMN owner_token TEXT",
            """CREATE TABLE IF NOT EXISTS documents (
                doc_id            TEXT PRIMARY KEY,
                project_id        TEXT NOT NULL REFERENCES projects(id),
                ingested_at       TEXT NOT NULL DEFAULT '',
                doc_type          TEXT NOT NULL DEFAULT '',
                ingest_source     TEXT,
                original_filename TEXT
            )""",
        ):
            try:
                await db.execute(stmt)
            except Exception:
                pass
        await db.commit()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fresh_token() -> str:
    return secrets.token_urlsafe(32)


async def create_project(
    project_id: str,
    title: str = "",
    doc_type: str = "",
    status: str = "active",
    owner_token: str | None = None,
) -> dict:
    """Legt ein neues Projekt an und gibt es zurück. Wirft bei Duplikat keinen Fehler."""
    created_at = _now_iso()
    token      = _fresh_token()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT OR IGNORE INTO projects
               (id, title, doc_type, created_at, status, token, owner_token)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (project_id, title, doc_type, created_at, status, token, owner_token),
        )
        await db.commit()
        # Return actual row (may differ if already existed)
        async with db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row)


async def get_project(project_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cur:
            row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def list_projects(invite_token: str | None = None) -> list[dict]:
    """Gibt sichtbare Projekte zurück.

    Ohne invite_token: nur öffentliche (is_public=1).
    Mit invite_token: öffentliche + Projekte, die diesem Token gehören.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        if invite_token:
            async with db.execute(
                "SELECT * FROM projects WHERE is_public=1 OR owner_token=? ORDER BY created_at",
                (invite_token,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM projects WHERE is_public=1 ORDER BY created_at",
            ) as cur:
                rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_project(project_id: str, **fields) -> None:
    """Aktualisiert beliebige Felder (title, doc_type, status)."""
    allowed = {"title", "doc_type", "status"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values     = list(updates.values()) + [project_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
        await db.commit()


async def delete_project(project_id: str) -> None:
    """Löscht das Projekt aus der DB."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await db.commit()


# ── Dokumente ─────────────────────────────────────────────────────────────────

async def upsert_document(
    doc_id: str,
    project_id: str,
    ingested_at: str = "",
    doc_type: str = "",
    ingest_source: str | None = None,
    original_filename: str | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO documents (doc_id, project_id, ingested_at, doc_type, ingest_source, original_filename)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(doc_id) DO UPDATE SET
                 ingested_at=excluded.ingested_at,
                 doc_type=excluded.doc_type,
                 ingest_source=excluded.ingest_source,
                 original_filename=excluded.original_filename""",
            (doc_id, project_id, ingested_at, doc_type, ingest_source, original_filename),
        )
        await db.commit()


async def get_latest_doc_id(project_id: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT doc_id FROM documents WHERE project_id=? ORDER BY ingested_at DESC LIMIT 1",
            (project_id,),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


# ── Token-Prüfung ─────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    return {
        "id":          row[0],
        "title":       row[1],
        "doc_type":    row[2],
        "created_at":  row[3],
        "status":      row[4],
        "token":       row[5],
        "is_public":   row[6] if len(row) > 6 else 0,
        "owner_token": row[7] if len(row) > 7 else None,
    }


def token_valid(project: dict, token: str) -> bool:
    """Prüft ob Token stimmt und noch nicht abgelaufen ist."""
    if project["token"] != token:
        return False
    try:
        created = datetime.fromisoformat(project["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        expiry = created + timedelta(days=TOKEN_TTL_DAYS)
        return datetime.now(timezone.utc) < expiry
    except Exception:
        return False
