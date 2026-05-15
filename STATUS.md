# STATUS — Aktueller Stand des Projekts

Stand: 2026-05-15 | Branch: feature/flexible-timeline-bins | D-P1–D-P8 umgesetzt

---

## Pipeline-Schritte

### 1. `parse_document.py` — Dokument parsen

Liest eine DOCX-Datei und zerlegt sie in typisierte Segmente (heading, bibliography, content).

| | |
|---|---|
| **Input** | DOCX-Datei (Pfad aus CLI oder `documents/{doc_id}/config.json`) |
| **Output** | `documents/{doc_id}/segments.json` |
| **LLM** | Nein |
| **Auslöser** | Wizard Schritt 3 (Analyse-Button) → POST `/ingest/run` Schritt 1 |

---

### 2. `detect_anchors.py` — Zeitanker erkennen

Findet Jahreszahlen, Dekaden und benannte Ereignisse in Segmenten via Regex und Ereignisliste.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json` |
| **Output** | `documents/{doc_id}/anchors.json` |
| **LLM** | Nein |
| **Auslöser** | POST `/ingest/run` Schritt 2 |
| **Presseartikel-Sonderfall** | Liest `seg["date"]`-Feld als Anker wenn kein Heading-Jahr vorhanden (D-P8) |

---

### 3. `interpolate_anchors.py` — Lücken interpolieren

Füllt undatierte Segmente durch lineare Interpolation zwischen datierten Nachbarn.

| | |
|---|---|
| **Input** | `documents/{doc_id}/anchors.json`, optional `documents/{doc_id}/overrides.json` |
| **Output** | `documents/{doc_id}/anchors_interpolated.json` |
| **LLM** | Nein |
| **Auslöser** | POST `/ingest/run` Schritt 3 |

---

### 4. `propose_taxonomy.py` — Taxonomie vorschlagen

3-stufige Architektur: Keyword-Extraktion (Stufe 1) → Destillation per LLM (Stufe 2) → Schreiben (Stufe 3).
Bis zu 80 Segmente à max. 1000 Zeichen, Batches à 4 → Keywords → ein Destillations-Call → 6-8 Kategorien.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json` |
| **Output** | `projects/{project}/config.json["taxonomy"]` (direkt, kein taxonomy_proposal.json) |
| **LLM** | Ja (Claude Sonnet, Stufe 1 parallel für Anthropic, Stufe 2 ein Call) |
| **Auslöser** | Wizard Schritt 4 (KI-Vorschlag-Button) → POST `/ingest/propose_taxonomy`; automatisch in `ingest_zotero.py` wenn Taxonomie fehlt |

---

### 5. `classify_segments.py` — Segmente klassifizieren

Weist jedem content-Segment genau eine Kategorie + Konfidenz zu; resume-fähig.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json`, Taxonomie aus `projects/{project}/config.json` (Fallback: `taxonomy_proposal.json`) |
| **Output** | `documents/{doc_id}/classified.json` (Felder `category`, `confidence`) |
| **LLM** | Ja (Claude Haiku, bis 10 parallele Requests) |
| **Auslöser** | POST `/ingest/run` Schritt 4 |

---

### 6. `extract_entities_v2.py` — Entities extrahieren

4-stufige Pipeline: Sample → Vollextraktion mit Few-Shot → LLM-Dedup → Normalisierung.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json`, optional `entities_seed.json`, `entities_rejected.json` |
| **Output** | `documents/{doc_id}/entities_proposal.json`, Checkpoint in `_v2_checkpoint.json` |
| **LLM** | Ja (Claude Sonnet, alle 4 Stufen) |
| **Auslöser** | POST `/ingest/run` Schritt 5; oder manuell aus Entity-Editor |

---

### 7. `match_entities.py` — Entities in Segmente eintragen

