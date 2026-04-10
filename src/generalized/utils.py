"""
utils.py — Gemeinsame Hilfsfunktionen für src/generalized.
"""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_template(name: str, **kwargs: str) -> str:
    """Lädt ein Template aus dem templates/-Verzeichnis und ersetzt {{key}}-Platzhalter."""
    tmpl = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    for key, val in kwargs.items():
        tmpl = tmpl.replace("{{" + key + "}}", str(val))
    return tmpl
