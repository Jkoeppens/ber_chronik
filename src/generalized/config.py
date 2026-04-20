import os
from pathlib import Path

ROOT         = Path(__file__).resolve().parent.parent.parent
DATA_ROOT    = Path(os.environ["DATA_ROOT"]) if "DATA_ROOT" in os.environ else ROOT / "data"
PROJECTS_DIR = DATA_ROOT / "projects"
RAW_DIR      = DATA_ROOT / "raw"
DEFAULTS_DIR = ROOT / "data" / "defaults"  # read-only defaults stay in repo
