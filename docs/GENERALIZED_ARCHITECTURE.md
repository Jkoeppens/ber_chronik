# Generalized Ingest System — Architektur

Das generalisierte Ingest-System verarbeitet beliebige historische DOCX-Dokumente zu interaktiv explorier­baren Zeitreihen. Es richtet sich an Forschende, die Quelltexte (Forschungsnotizen, Presseartikel, Chroniken) ohne Programmieraufwand aufbereiten wollen.

---

## Gesamtübersicht

```
DOCX-Datei
     │
     ▼
  upload  ──────────────────────────────── data/raw/{filename}
     │
     ▼
parse_document.py ─────────────────────── segments.json
     │
     ├─── propose_taxonomy.py ──────────── taxonomy_proposal.json
     │
     ▼
detect_anchors.py ─────────────────────── anchors.json
     │
     ▼
interpolate_anchors.py ─────────────────── anchors_interpolated.json
     │
     ├─── extract_entities_v2.py ────────── entities_proposal.json
     │         │
     │         ▼  (Entity-Editor + Merge)
     │    entities_seed.json
     │
     ▼
classify_segments.py ──────────────────── classified.json
     │
     ▼
match_entities.py ─────────────────────── classified.json  (+actors-Feld)
     │
     ├─── export_preview.py ─────────────── preview.html
     │
     ▼
export_exploration.py ──────────────────── exploration/data.json
                                            exploration/entities_seed.csv
                                            exploration/project_meta.json
                                                   │
                                                   ▼
                                            viz/index.html  (Browser-App)
```

---

## Dateistruktur

```
data/
  raw/
    {filename}.docx                 Hochgeladene Rohdokumente

  projects/
    projects.db                     SQLite – Projekt-Metadaten + Tokens

    {project_id}/
      config.json                   Projektebene: title, year_min/max, taxonomy, entities
      exploration/
        data.json                   → viz/boot.js (alle Einträge)
        entities_seed.csv           → viz/boot.js (Alias-Tabelle für Highlighting)
        project_meta.json           → viz/boot.js (Farben, Kategorienamen)

      documents/
        {doc_id}/
          config.json               Dokumentebene: doc_type, original_filename, ingested_at
          segments.json             Alle Absätze nach parse_document.py
          taxonomy_proposal.json    LLM-Kategorienvorschlag (pro Dokument, Fallback)
          anchors.json              Segmente + erkannte Zeitanker
          anchors_interpolated.json Segmente + interpolierte Zeitspannen + Overrides
          overrides.json            Manuelle Korrekturen (aus preview.html heruntergeladen)
          classified.json           Segmente + LLM-Kategorie + actors-Feld
          entities_proposal.json    Extrahierte Entity-Kandidaten
          entities_seed.json        Bestätigte Entities (manuell im Editor kuratiert)
          entities_merged.json      Merge aus seed + proposal + _status-Feldern
          entities_rejected.json    Abgelehnte Entities (dauerhaft ausgeschlossen)
          _v2_checkpoint.json       Resume-Checkpoint für extract_entities_v2 --mode full

  interim/
    generalized/
      project_config.json           Pointer auf aktuelles Projekt + Dokument
```

---

## Pipeline-Schritte

### Schritt 1 — parse_document.py
**Input:** DOCX-Datei
**Output:** `segments.json`

Wandelt DOCX-Absätze in strukturierte Segmente um. Zwei Modi:

| Modus | Aktivierung | Verhalten |
|---|---|---|
| `buchnotizen` | Default | 3 Ebenen (meta/bibliography/content), Seitenzahlen, Quellen-Headings |
| `presseartikel` | `--doc-type presseartikel` | Flach; reine Jahres-Überschriften → type `heading`, rest → `content` |

Jedes Segment hat: `segment_id`, `type`, `text`, `source`, `page`, `doc_type`.

### Schritt 2 — propose_taxonomy.py
**Input:** `segments.json`
**Output:** `taxonomy_proposal.json`

Zieht 20 zufällige content-Segmente (≥80 Zeichen) und schickt sie an Claude Sonnet. Das LLM erkennt selbst das Thema und schlägt 6–8 Kategorien vor (name, description, keywords).

