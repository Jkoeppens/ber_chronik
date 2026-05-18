# Architektur-Review — 15.05.2026

Branch: `feature/flexible-timeline-bins`  
Inspizierte Dateien: `dev_server.py` (1269 Z.), `match_entities.py`, `classify_segments.py`,
`export_exploration.py`, `templates/ingest_wizard.html` (2202 Z.)

---

## 1. Pipeline-Resilienz

### [KRITISCH] export_exploration.py mutiert config.json als Seiteneffekt

**Befund:** `export_exploration.py:327–329` schreibt `year_min`/`year_max` direkt in
`config.json` — als Seiteneffekt eines Export-Skripts.

```python
config["year_min"] = min(years)
config["year_max"] = max(years)
config_path.write_text(json.dumps(config, ...), encoding="utf-8")
```

Wenn der Nutzer im Wizard gerade andere Felder in `config.json` speichert (z.B. via
`save_taxonomy` oder `save_entities`) und gleichzeitig die Pipeline läuft, ist eine
Race Condition möglich. Konkreter Schaden: `taxonomy` oder `entities` könnten mit dem
Stand von vor dem Export-Lauf überschrieben werden (Read-Modify-Write ohne Lock).

**Lösung:** Nur die zwei Felder via `config_path.read_text → parse → patch → write_text`
atomar aktualisieren — nicht das gesamte Config-Objekt neu schreiben. Alternativ:
`year_min`/`year_max` in einem separaten Schritt nach dem Export schreiben, nie im
Merge-Schritt.

---

### [KRITISCH] Race Condition auf config.json bei parallelen Requests

**Befund:** Fünf Endpoints lesen `config.json`, modifizieren einen Schlüssel, schreiben
zurück — ohne jedes Locking:

- `save_taxonomy` (`/taxonomy/save`) — schreibt `cfg["taxonomy"]`
- `save_entities` (`/ingest/entities/save`) — schreibt `cfg["entities"]`
- `save_obsidian_config` (`/api/projects/{id}/obsidian/config`) — schreibt `cfg["obsidian"]`
- `ingest_save_config` — schreibt bis zu 5 Felder gleichzeitig
- `update_project_endpoint` — schreibt `cfg["title"]`

Wenn zwei Requests gleichzeitig eingehen (was bei SSE + parallelen Browser-Requests möglich
ist), gewinnt der letzte Write. Das bedeutet: ein laufender `propose_taxonomy`-SSE-Stream
(schreibt `taxonomy` in `config.json`) plus ein Editor-Save (schreibt `entities`) kann
das `entities`-Feld des anderen überschreiben.

**Lösung:** Einen `asyncio.Lock` pro Projekt-ID (z.B. `_project_locks: dict[str, asyncio.Lock]`)
einführen und alle config.json-Writes damit schützen. Alternativ kurzfristig: alle
config.json-Writes in eine einzige Helper-Funktion `patch_project_config(project, **fields)`
extrahieren, die das Locking intern handhabt.

---

### [MITTEL] match_entities.py schreibt classified.json nicht atomar

**Befund:** `match_entities.py:88–90` liest `classified.json` vollständig in RAM,
modifiziert alle Einträge und schreibt direkt zurück:

```python
CLASSIFIED_PATH.write_text(
    json.dumps(classified, ensure_ascii=False, indent=2), encoding="utf-8"
)
```

`write_text` öffnet die Datei im truncate-Modus. Wenn der Prozess während des Schreibens
stirbt (SIGKILL, OOM, Server-Restart), ist `classified.json` truncated und nicht
wiederherstellbar. Dasselbe gilt für `classify_segments.py:254` (`save_checkpoint`).

**Lösung:** Atomic-Write-Pattern: in eine `.tmp`-Datei schreiben, dann `os.replace()`.
Ein `write_atomic(path, data)` Helper für alle Pipeline-Outputs wäre sinnvoll:

```python
def write_atomic(path: Path, data: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(data, encoding="utf-8")
    tmp.replace(path)
```

---

### [MITTEL] Resume-Mischzustand nach Taxonomie-Änderung (bekannt, aber real)