Regex-Matching aller Entity-Aliases gegen Segment-Texte; schreibt `actors`-Felder in classified.json.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json`, `documents/{doc_id}/classified.json`, Entities aus `projects/{project}/config.json` (Fallback: `entities_seed.json`) |
| **Output** | `documents/{doc_id}/classified.json` (in-place, ergänzt `actors`-Felder) |
| **LLM** | Nein |
| **Auslöser** | POST `/ingest/run` Schritt 6 |

---

### 8. `export_preview.py` — Vorschau generieren

Erzeugt eine eigenständige HTML-Datei mit interaktiver Timeline, Filterbuttons und Inline-Editierformularen.

| | |
|---|---|
| **Input** | `documents/{doc_id}/anchors_interpolated.json`, `documents/{doc_id}/classified.json`, optional `overrides.json`, Taxonomie |
| **Output** | `documents/{doc_id}/preview.html` |
| **LLM** | Nein |
| **Auslöser** | POST `/ingest/run` Schritt 7; oder nach manueller Korrektur im Preview-Editor |

---

### 9. `export_exploration.py` — Exploration-Export

Merged alle Dokumente eines Projekts in den Visualization-Ordner.

| | |
|---|---|
| **Input** | Alle `documents/{doc_id}/anchors_interpolated.json` + `classified.json` im Projekt, `projects/{project}/config.json` |
| **Output** | `projects/{project}/exploration/data.json`, `entities_seed.csv`, `project_meta.json` |
| **LLM** | Nein |
| **Auslöser** | POST `/ingest/run` Schritt 8 (letzter Schritt) |

---

### 10. `precompute_network.js` — Netzwerk-Layout vorberechnen

Führt D3-Force-Simulation offline durch und speichert Knotenpositionen als `network_layout.json`.

| | |
|---|---|
| **Input** | `data/projects/{project}/exploration/data.json`, `data/projects/{project}/exploration/entities_seed.csv` |
| **Output** | `data/projects/{project}/exploration/network_layout.json` |
| **LLM** | Nein |
| **Auslöser** | Automatisch am Ende von `export_exploration.py` (via `subprocess.run`) |

---

## Neue Features (seit 2026-04-27)

### Version C — Projektorientierte Startseite
`/ingest` zeigt direkt die Projektliste statt Upload-Box. Erste Karte = „Neues Projekt +" mit Inline-Dialog (Datei-Tab + Zotero-Tab). Bestehende Projektkarten haben Zotero-Button mit SSE-Sync und aufklappbarer Konfig-Sektion.

### Inline Invite-Gate
`loadProjectList()` sendet `X-Invite-Token`-Header. Bei 401 erscheint ein Inline-Formular für den Einladungscode — kein Redirect auf `invite_gate.html`. Nach erfolgreichem Login: Cookie setzen + `loadProjectList()` erneut.

### Zotero-Ingest via UI
Neues Zotero-Projekt: Inline-Dialog in Schritt 1 → `POST /api/projects` → Zotero-Config speichern → SSE-Sync. Bestehende Projekte: „Aktualisieren ↻"-Button in der Projektkarte. `ingest_zotero.py` erkennt automatisch fehlende Taxonomie und schaltet `propose_taxonomy.py` vor.

### propose_taxonomy — 3-stufige Architektur
Stufe 1: Keywords pro Segment (kurze stabile Calls, parallelisierbar). Stufe 2: ein Destillations-Call (semantische Deduplizierung durch LLM). Ersetzt Batch-Merge-Ansatz (5×10-Segmente → Häufigkeitszählung).

### detect_anchors — date-Feld für Zotero-Segmente
Im Presseartikel-Modus: wenn kein Heading-Jahr aktiv, wird `seg["date"]` als Anker gesetzt (`precision="exact"`). Zotero-Metadaten-Datum (YYYY oder YYYY-MM-DD) landet damit direkt in `anchors.json`.

---

## Bekannte Fallbacks und Workarounds

### ~~classify_segments.py — Kategorie-Normalisierung nur hier~~ ✓ behoben (D-P2)

normalize_category() läuft jetzt in allen drei Skripten.

### classify_segments.py — Resume mit alter Taxonomie [MITTEL]

Beim Neustart werden bereits klassifizierte Segmente aus classified.json übersprungen (`--force` überschreibt das). Wenn die Taxonomie zwischenzeitlich geändert wurde, enthält classified.json danach Einträge aus zwei verschiedenen Taxonomien. `normalize_category` mappt alte Namen auf `"(unbekannt)"` ohne Warnung.

**Lösung (Backlog):** Beim Start einen Taxonomie-Hash berechnen und in `classified.json` als Metadaten-Feld speichern. Beim Resume: Hash vergleichen — abweichender Hash → Warnung + Auto-`--force`. (Quelle: REVIEW_15_05.md §1)

### ~~export_exploration.py — entities-Fallback auf Dokumentebene~~ ✓ behoben (D-P4)

Fallback entfernt. Einzige Quelle: `config.json["entities"]`.

### ~~export_exploration.py — Taxonomie-Fallback aus event_type-Werten~~ ✓ behoben (D-P1/D-P5)

Fallback entfernt. Fehlt Taxonomie in config.json → expliziter Fehler.

### export_exploration.py — segment_id-Präfix als Kollisionsvermeidung

Jede segment_id bekommt ein `{doc_id}-`-Präfix, weil der Parser segment_ids nur pro Dokument eindeutig vergibt. Workaround für fehlende globale IDs.

### interpolate_anchors.py — Presseartikel-Bypass ohne Warnung

Bei `doc_type=presseartikel` wird die gesamte Interpolation übersprungen. Kein Hinweis in der Ausgabe.

### interpolate_anchors.py — `_undatable`-Flag undokumentiert

Segmente mit `"action": "undatable"` in overrides.json bekommen ein internes `_undatable`-Flag in der Ausgabe. Das Flag wird von keinem nachgelagerten Skript erklärt.

### parse_document.py — Hardcodierte Organizer-Headings

`ORGANIZER_H1 = {"Notizen", "Übertrag von Zeitschriften"}` ist BER-spezifisch und nicht konfigurierbar. Für andere Projekte mit anderen Gliederungsüberschriften wird das falsch.

### entity_llm.py — Few-Shot-Limit auf 10 Seed-Entities

Nur die ersten 10 Entities aus `entities_seed.json` werden als Few-Shot-Beispiele ins Prompt gegeben. Projekte mit 60+ Seed-Entities verlieren den Großteil ihres Kontexts.

### entity_llm.py — Levenshtein selbst implementiert

Dedup-Erkennung nutzt eine eingebettete Levenshtein-Funktion statt einer Bibliothek. Für kurze Strings ausreichend, für längere Namen unzuverlässig.

### boot.js — Stille Fallbacks bei fehlenden Dateien

`entities_seed.csv`, `entities_summary.json`, `project_meta.json` werden mit `.catch(() => {})` geladen. Wenn sie fehlen: Entity-Highlighting fehlt, Knoten-Zusammenfassungen fehlen, Farbkarten fallen auf Hardcoded-Defaults zurück. Keine Fehlermeldung für den Nutzer.

### boot.js — node.typ-Fallback bei unbekannten Akteuren

Wenn ein Akteur nicht in der aliasMap ist, wird der Typ via `Object.keys(NODE_COLOR).find(k => /org/i.test(k))` bestimmt — erster Org-ähnlicher Schlüssel, dann erster Schlüssel überhaupt. Alle unbekannten Akteure bekommen dieselbe Farbe.

### network.js — Layout-Fallback bei fehlenden Knoten

Knoten die nicht in `network_layout.json` stehen, bekommen eine zufällige Position (80% der Canvas-Fläche). Bis April 2026 war der Fallback `(W/2, H/2)` — das führte zu einem Knotenhaufen im Zentrum der alle Playwright-Tests und die Viz brach.

### ~~network_layout.json — manuelle Regenerierung nötig~~ ✓ behoben

Das Layout wird automatisch am Ende jedes `export_exploration.py`-Laufs neu berechnet. Neue Knoten landen nicht mehr im Zufalls-Fallback, solange die Pipeline vollständig durchläuft.

---

## Offene Sicherheitsprobleme

### Token-Endpoint ohne Auth wenn ADMIN_KEY nicht gesetzt

`GET /api/projects/{id}/token` ist nur geschützt wenn `ADMIN_KEY` in `.env` gesetzt ist. Ohne
gesetzten Key gibt der Endpoint das Token ohne Auth zurück.
Vor öffentlicher Nutzung: `ADMIN_KEY=<secret>` in `.env` setzen.

---

## Offene Inkonsistenzen

### ~~I1 — Kategorie-Normalisierung fehlt in export-Skripten~~ ✓ behoben (D-P2)

`normalize_category()` läuft jetzt in classify_segments.py, export_preview.py und export_exploration.py.

### ~~I2 — Keine kanonische Taxonomiequelle~~ ✓ behoben (D-P1)

Einzige gültige Quelle: `config.json["taxonomy"]`. Fallback auf taxonomy_proposal.json (classify) und event_type-Ableitung (export_exploration) entfernt. Fehlt Taxonomie → expliziter Fehler.

### ~~I3 — classified.json wird von zwei Skripten unabhängig geschrieben~~ ✓ behoben (D-P3)

`/ingest/run/step` schaltet match_entities automatisch nach classify nach. Kein Mischzustand mehr möglich wenn classify über den Wizard läuft.

### ~~I4 — `precompute_network.js` liest BER-spezifische Pfade~~ ✓ behoben

Liest jetzt `data/projects/{project}/exploration/data.json` und schreibt `network_layout.json` in denselben Ordner. Wird via `--project`-Argument aus `export_exploration.py` aufgerufen — generisch verwendbar.

### ~~I5 — entities in config.json vs. Dokumentebene: kein Merge~~ ✓ behoben (D-P4)

Entity-Editor speichert in `config.json["entities"]`. match_entities und export_exploration lesen ausschließlich von dort. Doc-level Fallback entfernt.

### ~~I6 — 7 deprecated Funktionen noch in entity_llm.py~~ ✓ behoben

`_llm_task2_validate_aliases`, `_llm_task3_clarify_types`, `_llm_extract_uncovered`, `_select_uncovered_stratified` und weitere wurden entfernt. `entity_llm.py` enthält heute nur noch 8 aktiv genutzte Funktionen, alle importiert von `extract_entities_v2.py`.

### I7 — `actors` wird nach Override nicht aktualisiert

Wenn ein Segment via overrides.json manuell datiert wird, läuft match_entities.py nicht automatisch neu. Das `actors`-Feld stammt aus dem letzten Lauf und kann veraltet sein.

### I8 — presseartikel-Logik verteilt über 3 Skripte

Sonderbehandlung liegt in parse_document.py (Parser-Modus), detect_anchors.py (kein Fließtext-Regex) und interpolate_anchors.py (Interpolation übersprungen). Kein zentraler Ort, der beschreibt was presseartikel-Dokumente anders machen.

### ~~I9 — Link-Schwelle unterschiedlich in precompute vs. boot~~ ✓ behoben

Beide Dateien nutzen `LINK_MIN_COUNT = 2` mit gegenseitigem Kommentar-Verweis. Layout und Viz filtern identisch.

### I10 — Playwright-Tests testen nur BER-Projekt

`tests/viz.spec.js` öffnet hardcodiert `http://localhost:8765/` und setzt BER-Daten voraus. Keine Tests für andere Projekte oder für den Ingest-Wizard.

