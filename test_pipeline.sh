#!/usr/bin/env bash
# test_pipeline.sh — Compliance-Test nach D-P1 / D-P2 / D-P3 + Smoke-Test
#
# D-P1  Eine Information, eine Datei   (D-P1 + D-P4 aus DECISIONS.md)
# D-P2  Schritt-Verträge               (D-P2 + D-P3 + D-P5)
# D-P3  Keine verwaisten Endpoints     (D-P6)
#
# Aufruf: bash test_pipeline.sh
# Benötigt: .env mit LLM_PROVIDER (für Smoke-Test classify)

set -uo pipefail

PROJECT="pipeline_test"
DOCID="testdoc"
DOCX="data/raw/Osmanisches Reich Notizen.docx"
PROJECT_DIR="data/projects/${PROJECT}"
DOC_DIR="${PROJECT_DIR}/documents/${DOCID}"
EXPLORATION_DIR="${PROJECT_DIR}/exploration"
SRC="src/generalized"
TEMPLATES="${SRC}/templates"

# ── Tracking (bash 3.x-kompatibel — keine assoziativen Arrays) ────────────────
D1_PASS=0; D1_FAIL=0
D2_PASS=0; D2_FAIL=0
D3_PASS=0; D3_FAIL=0
SM_PASS=0; SM_FAIL=0
TOTAL_FAIL=0

_record() {       # _record <D1|D2|D3|SM> <PASS|FAIL> <label>
    local p="$1" r="$2" l="$3"
    local icon="✓"; [[ "$r" == "FAIL" ]] && icon="✗"
    printf "  %s  %s\n" "$icon" "$l"
    case "$r-$p" in
        PASS-D1) D1_PASS=$((D1_PASS+1)) ;;
        FAIL-D1) D1_FAIL=$((D1_FAIL+1)); TOTAL_FAIL=$((TOTAL_FAIL+1)) ;;
        PASS-D2) D2_PASS=$((D2_PASS+1)) ;;
        FAIL-D2) D2_FAIL=$((D2_FAIL+1)); TOTAL_FAIL=$((TOTAL_FAIL+1)) ;;
        PASS-D3) D3_PASS=$((D3_PASS+1)) ;;
        FAIL-D3) D3_FAIL=$((D3_FAIL+1)); TOTAL_FAIL=$((TOTAL_FAIL+1)) ;;
        PASS-SM) SM_PASS=$((SM_PASS+1)) ;;
        FAIL-SM) SM_FAIL=$((SM_FAIL+1)); TOTAL_FAIL=$((TOTAL_FAIL+1)) ;;
    esac
}
pass() { _record "$1" "PASS" "$2"; }
fail() { _record "$1" "FAIL" "$2"; }

# Befehl soll gelingen
ok() {
    local p="$1" l="$2"; shift 2
    if "$@" >/dev/null 2>&1; then pass "$p" "$l"; else fail "$p" "$l"; fi
}
# Befehl soll scheitern (exit ≠ 0)
nok() {
    local p="$1" l="$2"; shift 2
    if "$@" >/dev/null 2>&1
    then fail "$p" "$l (lief durch — exit≠0 erwartet)"
    else pass "$p" "$l"
    fi
}
# grep soll treffen
found() {
    local p="$1" l="$2"; shift 2
    if grep -q "$@" 2>/dev/null; then pass "$p" "$l"; else fail "$p" "$l"; fi
}
# grep darf NICHT treffen
absent() {
    local p="$1" l="$2"; shift 2
    if grep -q "$@" 2>/dev/null
    then fail "$p" "$l (unerwarteter Treffer)"
    else pass "$p" "$l"
    fi
}
# Python-Snippet soll exit 0 liefern
pyok() {
    local p="$1" l="$2" code="$3"
    if python3 -c "$code" >/dev/null 2>&1; then pass "$p" "$l"; else fail "$p" "$l"; fi
}
# Python-Snippet mit Here-Doc; aufrufer prüft $?
pyrun() { python3 - "$@"; }

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  PIPELINE COMPLIANCE TEST"
echo "════════════════════════════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── D-P1 — Eine Information, eine Datei ──────────────────────────────────"

# taxonomy_proposal.json darf nicht mehr als Schreibziel in *.py erscheinen
absent "D1" "taxonomy_proposal.json nicht als Write-Ziel in *.py" \
    -rE "write_text\(.+taxonomy_proposal|open\(.+taxonomy_proposal.+['\"]w" "${SRC}"

