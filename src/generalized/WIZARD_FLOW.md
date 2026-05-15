# Wizard Flow — Referenz

Stand: 2026-05-15 | Branch: fix/review-15-05

---

## Die drei Quellentypen im Wizard-Ablauf

Das Verhalten des Wizards hängt direkt vom Quellentyp ab. Wer das nicht weiß,
versteht weder den Schritt-2-Unterschied noch warum Step 3 beim Obsidian-Pfad
komplett anders aussieht.

| Schritt | Literaturexzerpt (`buchnotizen`) | Pressezusammenfassung (`presseartikel`/DOCX) | Pressesammlung (`presseartikel`/Obsidian) |
|---|---|---|---|
| **Schritt 1** | Datei-Upload im Dialog | Datei-Upload im Dialog | Obsidian-Tab im Dialog oder Karte öffnen |
| **Schritt 2** | **übersprungen** (doc_type im Dialog) | **übersprungen** (doc_type im Dialog) | **angezeigt** (nur Pressesammlung sichtbar, auto-ausgewählt) |
| **Schritt 3** | `POST /ingest/analyze` (LLM-Analyse) | `POST /ingest/analyze` (LLM-Analyse) | `POST /obsidian/sync` (SSE-Stream aus Dropbox) |
| **Schritt 4** | Taxonomie — normal | Taxonomie — normal | Taxonomie — normal |
| **Schritt 5** | Anker-Pipeline läuft voll | Anker-Pipeline läuft voll | detect+interpolate laufen, tun faktisch Bypass |
| **Schritt 6** | Entities — normal | Entities — normal | Entities — normal |
| **Schritt 7** | Pipeline ohne parse (Segs schon da) | Pipeline ohne parse | Pipeline ohne parse und detect/interpolate |

---

## Schritt-für-Schritt

### Schritt 1 — Projektliste

**Trigger:** Seitenload. Zeigt Projektliste statt Upload-Box.

**Was passiert:**
- `loadProjectList()` → `GET /api/projects` (mit `X-Invite-Token`-Header)
  - Bei 401: Inline Invite-Code-Formular (kein Redirect auf invite_gate.html)
  - Bei Erfolg: Projekt-Karten werden gerendert
- Erste Karte immer: **„Neues Projekt +"** — öffnet inline Dialog

**Dialog „Neues Projekt +" — Datei-Pfad (Literaturexzerpt / Pressezusammenfassung):**
- Projektname-Input + Datei-Drop + Dok-Typ-Selector
- Klick „Analysieren →":
  1. `POST /ingest/upload`
  2. Setzt `state.project_title`, `state.doc_type`, `state.files`
  3. `gotoStep(3)` — **Schritt 2 wird übersprungen**, doc_type kommt aus dem Dialog

**Dialog „Neues Projekt +" — Obsidian-Tab (Pressesammlung):**
- Dropbox-Auth-Button + Ordner-Input (oder Ordner-Picker)
- Klick „Importieren →":
  1. `POST /api/projects` → legt Projekt in DB an, gibt `token` zurück
  2. Setzt `state.project`, `state.obsidian_source = 'dropbox'`, `state.isExistingProject = true`
  3. `gotoStep(2)` — **Schritt 2 wird angezeigt**, automatisch Pressesammlung vorausgewählt

**Bestehende Projekt-Karte öffnen:**
- „Dokument hinzufügen" → Datei-Upload-Flow → `gotoStep(3)`
- Karte mit Obsidian-Konfiguration → setzt `state.obsidian_source = 'dropbox'` → `gotoStep(2)`
- Karte mit vorhandenen Dokumenten → `maxReachedStep = 7` → `gotoStep(6)`

**Kein regulärer „Weiter"-Button auf Schritt 1** — Navigation über Karten-Buttons.

---

### Schritt 2 — Dokumenttyp

**Wann angezeigt:** Nur im Obsidian-Pfad (neu oder bestehend ohne Dokument).
Im DOCX-Datei-Pfad wird dieser Schritt übersprungen.