### I11 — `/taxonomy/propose` + `taxonomy_editor.html` ohne Auth ✓ behoben

`taxonomy_editor.html` rief alle drei Endpoints (`/taxonomy/data`, `/taxonomy/save`, `/taxonomy/propose`) ohne `project`, `document` oder Token auf. `/taxonomy/propose` übergab außerdem keine Args an `propose_taxonomy.py`. Behoben: Endpoint liest Query-Params; Editor nutzt `_aq()` + `_th()` analog zu `entity_editor.html`.

### I12 — `export_preview.py` D-P1-Fallback auf taxonomy_proposal.json ✓ behoben

Fehlte `config.json["taxonomy"]`, fiel `export_preview.py` auf die per-doc `taxonomy_proposal.json` zurück — statt mit Fehler abzubrechen. Behoben: Fallback entfernt, expliziter Fehler wenn Taxonomie fehlt (analog `classify_segments.py` und `export_exploration.py`).

### I13 — `saveTimeConfig()` fire-and-forget ohne Error-Feedback [MITTEL]

`saveTimeConfig()` in `ingest_wizard.html` (Z. 1329) feuert `fetch(...)` ohne `await` und ohne `.catch()`. Wenn der Server nicht erreichbar ist oder kurz unterbrochen wird, verliert der Nutzer seine Zeitkonfigurationsänderungen still — keine UI-Rückmeldung, keine Konsolen-Warnung.

