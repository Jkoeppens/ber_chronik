#!/usr/bin/env bash
# test_wizard_api.sh — Wizard-Pfad via HTTP-Endpoints (curl)
#
# Simuliert genau das was der Browser-Wizard macht, aber via curl.
# Voraussetzung: Server läuft auf localhost:8001
#   uvicorn src.generalized.dev_server:app --port 8001
#
# Aufruf: bash test_wizard_api.sh
# Dauer:  ~8-12 Minuten (LLM: analyze + propose_taxonomy + classify)

set -euo pipefail

BASE="http://localhost:8001"
DOCX="data/raw/Osmanisches Reich Notizen.docx"
PROJECT_NAME="api_test"  # → slugified project ID = "api_test"
PROJECT_ID=""            # gesetzt nach /ingest/analyze
DOC_ID=""                # gesetzt nach /ingest/analyze
TOKEN=""                 # gesetzt nach /ingest/save_config

# ── Pass/Fail tracking ─────────────────────────────────────────────────────────
declare -a RESULTS=()
declare -a LABELS=()

pass()  { RESULTS+=("PASS"); LABELS+=("$1"); echo "  ✓ PASS — $1"; }
fail()  { RESULTS+=("FAIL"); LABELS+=("$1"); echo "  ✗ FAIL — $1"; }

# Prüft ob SSE-Stream erfolgreich: __done__ ohne __error__
sse_ok() {
    local output="$1"
    echo "$output" | grep -q "__done__" && ! echo "$output" | grep -q "__error__"
}

sse_check() {
    local label="$1" output="$2"
    if sse_ok "$output"; then
        pass "$label"
    else
        local err
        err=$(echo "$output" | grep "__error__" | head -1 || true)
        fail "$label${err:+: $err}"
    fi
}

json_check() {
    local label="$1" pycode="$2"
    if python3 -c "$pycode" 2>/dev/null; then
        pass "$label"
    else
        fail "$label"
    fi
}

# ── Server-Check ───────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════"
echo "  WIZARD API TEST — localhost:8001"
echo "════════════════════════════════════════════════════════"
echo ""

echo "── Server-Check ──"
if ! curl -s --max-time 5 "${BASE}/ingest" > /dev/null 2>&1; then
    echo "  ✗ Server nicht erreichbar auf ${BASE}"
    echo "    Starten mit: uvicorn src.generalized.dev_server:app --port 8001"
    exit 1
fi
echo "  Server erreichbar."
echo ""

# ── Altes Testprojekt löschen (idempotent) ─────────────────────────────────────
echo "── Setup: Altes Testprojekt bereinigen ──"
rm -rf "data/projects/${PROJECT_NAME}"
# Auch aus DB löschen (ignoriere Fehler wenn nicht vorhanden)
curl -s -X DELETE "${BASE}/api/projects/${PROJECT_NAME}" \
    -H "Content-Type: application/json" \
    -d '{"confirm": true}' > /dev/null 2>&1 || true
echo "  Bereinigt."
echo ""

# ── 1. POST /ingest/upload ─────────────────────────────────────────────────────
echo "── 1. POST /ingest/upload ──"

UPLOAD_RESP=$(curl -s -X POST "${BASE}/ingest/upload" \
    -F "files=@${DOCX}")

echo "  Response: $UPLOAD_RESP"

if echo "$UPLOAD_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok fehlt oder false: {d}'
files = d.get('files', [])
assert len(files) == 1, f'Erwartet 1 Datei, got {len(files)}'
assert files[0].get('size', 0) > 10000, f'Datei zu klein: {files[0]}'
print(f'  {files[0][\"name\"]}  {files[0][\"size\"]:,} Bytes')
" 2>/dev/null; then
    pass "Upload: Datei hochgeladen"
else
    fail "Upload: Antwort ungültig"
fi
echo ""

# ── 2. POST /ingest/analyze ────────────────────────────────────────────────────
echo "── 2. POST /ingest/analyze (LLM, ~30-60 s) ──"
echo "  Hinweis: LLM analysiert Dokument-Sample …"