**Was passiert:**
- `onEnterStep(2)`: Wenn `state.obsidian_source === 'dropbox'` → nur Pressesammlung-Karte
  sichtbar, automatisch ausgewählt; Literaturexzerpt und Presseexzerpt ausgeblendet
- Schreibt `state.doc_type = 'presseartikel'`
- Kein API-Call beim Betreten — reine UI

**Weiter-Button:**
- Im Obsidian-Pfad: `POST /api/projects/{id}/obsidian/config` mit `{doc_type, dropbox_folder}`
- Dann `gotoStep(3)`

---

### Schritt 3 — Analyse oder Obsidian-Import

**Zwei komplett verschiedene Pfade:**

#### DOCX-Pfad (Literaturexzerpt / Pressezusammenfassung)

**Neues Projekt:**
1. `POST /ingest/analyze` → `parse_document.py` + LLM-Analyse → JSON
2. Response setzt: `state.project`, `state.document`, `state.analysis`, `state.time_config`
3. Sofort danach: `POST /ingest/save_config` mit `title`, `doc_type`, `time_config`
   - Server schreibt `projects/{project}/config.json` + `documents/{doc_id}/config.json`
   - Legt Projekt in DB an, gibt `token` zurück → `state.token`

**Bestehendes Projekt (Restore via URL):**
1. `GET /ingest/doc_status` — prüft ob `segments.json` vorhanden
2. Wenn ja: `gotoStep(4)` (kein neuer Analyse-Lauf)
3. Wenn nein: Analyse wie oben

**Dateien geschrieben:** `data/raw/{filename}`, `segments.json`

#### Obsidian-Pfad (Pressesammlung)

Die Schrittüberschrift wechselt auf „Obsidian-Import".

1. `runObsidianSync()` startet automatisch bei `onEnterStep(3)` (nur einmal, `syncRan`-Flag)
2. `POST /api/projects/{id}/obsidian/sync` → SSE-Stream
   - Dropbox-Verbindung, .md-Dateien listen, Segmente bauen
   - `detect_anchors.py` + `interpolate_anchors.py` laufen serverseitig
   - Output-Log wird im Wizard angezeigt
3. Bei `__done__`: `loadProjectDocuments()` + `gotoStep(4)`

Der Analyse-Output (year_min/max, Taxonomie-Vorschlag) den der DOCX-Pfad liefert
existiert im Obsidian-Pfad nicht — `state.analysis` und `state.time_config` werden
nicht aus dem Sync befüllt. Schritt 5 zeigt daher Standardwerte.

**Dateien geschrieben:** `documents/{doc_id}/segments.json`, `anchors.json`,
`anchors_interpolated.json`

---

### Schritt 4 — Taxonomie

**onEnterStep(4):** `initTaxonomy()` → `GET /taxonomy/data?project=&document=&token=`
- Server liest `config.json["taxonomy"]`
- Setzt `taxData` (globale Variable) + rendert Grid
- `taxDirty = false`

**Aktionen:**
- „+ Kategorie": `taxData.push(...)`, `markTaxDirty()`
- **„Themen vorschlagen" / „Taxonomie verfeinern ↻"** (Button-Label dynamisch):
  - Leer → „Themen vorschlagen"; vorhanden → „Taxonomie verfeinern ↻"
  - `POST /ingest/propose_taxonomy?method=bge` → `propose_taxonomy.py` via BGE-M3 (D-T1)
  - SSE-Stream → danach `initTaxonomy()` + `markTaxDirty()`
- „Speichern": `POST /taxonomy/save` → schreibt `config.json["taxonomy"]` + `taxDirty = false`
- „Neu klassifizieren": `POST /ingest/run/step` mit `{step: 'classify_segments.py', force: true, method: 'bge'}`

