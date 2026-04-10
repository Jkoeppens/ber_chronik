"""
migrate_db.py — Einmaliges Migrationsskript

Trägt alle existierenden Ordner in data/projects/ in die SQLite-DB ein.
Überspringt bereits vorhandene Einträge (INSERT OR IGNORE).

Ausführen:
  .venv/bin/python -m src.generalized.migrate_db
"""

import asyncio
import json
from pathlib import Path

ROOT         = Path(__file__).resolve().parent.parent.parent
PROJECTS_DIR = ROOT / "data" / "projects"


async def main() -> None:
    from src.generalized.db import init_db, create_project, DB_PATH

    await init_db()
    print(f"DB: {DB_PATH}\n")

    if not PROJECTS_DIR.exists():
        print("Kein data/projects/ Verzeichnis gefunden.")
        return

    for d in sorted(PROJECTS_DIR.iterdir()):
        if not d.is_dir():
            continue
        project_id = d.name
        cfg: dict  = {}
        cfg_path   = d / "config.json"
        if cfg_path.exists():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        title    = cfg.get("title") or project_id
        doc_type = cfg.get("doc_type") or ""

        # doc_type aus erstem Dokument falls nicht in config
        if not doc_type:
            docs_dir = d / "documents"
            if docs_dir.exists():
                for doc_d in sorted(docs_dir.iterdir()):
                    doc_cfg = doc_d / "config.json"
                    if doc_cfg.exists():
                        try:
                            doc_type = json.loads(doc_cfg.read_text(encoding="utf-8")).get("doc_type", "")
                        except Exception:
                            pass
                        if doc_type:
                            break

        proj = await create_project(project_id, title=title, doc_type=doc_type)
        print(f"  {project_id:20s}  token={proj['token'][:16]}…  (created_at={proj['created_at']})")

    print("\nMigration abgeschlossen.")


if __name__ == "__main__":
    asyncio.run(main())
