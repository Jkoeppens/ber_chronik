# Wizard Flow — Referenz

Stand: 2026-04-27 | Branch: fix/except-blocks

---

## Schritt-für-Schritt

### Schritt 1 — Dateien hochladen

**Trigger:** Seitenload (frischer Start) oder Klick auf Schritt 1 in der Dot-Navigation.

**Was passiert:**
- Nutzer wählt Datei per Drag-&-Drop oder File-Input
- `state.files`, `state.project_title` werden gesetzt
- "Weiter" wird erst aktiv wenn `state.files.length > 0 && state.project_title`

**Kein API-Call in diesem Schritt.**

---

### Schritt 2 — Dokumenttyp

**Was passiert:**
- Nutzer wählt `doc_type` (Forschungsnotizen / Buchnotizen / Presseartikel)
- Schreibt `state.doc_type`
- Kein API-Call — reine UI

---

### Schritt 3 — LLM-Analyse

**Was passiert beim Vorwärtsnavigieren:**

**Neues Projekt:**
1. `POST /ingest/analyze` → `parse_document.py` + LLM-Analyse → JSON
2. Response setzt: `state.project`, `state.document`, `state.analysis`, `state.time_config`
3. Sofort danach: `POST /ingest/save_config` mit `title`, `doc_type`, `time_config`
   - Server schreibt `projects/{project}/config.json` (alle Felder) + `documents/{doc_id}/config.json` (doc_type, original_filename)
   - Server legt Projekt in DB an und gibt `token` zurück → `state.token`

**Bestehendes Projekt (Restore via URL):**
1. `GET /ingest/doc_status` — prüft ob `segments.json` vorhanden
2. Wenn ja: direkt weiter zu Schritt 4 (kein neuer Analyse-Lauf)
3. Wenn nein: `runAnalysis()` wie oben

**Dateien geschrieben:** `data/raw/{filename}` (Upload), `segments.json` (parse_document.py)

---

### Schritt 4 — Taxonomie

**onEnterStep(4):** `initTaxonomy()` → `GET /taxonomy/data?project=&document=&token=`
- Server liest `config.json["taxonomy"]`
- Setzt `taxData` (globale Variable) + rendert Grid
- `taxDirty = false`

**Aktionen:**
- "+ Kategorie": `taxData.push(...)`, `markTaxDirty()`
- "KI-Vorschlag": `POST /ingest/propose_taxonomy` (SSE) → `propose_taxonomy.py` → schreibt direkt in `config.json["taxonomy"]` → danach `initTaxonomy()` + `markTaxDirty()`
- "Speichern": `POST /taxonomy/save` → schreibt `config.json["taxonomy"]` + setzt `taxDirty = false`
- "Neu klassifizieren": `POST /ingest/run/step` mit `classify_segments.py` (SSE) → danach ggf. `export_preview.py`

**Weiter-Button:** Ruft `saveTaxonomy()` (wenn `taxDirty`) dann `gotoStep(5)`.

**Dateien geschrieben:** `config.json["taxonomy"]`

---

### Schritt 5 — Zeitkonfiguration

**onEnterStep(5):** `initTimeConfig()` liest aus `state.time_config` (bereits beim Analyse-Schritt befüllt). Lädt Preview-iframe wenn `anchors_interpolated.json` vorhanden.

**Aktionen:**
- Jahr-Inputs + Ereignis-Editor: mutieren `state.time_config` inline
- `saveTimeConfig()` (bei jeder Änderung): `POST /ingest/save_config` mit `time_config` → schreibt `year_min`, `year_max`, `events` in `config.json`
- "Zeitanker berechnen" / Weiter-Button: `runAnchorPipeline()`
  1. `POST /ingest/run/step` → `detect_anchors.py` (SSE)
  2. `POST /ingest/run/step` → `interpolate_anchors.py` (SSE)
  3. Wenn Taxonomie vorhanden: `POST /ingest/run/step` → `export_preview.py` (SSE)
  4. Lädt Preview-iframe: `/preview?project=&document=&token=`

**Dateien geschrieben:** `anchors.json`, `anchors_interpolated.json`, `preview.html`

