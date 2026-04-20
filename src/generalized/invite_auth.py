"""
invite_auth.py — Einladungstoken-Verwaltung.

Wenn invites.json nicht existiert (lokaler Dev-Modus): alle Anfragen erlaubt.
Wenn invites.json existiert und Einträge hat: Token-Prüfung aktiv.
"""

import json
import secrets
from pathlib import Path

from src.generalized.config import ROOT

INVITES_PATH = ROOT / "invites.json"


def _load() -> dict:
    if not INVITES_PATH.exists():
        return {}
    try:
        return json.loads(INVITES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def invite_required() -> bool:
    return bool(_load())


def invite_valid(token: str) -> bool:
    return bool(token) and token in _load()


def invite_info(token: str) -> dict | None:
    return _load().get(token)


def gen_invite(name: str, org: str = "") -> str:
    token = secrets.token_hex(8)
    invites = _load()
    invites[token] = {"name": name, "org": org}
    INVITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    INVITES_PATH.write_text(
        json.dumps(invites, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return token