**Befund:** Schon in STATUS.md dokumentiert, aber das tatsächliche Risiko ist unterschätzt:
`classify_segments.py` überspringt bereits klassifizierte Segmente anhand `segment_id`.
Wenn die Taxonomie zwischen zwei Läufen geändert wird (z.B. Kategorie umbenannt), enthält
`classified.json` danach Einträge mit zwei verschiedenen Taxonomien — und `normalize_category`
mappt die alten Namen auf `"(unbekannt)"` ohne Warnung.

Das ist kein hypothetisches Szenario: es passiert jedes Mal, wenn ein Nutzer die Taxonomie
in Schritt 4 verfeinert und dann in Schritt 7 die Pipeline neustartet ohne `--force`.

**Lösung:** `classify_segments.py` beim Start einen Taxonomie-Hash berechnen und in
`classified.json` als Metadaten-Feld speichern. Beim Resume: Hash vergleichen —
abweichender Hash → Warnung + Auto-`--force`. Keine stille Inkonsistenz mehr.

---

### [GERING] Pipeline-Teilfehler: export_exploration nicht-fatal, aber `__done__` kommt trotzdem

**Befund:** In `ingest_run` (Z. 638–645) gilt `export_exploration` als nicht-fatal:

```python
if "__error__" in chunk:
    break  # non-fatal: exploration failure doesn't abort
```

Danach wird `__done__` und der Viz-Link trotzdem gesendet. Der Nutzer sieht einen
Link der auf veraltete oder leere Daten zeigt — ohne Hinweis, dass der Export fehlschlug.

**Lösung:** Fehlermeldung aus dem Stream ins `__done__`-Payload codieren, oder den
Viz-Link nur senden wenn `exploration` erfolgreich war. Mindestens: eine SSE-Zeile
`data: ⚠ Explorer-Export fehlgeschlagen — Daten möglicherweise veraltet\n\n`.

---

## 2. Server-Architektur (dev_server.py)

### [KRITISCH] `/ingest/save_config` ohne Token-Prüfung

**Befund:** `POST /ingest/save_config` (Z. 517) hat keinen `_require_token`-Call.
Der Endpoint schreibt:
- `config.json` auf Projektebene (taxonomy, entities, year_min/max, title)
- `documents/{doc_id}/config.json` (doc_type, original_filename)
- Legt Projekte in der DB an oder aktualisiert sie

Jeder mit Invite-Token (oder wenn kein Invite konfiguriert: jeder überhaupt) kann
mit bekanntem `project`-Namen beliebige Felder überschreiben — z.B. die Taxonomie
durch eine leere Liste ersetzen.

Der erste `save_config`-Call in `runAnalysis()` erfolgt vor Token-Existenz (korrekt,
kein Token-Check möglich). Aber alle nachfolgenden Calls (Schritt 7) könnten einen
Token-Check haben — und tun es nicht.

**Lösung:** Endpoint aufteilen in zwei Handler:
1. `POST /ingest/bootstrap_config` — initialer Call ohne Token, nur für Neuanlage
2. `POST /ingest/save_config` — alle folgenden Calls, mit `_require_token`

Kurzfristig: Token optional prüfen — wenn Token vorhanden, validieren; wenn kein Token
im Request aber Projekt schon in DB: ablehnen.

---

### [MITTEL] Separation of Concerns: Business-Logic im HTTP-Handler

**Befund:** `ingest_analyze` (Z. 386–487) ist der schwergewichtigste Handler:
er parsed das Dokument via Subprocess, sampelt Segmente, baut LLM-Prompts,
ruft den Provider auf, normalisiert Events — alles in 100 Zeilen Handler-Code.
Kein separater Service, keine Funktion die man testen könnte.

Das ist der erste sinnvolle Refactor: `analyze_document(project, doc_id, doc_type, filename)`
als eigenständige Funktion extrahieren. Der HTTP-Handler wird dann zu ~15 Zeilen
Parameter-Extraktion + Fehlerweiterleitung.

