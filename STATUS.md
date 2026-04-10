# STATUS.md — Systemzustand (Stand: 2026-04-10)

## Aktives Modell

| Konfiguration              | Wert            |
|----------------------------|-----------------|
| LLM_PROVIDER               | ollama          |
| OLLAMA_MODEL               | llama3.2:3b     |
| Task-spezifische Overrides | — (alle auskommentiert) |

Alle Pipeline-Schritte verwenden derzeit `llama3.2:3b`.

---

## Pipeline-Schritte und Implementierungsstand

### Vollständig implementiert (Proposal → Feedback → Run)

| Schritt           | Propose                          | Editor/Feedback        | Run                            |
|-------------------|----------------------------------|------------------------|--------------------------------|
| Taxonomy          | `taxonomy/propose` (POST)        | Wizard Step 4 (UI)     | `taxonomy/save` + `ingest/run` |
| Entity-Extraktion | `extract_entities_v2.py` (manuell) | Entity-Editor (Wizard Step 5) | Re-Run manuell        |

### Nur Run, kein Review-Loop in der Wizard-UI

| Schritt                | Endpunkt              | Anmerkung                          |
|------------------------|-----------------------|------------------------------------|
| Anchor-Detection       | Teil von `ingest/run` | Kein eigener Proposal-Step         |
| Interpolation          | Teil von `ingest/run` | Kein eigener Proposal-Step         |
| Segment-Klassifikation | Teil von `ingest/run` | Kein eigener Proposal-Step         |
| Entity-Matching        | Teil von `ingest/run` | Matching läuft, keine Merge-UI     |

### `ingest/run` Schrittreihenfolge (tatsächlich im Code)

1. parse → 2. detect_anchors → 3. interpolate → 4. classify_segments →
5. match_entities → 6. export_preview → 7. export_exploration

Entity-Extraktion ist **nicht Teil von `ingest/run`** — sie muss manuell via Wizard Step 6 oder CLI ausgeführt werden.

---

## Entity-Pipeline (4 LLM-Schritte)

`extract_entities_v2.py` → `entity_llm.py`

| Schritt | Funktion                | Modus        |
|---------|-------------------------|--------------|
| 1       | `_llm_sample_iteration` | immer        |
| 2       | `_llm_full_extract`     | full + Seed  |
| 3       | `_llm_dedup`            | immer        |
| 4       | `_llm_task1_normalize`  | immer        |

Checkpoint/Resume: Schritt 2 hat Sub-Batch-Resume; alle anderen Schritte über `_run_stage`.

---

## Deprecated / Dead Code

### Dateien — vorhanden, aber nicht mehr importiert

| Datei                                  | Status                                           |
|----------------------------------------|--------------------------------------------------|
| `src/generalized/entity_classifier.py` | Nicht importiert von `extract_entities_v2.py` — dead code |
| `src/generalized/entity_cosine.py`     | Nicht importiert von `extract_entities_v2.py` — dead code |

### Funktionen in `entity_llm.py` — markiert als `# DEPRECATED`

- `_llm_task2_validate_aliases`
- `_llm_task3_clarify_types` *(enthält noch Import von `entity_classifier` in Funktionskörper — kein Runtime-Problem solange nicht aufgerufen)*
- `_select_uncovered_stratified`
- `_llm_extract_uncovered`

### Konstanten in `entity_llm.py` — markiert als `# DEPRECATED`

- `SEGMENT_BATCH`, `SAMPLE_UNCOVERED`, `ALIAS_VALIDATE_PROMPT`, `CLARIFY_TYPE_PROMPT`

---

## Abweichungen zwischen Dokumentation und Code

| Dokument                           | Was steht drin                                    | Was der Code macht                                          |
|------------------------------------|---------------------------------------------------|-------------------------------------------------------------|
| `docs/GENERALIZED_ARCHITECTURE.md` | Drei-Pfad Entity-Pipeline: iter1 / classifier / cosine | Nur 4-Schritt LLM-Pipeline, kein classifier/cosine    |
| `docs/GENERALIZED_DECISIONS.md`    | Begründung für mBERT+LogReg und SBERT+DBSCAN      | Beide Ansätze aus Produktionspipeline entfernt              |
| `dev_server.py` Header-Docstring   | Listet alte Endpunkte auf                         | Fehlt: `/ingest/entities/merge`, `/api/projects`, `/api/projects/{id}` |
| `docs/INGEST_WORKFLOW.md`          | Entity-Extraktion als Teil des Wizard-Flows       | Separater manueller Step, nicht in `ingest/run`             |