**Weiter-Button:**
- Ruft `saveTaxonomy()` (wenn `taxDirty`)
- Dann: `gotoStep(state.isExistingProject ? 6 : 5)`
  - **Neues Projekt → Schritt 5** (Zeitkonfiguration)
  - **Bestehendes Projekt → Schritt 6** (Entities, Schritt 5 übersprungen)

**Dateien geschrieben:** `config.json["taxonomy"]`

---

### Schritt 5 — Zeitkonfiguration

**onEnterStep(5):** `initTimeConfig()` liest aus `state.time_config` (beim DOCX-Analyse-Schritt befüllt;
beim Obsidian-Pfad Standardwerte). Lädt Preview-iframe wenn `anchors_interpolated.json` vorhanden.

**Aktionen:**
- Jahr-Inputs + Ereignis-Editor: mutieren `state.time_config` inline
- `saveTimeConfig()` (bei jeder Änderung): `POST /ingest/save_config` mit `time_config`
  → schreibt `year_min`, `year_max`, `events` in `config.json`

**Weiter-Button → `runAnchorPipeline()`:**
1. `POST /ingest/run/step` → `detect_anchors.py` (SSE)
2. `POST /ingest/run/step` → `interpolate_anchors.py` (SSE)
3. Wenn Taxonomie vorhanden: `POST /ingest/run/step` → `export_preview.py` (SSE)
4. Lädt Preview-iframe: `/preview?project=&document=&token=`
5. Bei Erfolg: `gotoStep(6)`

**Für Obsidian-Pressesammlung:** `detect_anchors.py` und `interpolate_anchors.py` laufen
technisch, tun aber faktisch nichts — Segmente sind bereits datiert (Bypass-Regel für
`presseartikel` in `interpolate_anchors.py`).

**Dateien geschrieben:** `anchors.json`, `anchors_interpolated.json`, `preview.html`

---

### Schritt 6 — Entities

**onEnterStep(6):** `initEntities()` → setzt `src` des iframes auf
`/ingest/entities?project=&document=&token=`

Der iframe lädt `entity_editor.html` als eigenständige Seite mit eigenen Fetch-Calls:
- `GET /ingest/entities/data` → liest ausschließlich `config.json["entities"]` (D-P4)
- `POST /ingest/entities/save` → schreibt `config.json["entities"]`
- `POST /ingest/entities/reject` → schreibt `entities_rejected.json` (Filter für nächsten Extraction-Run)
- `POST /ingest/entities/extract` (SSE) → `extract_entities_v2.py` → schreibt direkt in `config.json["entities"]`
- `GET /ingest/entities/near-duplicates` → Embedding-basierte Duplikat-Vorschläge

**Keine `entities_proposal.json` mehr.** D-P4: `config.json["entities"]` ist einzige
kanonische Quelle — kein Fallback-Layer zwischen Extraktion und Editor.

**Weiter-Button:** `gotoStep(7)` — kein API-Call.

---

### Schritt 7 — Pipeline

**Beim Klick auf „Pipeline starten":**
1. `POST /ingest/save_config` mit `title`, `doc_type`, `time_config`
   - `taxonomy: taxData` **nur wenn `taxData.length > 0`** — verhindert Überschreiben
2. `POST /ingest/run` (SSE) → **konditionelle Pipeline:**

```
Wenn segments.json fehlt:       parse_document.py
Wenn anchors_interp. fehlt:     detect_anchors.py
                                interpolate_anchors.py
Immer:                          classify_segments.py
                                match_entities.py
Wenn anchors_interp. fehlt:     export_preview.py
Immer (letzter Schritt):        export_exploration.py
```

Die Bedingungen spiegeln die Wizard-Geschichte wider: Segmente und Anker wurden
in früheren Schritten bereits gebaut. In Schritt 7 klassifiziert und exportiert
das System üblicherweise neu, ohne erneut zu parsen oder zu datieren.

3. Am Ende: SSE sendet `__link__:/viz/?project=...` → Viz-Link erscheint

**`extract_entities_v2.py` läuft nicht automatisch in `POST /ingest/run`.** Entity-Extraktion
ist ausschließlich aus Schritt 6 aufrufbar.