ANALYZE_RESP=$(curl -s --max-time 120 -X POST "${BASE}/ingest/analyze" \
    -H "Content-Type: application/json" \
    -d "{\"filename\": \"Osmanisches Reich Notizen.docx\",
         \"project_name\": \"${PROJECT_NAME}\",
         \"doc_type\": \"Forschungsnotizen\"}")

# Extrahiere project und document
PROJECT_ID=$(echo "$ANALYZE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('project',''))" 2>/dev/null || echo "")
DOC_ID=$(echo "$ANALYZE_RESP"     | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('document',''))" 2>/dev/null || echo "")

if [[ -z "$PROJECT_ID" || -z "$DOC_ID" ]]; then
    fail "analyze: kein project/document in Antwort — $ANALYZE_RESP"
    echo "  Abbruch: ohne project+doc_id können folgende Tests nicht laufen."
    exit 1
fi
echo "  project=${PROJECT_ID}  document=${DOC_ID}"

echo "$ANALYZE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok fehlt: {d}'
a = d.get('analysis', {})
assert isinstance(a.get('year_min'), int), f'year_min kein int: {a}'
assert isinstance(a.get('year_max'), int), f'year_max kein int: {a}'
events = a.get('events', [])
assert len(events) >= 1, f'Keine events: {a}'
print(f'  year_min={a[\"year_min\"]}  year_max={a[\"year_max\"]}  events={len(events)}')
e0 = events[0]
assert 'name' in e0 and 'year_from' in e0, f'Event-Felder fehlen: {e0}'
" 2>/dev/null && pass "analyze: LLM-Analyse valide (year_min/max/events)" \
               || fail "analyze: Antwort-Struktur fehlerhaft"

# Hilfswerte für weitere Tests
YEAR_MIN=$(echo "$ANALYZE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('analysis',{}).get('year_min',1800))" 2>/dev/null || echo "1800")
YEAR_MAX=$(echo "$ANALYZE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('analysis',{}).get('year_max',1950))" 2>/dev/null || echo "1950")
# Erstes Event als JSON-escaped String
EVENTS_JSON=$(echo "$ANALYZE_RESP" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin).get('analysis',{}).get('events',[])))" 2>/dev/null || echo "[]")
echo ""

# ── 3. POST /ingest/save_config — Projekt anlegen, Token holen ────────────────
echo "── 3. POST /ingest/save_config (Projekt anlegen + Token) ──"

SAVE_RESP=$(curl -s -X POST "${BASE}/ingest/save_config" \
    -H "Content-Type: application/json" \
    -d "{\"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\",
         \"title\": \"API-Test Osmanisches Reich\",
         \"doc_type\": \"buchnotizen\",
         \"year_min\": ${YEAR_MIN},
         \"year_max\": ${YEAR_MAX}}")