# entities_seed.json darf nicht als Schreibziel in *.py erscheinen
absent "D1" "entities_seed.json nicht als Write-Ziel in *.py" \
    -rE "write_text\(.+entities_seed|open\(.+entities_seed.+['\"]w" "${SRC}"

# propose_taxonomy.py schreibt config.json
found "D1" "propose_taxonomy.py Output-Pfad ist config.json" \
    -n "config.json" "${SRC}/propose_taxonomy.py"

# /taxonomy/data-Block enthält keinen taxonomy_proposal.json-Fallback mehr
if python3 - <<'PYEOF'
import re, sys
txt = open("src/generalized/dev_server.py").read()
m = re.search(r'(@app\.\w+\("/taxonomy/data"\).*?)(?=\n@app\.)', txt, re.S)
block = m.group(1) if m else ""
sys.exit(1 if "taxonomy_proposal" in block else 0)
PYEOF
then pass "D1" "/taxonomy/data-Block: kein taxonomy_proposal-Fallback"
else fail "D1" "/taxonomy/data-Block: taxonomy_proposal-Fallback noch vorhanden"
fi

# /ingest/entities/save schreibt config.json["entities"]
found "D1" "/ingest/entities/save schreibt config.json[\"entities\"]" \
    -A30 'ingest/entities/save' "${SRC}/dev_server.py" | grep -q '"entities"'
# Direktere Variante falls Pipe den Exit-Code versteckt:
if grep -A30 'ingest/entities/save' "${SRC}/dev_server.py" | grep -q '"entities"'
then pass "D1" "/ingest/entities/save schreibt config.json[\"entities\"]"
else fail "D1" "/ingest/entities/save: entities-Key nicht gefunden"
fi

# Wizard-Pfad: /ingest/propose_taxonomy übergibt --project + --document ans Skript
# → Ergebnis landet in data/projects/{project}/config.json, nicht in taxonomy_proposal.json
if python3 - <<'PYEOF'
import re, sys
txt = open("src/generalized/dev_server.py").read()
m = re.search(r'@app\.post\("/ingest/propose_taxonomy"\)(.*?)(?=\n@app\.)', txt, re.S)
block = m.group(0) if m else ""
has_project  = '"--project"' in block or "'--project'" in block
has_document = '"--document"' in block or "'--document'" in block
has_proposal = 'taxonomy_proposal' in block
if not has_project or not has_document:
    print("  ✗ --project / --document fehlen — Skript schreibt nicht in project-config.json")
    sys.exit(1)
if has_proposal:
    print("  ✗ taxonomy_proposal noch referenziert im ingest_propose_taxonomy-Block")
    sys.exit(1)
PYEOF
then pass "D1" "Wizard /ingest/propose_taxonomy: --project+--document → schreibt in project-config.json"
else fail "D1" "Wizard /ingest/propose_taxonomy: falscher Schreibpfad oder taxonomy_proposal-Referenz"
fi

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── D-P2 — Schritt-Verträge ──────────────────────────────────────────────"

# Testprojekt ohne Input-Dateien anlegen
rm -rf "${PROJECT_DIR}"
mkdir -p "${DOC_DIR}"
python3 -c "
import json
cfg = {'title':'Test','year_min':1800,'year_max':1950,'taxonomy':[],'entities':[]}
open('${PROJECT_DIR}/config.json','w').write(json.dumps(cfg))
"

nok "D2" "detect_anchors ohne segments.json → exit 1" \
    python -m src.generalized.detect_anchors --project "${PROJECT}" --document "${DOCID}"

nok "D2" "interpolate_anchors ohne anchors.json → exit 1" \
    python -m src.generalized.interpolate_anchors --project "${PROJECT}" --document "${DOCID}"

nok "D2" "match_entities ohne segments.json → exit 1" \
    python -m src.generalized.match_entities --project "${PROJECT}" --document "${DOCID}"

nok "D2" "export_preview ohne anchors_interpolated.json → exit 1" \
    python -m src.generalized.export_preview --project "${PROJECT}" --document "${DOCID}"

# classify braucht segments.json bevor es zur Taxonomie-Prüfung kommt
echo '[]' > "${DOC_DIR}/segments.json"
nok "D2" "classify_segments ohne Taxonomie in config.json → exit 1" \
    python -m src.generalized.classify_segments --project "${PROJECT}" --document "${DOCID}"

nok "D2" "export_exploration ohne Taxonomie in config.json → exit 1" \
    python -m src.generalized.export_exploration --project "${PROJECT}"

