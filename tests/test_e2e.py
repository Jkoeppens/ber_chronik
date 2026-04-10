"""
tests/test_e2e.py — End-to-End Test: kompletter Ingest-Workflow für Damaskus

Voraussetzungen:
  - dev_server läuft auf localhost:8001
  - viz-Server läuft auf localhost:8765
  - data/raw/Damakus Notizen.docx existiert

Ausführen:
  .venv/bin/python tests/test_e2e.py
"""

import csv
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import requests

# ── Konfiguration ──────────────────────────────────────────────────────────────
DEV_API  = "http://localhost:8001"
VIZ_BASE = "http://localhost:8765"
ROOT     = Path(__file__).resolve().parent.parent

RAW_FILE     = ROOT / "data" / "raw" / "Damakus Notizen.docx"
PROJECTS_DIR = ROOT / "data" / "projects"
DB_PATH      = ROOT / "data" / "projects.db"
PROJECT_ID   = "damaskus"

TIMEOUT_SHORT    = 30
TIMEOUT_LLM      = 180          # für non-streaming LLM-Requests
TIMEOUT_STREAM   = (30, None)   # (connect, read) — kein Read-Timeout für SSE-Streams
TIMEOUT_PIPELINE = 2400         # read_sse-Limit für ingest/run (672 Seg × ~3s = ~25 min)

# ── Farben + Reporter ──────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

_passed = 0
_failed = 0


def ok(label: str, detail: str = "") -> None:
    global _passed
    _passed += 1
    print(f"  {GREEN}✓{RESET} {label}" + (f"  {YELLOW}({detail}){RESET}" if detail else ""))