### Schritt 3 — detect_anchors.py
**Input:** `segments.json`
**Output:** `anchors.json`

Erkennt Zeitanker in content-Segmenten:

| Anker-Typ | Beispiel | Präzision |
|---|---|---|
| `exact` | Jahreszahl 1600–2029, nicht in Klammern | `exact` |
| `decade` | „1900er", „19. Jahrhundert" | `decade` |
| `event` | „Tanzimat", „Jungtürkenrevolution" | `event` |
| `heading` | Jahres-Überschrift vererbt an folgende Segmente | `heading` |

Lebensdaten `(1842–1898)` und Publikationsjahre `(1923)` werden vor der Erkennung entfernt.

Im `presseartikel`-Modus: nur Heading-Jahre, kein Fließtext-Regex.

### Schritt 4 — interpolate_anchors.py
**Input:** `anchors.json`, optional `overrides.json`
**Output:** `anchors_interpolated.json`

Datiert undatierte Segmente innerhalb derselben Quelle:

1. Segment zwischen zwei datierten → `time_from`/`time_to` aufspannen, `precision = interpolated`
2. Segment nach dem letzten Anker → letzten Anker vorwärts erben
3. Segment vor dem ersten Anker einer Quelle → bleibt undatiert
4. Quelle ohne jeden Anker → alle bleiben undatiert

Overrides (`set_anchor`, `undatable`) haben höchste Priorität. `decade`-Anker zählen nicht als Interpolationspunkt.

### Schritt 5 — classify_segments.py
**Input:** `segments.json`, Taxonomie aus `config.json` (Fallback: `taxonomy_proposal.json`)
**Output:** `classified.json`

Klassifiziert jeden content-Segment in genau eine Taxonomie-Kategorie. Resume-fähig: bereits klassifizierte Segmente werden übersprungen. Bei JSON-Fehler: ein Retry, dann `category=null, confidence=low`.

Parallelität: `max_concurrency` aus LLMProvider (Anthropic: 10, Ollama: 1).

### Schritt 6 — extract_entities_v2.py
**Input:** `segments.json`, optional `entities_seed.json`
**Output:** `entities_proposal.json`

Entity-Erkennung in zwei Modi (`--mode sample` / `--mode full`). Details → Abschnitt „Entity-Recognition-Architektur".

### Schritt 7 — match_entities.py
**Input:** `segments.json`, `classified.json`, Entities aus `config.json` (Fallback: `entities_seed.json`)
**Output:** `classified.json` (in-place, ergänzt `actors`-Feld)

Sucht alle Aliases aller Entities per Wortgrenz-Regex (`(?<!\w)…(?!\w)`, case-insensitive) in jedem content-Segment.

### Schritt 8 — export_preview.py
**Input:** `anchors_interpolated.json`, optional `overrides.json`, `classified.json`
**Output:** `preview.html`

Standalone-HTML mit vertikaler Zeitleiste und Korrektur-Loop. Kein Server nötig. Korrekturen werden als `overrides.json` heruntergeladen.

### Schritt 9 — export_exploration.py
**Input:** alle `anchors_interpolated.json` + `classified.json` aller Dokumente, `config.json`
**Output:** `exploration/data.json`, `exploration/entities_seed.csv`, `exploration/project_meta.json`

Merged alle Dokumente eines Projekts. Segment-IDs werden mit `{doc_id}-` präfixiert (Kollisionsvermeidung). Exportiert Farbzuweisungen für Kategorien und Entity-Typen.

---

## Skripte in src/generalized/