---

## Offene Punkte

- `entity_classifier.py` und `entity_cosine.py` können gelöscht werden, sobald sicher ist, dass kein anderer Code sie importiert
- Task-spezifische Modell-Overrides (`.env`) sind vorbereitet aber nicht aktiv — falls unterschiedliche Modelle pro Schritt gewünscht werden
- `taxonomy/propose` übergibt kein `project`/`document` Argument an das Propose-Script — nutzt globalen State-Fallback; sollte wie alle anderen Endpoints auf Request-Parameter umgestellt werden
- Entity-Extraktion läuft nicht automatisch in `ingest/run` — Entscheidung offen: automatisch integrieren oder manueller Schritt mit eigenem Wizard-Button (aktuell: manuell via Wizard Step 6)

---

## Priorisierte Baustellen

1. ~~**Preview-Editor in Wizard integrieren**~~ — erledigt: Button „Zeitanker bearbeiten →" in Step 7 nach Pipeline-Run + im `/editor`-Header unter „Daten bearbeiten".
2. ~~**Taxonomie-Stichprobe erhöhen**~~ — erledigt: `N_SAMPLES = 50` in `propose_taxonomy.py`.
3. ~~**Dead code löschen**~~ — erledigt: `entity_classifier.py`, `entity_cosine.py` gelöscht; `src/berchronik/` existiert nicht (bereits entfernt).
4. ~~**`taxonomy/propose` Parameter-Fix**~~ — kein Fix nötig: Wizard schickt `_aq()` mit, globaler Fallback wird nie aktiv. Muster ist konsistent mit allen anderen Endpoints.
5. ~~**Entity-Extraktion in `ingest/run`**~~ — Entscheidung: bleibt manueller Wizard-Schritt (Schritt 6). Passt zu Vorschlag→Feedback→Run Prinzip aus VISION.md.
6. **Periodisierungs-Editor fehlt im Wizard** — `overrides.json` + `interpolate_anchors.py` sind implementiert, aber der Editor (preview.html mit Bearbeiten-Buttons) ist nur über `/preview` erreichbar, nicht als integrierter Wizard-Schritt. Screenshot zeigt wie es aussehen sollte.
7. ~~**Taxonomie-Vorschlag: kein Fortschrittsindikator**~~ — erledigt: Batches à 10 Segmente mit SSE-Fortschritt, gemma4:e4b Fallback-Fix in llm.py, Prompts auf Deutsch + genau 3 Keywords.
8. ~~**Kein Wizard-Einstieg für bestehende Projekte**~~ — erledigt: Projektliste in Schritt 1, Klick setzt State und springt zu Schritt 6. `/api/projects/{id}/token` gibt jetzt auch `doc_id` zurück.
9. **Exploration-Link hardcoded auf `localhost:8765`** — `dev_server.py:555` sendet `__link__:http://localhost:8765/viz/…` via SSE; `ingest_wizard.html:930` hat denselben Fallback-Link hardcoded. Bricht sobald der Viz-Server auf einem anderen Port läuft.
10. **`GET /api/projects/{id}/token` ohne Auth** — Kommentar im Code: `# TODO: Schütze diesen Endpoint`. Gibt das Projekt-Token ohne Authentifizierung zurück. Unkritisch solange Server nur lokal läuft.
11. **Schritt 3 (Einlesen) startet Pipeline neu** — wenn Nutzer zurück zu Schritt 3 navigiert, wird das Analyse-Skript neu gestartet und bricht ab. Navigation zwischen Wizard-Schritten darf keine Pipeline-Schritte neu triggern.
12. **Zeitperiode wird vergessen** — `state.year_min` und `state.year_max` gehen verloren, auch innerhalb einer Session. Werden in Schritt 3 gesetzt aber irgendwo überschrieben oder nicht persistiert.
