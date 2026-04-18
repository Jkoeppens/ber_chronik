# STATUS — Aktueller Stand des Projekts

Stand: 2026-04-13 | Branch: wip/wizard-pipeline-fixes | D-P1–D-P5 umgesetzt + E2E-verifiziert

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

Sampelt 50 Segmente in 5 Batches, lässt LLM je 4–6 Kategorien generieren, mergt zu 6–8 Endkategorien.

| | |
|---|---|
| **Input** | `documents/{doc_id}/segments.json` |
| **Output** | `documents/{doc_id}/taxonomy_proposal.json` |
| **LLM** | Ja (Claude Sonnet, parallel für Anthropic, sequenziell für Ollama) |
| **Auslöser** | Wizard Schritt 5 (Taxonomie-Button) → POST `/ingest/propose_taxonomy` |

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
| **Input** | `viz/data.json`, `viz/entities_seed.csv` (hardcodiert auf BER-Pfade, nicht auf `data/projects/…`) |
| **Output** | `viz/network_layout.json` |
| **LLM** | Nein |
| **Auslöser** | Manuell: `npm run precompute-network` |

---

## Bekannte Fallbacks und Workarounds

### ~~classify_segments.py — Kategorie-Normalisierung nur hier~~ ✓ behoben (D-P2)

normalize_category() läuft jetzt in allen drei Skripten.

### classify_segments.py — Resume mit alter Taxonomie

Beim Neustart werden bereits klassifizierte Segmente aus classified.json übersprungen (`--force` überschreibt das). Wenn die Taxonomie zwischenzeitlich geändert wurde, enthält classified.json danach Einträge aus zwei verschiedenen Taxonomien.

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

### network_layout.json — manuelle Regenerierung nötig

Das Layout wird nicht automatisch aktualisiert wenn sich Akteure ändern. `npm run precompute-network` muss manuell laufen. Vergisst man es, landen neue Knoten im Zufalls-Fallback.

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

### I4 — `precompute_network.js` liest BER-spezifische Pfade

Liest hardcodiert `viz/data.json` und `viz/entities_seed.csv`. Für andere Projekte muss man die Datei manuell anpassen oder Dateien kopieren. Nicht generisch verwendbar.

### ~~I5 — entities in config.json vs. Dokumentebene: kein Merge~~ ✓ behoben (D-P4)

Entity-Editor speichert in `config.json["entities"]`. match_entities und export_exploration lesen ausschließlich von dort. Doc-level Fallback entfernt.

### I6 — 7 deprecated Funktionen noch in entity_llm.py

`_llm_task2_validate_aliases`, `_llm_task3_clarify_types`, `_llm_extract_uncovered`, `_select_uncovered_stratified` und drei weitere sind als `# DEPRECATED` markiert aber nicht entfernt, zusammen mit den zugehörigen Prompt-Strings.

### I7 — `actors` wird nach Override nicht aktualisiert

Wenn ein Segment via overrides.json manuell datiert wird, läuft match_entities.py nicht automatisch neu. Das `actors`-Feld stammt aus dem letzten Lauf und kann veraltet sein.

### I8 — presseartikel-Logik verteilt über 3 Skripte

Sonderbehandlung liegt in parse_document.py (Parser-Modus), detect_anchors.py (kein Fließtext-Regex) und interpolate_anchors.py (Interpolation übersprungen). Kein zentraler Ort, der beschreibt was presseartikel-Dokumente anders machen.

### I9 — Link-Schwelle unterschiedlich in precompute vs. boot

`precompute_network.js` filtert Links mit `count >= 2`. `boot.js` lässt alle Links durch (`threshold = 1`). Das Layout wird für einen anderen Graphen vorberechnet als den, der in der Viz erscheint.

### I10 — Playwright-Tests testen nur BER-Projekt

`tests/viz.spec.js` öffnet hardcodiert `http://localhost:8765/` und setzt BER-Daten voraus. Keine Tests für andere Projekte oder für den Ingest-Wizard.

### I11 — `/taxonomy/propose` + `taxonomy_editor.html` ohne Auth ✓ behoben

`taxonomy_editor.html` rief alle drei Endpoints (`/taxonomy/data`, `/taxonomy/save`, `/taxonomy/propose`) ohne `project`, `document` oder Token auf. `/taxonomy/propose` übergab außerdem keine Args an `propose_taxonomy.py`. Behoben: Endpoint liest Query-Params; Editor nutzt `_aq()` + `_th()` analog zu `entity_editor.html`.

### I12 — `export_preview.py` D-P1-Fallback auf taxonomy_proposal.json ✓ behoben

Fehlte `config.json["taxonomy"]`, fiel `export_preview.py` auf die per-doc `taxonomy_proposal.json` zurück — statt mit Fehler abzubrechen. Behoben: Fallback entfernt, expliziter Fehler wenn Taxonomie fehlt (analog `classify_segments.py` und `export_exploration.py`).