**Lösung:** `analyze_document()` nach `pipeline_analyze.py` auslagern. Der Handler
ruft `asyncio.to_thread(analyze_document, ...)` auf. Testbar, wiederverwendbar.

---

### [MITTEL] Fehlerbehandlung: inkonsistenter Flickenteppich

**Befund:** config.json lesen hat je nach Handler unterschiedliche Fehlerbehandlung:

```python
# save_taxonomy (Z. 354): try/except ✓
try:
    cfg = json.loads(config_p.read_text(encoding="utf-8"))
except (json.JSONDecodeError, OSError):
    pass

# save_obsidian_config (Z. 1187): kein try/except ✗
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}

# test_obsidian_config (Z. 1216): kein try/except ✗
tokens = json.loads(DROPBOX_TOKENS_PATH.read_text(encoding="utf-8"))
```

Wenn `dropbox_tokens.json` malformed JSON enthält, crashed `test_obsidian_config`
mit unbehandeltem `JSONDecodeError` — FastAPI gibt 500, der Nutzer sieht keine
hilfreiche Fehlermeldung.

**Lösung:** `read_json_safe(path, default)` Helper einführen:

```python
def read_json_safe(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}
```

Das eliminiert die 12 inkonsistenten Lesestellen, die in STATUS.md bereits als
technische Schulden gelistet sind.

---

### [GERING] `_obsidian_oauth_states` in-memory verliert State bei Hot-Reload

**Befund:** `_obsidian_oauth_states` (Z. 1105) ist ein Modul-globales Dict.
`uvicorn --reload` triggert einen Modul-Reload wenn eine Quelldatei geändert wird —
alle laufenden OAuth-Flows werden ungültig. Der Callback-Request nach dem Dropbox-Login
kommt dann mit "Ungültiger OAuth-State" zurück.

Kein kritischer Bug bei Single-Shot-Deployment, aber ärgerlich in der Entwicklung.

**Lösung:** OAuth-State in einer temporären Datei oder SQLite-Tabelle persistieren.
Alternativ: Reload-Schutz via `--reload-exclude` für `dev_server.py` in der
Entwicklungsanleitung dokumentieren.

---

## 3. Wizard (ingest_wizard.html)

### [MITTEL] `saveTimeConfig()` fire-and-forget ohne Feedback

**Befund:** `saveTimeConfig()` (Z. 1329) feuert `fetch(...)` ohne `await` und
ohne Error-Handling:

```javascript
function saveTimeConfig() {
  if (!state.project || !state.token) return;
  fetch('/ingest/save_config' + _aq(), {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ... }),
  });  // kein await, kein .catch()
}
```

Wenn der Server down ist oder das Netzwerk kurz unterbricht, verliert der Nutzer
seine Zeitkonfigurationsänderungen still. Die Debounced-Variante (Z. 1342) macht
es nicht besser — sie wartet nur 600ms, verspricht aber noch weniger.

**Lösung:** Entweder `async/await` + UI-Feedback (`tax-status`-ähnliches Element:
"⚠ Nicht gespeichert"), oder zumindest `.catch(e => console.warn('saveTimeConfig:', e))`.
Mittelfristig: Pending-Saves beim Schritt-Wechsel explizit awaiten.

---

### [MITTEL] Globaler State: unkontrollierte Mutation via `taxData`

**Befund:** `taxData` ist ein Modul-globales Array das an 7+ Stellen direkt mutiert
wird (`taxData.push(...)`, `taxData.splice(...)`, `taxData[idx].name = ...`).
Es gibt keinen einzigen kontrollierten Zugriffspunkt.

Das konkrete Problem: Nach einem erfolgreichen KI-Vorschlag ruft `_runProposeTaxonomy`
erst `await initTaxonomy()` (setzt taxData aus Server-Response) und dann sofort
`markTaxDirty()` (setzt `taxDirty = true`). Wenn der Nutzer in diesem Moment den
Zurück-Button drückt und zu Schritt 4 navigiert, triggert `gotoStep` ein `saveTaxonomy()`
mit dem aktuellen `taxData` — was korrekt ist. Aber `taxDirty` wurde noch nicht
zurückgesetzt (das passiert erst in `saveTaxonomy()`). Doppel-Save möglich.

