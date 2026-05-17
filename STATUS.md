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

### Flexible Timeline-Bins (2026-05-17, Branch feature/flexible-timeline-bins, 3b26da66)

`viz/boot.js`: Zeitachsen-Domain kommt jetzt primär aus `meta.year_min`/`year_max` (via `project_meta.json`, befüllt aus `config.json`), nicht mehr aus den Rohdaten-Extremwerten. Vier Granularitätsstufen anstatt drei:

| Zeitspanne | Bins |
|---|---|
| ≤ 50 Tage | täglich (`d3.timeDay`) |
| 51–350 Tage | wöchentlich (`d3.timeWeek`) — neu |
| 351–1500 Tage | monatlich (`d3.timeMonth`) |
| > 1500 Tage | jährlich (`d3.timeYear`) |

`viz/chart.js`: `_fmtBinDate` und `getContiguousSegments` um `d3.timeWeek`-Fall ergänzt. BER (1989–2017, ~10 200 Tage) greift weiterhin auf jährliche Bins.

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

### ~~Token-Endpoint ohne Auth wenn ADMIN_KEY nicht gesetzt~~ ✓ behoben (2026-05-15, f41b766d)

`_require_admin_key` auf `GET /api/projects/{id}/token` ergänzt. Ohne Key: offen (Dev-Betrieb). Mit Key: geschützt.

### ~~`/ingest/save_config` ohne Token-Prüfung~~ ✓ behoben (2026-05-15, c0308946)

Wenn das Projekt bereits in der DB existiert, wird jetzt `_require_token` aufgerufen. Erste Neuanlage (kein Token vorhanden) bleibt ohne Check — ist korrekt, da beim ersten Call noch kein Token existiert.

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

### ~~I7 — `actors` wird nach Override nicht aktualisiert~~ ✓ behoben (2026-05-15, 8ff17283)

`POST /overrides` speichert overrides.json und startet danach direkt `recompute_sse` als SSE-Stream. preview.js konsumiert den Stream identisch zu btnRecompute.

### ~~I8 — presseartikel-Logik verteilt über 3 Skripte~~ ✓ behoben (2026-05-15)

`utils.is_presseartikel(doc_dir)` zentralisiert den Typ-Check. detect_anchors.py und interpolate_anchors.py nutzen ihn. parse_document.py: direkter Vergleich (doc_type kommt vom CLI-Arg, vor config.json). DECISIONS.md D-I4.

### ~~I9 — Link-Schwelle unterschiedlich in precompute vs. boot~~ ✓ behoben

Beide Dateien nutzen `LINK_MIN_COUNT = 2` mit gegenseitigem Kommentar-Verweis. Layout und Viz filtern identisch.

### ~~I10 — Playwright-Tests testen nur BER-Projekt~~ ✓ behoben (2026-05-16, Branch test/api-coverage, 349f0336)

`tests/api_coverage.spec.js` ergänzt mit drei API-Tests: B (doc_status year_min/year_max aus geseedeten anchors), C (Taxonomy + Entity save/load Roundtrip), D (ingest/run ohne Eingabe → __error__ ohne __link__). `tests/ingest.spec.js`: is_geicke-Referenz entfernt (Feld in Fix 2 gelöscht).

### I11 — `/taxonomy/propose` + `taxonomy_editor.html` ohne Auth ✓ behoben

`taxonomy_editor.html` rief alle drei Endpoints (`/taxonomy/data`, `/taxonomy/save`, `/taxonomy/propose`) ohne `project`, `document` oder Token auf. `/taxonomy/propose` übergab außerdem keine Args an `propose_taxonomy.py`. Behoben: Endpoint liest Query-Params; Editor nutzt `_aq()` + `_th()` analog zu `entity_editor.html`.

### I12 — `export_preview.py` D-P1-Fallback auf taxonomy_proposal.json ✓ behoben

Fehlte `config.json["taxonomy"]`, fiel `export_preview.py` auf die per-doc `taxonomy_proposal.json` zurück — statt mit Fehler abzubrechen. Behoben: Fallback entfernt, expliziter Fehler wenn Taxonomie fehlt (analog `classify_segments.py` und `export_exploration.py`).

### ~~I13 — `saveTimeConfig()` fire-and-forget ohne Error-Feedback~~ ✓ behoben (2026-05-15, 034fe408)

`.catch(e => console.warn(...))` ergänzt — Netzwerkfehler erscheinen im Devtools-Log.