**Einzelne Schritte wiederholen:** Über die Rerun-Buttons neben jedem Schritt-Status
→ `POST /ingest/run/step` mit `{step: 'script.py'}`.

**Dateien geschrieben:** alle Pipeline-Outputs, final `exploration/data.json`

---

## State-Variablen (JS, global)

| Variable | Typ | Gesetzt wann | Gelesen wann |
|---|---|---|---|
| `state.project` | string | Analyse-Response, `openExistingProject`, `restoreFromUrl` | Alle API-Calls via `_aq()` |
| `state.document` | string | Analyse-Response, `openExistingProject`, `restoreFromUrl` | Alle API-Calls via `_aq()` |
| `state.token` | string | `save_config`-Response, Token-Fetch, `restoreFromUrl` | `authHeaders()`, `_aq()` |
| `state.project_title` | string | Schritt-1-Dialog, `restoreFromUrl` | Schritt-1-Anzeige, `save_config` |
| `state.doc_type` | string | Schritt-1-Dialog oder Schritt-2-Auswahl, `restoreFromUrl` | `save_config`, Analyse |
| `state.analysis` | object | Analyse-Response (nur DOCX-Pfad) | Schritt-3-Anzeige, `save_config` |
| `state.time_config` | object | Analyse-Response (DOCX) oder Standardwerte (Obsidian), `restoreFromUrl` | Schritt 5, `saveTimeConfig`, Pipeline-`save_config` |
| `state.isExistingProject` | bool | `restoreFromUrl` → `true`; Schritt-1-Dialog Datei-Pfad → `false` | Schritt-3-Logik, Schritt-4-Weiter (→5 oder →6) |
| `state.obsidian_source` | string\|null | Obsidian-Flow → `'dropbox'`; Datei-Flow → `null` | Schritt-2-UI, Schritt-3-Routing, btnNext-Logik |
| `state.obsidian_folder` | string | Obsidian-Dialog + `restoreFromUrl` | `POST /obsidian/config` |
| `taxData` | array | `initTaxonomy()`, `restoreFromUrl`, Inline-Edits | Schritt-4-Grid, `saveTaxonomy()`, Pipeline-`save_config` |
| `taxDirty` | bool | `markTaxDirty()` → `true`; `initTaxonomy()`, `saveTaxonomy()` → `false` | Weiter-Button Schritt 4 |
| `syncRan` | bool | Nach erstem `runObsidianSync()` → `true`; `onEnterStep(1)` → `false` | Verhindert doppelten Sync in Schritt 3 |
| `currentStep` | int | `gotoStep(n)` | Navigation, URL-Schreiben |
| `maxReachedStep` | int | `updateProgress(n)`, `restoreFromUrl` | Dot-Klick-Guard |
| `analysisRan` | bool | nach erstem `runAnalysis()` → `true` | Schritt-3-Guard gegen Doppelstart |
| `evNextId` | int | Inkrementiert bei jedem neuen Ereignis | Ereignis-IDs |

---

## Kritische Abhängigkeiten

```
Schritt 3 (DOCX)   benötigt:  state.files (Upload), state.project_title
                               → schreibt state.project, state.document, state.token

Schritt 3 (Obsidian) benötigt: state.project, state.token (bereits aus Schritt 1)
                               → schreibt segments.json + anchors direkt

Schritt 4          benötigt:  state.project, state.token (für /taxonomy/data)
                               → ohne token: 401, taxData bleibt []

Schritt 5          benötigt:  segments.json (aus Schritt 3)
                               → runAnchorPipeline schlägt fehl ohne segments

Schritt 6          benötigt:  state.project, state.token (iframe-src)
                               → ohne token: iframe zeigt Fehler

Schritt 7          benötigt:  config.json["taxonomy"] nicht leer
                               → classify_segments.py bricht ab mit "Keine Taxonomie"
                               → Taxonomie muss in Schritt 4 gespeichert worden sein

Pipeline classify   benötigt: segments.json, config.json["taxonomy"]
Pipeline match_ent. benötigt: classified.json, config.json["entities"]
Pipeline export_prev benötigt: anchors_interpolated.json, classified.json, config.json["taxonomy"]
Pipeline export_expl benötigt: alle obigen
```