**Lösung:** `taxData` und `taxDirty` in ein State-Objekt zusammenführen, das nur via
definierten Funktionen mutiert wird (`setTaxData(data)`, `patchTaxItem(idx, fields)`).
Das sind ~30 Zeilen Refactor mit messbarem Nutzen.

---

### [GERING] iframe-Architektur (entity_editor): funktional, aber blind

**Befund:** Der Entity-Editor läuft in einem `<iframe>` der `entity_editor.html` lädt.
Die Kommunikation zwischen Wizard und Editor ist unidirektional: Wizard setzt `iframe.src`,
Editor macht eigene API-Calls. Es gibt kein `postMessage`-Protokoll.

Konsequenz: Der Wizard weiß nicht ob der Editor-State "dirty" ist. Wenn der Nutzer
in Schritt 6 Entities bearbeitet, dann direkt auf Schritt 7 (Pipeline) klickt, gibt es
keine Bestätigung "Änderungen wurden gespeichert". Der Entity-Editor setzt bei jeder
Aktion sofort einen `POST /ingest/entities/save` ab (D-P4), also ist das in der Praxis
harmlos — aber wenn ein Request im Flug ist und der Nutzer weiternavigiert, ist der
Save verlorengegangen.

Das ist eine bewusste Architekturentscheidung (Isolation), keine technische Schuld.
Das einzige echte Risiko ist der Token-Expiry: wenn der Token während einer langen
Entity-Editing-Session abläuft, zeigt der iframe eine 403-Fehlerseite ohne UI-Feedback
im Wizard.

**Lösung:** `postMessage` vom iframe bei erfolgreichem Save (1 Zeile) → Wizard kann
optional einen "✓ Gespeichert"-Status anzeigen. Minimaler Aufwand, maximaler
UX-Nutzen.

---

### [GERING] `console.log` Debug-Statement in Produktionscode

**Befund:** `renderEventsList()` (Z. 1392):

```javascript
console.log('[renderEventsList] events:', JSON.stringify(state.time_config.events));
```

Wird bei jeder Timeline-Änderung gefeuert. In großen Projekten (viele Events)
unnötige JSON-Serialisierung und Browser-Console-Spam.

**Lösung:** Eine Zeile löschen.

---

### [GERING] Stille `catch (_) {}` an kritischen Stellen

**Befund:** Im Wizard an mindestens 3 Stellen:

```javascript
} catch (_) {}                    // Z. 1218: Preview-Regenerierung nach Classify
} catch (_) { return false; }    // Z. 1297: runAnchorPipeline Fehler
} catch (_) {}                    // Z. 1249: doc_status-Check in initTimeConfig
```

Die ersten beiden sind operativ — wenn die Pipeline-Requests scheitern, sieht der
Nutzer keine Fehlermeldung. Der Nutzer denkt die Pipeline ist fertig, obwohl sie
abgebrochen hat.

**Lösung:** Mindestens ein `console.error(_, 'in runAnchorPipeline')` in den
kritischen Catches. Besser: UI-Feedback analog zu `statusEl.textContent = '✗ Fehler'`.

---

## 4. Datenpersistenz

### [KRITISCH] `/ingest/save_config` als Angriffsvektor auf Projektdaten

Bereits unter Server-Architektur gelistet. Zur Vollständigkeit:
Ohne Token-Check kann jeder mit bekanntem Projektnamen `taxonomy: []` senden und
damit alle Taxonomie-Daten unwiederbringlich überschreiben. Die Pipeline-Skripte
scheitern danach (D-P1 — expliziter Fehler bei leerer Taxonomie), aber die Daten
sind weg.

---

### [MITTEL] Kein Transaktionsschutz für config.json als gemeinsames Dokument

`config.json` auf Projektebene ist die kanonische Quelle für `taxonomy`, `entities`,
`year_min/max`, `title` und `obsidian`-Config — d.h. 5 unabhängige Write-Pfade teilen
sich eine Datei ohne Mutex. Schon zwei gleichzeitige Browser-Tabs des Wizards können
eine Race Condition auslösen.