### ~~I14 — Segment-Schema nicht in ARCHITECTURE.md dokumentiert~~ ✓ behoben (2026-05-16)

Tabelle „Segment-Schema" in ARCHITECTURE.md ergänzt: alle Felder, welches Skript sie setzt, mögliche Werte und wann ein Feld fehlen kann.

### ~~I15 — data.json-Format nicht in ARCHITECTURE.md dokumentiert~~ ✓ behoben (2026-05-16)

Abschnitt „data.json-Schema" in ARCHITECTURE.md ergänzt: Toplevel-Felder, vollständiges Entry-Schema mit Typen, Verweis auf `export_exploration.py:build_entries()` als autoritative Quelle. Auch `project_meta.json`-Struktur dokumentiert.

### ~~I16 — `export_exploration.py` mutiert config.json als Seiteneffekt~~ ✓ behoben (2026-05-15, e5e9b494)

Liest config.json jetzt direkt vor dem Schreiben frisch von Disk, damit kein veralteter Stand aus dem Skript-Start überschrieben wird.

### ~~I17 — Race Condition auf config.json: 4 Endpoints ohne Lock~~ ✓ behoben (2026-05-15, ca27c5d0)

`save_taxonomy`, `save_entities`, `save_obsidian_config`, `ingest_save_config` haben alle `async with _project_lock(project):`.

### ~~I18 — `classified.json` nicht atomar geschrieben~~ ✓ behoben (2026-05-15, a7da8926)

`match_entities.py` und `classify_segments.py` nutzen jetzt `write_atomic()` aus `utils.py`.

### I19 — `taxData` — unkontrollierte Mutation an 7+ Stellen [MITTEL]

`taxData` ist ein Modul-globales Array das direkt mutiert wird (`push`, `splice`, `taxData[idx].name = ...`). Nach einem KI-Vorschlag setzt `_runProposeTaxonomy` erst `taxData` (via `initTaxonomy()`) und dann sofort `taxDirty = true`. Wenn der Nutzer in diesem Moment navigiert, triggert `gotoStep` ein `saveTaxonomy()` bevor `taxDirty` zurückgesetzt ist — Doppel-Save möglich.

**Lösung (Backlog):** `taxData` und `taxDirty` in ein State-Objekt zusammenführen mit definierten Setter-Funktionen. (Quelle: REVIEW_15_05.md §3)

### ~~I20 — `console.log` Debug-Statement in Produktionscode~~ ✓ behoben (2026-05-15, 513a1f8c)

`console.log` in `renderEventsList()` entfernt.

### ~~I21 — Stille `catch (_) {}` an operativen Stellen~~ ✓ behoben (2026-05-16, 0b2c1f84)

`console.error` in allen drei Stellen ergänzt; bei preview- und classify-SSE-Fehlern zusätzlich Fehlertext im logEl.

### ~~I22 — Pipeline-Teilfehler: Viz-Link trotz fehlgeschlagenem Export~~ ✓ behoben (2026-05-15, b549bf12)

`exploration_ok`-Flag: `__link__` nur bei Erfolg, sonst SSE-Warnung. `__done__` kommt immer.

### I23 — `_obsidian_oauth_states` in-memory: verliert State bei Hot-Reload [GERING]

`_obsidian_oauth_states` ist ein Modul-globales Dict. `uvicorn --reload` triggert einen Modul-Reload bei Quelldatei-Änderungen — alle laufenden OAuth-Flows werden ungültig. Betrifft nur Entwicklung, nicht Produktion.

**Lösung:** OAuth-State in einer temporären Datei oder SQLite-Tabelle persistieren. Kurzfristig: `--reload-exclude dev_server.py` in Entwicklungsanleitung dokumentieren. (Quelle: REVIEW_15_05.md §2)

### I24 — DB und Filesystem können divergieren [GERING]

`create_project` in SQLite und das Anlegen von `config.json` auf dem Filesystem sind zwei separate Operationen ohne gemeinsame Transaktion. Bei Serverabsturz zwischen beiden Operationen existiert das Verzeichnis ohne DB-Eintrag (oder umgekehrt). `list_projects_endpoint` zeigt das Projekt danach nicht, das Verzeichnis bleibt.

**Lösung (Backlog):** Reconcile-Schritt beim Serverstart — Projekte in DB aber nicht im FS als `orphan` markieren. Kein Auto-Delete. (Quelle: REVIEW_15_05.md §4)