rm "${DOC_DIR}/segments.json"

# normalize_category() in allen drei Export-Skripten
found "D2" "classify_segments.py importiert normalize_category" \
    -q "normalize_category" "${SRC}/classify_segments.py"

found "D2" "export_preview.py importiert normalize_category" \
    -q "normalize_category" "${SRC}/export_preview.py"

found "D2" "export_exploration.py importiert normalize_category" \
    -q "normalize_category" "${SRC}/export_exploration.py"

# dev_server.py: auto-chain match_entities nach classify (D-P3 aus DECISIONS.md)
found "D2" "dev_server.py: auto-chain match_entities nach classify" \
    -q 'step == "classify_segments.py"' "${SRC}/dev_server.py"

# Wizard-Pfad: GET /api/projects/{id} muss taxonomy zurückgeben
# Nach save_config(taxonomy=...) muss das GET die taxonomy im Response enthalten
if python3 - <<'PYEOF'
import re, sys
txt = open("src/generalized/dev_server.py").read()
m = re.search(r'@app\.get\("/api/projects/\{project_id\}"\)(.*?)(?=\n@app\.)', txt, re.S)
block = m.group(0) if m else ""
has_taxonomy = '"taxonomy"' in block or "'taxonomy'" in block
if not has_taxonomy:
    print("  ✗ /api/projects/{id}: taxonomy-Feld fehlt in JSONResponse")
    sys.exit(1)
PYEOF
then pass "D2" "Wizard GET /api/projects/{id}: taxonomy-Feld im Response"
else fail "D2" "Wizard GET /api/projects/{id}: taxonomy-Feld fehlt im Response"
fi

rm -rf "${PROJECT_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── D-P3 — Keine verwaisten Endpoints ────────────────────────────────────"

if python3 - <<'PYEOF'
import re, sys
from pathlib import Path

src = Path("src/generalized/dev_server.py").read_text()
tmpls = [p.read_text(errors="replace")
         for p in Path("src/generalized/templates").rglob("*")
         if p.suffix in (".html", ".js")]
combined = "\n".join(tmpls)

# Endpoints extrahieren
endpoints = sorted(set(re.findall(r'@app\.\w+\("(/[^"]+)"', src)))

# HTML-Navigation-Endpoints: werden per Browser-URL aufgerufen, kein fetch()
NAV_ONLY = {"/editor", "/ingest", "/taxonomy", "/entities"}

def is_referenced(ep):
    if ep in NAV_ONLY:
        return True          # Navigation-only — kein JS fetch() nötig
    if "{" in ep:
        # Parameterisierter Pfad: Präfix bis zum ersten {
        prefix = ep[:ep.index("{")].rstrip("/")
        return bool(prefix) and prefix in combined
    return ep in combined

orphans = [ep for ep in endpoints if not is_referenced(ep)]

print(f"  {len(endpoints)} Endpoints geprüft ({len(NAV_ONLY)} nav-only, {len(orphans)} verwaist)")
for o in orphans:
    print(f"  ✗  verwaist: {o}")

sys.exit(1 if orphans else 0)
PYEOF
then pass "D3" "alle Endpoints in mind. einer Template-Datei oder als nav-only bekannt"
else fail "D3" "verwaiste Endpoints gefunden (Details oben)"
fi

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Smoke-Test: Vollständiger Pipeline-Durchlauf ─────────────────────────"
echo "   (LLM-Aufruf für classify — bitte warten)"

rm -rf "${PROJECT_DIR}"
mkdir -p "${DOC_DIR}"
# config.json von Anfang an anlegen (braucht parse_document nicht, aber folgende Schritte)
python3 -c "
import json
cfg = {'title':'Smoke-Test','year_min':1800,'year_max':1950,'taxonomy':[],'entities':[]}
open('${PROJECT_DIR}/config.json','w').write(json.dumps(cfg, ensure_ascii=False, indent=2))
"

ok "SM" "parse_document → segments.json" \
    python -m src.generalized.parse_document \
        --project "${PROJECT}" --document "${DOCID}" "${DOCX}"

ok "SM" "detect_anchors → anchors.json" \
    python -m src.generalized.detect_anchors \
        --project "${PROJECT}" --document "${DOCID}"

ok "SM" "interpolate_anchors → anchors_interpolated.json" \
    python -m src.generalized.interpolate_anchors \
        --project "${PROJECT}" --document "${DOCID}"