---

### Schritt 6 — Entities

**onEnterStep(6):** `initEntities()` → setzt `src` des iframes auf `/ingest/entities?project=&document=&token=`

Der iframe lädt `entity_editor.html` als eigenständige Seite mit eigenen Fetch-Calls:
- `GET /ingest/entities/data` → liest `entities_proposal.json` (Prio 1), dann `config.json["entities"]` (Fallback)
- `POST /ingest/entities/save` → schreibt `entities_proposal.json` + spiegelt in `config.json["entities"]`
- `POST /ingest/entities/reject` → schreibt `entities_rejected.json` + entfernt Entity aus `entities_proposal.json`
- `POST /ingest/entities/extract` (SSE) → `extract_entities_v2.py` → schreibt `entities_proposal.json`

**Dateien gelesen/geschrieben:**
- `entities_proposal.json` — kanonische Quelle, Lesen + Schreiben
- `config.json["entities"]` — Spiegel für Pipeline-Schritte
- `entities_rejected.json` — Filter für nächsten Extraction-Run

---

### Schritt 7 — Pipeline

**Beim Klick auf "Pipeline starten":**
1. `POST /ingest/save_config` mit `title`, `doc_type`, `time_config`, `created_at`
   - `taxonomy: taxData` **nur wenn `taxData.length > 0`** — verhindert Überschreiben
2. `POST /ingest/run` (SSE) → läuft alle 8 Pipeline-Schritte sequenziell:
   `parse_document.py` → `detect_anchors.py` → `interpolate_anchors.py` →
   `classify_segments.py` → `match_entities.py` → `export_preview.py` →
   `extract_entities_v2.py` (optional) → `export_exploration.py`

   **Pipeline-Skipping:** `parse_document.py` wird übersprungen wenn `segments.json`
   bereits vorhanden ist. `detect_anchors.py` und `interpolate_anchors.py` werden
   übersprungen wenn `anchors_interpolated.json` bereits vorhanden ist.
3. Am Ende: SSE sendet `__link__:/viz/?project=...` → Viz-Link erscheint

**Dateien geschrieben:** alle Pipeline-Outputs, final `exploration/data.json`

---

## State-Variablen (JS, global)

| Variable | Typ | Gesetzt wann | Gelesen wann |
|---|---|---|---|
| `state.project` | string | Analyse-Response, `openExistingProject`, `restoreFromUrl` | Alle API-Calls via `_aq()` |
| `state.document` | string | Analyse-Response, `openExistingProject`, `restoreFromUrl` | Alle API-Calls via `_aq()` |
| `state.token` | string | `save_config`-Response, `openExistingProject`-Token-Fetch, `restoreFromUrl` | `authHeaders()`, `_aq()` |
| `state.project_title` | string | Schritt 1 Input, `restoreFromUrl` | Schritt 1 Anzeige, `save_config` |
| `state.doc_type` | string | Schritt 2 Auswahl, `restoreFromUrl` | `save_config`, Analyse |
| `state.analysis` | object | Analyse-Response | Schritt 3 Anzeige, `save_config` |
| `state.time_config` | object | Analyse-Response, `restoreFromUrl` (aus `cfg`) | Schritt 5, `saveTimeConfig`, Pipeline-`save_config` |
| `state.isExistingProject` | bool | `restoreFromUrl` → `true`; Schritt 1 → `false` | Schritt-3-Logik, `save_config` (`taxonomy:[]` guard) |
| `taxData` | array | `initTaxonomy()`, `restoreFromUrl` (aus `cfg.taxonomy`), Inline-Edits | Schritt 4 Grid, `saveTaxonomy()`, Pipeline-`save_config` |
| `taxDirty` | bool | `markTaxDirty()` → `true`; `initTaxonomy()`, `saveTaxonomy()` → `false` | Weiter-Button Schritt 4 |
| `currentStep` | int | `gotoStep(n)` | Navigation, URL-Schreiben |
| `maxReachedStep` | int | `updateProgress(n)`, `restoreFromUrl` | Dot-Klick-Guard |
| `analysisRan` | bool | nach erstem `runAnalysis()` → `true` | Schritt-3-Guard gegen Doppelstart |
| `evNextId` | int | Inkrementiert bei jedem neuen Ereignis | Ereignis-IDs |