| Skript | Aufgabe | Input | Output |
|---|---|---|---|
| `parse_document.py` | DOCX → Segmente | DOCX-Datei | `segments.json` |
| `propose_taxonomy.py` | LLM-Taxonomievorschlag | `segments.json` | `taxonomy_proposal.json` |
| `detect_anchors.py` | Zeitanker erkennen | `segments.json` | `anchors.json` |
| `interpolate_anchors.py` | Undatierte Segmente interpolieren | `anchors.json` | `anchors_interpolated.json` |
| `classify_segments.py` | Segmente klassifizieren | `segments.json` + Taxonomie | `classified.json` |
| `extract_entities_v2.py` | Entity-Erkennung | `segments.json` + optional Seed | `entities_proposal.json` |
| `match_entities.py` | Entity-Matching per Regex | `segments.json` + `classified.json` + Entities | `classified.json` (+actors) |
| `export_preview.py` | HTML-Korrekturvorschau | `anchors_interpolated.json` + `classified.json` | `preview.html` |
| `export_exploration.py` | Exploration-Export | alle Doc-Outputs + `config.json` | `exploration/` |
| `llm.py` | LLM-Provider-Abstraktion | — | Provider-Objekt |
| `db.py` | SQLite-Persistenz | — | CRUD für Projekte + Tokens |
| `dev_server.py` | FastAPI-Entwicklungsserver | — | HTTP/SSE-Endpoints |

Nicht mehr im Einsatz (noch vorhanden):
- `detect_entities.py` — ältere Entity-Erkennung (ohne Classifier)
- `propose_entities.py` — älteres Vorschlagsverfahren
- `extract_entities.py` — Vorgänger von v2
- `migrate_db.py` — einmalige DB-Migration
- `convert_ber.py` — BER-spezifische Konversion

---

## Dev-Server Endpoints

Server starten:
```bash
uvicorn src.generalized.dev_server:app --port 8001 --reload
```

### Token-Anforderung

Endpoints mit `🔒` erwarten ein gültiges Token — entweder als Query-Parameter `?token=…` oder als HTTP-Header `X-Project-Token`. Token werden bei `POST /ingest/save_config` erzeugt (30 Tage TTL).

| Method | Endpoint | Token | Beschreibung |
|---|---|---|---|
| GET | `/ingest` | — | Ingest-Wizard HTML |
| POST | `/ingest/upload` | — | DOCX-Datei nach `data/raw/` speichern |
| POST | `/ingest/analyze` | — | parse_document + LLM-Analyse (Zeitraum, Sprache, Ereignisse) |
| POST | `/ingest/save_config` | — | project/doc config.json schreiben, Projekt in DB anlegen, Token zurückgeben |
| POST | `/ingest/propose_taxonomy` | 🔒 | propose_taxonomy.py als SSE |
| POST | `/ingest/run` | 🔒 | Vollständige Pipeline (parse → detect → interpolate → classify → match → export) als SSE |
| POST | `/ingest/extract_entities` | 🔒 | extract_entities_v2 `--mode sample` + Merge als SSE |
| POST | `/ingest/extract_entities_full` | 🔒 | extract_entities_v2 `--mode full` + Merge als SSE |
| GET | `/ingest/entities/data` | 🔒 | entities_merged.json / entities_seed.json / entities_proposal.json |
| POST | `/ingest/entities/save` | 🔒 | entities_seed.json schreiben (interne Felder `_*` werden entfernt) |
| POST | `/ingest/entities/merge` | 🔒 | seed + proposal → entities_merged.json |
| POST | `/ingest/entities/reject` | 🔒 | Entity zu entities_rejected.json hinzufügen |
| GET | `/ingest/entities` | — | Entity-Editor HTML (`?token=` als Query-Parameter) |
| GET | `/ingest/segments/data` | 🔒 | segments.json zurückgeben |
| POST | `/overrides` | 🔒 | overrides.json speichern |
| POST | `/recompute` | 🔒 | interpolate_anchors + export_preview als SSE |
| GET | `/preview` | — | preview.html ausliefern |
| GET | `/taxonomy` | — | Taxonomy-Editor HTML |
| GET | `/taxonomy/data` | — | taxonomy_proposal.json |
| POST | `/taxonomy/save` | — | Taxonomie speichern |
| POST | `/taxonomy/propose` | — | propose_taxonomy.py als SSE |
| GET | `/editor` | — | Projekt-Übersichtsseite |
| GET | `/api/projects` | — | Alle Projekte aus DB (mit entry_count) |
| GET | `/api/projects/{id}/token` | — | Token eines Projekts |
| PUT | `/api/projects/{id}` | — | Projekt-Metadaten aktualisieren |
| DELETE | `/api/projects/{id}` | — | Projekt aus DB löschen |