**Lösung:** `asyncio.Lock` pro Projekt-ID, beschrieben unter Pipeline-Resilienz/Race Condition.

---

### [MITTEL] Kein persistenter Checkpoint für classify_segments nach Prozessabbruch

**Befund:** `classify_segments.py` schreibt alle `SAVE_INTERVAL = 2` Batches einen
Checkpoint. Bei `max_concurrency = 10` (Anthropic-Pfad) sind das maximal 20 verlorene
Klassifizierungen bei Absturz. Das Resume beim nächsten Start holt diese nach —
sofern `classified.json` nicht truncated ist (siehe: atomares Schreiben fehlt).

Bei `category: None` (LLM-Parse-Fehler nach 2 Retries, Z. 103) werden diese
Segmente beim nächsten Resume als "bereits klassifiziert" markiert (`category is not None`
Check, Z. 232) und nie nachklassifiziert — also permanent `None`.

**Lösung:** `category: None` explizit aus dem Resume-Existing-Filter ausschließen:
```python
if r.get("category") is not None:  # aktuell
if r.get("category") is not None and r.get("category") != None:  # gleich
# Richtig:
if r.get("category") is not None and r.get("confidence") is not None:
```
Nein — einfacher: `if r.get("category")` (falsy für None und "") als Resume-Bedingung.

---

### [GERING] DB und Filesystem können divergieren

**Befund:** `create_project` in der DB und das Anlegen von `config.json` auf dem
Filesystem sind zwei separate Operationen ohne gemeinsame Transaktion. Wenn der
Server zwischen beiden Operationen abstürzt, existiert das Verzeichnis ohne DB-Eintrag
(oder umgekehrt). Beim nächsten Serverstart: `list_projects_endpoint` zeigt das Projekt
nicht, aber das Verzeichnis bleibt.

Kein kritisches Problem bei Single-User-Dev, aber ein Debugging-Headache.

**Lösung:** Nach jedem Serverstart einen Reconcile-Schritt: Projekte in DB aber nicht
im FS (oder umgekehrt) als `orphan` markieren. Kein Auto-Delete.

---

## 5. Technische Schulden vs. echte Risiken

### Echte Risiken (handeln, nicht dokumentieren)

| Problem | Schweregrad | Aufwand Fix |
|---|---|---|
| `/ingest/save_config` ohne Token-Check | KRITISCH | mittel |
| Race Condition config.json parallel writes | KRITISCH | mittel |
| `export_exploration` mutiert config.json als Seiteneffekt | KRITISCH | klein |
| Kein atomares Schreiben für classified.json | MITTEL | klein |
| `saveTimeConfig()` fire-and-forget | MITTEL | klein |

### Bewusster Pragmatismus (dokumentiert, akzeptiert)

- **Kein Build-Tool, globaler JS-Scope**: Bewusst (DECISIONS.md). Richtige Entscheidung
  für Single-Dev-Deployment. Würde sich erst bei ≥3 gleichzeitigen Entwicklern rächen.

- **iframe für entity_editor**: Saubere Isolation. Die "Blindheit" des Wizards ist real,
  aber der Auto-Save-On-Every-Action (D-P4) fängt den praktischen Fall ab.

- **Globaler `state`-Object ohne Observer**: Akzeptabel bei dieser Größe (~2200 Zeilen).
  Riskant wenn die Datei weiter wächst. Grenze wäre bei ~3500 Zeilen.

- **`classify_segments.py` Resume mit alter Taxonomie**: In STATUS.md dokumentiert.
  Im Praxisbetrieb: Nutzer weiß, dass er bei Taxonomie-Änderung `--force` braucht.
  Das Risiko ist echt, aber der Schaden (falsch klassifizierte Segmente) ist sichtbar.

- **`is_geicke`-Feld in generalisierten Exports**: Technische Schuld, kein Risiko.
  Alle Nicht-BER-Projekte emittieren `"is_geicke": false` in data.json — panel.js
  ignoriert das Feld wenn false. Löschen wenn BER-Daten migriert.

