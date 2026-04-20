"""
manage.py — Verwaltungs-CLI

Befehle:
  gen-invite <name> [org]  — Einladungstoken generieren und in invites.json speichern
  list-invites             — Alle vorhandenen Tokens anzeigen
  revoke-invite <token>    — Token widerrufen

Aufruf:
  python -m src.generalized.manage gen-invite "Anna Schmidt" "FU Berlin"
"""

import sys

from src.generalized.invite_auth import gen_invite, invite_info, _load, INVITES_PATH
import json


def _save(invites: dict) -> None:
    INVITES_PATH.write_text(
        json.dumps(invites, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cmd_gen_invite(args: list[str]) -> None:
    name  = args[0] if args else "Unbekannt"
    org   = args[1] if len(args) > 1 else ""
    token = gen_invite(name, org)
    print(f"Name:   {name}" + (f" ({org})" if org else ""))
    print(f"Token:  {token}")
    print(f"Link:   https://DEINE-DOMAIN.com/?invite={token}")


def cmd_list_invites() -> None:
    invites = _load()
    if not invites:
        print("Keine Einladungen vorhanden.")
        return
    print(f"{'Token':<20}  {'Name':<25}  Org")
    print("-" * 60)
    for token, info in invites.items():
        print(f"{token:<20}  {info.get('name', '?'):<25}  {info.get('org', '')}")


def cmd_revoke(args: list[str]) -> None:
    if not args:
        print("Fehler: Token angeben.", file=sys.stderr)
        sys.exit(1)
    token   = args[0]
    invites = _load()
    if token not in invites:
        print(f"Token nicht gefunden: {token}", file=sys.stderr)
        sys.exit(1)
    info = invites.pop(token)
    _save(invites)
    print(f"Token widerrufen: {token}  ({info.get('name', '?')})")


COMMANDS = {
    "gen-invite":    cmd_gen_invite,
    "list-invites":  lambda _: cmd_list_invites(),
    "revoke-invite": cmd_revoke,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 1)
    COMMANDS[sys.argv[1]](sys.argv[2:])