---

## Dateien und ihre Rollen

### `projects/{project}/config.json`

**Kanonische Quelle für:** `taxonomy`, `entities`, `year_min/max`, `events`, `title`, `obsidian.*`

| Feld | Geschrieben von | Darf überschrieben werden |
|---|---|---|
| `taxonomy` | `/taxonomy/save`, `propose_taxonomy.py`, `/ingest/save_config` (nur wenn `taxData.length > 0`) | Nur durch explizites Speichern in Schritt 4 — nie mit leerem Array |
| `entities` | `/ingest/entities/save`, `extract_entities_v2.py` | Bei jedem Editor-Save oder Extraction-Run |
| `year_min/max/events` | `/ingest/save_config` via `time_config` | Bei jeder Zeitconfig-Änderung |
| `obsidian.*` | `/api/projects/{id}/obsidian/config` | Bei jedem Obsidian-Config-Save |
| `title` | `/ingest/save_config`, `PUT /api/projects/{id}` | Unkritisch |

**Gelesen von:** `classify_segments.py`, `match_entities.py`, `export_preview.py`,
`export_exploration.py`, `/taxonomy/data`, `/ingest/entities/data`, `restoreFromUrl`
via `/api/projects/{id}`

### `documents/{doc_id}/entities_rejected.json`

**Zweck:** Filter für nächsten Extraction-Run

**Geschrieben von:** `/ingest/entities/reject`

**Gelesen von:** `extract_entities_v2.py` (beim nächsten Run als `rejected_lc`)

### `documents/{doc_id}/segments.json`

Geschrieben von `parse_document.py` (DOCX) oder `ingest_obsidian.py` (Obsidian).
Eingabe für alle nachgelagerten Schritte.

### `documents/{doc_id}/anchors.json` / `anchors_interpolated.json`

Geschrieben von `detect_anchors.py` / `interpolate_anchors.py`.
Bei Obsidian: beide Dateien entstehen, aber `anchors_interpolated.json` enthält
dieselben Zeitanker wie `anchors.json` (kein Interpolationsbedarf).

### `documents/{doc_id}/classified.json`

Geschrieben von `classify_segments.py` (category + confidence) und
`match_entities.py` (actors, in-place). Eingabe für beide Export-Skripte.

---

## URL-State (Reload-Persistenz)

`gotoStep(n)` schreibt bei jedem Schritt-Wechsel:
```
?project={state.project}&document={state.document}&step={n}
```

Beim Laden liest `restoreFromUrl()` diese Parameter:
1. `GET /api/projects/{id}/token` → `state.token`
2. `GET /api/projects/{id}` → `state.project_title`, `state.doc_type`, `state.time_config`,
   `taxData` (wenn `cfg.taxonomy.length > 0`), `state.obsidian_source` (wenn `cfg.obsidian.dropbox_folder`)
3. `gotoStep(step)` → springt direkt zum gespeicherten Schritt

**Token ist nie in der URL** — wird immer neu geholt.

---

## Entfernte Features

### Zotero-Flow (deaktiviert seit 2026-05-12)

Der Zotero-Flow erlaubte einen direkten API-Ingest ohne Wizard-Schritte. Endpoints:
`/api/projects/_new/zotero/test`, `/api/projects/{id}/zotero/config`,
`/api/projects/{id}/zotero/sync`. **Diese Endpoints existieren nicht mehr in `dev_server.py`.**

`ingest_zotero.py` liegt noch im Dateisystem, wird aber von keiner Stelle aufgerufen.
Vollständige historische Dokumentation des Flows: `ARCHITECTURE.md` (Abschnitt „Entfernte Features").