# Taxonomie + Entities in config.json setzen (D-P1: einzige Quelle)
if python3 - <<PYEOF
import json
p = "${PROJECT_DIR}/config.json"
cfg = json.load(open(p, encoding="utf-8"))
cfg["taxonomy"] = [
    {"name":"Politik",      "description":"Politische Ereignisse", "keywords":["Sultan","Vezir","Firman","Reform"]},
    {"name":"Wirtschaft",   "description":"Wirtschaft und Handel",  "keywords":["Handel","Steuer","Zoll","Finanzen"]},
    {"name":"Gesellschaft", "description":"Gesellschaft und Kultur","keywords":["Gesellschaft","Kultur","Bildung","Religion"]},
]
cfg["entities"] = [
    {"normalform":"Osmanisches Reich","typ":"Organisation","aliases":["Osmanisches Reich","Hohe Pforte"]},
    {"normalform":"Sultan","typ":"Person","aliases":["Sultan","Padischah"]},
]
open(p, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
PYEOF
then pass "SM" "Taxonomie (3) + Entities (2) in config.json gesetzt"
else fail "SM" "config.json-Schreiben fehlgeschlagen"
fi

ok "SM" "classify_segments → classified.json" \
    python -m src.generalized.classify_segments \
        --project "${PROJECT}" --document "${DOCID}" --force

ok "SM" "match_entities → actors in classified.json" \
    python -m src.generalized.match_entities \
        --project "${PROJECT}" --document "${DOCID}"

ok "SM" "export_preview → preview.html" \
    python -m src.generalized.export_preview \
        --project "${PROJECT}" --document "${DOCID}"

ok "SM" "export_exploration → data.json" \
    python -m src.generalized.export_exploration \
        --project "${PROJECT}"

# D-P2: normalize_category — alle event_type-Werte sind kanonische Taxonomie-Namen
pyok "SM" "D-P2: data.json event_type alle kanonisch oder (unbekannt)" "
import json
from pathlib import Path
meta  = json.loads(Path('${EXPLORATION_DIR}/project_meta.json').read_text())
data  = json.loads(Path('${EXPLORATION_DIR}/data.json').read_text())
valid = {c['name'] for c in meta.get('taxonomy',[])} | {None,'(unbekannt)'}
bad   = [e for e in data.get('entries',[]) if e.get('event_type') not in valid]
assert not bad, f'{len(bad)} Phantomkategorien: {set(e[\"event_type\"] for e in bad)}'
"

# D-P1: Taxonomie liegt in config.json, taxonomy_proposal.json unberührt
pyok "SM" "D-P1: config.json[taxonomy] nach Pipeline befüllt" "
import json; from pathlib import Path
cfg = json.loads(Path('${PROJECT_DIR}/config.json').read_text())
assert cfg.get('taxonomy'), 'taxonomy leer in config.json'
"

if [[ ! -f "${DOC_DIR}/taxonomy_proposal.json" ]]; then
    pass "SM" "D-P1: taxonomy_proposal.json wurde nicht geschrieben"
else
    fail "SM" "D-P1: taxonomy_proposal.json existiert — darf nicht mehr geschrieben werden"
fi

# D-P2: classified.json hat actors-Felder (match_entities hat gelaufen)
pyok "SM" "D-P2: classified.json enthält actors-Felder nach match_entities" "
import json; from pathlib import Path
data = json.loads(Path('${DOC_DIR}/classified.json').read_text())
assert all('actors' in r for r in data), 'actors-Feld fehlt in manchen Einträgen'
"

rm -rf "${PROJECT_DIR}"

# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ERGEBNIS"
echo "════════════════════════════════════════════════════════════════"
echo ""
printf "  %-10s  %d/%d PASS\n" "D-P1:" "$D1_PASS" "$((D1_PASS+D1_FAIL))"
printf "  %-10s  %d/%d PASS\n" "D-P2:" "$D2_PASS" "$((D2_PASS+D2_FAIL))"
printf "  %-10s  %d/%d PASS\n" "D-P3:" "$D3_PASS" "$((D3_PASS+D3_FAIL))"
printf "  %-10s  %d/%d PASS\n" "Smoke:" "$SM_PASS" "$((SM_PASS+SM_FAIL))"
echo ""

if [[ $TOTAL_FAIL -eq 0 ]]; then
    echo "  ✓  Alle Checks bestanden."
    exit 0
else
    echo "  ✗  ${TOTAL_FAIL} Check(s) fehlgeschlagen."
    exit 1
fi