### Nicht-offensichtliche Kopplung (weder Risiko noch Schuld, aber Wissen nötig)

- `ingest_run` (`POST /ingest/run`) schaltet `export_preview.py` NUR dann ein,
  wenn `has_anchors` false war (Z. 624–625). Wenn Anchors bereits existieren und
  Pipeline neu läuft (Taxonomie-Update-Szenario), wird preview.html NICHT aktualisiert.
  Designentscheidung oder Lücke? Nicht dokumentiert.

- `run_pipeline_sse` sendet `__done__` nur nach dem letzten Schritt (Z. 242).
  Aber `ingest_run/gen()` sendet `__done__` selbst (Z. 645) — nicht via
  `run_pipeline_sse`. Die zwei Code-Pfade sind subtil verschieden. Nach einem
  Fehler in Schritt N sendet der gen()-Pfad `__done__` explizit (Z. 635),
  der `run_pipeline_sse`-Pfad würde returnen. Das ist korrekt, aber wer diesen Code
  liest, erwartet das nicht.

---

## Priorisierte Handlungsliste

1. **Sofort:** `console.log` aus `renderEventsList` entfernen (1 Zeile)
2. **Diese Woche:** Token-Check in `save_config` einführen oder Bootstrap/Update trennen
3. **Diese Woche:** `write_atomic` Helper für alle classified.json Writes
4. **Diese Woche:** `export_exploration` darf config.json nur via Patch schreiben, nicht komplett überschreiben
5. **Nächste Woche:** `asyncio.Lock` pro Projekt für alle config.json Writes
6. **Nächste Woche:** `read_json_safe()` Helper — alle 12 inkonsistenten Lesestellen vereinheitlichen
7. **Backlog:** `saveTimeConfig` mit Error-Feedback; `classify` Mischzustand via Taxonomie-Hash detektieren

---

## 6. Wartbarkeit und Lesbarkeit

Scope: ausschließlich Benennung, Struktur, Muster-Konsistenz. Kein Security, keine Resilienz.

---

### dev_server.py

#### Benennung: ein Namenskonflikt zieht sich durch die gesamte Datei

`project` und `project_id` bezeichnen dasselbe Konzept — den Slug-Identifier eines Projekts —
aber in verschiedenen Handlern unter verschiedenen Namen:

```python
# Ingest-Endpunkte: "project" (aus Body oder Query-Param)
project = request.query_params.get("project")

# API-Endpunkte: "project_id" (aus Pfad-Parameter)
@app.get("/api/projects/{project_id}")
async def get_project_endpoint(project_id: str):
```

Ein neuer Leser sieht beide Namen, geht davon aus, dass sie sich unterscheiden, und sucht
nach der Stelle wo das eine ins andere konvertiert wird. Die gibt es nicht — sie sind identisch.

Die Entity-Handler haben kein konsistentes Namensmuster:
`get_entities_data`, `save_entities`, `reject_entity`, `get_near_duplicates` — mal Plural,
mal Singular, mal Verb vorn, mal Verb hinten. Im Vergleich dazu sind die CRUD-Handler
für Projekte vorbildlich konsistent (`create_project_endpoint`, `list_projects_endpoint`,
`update_project_endpoint`, `delete_project_endpoint`).

Die Obsidian-Handler folgen keiner Regel:
`obsidian_oauth_start`, `obsidian_oauth_callback` (Präfix vorn) vs.
`save_obsidian_config`, `test_obsidian_config` (Präfix hinten) vs.
`obsidian_sync` (wieder vorn).

`_get_latest_doc_id` (Z. 913) ist ein Ein-Zeiler der nur `get_latest_doc_id` aus dem
DB-Modul durchreicht — kein Mehrwert, keine Transformation, löschwürdig.

#### Benennung: Response-Shape ohne Vertrag

