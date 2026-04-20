"""
utils.py — Gemeinsame Hilfsfunktionen für src/generalized.
"""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"


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