### I25 — `export_preview.py` wird bei Taxonomie-Update nicht neu generiert [Hinweis]

`ingest_run` schaltet `export_preview.py` nur dann ein, wenn `has_anchors` zuvor `false` war (Z. 624–625). Wenn Anchors bereits existieren und die Pipeline neu läuft (z.B. nach Taxonomie-Änderung in Schritt 4), bleibt `preview.html` veraltet. Designentscheidung oder Lücke — nirgends dokumentiert. (Quelle: REVIEW_15_05.md §5)

---

### I26 — `generate_entity_summaries` läuft beim Obsidian-Sync immer vollständig neu [MITTEL]

`export_exploration.py` ruft `build_summaries()` für alle Entities neu auf, jedes Mal wenn der Obsidian-Sync läuft. Das ist bei größeren Entity-Listen teuer (LLM-Calls pro Entity) und ignoriert bereits generierte Summaries.

Soll-Verhalten:
- Summaries nur generieren wenn das Feature beim letzten Export aktiv war (kein `--no-summaries`)
- Bei Aktualisierung: nur Entities neu zusammenfassen, die in neu ingested Segmenten vorkommen
- Bestehende Summary als Kontext mitgeben: „hier alte Zusammenfassung, ergänze um neue Informationen"

Aktuell kein Workaround — `--no-summaries`-Flag ist vorhanden und kann manuell gesetzt werden, wird beim Sync aber nicht durchgereicht.

---

### I27 — Embedding-Provider-Abstraktion [BACKLOG]

Analog zu `get_provider()` für LLMs. Aktuell drei unabhängige Modell-Ladestellen ohne gemeinsame Abstraktion.

Lokal:
- MiniLM (`paraphrase-multilingual-MiniLM-L12-v2`) für Entity-Clustering
- BGE-M3 (`BAAI/bge-m3`) für Taxonomie-Vorschlag und Klassifizierung

API-Alternative (für Deployment ohne lokale Modelle):
- Voyage-4 via `voyageai` SDK, `VOYAGE_API_KEY` bereits in `.env` vorhanden
- Threshold für Entity-Clustering: ~0.78 statt 0.82 (MiniLM-Wert)

Vergleichsergebnis (2026-05-17): MiniLM beste Qualität für kurze Entity-Strings; BGE-M3 ungeeignet für Entity-Clustering; Voyage-4 funktioniert mit angepasstem Threshold.

---

## Audit-Befunde (2026-04-30)

### Kritisch (Deployment-Blocker)

- ~~**`POST /ingest/analyze` — Path Traversal**~~ ✓ behoben (2026-05-15)
  Fix A (e2ebf665): `project` immer durch `_slugify`, egal ob `project_name` oder `project` kommt.
  Fix B (bb8dfcf5): `doc_id` via `validate_doc_id()` — nur `[0-9a-f]{8}` oder `main` akzeptiert.

### Mittel

- ~~**`doc_id` unvalidiert in mehreren Endpoints**~~ ✓ behoben (2026-05-15, bb8dfcf5)
  `validate_doc_id()` auf 7 Endpoints: `/overrides`, `/ingest/analyze`, `/ingest/save_config`, `/ingest/run`, `/ingest/extract_entities`, `/ingest/entities/reject`, `/ingest/doc_status`.

- ~~**`entity_spacy.py:83` — alle spaCy-Fehler geschluckt**~~ ✓ behoben (2026-05-15, aa8659d4)
  `RuntimeError` wenn `raw_entities` leer und `content_segs` nicht leer — statt stiller leerer Rückgabe.

- ~~**`CAT_PALETTE` zweifach mit verschiedenen Farben definiert**~~ ✓ behoben (2026-05-15, d58ebd69)
  `export_preview.py` auf kanonische Palette aus `export_exploration.py` vereinheitlicht.

- ~~**`db.list_all_projects()` und `db.update_status()` — dead code**~~ ✓ behoben (2026-05-15, 701f1a89)
  Beide Funktionen und der Import in `dev_server.py` entfernt.

### Niedrig

- ~~**`"date"` vs `"date_raw"` — Feldnamen inkonsistent**~~ ✓ behoben (2026-05-15, 150fc424)
  `export_exploration.py`: `seg.get("date_raw") or seg.get("date")` — Obsidian/Zotero-Tagesdaten nicht mehr verloren.

