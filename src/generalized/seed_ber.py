"""
seed_ber.py — Legt das BER-Demoprojekt beim ersten Start an.

Idempotent: läuft ohne Effekt wenn "ber" bereits in projects.db existiert
und data/projects/ber/ am Zielort vorhanden ist.
"""

import os
import shutil
import sys
from pathlib import Path

from src.generalized.config import DATA_ROOT, ROOT
from src.generalized.db import create_project, get_project, upsert_document

# Quelldaten liegen immer im Repo (auch auf Railway via git)
_SEED_SRC = ROOT / "data" / "projects" / "ber"

_BER_ID    = "ber"
_BER_TITLE = "BER Chronik 1989–2017"
_BER_DOC   = "main"


async def seed_ber() -> None:
    dest = DATA_ROOT / "projects" / _BER_ID

    # ── 1. DB-Eintrag ──────────────────────────────────────────────────────────
    existing = await get_project(_BER_ID)
    if not existing:
        owner = os.environ.get("ADMIN_KEY") or "seed"
        await create_project(
            project_id=_BER_ID,
            title=_BER_TITLE,
            doc_type="presseartikel",
            owner_token=owner,
        )
        # is_public=1 via direktes UPDATE (create_project hat kein is_public-Param)
        import aiosqlite
        from src.generalized.db import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE projects SET is_public=1 WHERE id=?", (_BER_ID,)
            )
            await db.commit()
        await upsert_document(
            doc_id=_BER_DOC,
            project_id=_BER_ID,
            ingested_at="2025-01-01T00:00:00+00:00",
            doc_type="presseartikel",
            ingest_source="seed",
            original_filename="BER_Chronik.docx",
        )
        print(f"[seed_ber] Projekt '{_BER_ID}' angelegt.", file=sys.stderr)
    else:
        print(f"[seed_ber] Projekt '{_BER_ID}' existiert bereits — übersprungen.", file=sys.stderr)

    # ── 2. Dateisystem ─────────────────────────────────────────────────────────
    if not dest.exists():
        if not _SEED_SRC.exists():
            print(
                f"[seed_ber] Warnung: Seed-Quelle {_SEED_SRC} nicht gefunden.",
                file=sys.stderr,
            )
            return
        shutil.copytree(_SEED_SRC, dest)
        print(f"[seed_ber] {_SEED_SRC} → {dest} kopiert.", file=sys.stderr)
    else:
        print(f"[seed_ber] {dest} existiert bereits — nicht kopiert.", file=sys.stderr)