SSE-Endpoints senden Zeilen als `data: …\n\n`, abgeschlossen mit `data: __done__\n\n` oder `data: __error__ …\n\n`.

---

## LLM-Provider-Abstraktion

`src/generalized/llm.py` definiert eine einheitliche Schnittstelle:

```python
provider = get_provider()          # liest LLM_PROVIDER aus .env
text = provider.complete(prompt, system="…")
data = provider.complete_json(prompt, system="…")   # parst JSON automatisch
```

| Provider | Klasse | Default-Modell | `max_concurrency` |
|---|---|---|---|
| `ollama` | `OllamaProvider` | `llama3.1:8b` (aus `OLLAMA_MODEL`) | 1 |
| `anthropic` | `AnthropicProvider` | `claude-haiku-4-5-20251001` | 10 |

Konfiguration in `.env`:
```
LLM_PROVIDER=ollama          # oder: anthropic
ANTHROPIC_API_KEY=sk-...     # nur für anthropic
OLLAMA_MODEL=llama3.1:8b     # optionaler Override
```

`complete_json` extrahiert das erste vollständige JSON-Objekt oder -Array aus der Antwort: entfernt Code-Fences, überspringt führende Prosa, verwendet `json.JSONDecoder.raw_decode`.

---

## Entity-Recognition-Architektur

### Pipeline-Pfad-Wahl (in `main()`)

```
kein Seed vorhanden          →  Pfad "iter1"  (LLM-Stichprobe)
Seed ≥ 20 Person + ≥ 20 Ort  →  Pfad "classifier"  (mBERT + LogReg)
sonst                         →  Pfad "cosine"  (SBERT + DBSCAN)
```

### Iteration 1 — kein Seed

50 zufällige content-Segmente, Batches à 10. Das LLM extrahiert direkt Eigennamen mit Typ, Normalform und Aliases. Output → `entities_proposal.json`.

### Classifier-Loop — Stufen A/B/2b/C

**Stufe A — Kandidaten-Extraktion:**

- **Classifier-Pfad:** `bert-base-multilingual-cased` (mBERT) erzeugt per-Wort-Embeddings via `word_ids()` (Fast-Tokenizer, Subword-Pooling). Ein `LogisticRegression`-Classifier (Konfidenz-Schwelle 0.6) klassifiziert Tokens. Konsekutive gleichartige Tokens → Span. Person-Spans mit einem Connector-Wort (≤4 Zeichen Kleinschrift, z.B. „al", „von", „de") dazwischen → zusammengeführt.
- **Cosine-Pfad:** `paraphrase-multilingual-mpnet-base-v2` (SBERT) bettet alle großgeschriebenen Tokens ein. DBSCAN (eps=0.18, min_samples=2) clustert sie. Cosine-Similarity gegen Seed-Typ-Zentren (Schwelle 0.60) filtert Kandidaten.

**Stufe B — LLM-Bereinigung:**

| Stufe | Aufgabe | Kandidaten | Batch |
|---|---|---|---|
| B1 | Normalform + Typ für alle Kandidaten | alle | 20 |
| B2 | Alias-Validierung | Kandidaten mit ≥2 Aliases | pro Kandidat |
| B3 | Typ klären | Kandidaten mit Konfidenz < 0.6 | pro Kandidat |

**Stufe 2b — Segmente ohne Treffer:**
Stratifizierte Auswahl uncovered Segmente (max. 30 im sample-Modus, alle im full-Modus). Typen unter 90% des Seed-Anteils → bevorzugt. Scoring nach Alias-Treffern. Das LLM extrahiert neu aus diesen Segmenten.

**Stufe C — Merge:**
`_merge()` kombiniert alle Kandidaten aus allen Stufen alias-basiert (lowercase-Overlap). `SOURCE_PRIORITY` entscheidet bei Konflikten: seed > llm > classifier/embedding.

**Checkpoint** (`_v2_checkpoint.json`): speichert erledigten Stufen, damit `--mode full` bei Unterbrechung resume-fähig ist.
