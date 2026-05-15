"""
utils.py — Gemeinsame Hilfsfunktionen für src/generalized.
"""

import json
import os
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


def write_atomic(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Schreibt data atomar nach path via temporäre Datei + os.replace().

    Verhindert truncated/corrupted files bei Prozessabbruch während des Schreibens.
    Die .tmp-Datei liegt im selben Verzeichnis wie path, damit os.replace() ein
    atomarer Rename auf demselben Dateisystem ist.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding=encoding)
    os.replace(tmp, path)


def read_json_safe(path: Path, default: "dict | None" = None) -> dict:
    """Liest eine JSON-Datei; gibt default (oder {}) zurück bei Fehler oder fehlendem File."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def render_template(name: str, **kwargs: str) -> str:
    """Lädt ein Template aus dem templates/-Verzeichnis und ersetzt {{key}}-Platzhalter.

    {{APP_CSS}} wird automatisch aus app.css befüllt, außer es wird explizit überschrieben.
    """
    tmpl = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
    if "APP_CSS" not in kwargs:
        app_css_path = TEMPLATES_DIR / "app.css"
        if app_css_path.exists():
            kwargs = {"APP_CSS": app_css_path.read_text(encoding="utf-8"), **kwargs}
    for key, val in kwargs.items():
        tmpl = tmpl.replace("{{" + key + "}}", str(val))
    return tmpl
