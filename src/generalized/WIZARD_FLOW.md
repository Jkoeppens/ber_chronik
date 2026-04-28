# Wizard Flow — Referenz

Stand: 2026-04-27 (aktualisiert) | Branch: fix/except-blocks

---

## Schritt-für-Schritt

### Schritt 1 — Projektstartseite (Version C)

**Trigger:** Seitenload. Zeigt Projektliste statt Upload-Box.

**Was passiert:**
- `loadProjectList()` → `GET /api/projects` (mit `X-Invite-Token`-Header)
  - Bei 401: Inline Invite-Code-Formular (kein Redirect auf invite_gate.html)
  - Bei Erfolg: Projekt-Karten werden gerendert
- Erste Karte immer: **„Neues Projekt +"** — öffnet inline Dialog

**Dialog „Neues Projekt +" — Datei-Pfad:**
- Projektname-Input + Datei-Drop + Dok-Typ
- Klick „Analysieren →": Upload → setzt `state.project_title`, `state.doc_type`, `state.files` → `gotoStep(3)`
- Schritt 2 wird übersprungen

**Dialog „Neues Projekt +" — Zotero-Pfad:**
→ Siehe Abschnitt [Zotero-Flow](#zotero-flow) unten.

**Kein regulärer „Weiter"-Button auf Schritt 1** — Navigation erfolgt ausschließlich über die Karten-Buttons.

---

### Schritt 2 — Dokumenttyp

**Was passiert:**
- Nutzer wählt `doc_type` (Forschungsnotizen / Buchnotizen / Presseartikel)
- Schreibt `state.doc_type`
- Kein API-Call — reine UI
- **Wird im Datei-Pfad von Schritt 1 übersprungen** (doc_type kommt aus dem Inline-Dialog)

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

---

## Zotero-Flow

### Neues Zotero-Projekt anlegen (Schritt 1, Inline-Dialog)

1. Nutzer klickt „Neues Projekt +" → Tab „Zotero" wählen
2. Felder: Projektname, API-Key, User-ID, Collection-Key, Dok-Typ
3. **Testen**: `GET /api/projects/_new/zotero/test?api_key=&user_id=&collection=`
   → pyzotero-Test im Thread-Executor, gibt `{ok, count}` zurück
4. **Importieren →**:
   1. `POST /api/projects` → legt Projekt in DB + `config.json` an, gibt `token` zurück
   2. `POST /api/projects/{id}/zotero/config` → speichert Credentials in `config.json["zotero"]`
   3. `POST /api/projects/{id}/zotero/sync` (SSE) → `ingest_zotero.py` läuft durch
5. SSE-Log wird inline angezeigt; bei `__done__`: „Schließen"-Button + `loadProjectList()`

**Kein Wizard-Schritt wird durchlaufen** — der gesamte Ingest (Fetch → Segmente → Pipeline) läuft serverseitig in `ingest_zotero.py`.

### Zotero-Sync für bestehendes Projekt (Projekt-Karte)

- Karte hat Zotero-Button: wenn konfiguriert → zeigt „Aktualisieren ↻" + aufklappbare Konfig-Sektion
- „Aktualisieren ↻": `POST /api/projects/{id}/zotero/sync` (SSE) → SSE-Log in Karte
- Konfig bearbeiten: API-Key, User-ID, Collection, Dok-Typ → Testen + Speichern (`POST /api/projects/{id}/zotero/config`)

### Was `ingest_zotero.py` intern tut

```
1. pyzotero: Items der Collection laden
   Attachments und Notes auf oberster Ebene werden gefiltert
2. Checkpoint prüfen (zotero_checkpoint.json) — neue Items identifizieren,
   bereits verarbeitete Keys überspringen
3. Pro neuem Item: HTML-Snapshot → trafilatura-Volltext
   Fallback 1: URL direkt fetchen
   Fallback 2: Abstract (mit WARNING)
   Kein Text → Item überspringen
4. segments.json schreiben (doc_id = neue UUID)
   Jedes Segment trägt:
     "source"    → Titel des Artikels
     "date"      → Erscheinungsdatum aus Zotero-Metadaten (issued/date-Feld)
     "item_type" → Zotero-Typ, z.B. "newspaperArticle", "videoRecording"
     "url"       → Artikel-URL aus Zotero-Metadaten
5. Taxonomie prüfen: config.json["taxonomy"] leer?
   → propose_taxonomy.py vorschalten (--project, --document)
6. Pipeline:
     detect_anchors.py      (liest "date"-Feld im Presseartikel-Modus, D-P8)
     interpolate_anchors.py
     classify_segments.py
     match_entities.py
7. export_exploration.py (aggregiert alle Dokumente des Projekts)
   Jedes data.json-Entry enthält das url-Feld aus dem Segment (D-P10)
8. Checkpoint aktualisieren (verarbeitete Keys speichern)
```

**Entity-Extraktion läuft NICHT automatisch** — `extract_entities_v2.py` ist nicht
in der Zotero-Pipeline. Entities werden bei Bedarf über den Entity-Editor (Wizard
Schritt 6) oder manuell extrahiert:
```
python3 -m src.generalized.extract_entities_v2 --project … --document … --mode sample
```
Der NER-Backend-Switcher (D-E1) gilt: `doc_type=presseartikel` → spaCy-Backend,
das `item_type=="videoRecording"`-Segmente automatisch überspringt (D-E3).

**Unterschied zu Datei-Upload-Flow:**
- Kein Wizard-Schritt 2 (Dok-Typ kommt aus Zotero-Config)
- Kein Schritt 3 (parse_document.py entfällt — Segmente werden direkt gebaut)
- Kein Schritt 4–6 interaktiv — Taxonomie wird automatisch vorgeschlagen, Entities manuell
- Segmente haben `"date"`-Feld aus Zotero-Metadaten; `detect_anchors.py` liest es im Presseartikel-Modus direkt als Anker (D-P8)