**Lösung (Backlog):** Mindestens `.catch(e => console.warn('saveTimeConfig:', e))` ergänzen. Besser: `async/await` + UI-Feedback analog zum `tax-status`-Element ("⚠ Nicht gespeichert"). (Quelle: REVIEW_15_05.md §3)

### I14 — Segment-Schema nicht in ARCHITECTURE.md dokumentiert [GERING]

Die Felder eines Segments (`segment_id`, `type`, `text`, `source`, `time_from`, `time_to`, `precision`, `anchors`, `actors`, `category`, `confidence`, `is_geicke`, `doc_type`, …) sind in keinem Dokument beschrieben. Wer verstehen will, welche Felder wann gesetzt sind und von welchem Skript, muss den Quellcode lesen.

**Lösung (Backlog):** Segment-Schema-Tabelle in ARCHITECTURE.md ergänzen — welche Felder von welchem Skript gesetzt werden und was ihre möglichen Werte sind.

### I15 — data.json-Format nicht in ARCHITECTURE.md dokumentiert [GERING]

`exploration/data.json` ist die zentrale Schnittstelle zwischen Pipeline und Visualisierung, aber ihr Schema ist nirgends beschrieben. `boot.js` und `panel.js` lesen `entries`, `taxonomy`, `entities`, `year_min`/`year_max` daraus — wer den Explorer debuggen will, muss beide Seiten im Kopf haben.