- ~~**`is_geicke` BER-Feld im generalisierten Code**~~ ✓ behoben (2026-05-15, 2a7b55eb)
  Aus `parse_document.py`, `export_exploration.py` (emit + REQUIRED_FIELDS) entfernt.

- ~~**Config-Lesen ohne Helper**~~ ✓ behoben (2026-05-15, 87676925)
  17 nackte `json.loads()`-Aufrufe in 5 Skripten auf `read_json_safe()` umgestellt.

- ~~**`classify_segments.py:104` — silent fallback zu `category: None`**~~ ✓ behoben (2026-05-15, 0ff5d3ba)
  `confidence` im Fallback auf `None` gesetzt — Resume versucht fehlgeschlagene Segmente erneut.

- ~~**`entity_utils.py:9` — `VALID_TYPES` als `set` statt `frozenset`**~~ ✓ behoben (2026-05-15, 9f4660c6)

---

## Railway Deployment

Analysiert 2026-05-17. Noch kein Fix implementiert.

### BLOCKER

#### R1 — BGE-M3 (~2,5 GB) im Container ✓ behoben (2026-05-17)

~~`BGEProvider` lädt `BAAI/bge-m3` lazy beim ersten Request.~~ Auf Railway wird `EMBEDDING_PROVIDER=voyage` gesetzt (`railway.toml [variables]`) — BGE-M3 wird nie geladen. MiniLM (120 MB) bleibt für Entity-Clustering lokal.

**Hinweis:** `classify_segments.py --method bge` funktioniert auf Railway nicht (BGE-M3 fehlt). Der Default-Pfad (`--method llm`) ist unberührt. Der `bge`-Pfad ist ausschließlich für lokale Experimente vorgesehen.

#### R2 — `data/` + `projects.db` ephemeral ✓ behoben (2026-05-17)

~~Railway-Container haben kein persistentes Filesystem.~~ Gelöst via Railway Volume:

- `railway.toml`: `volumeMounts = [{ mountPath = "/data", name = "ber-data" }]`
- `DATA_ROOT=/data` als Variable gesetzt
- Volume `ber-data` muss einmalig manuell im Railway-Dashboard angelegt werden (siehe Deployment-Anleitung)

Alle Schreibpfade (`projects.db`, `config.json`, `dropbox_tokens.json`, Pipeline-Outputs) landen auf dem Volume und überleben Restarts.

#### R3 — `LLM_PROVIDER=ollama` als Default — Connection refused auf Railway

`get_provider()` in `llm.py` defaultet auf `ollama` wenn `LLM_PROVIDER` nicht gesetzt. Ollama läuft nicht auf Railway → erster LLM-Call gibt `RuntimeError: Ollama nicht erreichbar (http://localhost:11434)`. Betrifft alle Pipeline-Schritte die LLM nutzen (Klassifizierung, Entity-Extraktion, Taxonomie-Vorschlag, Summaries).

#### R4 — `railway.toml` und `Dockerfile` starten verschiedene Apps

`railway.toml` startet `src.api_server:app` (leichte Chat-Only-API, kein Wizard).
`Dockerfile` startet `src.generalized.dev_server:app` (vollständiger Wizard-Server).
Railway nutzt bei Nixpacks-Build `railway.toml` — `Dockerfile` wird ignoriert. Der Wizard ist damit auf Railway nie erreichbar.

---

### HOCH

#### R5 — Node.js fehlt für `precompute_network.js`

`export_exploration.py` ruft `node src/precompute_network.js` via `subprocess.run` auf. Node.js ist weder im `Dockerfile` noch in `railway.toml` (`requirements-api.txt`) als Dependency deklariert. Das Netzwerk-Layout wird stumm übersprungen oder wirft einen Fehler.

#### R6 — `PORT`-Env-Var wird ignoriert in `dev_server.py`

Railway setzt `PORT` automatisch und erwartet, dass der Server darauf hört. `dev_server.py` hat keinen `PORT`-Env-Var-Support — `uvicorn` würde hardcoded auf 8001 starten. Der Healthcheck schlägt fehl, Railway sieht den Service als nicht bereit.

#### R9 — Dropbox OAuth nicht Multi-User-fähig [HOCH]

`dropbox_tokens.json` speichert alle OAuth-Token in einer einzigen globalen Datei ohne Nutzer- oder Projekt-Trennung. Bei mehreren Nutzern oder Projekten überschreiben die OAuth-Callbacks sich gegenseitig — der zuletzt authentifizierte Nutzer gewinnt, alle anderen verlieren den Sync-Zugang.