---

## Kritische Abhängigkeiten

```
Schritt 3 benötigt:  state.files (Upload), state.project_title
                     → schreibt state.project, state.document, state.token

Schritt 4 benötigt:  state.project, state.token (für /taxonomy/data)
                     → ohne token: 401, taxData bleibt []

Schritt 5 benötigt:  segments.json (aus Schritt 3)
                     → runAnchorPipeline schlägt fehl ohne segments

Schritt 6 benötigt:  state.project, state.token (iframe-src)
                     → ohne token: iframe zeigt Fehler

Schritt 7 benötigt:  config.json["taxonomy"] nicht leer
                     → classify_segments.py bricht ab mit "Keine Taxonomie"
                     → Taxonomie muss in Schritt 4 gespeichert worden sein

Pipeline classify    benötigt: segments.json, config.json["taxonomy"]
Pipeline match_ent.  benötigt: classified.json, config.json["entities"]
Pipeline export_prev benötigt: anchors_interpolated.json, classified.json, config.json["taxonomy"]
Pipeline export_expl benötigt: alle obigen
```

---

## Dateien und ihre Rollen

### `projects/{project}/config.json`

**Kanonische Quelle für:** `taxonomy`, `entities`, `year_min/max`, `events`, `title`

| Feld | Geschrieben von | Darf überschrieben werden |
|---|---|---|
| `taxonomy` | `/taxonomy/save`, `propose_taxonomy.py`, `/ingest/save_config` (nur wenn `taxData.length > 0`) | Nur durch explizites Speichern in Schritt 4 — nie mit leerem Array |
| `entities` | `/ingest/entities/save` | Bei jedem Editor-Save |
| `year_min/max/events` | `/ingest/save_config` via `time_config` | Bei jeder Zeitconfig-Änderung |
| `title` | `/ingest/save_config`, `PUT /api/projects/{id}` | Unkritisch |

**Gelesen von:** `classify_segments.py`, `match_entities.py`, `export_preview.py`, `export_exploration.py`, `/taxonomy/data`, `/ingest/entities/data` (Fallback), `restoreFromUrl` via `/api/projects/{id}`

### `documents/{doc_id}/entities_proposal.json`

**Kanonische Quelle für:** Entity-Liste nach Extraction

**Geschrieben von:** `extract_entities_v2.py` (Extraction-Run), `/ingest/entities/save` (Editor-Save), `/ingest/entities/reject` (Entity entfernen)

**Gelesen von:** `/ingest/entities/data` (Prio 1)

### `documents/{doc_id}/entities_rejected.json`

**Zweck:** Filter für nächsten Extraction-Run

**Geschrieben von:** `/ingest/entities/reject`

**Gelesen von:** `extract_entities_v2.py` (beim nächsten Run als `rejected_lc`)

### `documents/{doc_id}/segments.json`

Geschrieben von `parse_document.py`. Eingabe für alle nachgelagerten Schritte.

### `documents/{doc_id}/anchors.json` / `anchors_interpolated.json`

Geschrieben von `detect_anchors.py` / `interpolate_anchors.py`. Eingabe für `export_preview.py` und `export_exploration.py`.

### `documents/{doc_id}/classified.json`

Geschrieben von `classify_segments.py` (category + confidence) und `match_entities.py` (actors, in-place). Eingabe für beide Export-Skripte.

---

## URL-State (Reload-Persistenz)

`gotoStep(n)` schreibt bei jedem Schritt-Wechsel:
```
?project={state.project}&document={state.document}&step={n}
```

Beim Laden liest `restoreFromUrl()` diese Parameter:
1. `GET /api/projects/{id}/token` → `state.token`
2. `GET /api/projects/{id}` → `state.project_title`, `state.doc_type`, `state.time_config`, `taxData` (wenn `cfg.taxonomy.length > 0`)
3. `gotoStep(step)` → springt direkt zum gespeicherten Schritt

**Token ist nie in der URL** — wird immer neu geholt.