Einige Handler antworten mit `{"ok": True/False, "error": "..."}`, andere nur mit
`{"error": "..."}`, und `get_doc_status` gibt ein reines Dict ohne `ok`-Feld zurück.
Es gibt keine gemeinsame Konvention. Wer einen neuen Handler schreibt, rät:

```python
# POST /overrides:
return JSONResponse({"ok": False, "error": "..."}, status_code=400)

# POST /recompute:
return JSONResponse({"error": "..."}, status_code=400)         # kein "ok"

# GET /ingest/doc_status:
return JSONResponse({"segments": ..., "anchors": ...})          # kein "ok", kein "error"
```

#### Struktur: gut — mit einem blinden Fleck

Die `# ── VERB /endpoint ───` Kommentar-Trennlinien sind konsequent und nützlich.
`run_script_sse` und `run_pipeline_sse` sind als "Shared SSE helper" klar abgesetzt.
Die Static-Mounts am Ende sind logisch letzter Schritt.

Der blinde Fleck: Es fehlt eine übergeordnete Domänen-Gruppierung. Die Datei hat
fünf inhaltliche Bereiche — Pipeline-Ingest, Taxonomie, Entities, Projekte/Auth,
Obsidian — aber das ist nirgends durch einen Rahmen-Kommentar sichtbar. Wer "alle
Obsidian-Endpoints" sucht, muss die gesamte Datei lesen.

#### Muster-Konsistenz: alle SSE-Generatoren heißen `gen`

Alle fünf SSE-Handler definieren eine innere Funktion namens `gen`, die sofort
an `sse_response()` übergeben wird. Das Muster ist intern konsistent, aber
`grep gen dev_server.py` findet alle fünf ohne sie zu unterscheiden.
Sprechende Namen (`classify_stream`, `obsidian_sync_stream`) würden hier helfen.

#### Was ein neuer Leser als erstes missverstehen würde

Das Walrus-Operator-Auth-Pattern ist für FastAPI-Einsteiger ungewohnt:

```python
if err := await _require_token(request, project): return err
```

Wer FastAPI aus Tutorials kennt (Auth als Dependency Injection), wird `_require_token`
für eine normale Funktion halten und dann überrascht sein, dass sie eine `JSONResponse`
zurückgeben kann — und dass `return err` innerhalb eines async-Handlers direkt die
Response ausliefert.

---

### ingest_wizard.html (2202 Zeilen)

#### Benennung: `_aq()` ist das meistgenutzte Rätsel der Datei

`_aq()` erscheint in ~25 API-Calls. Die Funktion baut den Auth-Query-String:

```javascript
function _aq() {
  // gibt "?project=X&document=Y&token=Z" zurück
}
```

Kein Leser erschließt das aus dem Namen. `_authQuery()` wäre ein Buchstabe mehr und
vollständig lesbar. `_aq` kostet jeden neuen Leser 5 Minuten Suche bevor sie
irgendeinen API-Call verstehen können.

`z*`-Präfix auf Obsidian-Variablen ist Zotero-Erbgut. Der Code hieß früher
`ingest_zotero.html`, der Präfix blieb. `zBtn`, `zPanel`, `zFolder`, `zConnBtn` usw.
beschreiben heute das Obsidian-Panel — ein neuer Leser fragt sich warum Obsidian-Code
mit `z` beginnt und findet keine Antwort im Code.

`taxData` (global) und `state.*` (global object) koexistieren als zwei verschiedene
State-Idiome ohne erkennbaren Grund. Die Taxonomie hätte in `state.taxonomy` liegen
können. So müssen Leser zwei mentale Modelle für "wo ist der State" pflegen.

`syncRan` (lokal in `onEnterStep`) vs. `analysisRan` (Modul-global): beide sind
Guards gegen Doppelausführung, aber auf verschiedenen Ebenen ohne dokumentierten Grund.

#### Muster-Konsistenz: der SSE-Loop ist achtmal neu geschrieben

Der SSE-Leseloop erscheint wortwörtlich an acht Stellen (12–15 Zeilen, identischer Kern):

