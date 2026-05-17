"""
utils.py — Gemeinsame Hilfsfunktionen für src/generalized.
"""

import json
import os
import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"

_VALID_DOC_ID_RE = re.compile(r"^([0-9a-f]{8}|main)$")


def validate_doc_id(doc_id: str) -> bool:
    """Gibt True zurück wenn doc_id ein gültiger Dokumentpfad-Bezeichner ist.

    Gültig: 8 lowercase hex chars (UUID-Kurzform) oder "main" (Legacy-BER).
    Verhindert Path-Traversal via doc_id wie "../../other_project/documents/main".
    """
    return bool(_VALID_DOC_ID_RE.match(doc_id or ""))


def write_atomic(path: Path, data: str, encoding: str = "utf-8") -> None:
    """Schreibt data atomar nach path via temporäre Datei + os.replace().

    Verhindert truncated/corrupted files bei Prozessabbruch während des Schreibens.
    Die .tmp-Datei liegt im selben Verzeichnis wie path, damit os.replace() ein
    atomarer Rename auf demselben Dateisystem ist.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding=encoding)
    os.replace(tmp, path)


def is_presseartikel(doc_dir: Path) -> bool:
    """Gibt True zurück wenn das Dokument doc_type=presseartikel hat.

    Liest aus doc_dir/config.json via read_json_safe. Zentraler Ort für
    alle drei Skripte (detect_anchors, interpolate_anchors, parse_document)
    die presseartikel-Sonderbehandlung benötigen.
    """
    return read_json_safe(doc_dir / "config.json").get("doc_type") == "presseartikel"


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