Was für echte Multi-User-Nutzung fehlt:
1. `/api/obsidian/oauth/start` muss `project_id` empfangen und im OAuth-State mitführen
2. `_obsidian_oauth_states` muss `project_id` speichern, damit der Callback weiß wohin
3. Callback schreibt Token in `config.json["obsidian"]["tokens"]` des jeweiligen Projekts (statt globale `dropbox_tokens.json`)
4. `_obsidian_oauth_states` muss persistent sein (SQLite, I23) — bei Restart gehen laufende OAuth-Flows verloren

**Lösung:** OAuth-State um `project_id` erweitern. Token-Speicherung pro Projekt in `config.json`. Bestehende `DROPBOX_TOKENS_PATH`-Referenzen in `dev_server.py` und `ingest_obsidian.py` auf projekt-lokale Pfade umstellen.

#### R10 — `DROPBOX_REDIRECT_URL` auf Railway nicht konfiguriert [HOCH]

`ingest_obsidian.py:55–58` liest `DROPBOX_REDIRECT_URL` aus `os.environ`, Default: `http://localhost:8001/api/obsidian/oauth/callback`. Auf Railway ist die URL `https://{service}.railway.app/api/obsidian/oauth/callback`. Dropbox lehnt den OAuth-Flow ab wenn `redirect_uri` nicht mit dem in der Dropbox-App registrierten Wert übereinstimmt — der Callback erhält keinen `code`, `flow.finish()` schlägt fehl, der Wizard zeigt einen JSON-Parse-Fehler.

`DROPBOX_APP_KEY`/`SECRET` werden korrekt aus Railway-Env-Vars gelesen (via `os.environ.get()` nach `load_dotenv()`).

**Lösung:** `DROPBOX_REDIRECT_URL=https://{service}.railway.app/api/obsidian/oauth/callback` als Railway-Variable setzen. Zusätzlich diese URL in der Dropbox-App-Konfiguration unter "Redirect URIs" eintragen.

#### R11 — BER Demo-Daten auf Railway Volume nicht vorhanden [MITTEL]

Mit `DATA_ROOT=/data` liest der Server vom Railway Volume. Committed `data/projects/ber/`-Dateien liegen im Container-Dateisystem unter `/app/data/`, aber der Server liest von `/data/` (Volume) — die Demo-Daten sind nicht sichtbar.

Optionen:
- **(a) Seed-Script beim Start:** Prüft ob `/data/projects/ber/` leer ist und kopiert Daten aus `/app/data/projects/ber/`. Einmalig, idempotent, reproduzierbar. Empfohlen.
- **(b) Manuell via Railway Volume:** Nicht reproduzierbar, entfällt bei Volume-Reset.
- **(c) Nur `exploration/data.json` committen + statisch ausliefern:** Funktioniert für Read-Only-Demo ohne Wizard, umgeht das Volume-Problem.

**Lösung (Backlog):** `startCommand` um Seed-Script erweitern: `python src/generalized/seed_demo.py && uvicorn ...`. Script kopiert `/app/data/projects/ber/` nach `/data/projects/ber/` wenn Zielverzeichnis leer.

---

### MITTEL

#### R7 — Keine `.env.example` / Deployment-Dokumentation

Benötigte Env-Vars für Railway sind nirgends dokumentiert. Erforderlich (je nach Konfiguration):

| Variable | Erforderlich wenn | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=anthropic` | — |
| `LLM_PROVIDER` | immer | `ollama` (→ R3) |
| `EMBEDDING_PROVIDER` | immer | `local` (→ R1) |
| `VOYAGE_API_KEY` | `EMBEDDING_PROVIDER=voyage` | — |
| `DROPBOX_APP_KEY` / `DROPBOX_APP_SECRET` | Obsidian-Sync | `""` |
| `DATA_ROOT` | persistentes Volume | `./data` |
| `ADMIN_KEY` | Admin-Bypass | — |

Kein `.env.example`, kein README-Abschnitt zu Railway.

#### R8 — Kein Request-Timeout für BGE/GLiNER-Loads beim ersten Aufruf

`asyncio.create_subprocess_exec` in `dev_server.py` hat kein Timeout. Läuft ein Pipeline-Script das BGE-M3 oder GLiNER erstmalig lädt, hängt der SSE-Stream bis Railway den Container terminiert (default: 60s). Für den Client sieht das wie ein Silent Failure aus.