| Funktion | Zweck |
|---|---|
| `runObsidianSync` | Obsidian-Import |
| `runClassifyAfterTaxonomy` | Klassifizierung (zweimal verschachtelt) |
| `runAnchorPipeline` | Zeitanker-Pipeline |
| `_runProposeTaxonomy` | KI-Taxonomie-Vorschlag |
| `zSyncBtn` event listener | Obsidian-Sync in Projektkarte |
| `runBtn` in proj-card | Dokument-Upload-Pipeline |
| Step-7-Pipeline-Handler | Vollständige Pipeline |
| `runSingleStep` | Einzelschritt-Neustart |

`runSseTask()` (Z. 2015) existiert als Extraktionsversuch, wird aber an keiner dieser
acht Stellen tatsächlich genutzt. Das ist die teuerste Inkonsistenz der Datei:
eine Abstraktion die existiert aber nicht gilt. Ein neuer Entwickler findet sie,
versteht das Muster — und sieht dann, dass alle acht Stellen sie ignorieren.
Das Signal "wir haben eine Abstraktion, die wir nicht benutzen" erzeugt mehr
Verwirrung als gar keine Abstraktion.

#### Muster-Konsistenz: Token-Beschaffung, drei Varianten an derselben Stelle

Im `loadProjectList`-Block, innerhalb desselben Event-Handler-Kontexts:

```javascript
// zSyncBtn: _getProjectToken() Helper
const syncTok = await _getProjectToken(projId);
headers: { 'X-Project-Token': syncTok }

// zTest: _getProjectToken() Helper
const testTok = await _getProjectToken(projId);
headers: { 'X-Project-Token': testTok }

// zSave: manuell inline (offensichtlich nachträglich hinzugefügt)
const tokRes = await fetch('/api/projects/' + encodeURIComponent(projId) + '/token' + _aq());
const tokData = await tokRes.json();
headers: { 'X-Project-Token': tokData.token || '' }
```

`zSave` kennt `_getProjectToken` nicht — oder hat es vergessen. Drei Wege zum
gleichen Ziel, drei Zeilen auseinander.

#### Struktur: `loadProjectList` ist ein versteckter Monolith

`loadProjectList()` macht dem Namen nach eine Sache. Tatsächlich enthält sie:
1. API-Call + Fehlerbehandlung für die Projektliste
2. Template-String für alle Projektkarten (HTML-Generierung)
3. Event-Binding für das "Dokument hinzufügen"-Panel (~60 Z.)
4. Vollständige Obsidian-Panel-Logik (~120 Z.) mit eigenem State
5. Drag-and-Drop-Handling
6. Pipeline-SSE-Streaming für den Upload-Flow

Die Verschachtelungstiefe geht bis 5 Ebenen:
`Funktion → forEach → Closure → Event-Listener → async → try/catch`.

Der erste sinnvolle Schritt: `setupObsidianPanel(wrap, projId)` und
`setupAddDocPanel(wrap, projId)` als eigenständige Funktionen auslagern.
`loadProjectList` wird dann zu dem, was der Name verspricht.

#### Was ein neuer Leser als erstes missverstehen würde

**`runSseTask` gilt nicht.**
Es ist die einzige benannte Abstraktion für das dominierende Muster der Datei.
Ein neuer Leser findet sie, versteht das Muster, will sie benutzen — und merkt,
dass alle acht existierenden Stellen sie ignorieren. Das kostet Vertrauen in
den Rest des Codes ("was gilt hier eigentlich?").

**`taxData[idx]` in Closures nach `splice`.**
`renderTaxGrid()` generiert Closures die den aktuellen `idx` einfangen.
Wenn `del` geklickt wird: `splice` verschiebt alle Indizes über dem gelöschten.
Dann ruft der Handler `renderTaxGrid()` auf — die alten Closures werden durch
neue ersetzt, die Indizes sind wieder korrekt. Das ist richtig, aber eine
kommentarlose Invariante: wer `renderTaxGrid()` aus dem `del`-Handler entfernt,
erzeugt einen stillen Index-Fehler. Ein Kommentar "// Indizes neu aufbauen —
splice macht idx > N ungültig" würde reichen.