TOKEN=$(echo "$SAVE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null || echo "")

if [[ -z "$TOKEN" ]]; then
    fail "save_config: kein token in Antwort — $SAVE_RESP"
    echo "  Abbruch: ohne Token können geschützte Endpoints nicht getestet werden."
    exit 1
fi
echo "  Token: ${TOKEN:0:16}…"
pass "save_config: Projekt angelegt, Token erhalten"

# Prüfe config.json auf Dateisystem
json_check "save_config: data/projects/${PROJECT_ID}/config.json geschrieben" "
import json
cfg = json.load(open('data/projects/${PROJECT_ID}/config.json'))
assert cfg.get('year_min') == ${YEAR_MIN}, f'year_min falsch: {cfg}'
print(f'  title={cfg.get(\"title\")}  year_min={cfg.get(\"year_min\")}')
"
echo ""

# ── 4. POST /ingest/run/step detect_anchors.py ────────────────────────────────
echo "── 4. POST /ingest/run/step detect_anchors.py ──"

DETECT_OUT=$(curl -s --max-time 60 -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: ${TOKEN}" \
    -d "{\"step\": \"detect_anchors.py\",
         \"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\"}")

sse_check "detect_anchors: SSE abgeschlossen" "$DETECT_OUT"

json_check "detect_anchors: anchors.json erzeugt und nicht leer" "
import json
d = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/anchors.json'))
assert len(d) > 0, 'Leer'
print(f'  {len(d)} Ankersegmente')
"
echo ""

# ── 5. POST /ingest/run/step interpolate_anchors.py ──────────────────────────
echo "── 5. POST /ingest/run/step interpolate_anchors.py ──"

INTERP_OUT=$(curl -s --max-time 60 -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: ${TOKEN}" \
    -d "{\"step\": \"interpolate_anchors.py\",
         \"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\"}")

sse_check "interpolate_anchors: SSE abgeschlossen" "$INTERP_OUT"

json_check "interpolate_anchors: anchors_interpolated.json mit precision-Feldern" "
import json
d = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/anchors_interpolated.json'))
dated = [s for s in d if s.get('precision')]
print(f'  {len(dated)}/{len(d)} datierte Segmente')
assert len(dated) > 0
"
echo ""

# ── 6. POST /ingest/propose_taxonomy (LLM) ────────────────────────────────────
# Hinweis: /taxonomy/propose übergibt keine --project/--document args an das Skript
#          und würde scheitern. Der Wizard nutzt /ingest/propose_taxonomy.
echo "── 6. POST /ingest/propose_taxonomy (LLM, ~2-4 min) ──"
echo "  Hinweis: LLM generiert Taxonomie-Vorschlag …"

PROPOSE_OUT=$(curl -s --max-time 300 -X POST \
    "${BASE}/ingest/propose_taxonomy?project=${PROJECT_ID}&document=${DOC_ID}&token=${TOKEN}")

sse_check "propose_taxonomy: SSE abgeschlossen" "$PROPOSE_OUT"

json_check "propose_taxonomy: taxonomy_proposal.json erzeugt" "
import json
d = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/taxonomy_proposal.json'))
assert isinstance(d, list) and len(d) >= 3, f'Erwartet >=3 Kategorien, got {d}'
print(f'  {len(d)} Kategorien: {[c[\"name\"] for c in d]}')
assert all(\"name\" in c for c in d)
"
echo ""

# ── 7. POST /taxonomy/save ─────────────────────────────────────────────────────
echo "── 7. POST /taxonomy/save ──"

# Taxonomie aus taxonomy_proposal.json holen und speichern
TAX_BODY=$(python3 -c "
import json
proposal = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/taxonomy_proposal.json'))
print(json.dumps(proposal))
" 2>/dev/null || echo "[]")

TAX_SAVE_RESP=$(curl -s -X POST \
    "${BASE}/taxonomy/save?project=${PROJECT_ID}&token=${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$TAX_BODY")

echo "$TAX_SAVE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok=false: {d}'
print(f'  {d[\"count\"]} Kategorien gespeichert')
" 2>/dev/null && pass "taxonomy/save: HTTP-Response ok" \
               || fail "taxonomy/save: Response fehlerhaft — $TAX_SAVE_RESP"

# D-P1: config.json["taxonomy"] muss jetzt befüllt sein
json_check "D-P1: config.json[\"taxonomy\"] nach save befüllt" "
import json
cfg = json.load(open('data/projects/${PROJECT_ID}/config.json'))
tax = cfg.get('taxonomy', [])
assert len(tax) >= 3, f'taxonomy leer oder zu kurz: {tax}'
print(f'  taxonomy: {len(tax)} Kategorien in config.json')
assert all('name' in c for c in tax)
"
echo ""

# ── 8. POST /ingest/entities/save — Test-Entities setzen (für D-P3/D-P4) ──────
echo "── 8. POST /ingest/entities/save (Test-Entities für D-P3/D-P4) ──"

ENTITIES_BODY='[
    {"normalform": "Osmanisches Reich", "typ": "Org",    "aliases": ["Osmanisches Reich", "Hohe Pforte", "Osmanien"]},
    {"normalform": "Sultan",            "typ": "Person", "aliases": ["Sultan", "Padischah"]}
]'

ENT_SAVE_RESP=$(curl -s -X POST \
    "${BASE}/ingest/entities/save?project=${PROJECT_ID}&document=${DOC_ID}&token=${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$ENTITIES_BODY")

echo "$ENT_SAVE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok=false: {d}'
print(f'  {d[\"count\"]} Entities gespeichert')
" 2>/dev/null && pass "entities/save: in config.json gespeichert" \
               || fail "entities/save: Response fehlerhaft — $ENT_SAVE_RESP"

# D-P4: config.json["entities"] muss jetzt die Entities enthalten
json_check "D-P4: config.json[\"entities\"] nach save befüllt" "
import json
cfg = json.load(open('data/projects/${PROJECT_ID}/config.json'))
ents = cfg.get('entities', [])
assert len(ents) == 2, f'Erwartet 2 Entities, got {len(ents)}'
norms = {e['normalform'] for e in ents}
assert 'Sultan' in norms, f'Sultan fehlt: {norms}'
print(f'  entities: {sorted(norms)}')
"
echo ""

# ── 9. POST /ingest/run/step classify_segments.py + D-P3 Check ────────────────
echo "── 9. POST /ingest/run/step classify_segments.py (LLM, ~3-5 min) ──"
echo "  Hinweis: D-P3 — match_entities wird automatisch nach classify nachgeschaltet."
echo "  LLM klassifiziert Segmente …"

CLASSIFY_OUT=$(curl -s --max-time 600 -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: ${TOKEN}" \
    -d "{\"step\": \"classify_segments.py\",
         \"force\": true,
         \"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\"}")

sse_check "classify: SSE abgeschlossen" "$CLASSIFY_OUT"

# D-P3: match_entities läuft nach classify → actors-Feld in classified.json
json_check "D-P3: classified.json enthält actors-Feld (auto-match_entities)" "
import json
rows = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/classified.json'))
assert len(rows) > 0, 'classified.json leer'
all_have_actors = all('actors' in r for r in rows)
with_actors = [r for r in rows if r.get('actors')]
assert all_have_actors, 'actors-Feld fehlt bei manchen Einträgen'
print(f'  {len(with_actors)}/{len(rows)} Segmente mit actors (actors-Feld überall vorhanden)')
"

# D-P3: actors-Werte kommen aus config.json entities (D-P4 Kreuzcheck)
json_check "D-P3+D-P4: actors stammen aus config.json entities" "
import json
rows = json.load(open('data/projects/${PROJECT_ID}/documents/${DOC_ID}/classified.json'))
cfg  = json.load(open('data/projects/${PROJECT_ID}/config.json'))
valid = set()
for e in cfg.get('entities', []):
    valid.add(e.get('normalform',''))
    valid.update(e.get('aliases', []))
all_actors = {a for r in rows for a in r.get('actors', [])}
unknown = all_actors - valid
print(f'  actors im Dokument: {sorted(all_actors) or \"(keine Treffer)\"}')
assert not unknown, f'Unbekannte actors (nicht in config.json): {unknown}'
"
echo ""

# ── 10. POST /ingest/save_config — year_min/max/events updaten ────────────────
echo "── 10. POST /ingest/save_config (year_min/max/events updaten) ──"

UPDATE_RESP=$(curl -s -X POST "${BASE}/ingest/save_config" \
    -H "Content-Type: application/json" \
    -d "{\"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\",
         \"time_config\": {
             \"year_min\": ${YEAR_MIN},
             \"year_max\": ${YEAR_MAX},
             \"events\": ${EVENTS_JSON}
         }}")

echo "$UPDATE_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok=false: {d}'
" 2>/dev/null && pass "save_config: year_min/max/events gespeichert" \
               || fail "save_config: Response fehlerhaft — $UPDATE_RESP"

json_check "save_config: config.json[\"events\"] korrekt" "
import json
cfg = json.load(open('data/projects/${PROJECT_ID}/config.json'))
assert cfg.get('year_min') == ${YEAR_MIN}, f'year_min falsch: {cfg}'
assert cfg.get('year_max') == ${YEAR_MAX}, f'year_max falsch: {cfg}'
events = cfg.get('events', [])
print(f'  year_min={cfg[\"year_min\"]}  year_max={cfg[\"year_max\"]}  events={len(events)}')
"
echo ""

# ── 11. POST /ingest/run/step export_preview.py ───────────────────────────────
echo "── 11. POST /ingest/run/step export_preview.py ──"

PREVIEW_OUT=$(curl -s --max-time 60 -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: ${TOKEN}" \
    -d "{\"step\": \"export_preview.py\",
         \"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\"}")

sse_check "export_preview: SSE abgeschlossen" "$PREVIEW_OUT"

json_check "export_preview: preview.html erzeugt und > 10 KB" "
import os
p = 'data/projects/${PROJECT_ID}/documents/${DOC_ID}/preview.html'
assert os.path.exists(p), 'preview.html fehlt'
size = os.path.getsize(p)
print(f'  preview.html  {size:,} Bytes')
assert size > 10000, f'Zu klein: {size}'
"
echo ""

# ── 12. POST /ingest/run — Vollständiger Pipeline-Run ─────────────────────────
echo "── 12. POST /ingest/run (Vollständiger Pipeline-Run) ──"
echo "  Hinweis: classify resume ohne --force (überspringt bereits klassifizierte Segmente) …"

FULL_RUN_OUT=$(curl -s --max-time 600 -X POST "${BASE}/ingest/run" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: ${TOKEN}" \
    -d "{\"project\": \"${PROJECT_ID}\",
         \"document\": \"${DOC_ID}\",
         \"filename\": \"Osmanisches Reich Notizen.docx\"}")

sse_check "ingest/run: SSE abgeschlossen" "$FULL_RUN_OUT"

json_check "ingest/run: exploration/data.json erzeugt" "
import json
d = json.load(open('data/projects/${PROJECT_ID}/exploration/data.json'))
entries = d.get('entries', [])
count   = d.get('count', 0)
print(f'  data.json: {count} Einträge')
assert count > 0
assert len(entries) == count
"

# D-P2: event_type-Werte in data.json gegen Taxonomie prüfen
json_check "D-P2: event_type-Werte in data.json kanonisch" "
import json
data = json.load(open('data/projects/${PROJECT_ID}/exploration/data.json'))
meta = json.load(open('data/projects/${PROJECT_ID}/exploration/project_meta.json'))
valid = {c['name'] for c in meta.get('taxonomy', [])} | {None, '(unbekannt)'}
entries = data.get('entries', [])
bad = [e for e in entries if e.get('event_type') not in valid]
unknown_pct = sum(1 for e in entries if e.get('event_type') == '(unbekannt)') / len(entries) * 100
print(f'  {len(entries)} Einträge, (unbekannt): {unknown_pct:.1f}%')
if bad:
    print(f'  ✗ Ungültige event_type: {[(e[\"id\"], e[\"event_type\"]) for e in bad[:3]]}')
assert not bad, f'{len(bad)} Einträge mit ungültigem event_type'
assert unknown_pct < 30, f'{unknown_pct:.1f}% (unbekannt) — über 30%'
"
echo ""

# ── 13. GET /preview ───────────────────────────────────────────────────────────
echo "── 13. GET /preview ──"

PREVIEW_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    "${BASE}/preview?project=${PROJECT_ID}&document=${DOC_ID}&token=${TOKEN}")

PREVIEW_SIZE=$(curl -s \
    "${BASE}/preview?project=${PROJECT_ID}&document=${DOC_ID}&token=${TOKEN}" \
    | wc -c)

if [[ "$PREVIEW_STATUS" == "200" ]]; then
    pass "GET /preview: HTTP 200"
else
    fail "GET /preview: HTTP ${PREVIEW_STATUS}"
fi

if [[ "$PREVIEW_SIZE" -gt 10000 ]]; then
    pass "GET /preview: Inhalt > 10 KB (${PREVIEW_SIZE} Bytes)"
else
    fail "GET /preview: Inhalt zu klein (${PREVIEW_SIZE} Bytes)"
fi
echo ""

# ── 14. GET /ingest/entities/data — D-P4: entities aus config.json ─────────────
echo "── 14. GET /ingest/entities/data (D-P4) ──"

ENT_DATA_RESP=$(curl -s \
    "${BASE}/ingest/entities/data?project=${PROJECT_ID}&document=${DOC_ID}&token=${TOKEN}")

echo "$ENT_DATA_RESP" | python3 -c "
import json, sys
ents = json.load(sys.stdin)
assert isinstance(ents, list) and len(ents) == 2, f'Erwartet 2 Entities, got {ents}'
norms = {e['normalform'] for e in ents}
print(f'  {sorted(norms)}')
assert 'Sultan' in norms
assert 'Osmanisches Reich' in norms
# D-P4: _status sollte confirmed sein (aus config.json)
statuses = {e.get('_status') for e in ents}
print(f'  _status: {statuses}')
assert statuses == {'confirmed'}, f'Erwartet confirmed, got {statuses}'
" 2>/dev/null && pass "D-P4: /ingest/entities/data liefert entities aus config.json (confirmed)" \
               || fail "D-P4: Entities-Antwort fehlerhaft — ${ENT_DATA_RESP:0:200}"
echo ""

# ── 15. GET /api/projects/{id} — config-Felder prüfen ─────────────────────────
echo "── 15. GET /api/projects/${PROJECT_ID} ──"

PROJ_RESP=$(curl -s "${BASE}/api/projects/${PROJECT_ID}")

echo "$PROJ_RESP" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('ok'), f'ok=false: {d}'
assert d.get('year_min') == ${YEAR_MIN}, f'year_min falsch: {d}'
assert d.get('year_max') == ${YEAR_MAX}, f'year_max falsch: {d}'
print(f'  id={d[\"id\"]}  title={d[\"title\"]}')
print(f'  year_min={d[\"year_min\"]}  year_max={d[\"year_max\"]}  events={len(d.get(\"events\",[]))}')
" 2>/dev/null && pass "/api/projects/{id}: year_min/max/events korrekt" \
               || fail "/api/projects/{id}: Response fehlerhaft — ${PROJ_RESP:0:200}"
echo ""

# ── 16. Token-Schutz prüfen ────────────────────────────────────────────────────
echo "── 16. Token-Schutz (403 ohne Token) ──"

STATUS_NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -d "{\"step\": \"detect_anchors.py\", \"project\": \"${PROJECT_ID}\", \"document\": \"${DOC_ID}\"}")

if [[ "$STATUS_NO_TOKEN" == "403" ]]; then
    pass "Token-Schutz: /ingest/run/step ohne Token → 403"
else
    fail "Token-Schutz: Erwartet 403, got ${STATUS_NO_TOKEN}"
fi

STATUS_BAD_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "${BASE}/ingest/run/step" \
    -H "Content-Type: application/json" \
    -H "X-Project-Token: falsch-token-xyz" \
    -d "{\"step\": \"detect_anchors.py\", \"project\": \"${PROJECT_ID}\", \"document\": \"${DOC_ID}\"}")

if [[ "$STATUS_BAD_TOKEN" == "403" ]]; then
    pass "Token-Schutz: /ingest/run/step mit falschem Token → 403"
else
    fail "Token-Schutz: Erwartet 403, got ${STATUS_BAD_TOKEN}"
fi
echo ""

# ── Cleanup ────────────────────────────────────────────────────────────────────
echo "── Cleanup ──"
curl -s -X DELETE "${BASE}/api/projects/${PROJECT_ID}" \
    -H "Content-Type: application/json" \
    -d '{"confirm": true}' > /dev/null 2>&1 && echo "  Projekt aus DB gelöscht." || true
rm -rf "data/projects/${PROJECT_ID}" && echo "  data/projects/${PROJECT_ID} gelöscht." || true
echo ""

# ── Zusammenfassung ────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════"
echo "  ERGEBNIS"
echo "════════════════════════════════════════════════════════"
echo ""

PASS_COUNT=0
FAIL_COUNT=0

for i in "${!RESULTS[@]}"; do
    result="${RESULTS[$i]}"
    label="${LABELS[$i]}"
    if [[ "$result" == "PASS" ]]; then
        echo "  ✓ ${label}"
        ((PASS_COUNT++)) || true
    else
        echo "  ✗ ${label}"
        ((FAIL_COUNT++)) || true
    fi
done

echo ""
echo "  Gesamt: ${PASS_COUNT} PASS, ${FAIL_COUNT} FAIL"
echo ""

if [[ $FAIL_COUNT -eq 0 ]]; then
    echo "  ✓ Alle Tests bestanden."
    exit 0
else
    echo "  ✗ ${FAIL_COUNT} Test(s) fehlgeschlagen."
    exit 1
fi