**Lösung (Backlog):** data.json-Toplevel-Felder und Entry-Schema in ARCHITECTURE.md dokumentieren, idealerweise mit Verweis auf `export_exploration.py:build_entries()` als autoritative Quelle.

---

## Audit-Befunde (2026-04-30)

### Kritisch (Deployment-Blocker)

- **`POST /ingest/analyze` — Path Traversal** (`dev_server.py:381`)
  Kein `_require_token`-Check. `project` wird nur slugifiziert wenn `project_name` im Body vorhanden — bei direktem `project`-Feld keine Sanitierung. `doc_id` ebenfalls unvalidiert. `get_doc_dir(project, doc_id)` baut Pfad direkt aus User-Input; `mkdir(parents=True)` + Datei-Schreiboperationen folgen. Angreifer mit Invite-Token kann Dateien außerhalb von `PROJECTS_DIR` anlegen.

### Mittel

- **`doc_id` unvalidiert in mehreren Endpoints** (`dev_server.py:241, 791, 821`)
  `POST /overrides`, `POST /ingest/classified/update`, `GET /ingest/segments/data`: `_require_token` prüft `project` gegen DB (impliziter Traversal-Schutz), aber `doc_id` wird nicht validiert. Valides `project` + `doc_id = "../../other_project/documents/main"` ermöglicht Lese-/Schreibzugriff auf fremde Dokumente.

- **`entity_spacy.py:83` — alle spaCy-Fehler geschluckt**
  `except Exception as exc: print(...); continue` pro Segment. Wenn spaCy für alle Segmente versagt, gibt `extract_with_spacy()` eine leere Entity-Liste zurück ohne `sys.exit`. `ingest_zotero.py:210` macht dagegen `sys.exit(1)` — inkonsistentes Fehlerverhalten im selben Pipeline-Pfad.

- **`CAT_PALETTE` zweifach mit verschiedenen Farben definiert**
  `export_preview.py:31` → `["#0891b2", "#d97706", "#16a34a", ...]`
  `export_exploration.py:42` → `["#3b82f6", "#f59e0b", "#10b981", ...]`
  Gleiche Kategorie trägt in `preview.html` und Viz-Explorer unterschiedliche Farben.

- **`db.list_all_projects()` und `db.update_status()` — dead code**
  `db.py:116`: importiert als `db_list_all_projects` in `dev_server.py:42`, aber in keinem Endpoint aufgerufen.
  `db.py:137`: `update_status()` nur definiert, nirgends aufgerufen.

### Niedrig

- **`"date"` vs `"date_raw"` — Feldnamen inkonsistent**
  `ingest_zotero.py:152` schreibt `"date"` in Segmente. `export_exploration.py:91` liest `seg.get("date_raw")` — gibt für Zotero-Segmente immer `None` zurück; Fallback `str(tf)` verliert Tag-Genauigkeit.

- **`is_geicke` BER-Feld im generalisierten Code**
  `export_exploration.py:118, 182`: `"is_geicke"` in `build_entries()` und `REQUIRED_FIELDS`. Alle Nicht-BER-Projekte emittieren `"is_geicke": false` in `data.json`.

- **Config-Lesen ohne Helper** — 12 Stellen
  `json.loads(path.read_text(encoding="utf-8"))` ohne gemeinsamen Wrapper:
  `dev_server.py:274, 330, 350, 717, 744` — `extract_entities_v2.py:86, 99` — `export_preview.py:498, 517` — `export_exploration.py:249` — `propose_taxonomy.py:224` — `parse_document.py:210`

- **`classify_segments.py:100` — silent fallback zu `category: None`**
  Nach 2 fehlgeschlagenen LLM-Parses: `return {**segment, "category": None, "confidence": "low"}` ohne Warning oder Zähler im Output.

- **`entity_utils.py:9` — `VALID_TYPES` als `set` statt `frozenset`**
  Mutable, wird nie modifiziert — kein Laufzeitproblem, aber falsches Signal.