def fail(label: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    print(f"  {RED}✗{RESET} {label}" + (f"  {RED}{detail}{RESET}" if detail else ""))


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


def abort(msg: str) -> None:
    print(f"\n{RED}ABBRUCH: {msg}{RESET}")
    _summary()
    sys.exit(1)


def _summary() -> None:
    total = _passed + _failed
    color = GREEN if _failed == 0 else RED
    print(f"\n{color}{BOLD}{_passed}/{total} Tests bestanden{RESET}")


# ── SSE-Reader ──────────────────────────────────────────────────────────────────

def read_sse(response, label: str, timeout: int = TIMEOUT_LLM) -> tuple[bool, str | None]:
    """
    Liest einen SSE-Stream zeilenweise.
    Gibt (success, link_url) zurück.
    success=False wenn __error__ gefunden.
    """
    link_url = None
    start    = time.time()
    for raw in response.iter_lines():
        if time.time() - start > timeout:
            print(f"    {YELLOW}Timeout nach {timeout}s{RESET}")
            return False, None
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if not line.startswith("data: "):
            continue
        msg = line[6:]
        if msg.startswith("__error__"):
            print(f"    {RED}Fehler: {msg}{RESET}")
            return False, link_url
        if msg.startswith("__link__:"):
            link_url = msg[9:]
            print(f"    → Link: {link_url}")
        elif msg.startswith("__done__") or msg.startswith("__ok__"):
            pass
        elif msg.startswith("▶") or msg.startswith("✓"):
            print(f"    {msg}")
        elif msg.startswith("__report__"):
            pass  # Quality report, ignorieren
        else:
            if msg.strip():
                print(f"    {msg}")
        if msg == "__done__":
            return True, link_url
    return True, link_url


# ── Schritt 0: Teardown ────────────────────────────────────────────────────────

section("0. Teardown")

proj_dir = PROJECTS_DIR / PROJECT_ID
if proj_dir.exists():
    shutil.rmtree(proj_dir)
    ok("data/projects/damaskus/ gelöscht")
else:
    ok("data/projects/damaskus/ war nicht vorhanden")

if DB_PATH.exists():
    con = sqlite3.connect(DB_PATH)
    con.execute("DELETE FROM projects WHERE id = ?", (PROJECT_ID,))
    con.commit()
    con.close()
    ok("DB-Eintrag damaskus gelöscht")
else:
    ok("DB nicht vorhanden (wird bei Server-Start erzeugt)")

if not RAW_FILE.exists():
    abort(f"Rohdatei nicht gefunden: {RAW_FILE}")
ok(f"Rohdatei gefunden: {RAW_FILE.name}")


# ── Schritt 1: Upload ──────────────────────────────────────────────────────────

section("1. Upload")

try:
    with open(RAW_FILE, "rb") as fh:
        r = requests.post(
            f"{DEV_API}/ingest/upload",
            files={"files": (RAW_FILE.name, fh, "application/octet-stream")},
            timeout=TIMEOUT_SHORT,
        )
    if r.status_code == 200 and r.json().get("ok"):
        ok("POST /ingest/upload", f"HTTP {r.status_code}")
    else:
        abort(f"Upload fehlgeschlagen: {r.status_code} {r.text[:200]}")
except requests.exceptions.ConnectionError:
    abort("dev_server nicht erreichbar auf localhost:8001")


# ── Schritt 2: Analyze ────────────────────────────────────────────────────────

section("2. Analyze")

r = requests.post(
    f"{DEV_API}/ingest/analyze",
    json={"filename": RAW_FILE.name, "doc_type": "buchnotizen", "project": PROJECT_ID},
    timeout=TIMEOUT_LLM,
)
if r.status_code != 200 or not r.json().get("ok"):
    abort(f"Analyze fehlgeschlagen: {r.status_code} {r.text[:300]}")

data     = r.json()
doc_id   = data.get("document")
analysis = data.get("analysis", {})
year_min = analysis.get("year_min")
year_max = analysis.get("year_max")

ok(f"POST /ingest/analyze", f"doc_id={doc_id}")
if year_min and year_max:
    ok(f"Zeitraum erkannt", f"{year_min}–{year_max}")
else:
    fail("Kein Zeitraum erkannt", str(analysis))


# ── Schritt 3: Save Config (minimal → Token holen) ────────────────────────────

section("3. Save Config (minimal)")

r = requests.post(
    f"{DEV_API}/ingest/save_config",
    json={
        "project":           PROJECT_ID,
        "document":          doc_id,
        "title":             "Damaskus Notizen",
        "year_min":          year_min or 1800,
        "year_max":          year_max or 2000,
        "doc_type":          "buchnotizen",
        "original_filename": RAW_FILE.name,
        "taxonomy":          [],
        "entities":          [],
    },
    timeout=TIMEOUT_SHORT,
)
if r.status_code != 200 or not r.json().get("ok"):
    abort(f"save_config fehlgeschlagen: {r.status_code} {r.text[:300]}")

token = r.json().get("token")
if token:
    ok("POST /ingest/save_config", f"token={token[:16]}…")
else:
    abort("Kein Token in save_config Response")


# ── Schritt 4: Propose Taxonomy (SSE) ─────────────────────────────────────────

section("4. Propose Taxonomy")

r = requests.post(
    f"{DEV_API}/ingest/propose_taxonomy?token={token}",
    json={},
    stream=True,
    timeout=TIMEOUT_STREAM,
)
success, _ = read_sse(r, "propose_taxonomy")
if success:
    ok("POST /ingest/propose_taxonomy SSE abgeschlossen")
else:
    fail("propose_taxonomy fehlgeschlagen – fahre mit leerer Taxonomie fort")

taxonomy_path = PROJECTS_DIR / PROJECT_ID / "documents" / doc_id / "taxonomy_proposal.json"
if taxonomy_path.exists():
    taxonomy = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    ok(f"taxonomy_proposal.json gelesen", f"{len(taxonomy)} Kategorien")
else:
    taxonomy = []
    fail("taxonomy_proposal.json nicht gefunden")


# ── Schritt 5: Save Config (mit Taxonomie) ────────────────────────────────────

section("5. Save Config (mit Taxonomie)")

r = requests.post(
    f"{DEV_API}/ingest/save_config",
    json={
        "project":  PROJECT_ID,
        "document": doc_id,
        "title":    "Damaskus Notizen",
        "year_min": year_min or 1800,
        "year_max": year_max or 2000,
        "taxonomy": taxonomy,
    },
    timeout=TIMEOUT_SHORT,
)
if r.status_code == 200 and r.json().get("ok"):
    ok("POST /ingest/save_config mit Taxonomie", f"{len(taxonomy)} Kategorien gespeichert")
else:
    fail("save_config mit Taxonomie fehlgeschlagen", r.text[:200])


# ── Schritt 6: Ingest Run (SSE) ───────────────────────────────────────────────

section("6. Ingest Run")

r = requests.post(
    f"{DEV_API}/ingest/run?token={token}",
    json={"filename": RAW_FILE.name, "project": PROJECT_ID, "document": doc_id},
    stream=True,
    timeout=TIMEOUT_STREAM,
)
success, link_url = read_sse(r, "ingest/run", timeout=TIMEOUT_PIPELINE)
if success:
    ok("POST /ingest/run SSE abgeschlossen")
else:
    abort("ingest/run fehlgeschlagen")


# ── Schritt 7: Ergebnis-Validierung ───────────────────────────────────────────

section("7. Ergebnis-Validierung")

exploration_dir = PROJECTS_DIR / PROJECT_ID / "exploration"
data_json_path  = exploration_dir / "data.json"

if not data_json_path.exists():
    abort(f"data.json nicht gefunden: {data_json_path}")
ok("data/projects/damaskus/exploration/data.json existiert")

data_json = json.loads(data_json_path.read_text(encoding="utf-8"))
entries   = data_json.get("entries", [])
count     = len(entries)

if count >= 500:
    ok(f"Mindestens 500 Einträge", f"{count} Einträge")
else:
    fail(f"Zu wenig Einträge", f"{count} (erwartet ≥ 500)")

dated = sum(1 for e in entries if e.get("year") is not None)
dated_pct = dated / count * 100 if count else 0
if dated_pct >= 80:
    ok(f"Mindestens 80% datiert", f"{dated_pct:.1f}%")
else:
    fail(f"Zu wenig datiert", f"{dated_pct:.1f}% (erwartet ≥ 80%)")

with_cat = sum(1 for e in entries if e.get("event_type") not in (None, "", "keine Kategorie"))
cat_pct  = with_cat / count * 100 if count else 0
if cat_pct >= 70:
    ok(f"Mindestens 70% mit Kategorie", f"{cat_pct:.1f}%")
else:
    fail(f"Zu wenig kategorisiert", f"{cat_pct:.1f}% (erwartet ≥ 70%)")

r = requests.get(f"{DEV_API}/api/projects", timeout=TIMEOUT_SHORT)
projects    = r.json()
damaskus_p  = next((p for p in projects if p["id"] == PROJECT_ID), None)
if damaskus_p and damaskus_p.get("entry_count", 0) > 0:
    ok("GET /api/projects zeigt damaskus", f"entry_count={damaskus_p['entry_count']}")
else:
    fail("damaskus nicht in /api/projects oder entry_count=0", str(damaskus_p))


# ── Schritt 8: Datenqualität ──────────────────────────────────────────────────

section("8. Datenqualität")

# Kategorie-Verteilung: keine > 80%
from collections import Counter
cat_dist  = Counter(e.get("event_type") for e in entries if e.get("event_type"))
if cat_dist:
    max_cat, max_n = cat_dist.most_common(1)[0]
    max_pct = max_n / count * 100
    if max_pct <= 80:
        ok(f"Keine Kategorie dominiert > 80%", f"'{max_cat}' = {max_pct:.1f}%")
    else:
        fail(f"Kategorie '{max_cat}' dominiert zu stark", f"{max_pct:.1f}%")

# Confidence: mindestens 50% high
high_conf = sum(1 for e in entries if e.get("confidence") == "high")
high_pct  = high_conf / count * 100 if count else 0
if high_pct >= 50:
    ok(f"Mindestens 50% high confidence", f"{high_pct:.1f}%")
else:
    fail(f"Zu wenig high confidence", f"{high_pct:.1f}% (erwartet ≥ 50%)")

# Entity-Abdeckung: nur prüfen wenn Entities konfiguriert wurden
proj_entities = []
proj_cfg_path = PROJECTS_DIR / PROJECT_ID / "config.json"
if proj_cfg_path.exists():
    proj_entities = json.loads(proj_cfg_path.read_text(encoding="utf-8")).get("entities") or []

if proj_entities:
    with_entity = sum(1 for e in entries if e.get("actors"))
    ent_pct     = with_entity / count * 100 if count else 0
    if ent_pct >= 70:
        ok(f"Mindestens 70% mit Entity", f"{ent_pct:.1f}%")
    else:
        fail(f"Zu wenig Entity-Abdeckung", f"{ent_pct:.1f}% (erwartet ≥ 70%)")
else:
    ok("Entity-Abdeckung übersprungen", "keine Entities konfiguriert")


# ── Schritt 9: Datenformat ────────────────────────────────────────────────────

section("9. Datenformat")

REQUIRED_FIELDS = [
    "id", "doc_anchor", "year", "text", "event_type", "confidence",
    "source_name", "source_date", "is_quote", "is_geicke",
    "actors", "causal_theme", "date_raw", "date_precision",
]
missing_fields: Counter = Counter()
for e in entries:
    for f in REQUIRED_FIELDS:
        if f not in e:
            missing_fields[f] += 1

if not missing_fields:
    ok(f"Alle {len(REQUIRED_FIELDS)} Pflichtfelder vorhanden")
else:
    for f, n in missing_fields.most_common():
        fail(f"Pflichtfeld '{f}' fehlt", f"in {n} Einträgen")

meta_path = exploration_dir / "project_meta.json"
if meta_path.exists():
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    for key in ("color_map", "taxonomy"):
        if meta.get(key):
            ok(f"project_meta.json hat '{key}'")
        else:
            fail(f"project_meta.json fehlt '{key}'")
    # node_color_map nur prüfen wenn Entities vorhanden
    if proj_entities:
        if meta.get("node_color_map"):
            ok("project_meta.json hat 'node_color_map'")
        else:
            fail("project_meta.json fehlt 'node_color_map'")
    else:
        ok("node_color_map übersprungen", "keine Entities konfiguriert")
else:
    fail("project_meta.json nicht gefunden")

csv_path = exploration_dir / "entities_seed.csv"
if proj_entities:
    if csv_path.exists():
        rows = list(csv.reader(csv_path.open(encoding="utf-8")))
        n_data = len(rows) - 1  # ohne Header
        if n_data >= 10:
            ok(f"entities_seed.csv hat ≥ 10 Zeilen", f"{n_data} Zeilen")
        else:
            fail(f"entities_seed.csv zu kurz", f"{n_data} Zeilen (erwartet ≥ 10)")
    else:
        fail("entities_seed.csv nicht gefunden")
else:
    ok("entities_seed.csv übersprungen", "keine Entities konfiguriert")


# ── Schritt 10: Token-Schutz ──────────────────────────────────────────────────

section("10. Token-Schutz")

r = requests.get(f"{DEV_API}/taxonomy/data", timeout=TIMEOUT_SHORT)
if r.status_code == 403:
    ok("Ohne Token → 403")
else:
    fail("Ohne Token sollte 403 sein", f"bekommen: {r.status_code}")

r = requests.get(f"{DEV_API}/taxonomy/data?token=falsches_token_xyz", timeout=TIMEOUT_SHORT)
if r.status_code == 403:
    ok("Falsches Token → 403")
else:
    fail("Falsches Token sollte 403 sein", f"bekommen: {r.status_code}")

r = requests.get(f"{DEV_API}/taxonomy/data?token={token}", timeout=TIMEOUT_SHORT)
if r.status_code == 200:
    ok("Richtiges Token → 200")
else:
    fail("Richtiges Token sollte 200 sein", f"bekommen: {r.status_code}")


# ── Schritt 11: Korrektur-Loop ────────────────────────────────────────────────

section("11. Korrektur-Loop")

test_override = [{"segment_id": "test-s0001", "year": 1900, "note": "e2e-test"}]
r = requests.post(
    f"{DEV_API}/overrides?token={token}",
    json=test_override,
    timeout=TIMEOUT_SHORT,
)
if r.status_code == 200 and r.json().get("ok"):
    ok("POST /overrides mit Token → 200")
else:
    fail("POST /overrides fehlgeschlagen", f"{r.status_code} {r.text[:200]}")

overrides_path = PROJECTS_DIR / PROJECT_ID / "documents" / doc_id / "overrides.json"
if overrides_path.exists():
    written = json.loads(overrides_path.read_text(encoding="utf-8"))
    if written == test_override:
        ok("overrides.json korrekt geschrieben")
    else:
        fail("overrides.json Inhalt stimmt nicht", str(written))
else:
    fail("overrides.json nicht gefunden", str(overrides_path))

r = requests.post(
    f"{DEV_API}/recompute?token={token}",
    json={},
    stream=True,
    timeout=TIMEOUT_STREAM,
)
success, _ = read_sse(r, "recompute")
if success:
    ok("POST /recompute SSE abgeschlossen")
else:
    fail("recompute fehlgeschlagen")


# ── Schritt 12: API-Projekte ──────────────────────────────────────────────────

section("12. API-Projekte")

r = requests.get(f"{DEV_API}/api/projects", timeout=TIMEOUT_SHORT)
projects = r.json()
ids = [p["id"] for p in projects]

if "ber" in ids:
    ber_p = next(p for p in projects if p["id"] == "ber")
    ok(f"ber in /api/projects", f"entry_count={ber_p.get('entry_count', 0)}")
else:
    fail("ber fehlt in /api/projects")

if "damaskus" in ids:
    dam_p = next(p for p in projects if p["id"] == PROJECT_ID)
    if dam_p.get("entry_count", 0) > 0:
        ok(f"damaskus in /api/projects", f"entry_count={dam_p['entry_count']}")
    else:
        fail("damaskus entry_count = 0")
else:
    fail("damaskus fehlt in /api/projects")


# ── Schritt 13: Exploration erreichbar ────────────────────────────────────────

section("13. Exploration erreichbar (localhost:8765)")

try:
    r = requests.get(
        f"{VIZ_BASE}/data/projects/{PROJECT_ID}/exploration/data.json",
        timeout=TIMEOUT_SHORT,
    )
    if r.status_code == 200:
        served = r.json()
        if served.get("count", 0) > 0:
            ok("data.json via viz-Server erreichbar", f"count={served['count']}")
        else:
            fail("data.json geladen aber count=0")
    else:
        fail("data.json nicht erreichbar", f"HTTP {r.status_code}")
except requests.exceptions.ConnectionError:
    fail("viz-Server nicht erreichbar auf localhost:8765")


# ── Zusammenfassung ───────────────────────────────────────────────────────────

_summary()
sys.exit(0 if _failed == 0 else 1)
