# BER Chronik — Designentscheidungen

Designentscheidungen die nicht aus dem Code hervorgehen. Warum etwas so ist wie es ist.

---

## Meta-Prinzipien

### Eine Quelle, kein Fallback
Jedes persistierte Datum hat genau eine autoritative Quelle. Sekundäre Fallbacks
erzeugen stille Inkonsistenzen und werden nicht toleriert.
Instanzen: **D-P1** (Taxonomie-Quelle), **D-P4** (Entity-Quelle).

### Pipeline-Verträge sind explizit
Jeder Schritt deklariert was er braucht und was er schreibt. Implizite Konventionen
— fehlende Dateien still ignorieren, Feldnamen raten — sind verboten.
Instanzen: **D-P2** (normalize_category überall), **D-P3** (classified.json-Komposit), **D-P5** (Input-Prüfung).

---

## Pipeline

### D-P1 — Kanonische Taxonomiequelle
Einzige gültige Quelle: `projects/{project}/config.json["taxonomy"]`.
Kein Fallback auf taxonomy_proposal.json oder event_type-Ableitung.
Konsequenz: nach propose_taxonomy direkt in config.json — taxonomy/save
ist weiterhin der offizielle Speicherpfad aus dem Wizard.
Fehlt taxonomy in config.json: Fehler, kein stiller Fallback.

`taxonomy_proposal.json` ist abgeschafft: wird nicht mehr geschrieben,
nicht mehr gelesen. Bestehende Dateien können liegenbleiben, sind aber
ohne Funktion. `propose_taxonomy.py` schreibt direkt in config.json["taxonomy"].

### D-P2 — normalize_category() läuft überall
classify_segments.py, export_preview.py und export_exploration.py
rufen alle normalize_category() auf — nicht nur classify.
Normalisierung: exakter Match → längster Substring-Match → "(unbekannt)".

### D-P3 — classified.json ist ein gemeinsames Dokument
classify_segments.py schreibt category+confidence.
match_entities.py ergänzt actors in-place.
Regel: nach jedem classify-Lauf muss match_entities neu laufen.
Kein Mischzustand (neue Kategorien + alte actors) ist erlaubt.

### D-P4 — Entities haben eine einzige Quelle
Einzige gültige Quelle: `projects/{project}/config.json["entities"]`.
Kein doc-level Fallback, kein stilles Ignorieren.

`documents/{doc_id}/entities_proposal.json` ist temporärer Extraktor-Output —
wird von `extract_entities_v2.py` geschrieben und sofort nach `config.json["entities"]`
gespiegelt. Der Entity-Editor liest und schreibt ausschließlich `config.json["entities"]`.
Jede Aktion im Editor (Bearbeiten, Ablehnen, Löschen, Hinzufügen) löst sofort ein
automatisches `POST /ingest/entities/save` aus — kein expliziter Speichern-Button.

### D-P5 — Schritt-Verträge sind explizit
Jedes Skript prüft beim Start ob seine Input-Dateien existieren.
Fehlt eine Input-Datei: Fehler mit klarem Text, kein Weiterlaufen.

### D-P6 — Keine verwaisten Endpoints
Jeder Endpoint in dev_server.py wird von mindestens einer 
bekannten Stelle aufgerufen. Nach jedem Feature-Block: 
grep aller Endpoints gegen ingest_wizard.html und 
taxonomy_editor.html. Verwaiste Endpoints werden 
entweder gefixt oder gelöscht.

### D-P7 — Wizard-State-Persistenz
`state.project`, `state.document` und `step` werden bei jedem Schritt-Wechsel
in die URL geschrieben (`gotoStep`). Bei Reload liest `restoreFromUrl()` diese
Parameter und springt direkt zum gespeicherten Schritt.

Token ist nie in der URL — wird immer frisch von `GET /api/projects/{id}/token`
geholt. Kein Token-Leak durch Browser-Historie.

`taxData` ist die einzige Browser-Variable für Taxonomie-Daten. `state.taxonomy`
existiert nicht — Taxonomie lebt ausschließlich in `taxData` (Browser) und
`config.json["taxonomy"]` (Server).

### D-P8 — Ingest-Segmente tragen Erscheinungsdatum als Metadatenfeld
`ingest_obsidian.py` schreibt das Erscheinungsdatum aus dem Frontmatter-Feld
`published` (Fallback: `created`) in das Feld `"date"` jedes Segments
(String, Format YYYY-MM-DD oder YYYY).

`detect_anchors.py` liest dieses Feld im Presseartikel-Modus: wenn kein
aktives Heading-Jahr vorhanden, wird `seg["date"]` direkt als Anker gesetzt
(`precision="exact"`, `source="date"`). Kein Regex-Suchen im Fließtext.
`date_raw` wird in `anchors.json` aus `date` kopiert → `export_exploration.py`
baut daraus `date_js` (volle Tag-Präzision wenn YYYY-MM-DD).

Gilt nur für `doc_type=presseartikel`. Forschungsnotizen-Modus unverändert.
Konsequenz: Obsidian-Artikel mit `published`-Frontmatter sind nach dem Ingest
präzise auf den Tag datiert.

### D-P9 — propose_taxonomy: 3-stufige Keyword→Destillation-Architektur
Statt 5 Batches à 10 Segmente direkt Kategorien generieren (alter Ansatz:
Häufigkeitszählung als Merge) gilt jetzt:

**Stufe 1 — Keywords:** Bis zu 80 Segmente in Batches à 4, je ein kurzer
LLM-Call: „2-3 Themen pro Text". Output: kommaseparierte Keyword-Listen.
Parallel (Anthropic) oder sequenziell (Ollama).

**Stufe 2 — Destillation:** Alle gesammelten Keywords in einem einzigen
LLM-Call: „Fasse zu 6-8 Kategorien zusammen, führe Ähnliches zusammen."
Output: ## Name / Beschreibung / Keywords-Format (identisch zu vorher).

**Stufe 3 — Schreiben:** Unverändert: `config.json["taxonomy"]` (D-P1).

Warum: Stufe-1-Calls sind kurz und stabil (kein Context-Window-Problem
bei langen Artikeln). Semantische Deduplizierung durch LLM in Stufe 2
ist robuster als Häufigkeitszählung — erkennt „Kosten" und „Finanzierung"
als dieselbe Kategorie.

### D-T1 — BGE-M3 + TF-IDF-Anchor als primäres Taxonomie- und Klassifikations-Backend
BGE-M3 (BAAI/bge-m3) ersetzt MiniLM und LLM-Klassifikation als Standard-Embedding-Modell.
Benchmarkergebnis 2026-05-06: Ø Delta +0.1403, Synergieeffekt TF-IDF + Rolling Context +0.0254.

**Taxonomie-Vorschlag** (`propose_taxonomy.py --method bge`):
Iteratives k-means-Clustering + TF-IDF-Keywords pro Iteration + Rolling-Context-LLM-Labels (Claude Haiku).
Warm-Start: wenn `config.json["taxonomy"]` bereits Einträge hat, starten `prev_descs` und `summaries`
aus der bestehenden Taxonomie (kein Kaltstart, schnellere Konvergenz).
Output: `config.json["taxonomy"]` (D-P1), Format `{"name", "description", "keywords"}`.

**Klassifikation** (`classify_segments.py --method bge`):
Cosine-Similarity zwischen Segment-Embedding und Taxonomie-Kategorie-Embedding.
Konfidenz: sim > 0.5 → high, > 0.35 → medium, sonst → low.
Output: `classified.json` identisch zu LLM-Pfad — nachgelagerte Schritte sind pfadagnostisch.

**Cache**: `data/projects/{project}/documents/{doc_id}/bge_embeddings.npy` — projekt-lokal,
persistent über Reboots, git-ignoriert via `.gitignore`. Shape-Check verhindert stale cache.

**Wizard Schritt 4**: Ein Button statt zwei — Label dynamisch je nach Zustand:
- Leer: "Themen vorschlagen" → `POST /ingest/propose_taxonomy?method=bge`
- Vorhanden: "Taxonomie verfeinern ↻" → gleicher Endpoint mit Warm-Start

### D-P10 — url-Feld durch die gesamte Pipeline
`ingest_obsidian.py` schreibt das `url`-Feld (Artikel-URL aus dem Frontmatter-Feld
`source`) in jedes Segment. `export_exploration.py` (`build_entries`) propagiert
es unverändert in den data.json-Eintrag. `panel.js` (`renderParaCard`) stellt
`source_name` als `<a href>` dar wenn `p.url` gesetzt ist.

Gilt für Obsidian-Ingests wenn `source` im Frontmatter gesetzt ist.
Segmente aus Datei-Upload haben kein url-Feld
(`seg.get("url", "")` gibt leer zurück → kein Link).

### D-I1 — Obsidian/Dropbox Ingest ersetzt Zotero
`ingest_obsidian.py` ersetzt `ingest_zotero.py` als primären externen Ingest-Pfad.
Quellformat: Obsidian Web Clipper `.md`-Dateien mit YAML-Frontmatter.
Transport: Dropbox OAuth2 (offline, refresh_token) oder lokaler Vault-Pfad (Tests).

**Frontmatter-Mapping:**
- `title` → `source` (Artikel-Titel)
- `source` → `url` (ist die URL, nicht die Zeitung)
- `author` → `author` (Obsidian `[[Link]]`-Format wird bereinigt)
- `published` → `date` (Präzision YYYY-MM-DD; detect_anchors liest es, D-P8)
- `created` → `date` (Fallback wenn `published` fehlt)
- `description` → `abstract`

**OAuth2:** `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REDIRECT_URL` in `.env`.
Redirect-URL via Umgebungsvariable für einfachen Hosting-Wechsel.
Tokens werden in `config.json["obsidian"]["tokens"]` gespeichert.

**Wizard:** Obsidian-Tab im „Neues Projekt +"-Dialog (ersetzt Zotero-Tab).
Obsidian-Panel in Projektkarten (ersetzt Zotero-Panel).
Endpoints: `/api/obsidian/oauth/start`, `/api/obsidian/oauth/callback`,
`/api/projects/{id}/obsidian/config`, `/api/projects/{id}/obsidian/test`,
`/api/projects/{id}/obsidian/sync`.

**Lokaler Modus:** `--source local --vault /pfad` für Tests ohne Dropbox-Auth.

## Entity-Extraktion

### D-E1 — Plaintext-Format für alle geparsten LLM-Ausgaben
LLM-Antworten die anschließend geparst werden verwenden kein JSON,
sondern einfache Plaintext-Formate. Gilt für Entity-Extraktion und
Taxonomie-Vorschlag.

**Entity-Extraktion** (`_llm_sample_iteration`, `_llm_full_extract`, `_llm_task1_normalize`):
```
# Personen
Enver, Enver Pasha, Enver Bey
Muhammad Ali, Muhammad Ali Pasha

# Organisationen
Osmanisches Reich, Hohe Pforte

# Orte
Kairo, al-Qahira

# Konzepte
Nahda, arabische Aufklärung
```
Parser: `#`-Zeile = Typ-Header; alle anderen Zeilen kommasepariert,
erste Schreibweise = Normalform, Rest = Aliases.

**Taxonomie-Vorschlag** (`propose_taxonomy.py`):
```
## Kategoriename
Beschreibung in einem Satz.
Keywords: keyword1, keyword2, keyword3

## Zweite Kategorie
...
```
Parser: `##`-Zeile = Kategoriename; nächste nicht-leere Zeile = Beschreibung;
`Keywords:`-Zeile = kommaseparierte Keywords.

**NER-Backend-Switcher** (`extract_entities_v2.py`):
```python
backend = NER_BACKEND.get(doc_type, "llm")  # NER_BACKEND in config.py
```
- `presseartikel` → spaCy (`entity_spacy.py`): `en_core_web_trf` oder `en_core_web_sm` als Fallback
- alle anderen → LLM-Pipeline (Schritt 1–4)

Warum: Presseartikel sind englischsprachig und strukturiert — spaCy NER ist schneller
und hat kein Kontextfenster-Problem. Lange Texte (z.B. Video-Transkripte) bleiben dem
LLM-Pfad überlassen. Der Taxonomie-Vorschlag-Merge-Schritt (5 Batches → Häufigkeitszählung)
ist durch D-P9 (3-stufige Keyword→Destillation) ersetzt worden.

Warum kein JSON:
- Kleine Modelle (llama3.2:3b, llama3.1:8b) brechen bei langen JSON-Arrays häufig
  die Struktur ab oder geben ein einzelnes Objekt statt Array zurück
- Plaintext-Format ist robuster: jede korrekte Zeile/Block ist verwertbar,
  auch wenn das Ende der Antwort fehlt oder Sonderzeichen falsch escaped sind
- `complete_json()` fällt bei jedem Syntaxfehler komplett aus;
  Plaintext-Parser verwerfen nur den fehlerhaften Block

Ausnahme: Dedup (`_llm_dedup`) bleibt JSON — binäre keep/merge-Entscheidungen
sind als strukturierter Paarvergleich besser formulierbar.

### D-E2 — max_chars_per_chunk und Ollama-Kontextfenster
Lange Segmente (z.B. Video-Transkripte, 80k Zeichen) überfordern das Kontextfenster
kleiner Modelle. Lösung: `max_chars_per_chunk` als Klassenattribut in `LLMProvider`:

```python
class LLMProvider:       max_chars_per_chunk = 8000
class AnthropicProvider: max_chars_per_chunk = 8000
class OllamaProvider:    max_chars_per_chunk = 2000   # kleines lokales Modell
```

`_chunk_text(text, max_chars)` teilt am letzten `. ` vor dem Limit. Jedes Segment
das größer ist wird vor dem LLM-Call in Pseudo-Segmente gesplittet.

`OllamaProvider.complete()` setzt außerdem `"options": {"num_ctx": 8192}` im Payload —
ohne diesen Parameter verwendet Ollama standardmäßig 2048 Token, was auch bei kurzen
Texten zu Abschneiden führen kann.

### D-E4 — GLiNER als Standard-NER-Backend
`entity_gliner.py` ersetzt `entity_spacy.py` und die LLM-Extraktionsstufen 1+2.
`NER_BACKEND` routet alle doc_types auf `"gliner"`.

**Warum:**
- 4× schneller als LLM-Vollpipeline (2s Extraktion lokal statt 75s API)
- Multilingual — funktioniert für Deutsch, Türkisch, Arabisch, Englisch ohne Modellwechsel
- Vergleichbare Qualität zur LLM-Pipeline auf Sample-Ebene (Benchmark 2026-05-04)
- Score-Felder auf allen Entities (LLM hatte immer `score=null`)

**Was bleibt LLM:**
- `_llm_group()` (Stage 3): semantische Dedup + Alias-Zusammenführung — kein statistisches Modell kann das ersetzen
- `_llm_task1_normalize()` (Stage 4): Normalform-Bereinigung, Groß-/Kleinschreibung, Typ-Validierung

**Archiviert (nicht gelöscht):**
- `_llm_sample_iteration()` / `_llm_full_extract()` in entity_llm.py: nur noch benchmark_ner.py
- `entity_spacy.py`: explizit über `backend="spacy"` weiterhin nutzbar

**Offene Frage:** Benchmark hat nur `mode=sample` verglichen (Stage 1+3+4 vs. GLiNER+3+4).
Stage 2 (Full-Extract über alle Segmente mit Few-Shot) wurde noch nicht gegen GLiNER
auf großen Dokumenten verglichen.

### D-E3 — videoRecording-Segmente überspringen
Der spaCy-Pfad (`entity_spacy.py`) filtert Segmente mit `item_type == "videoRecording"`:
Video-Transkripte sind oft mehrstündig (>80k Zeichen), enthalten viel Fülltext und
liefern schlechte NER-Ergebnisse. Das Feld `item_type` kommt aus Zotero-Metadaten
(`data["itemType"]`) und wird von `ingest_zotero.py` in jedes Segment geschrieben.

LLM-Pfad: keine spezielle Filterung — Chunking via `max_chars_per_chunk` fängt
überlange Segmente ab (D-E2).

---

## Architektur

### Kein Build-Tool, keine ES-Module
Alle JS-Dateien laufen im globalen Browser-Scope, geladen als plain `<script>`-Tags. Das erlaubt:
- Direktes Öffnen via `python3 -m http.server` ohne Compile-Schritt
- Einfaches Debugging im Browser ohne Source Maps
- Dateien sind von jeder Stelle aus editierbar ohne ein Tool zu kennen

Konsequenz: Load-Reihenfolge in `index.html` ist **zwingend**. Wer eine Funktion referenziert muss sicherstellen dass die deklarierende Datei vorher geladen wird.

### Aktuell gültige Ladereihenfolge
```
highlight.js → highlight-state.js → panel.js → chart.js
→ utils.js → tabs.js → network.js → search.js → boot.js → tutorial.js
```
ARCHITECTURE.md ist in diesem Punkt **veraltet** — tabs.js und boot.js wurden nachträglich extrahiert.

---

## Highlight-System

### Zwei getrennte Highlight-Ebenen
`_applyTimelineHighlight()` und `applyNetworkState()` werden beide von `setHighlight()` ausgelöst, sind aber konzeptuell getrennt:
- **Timeline**: nur `hlState` (mode, anchors, active) relevant
- **Netzwerk**: `netFocusNode` und `netFocusPair` haben höhere Priorität als `hlState`

`applyNetworkState()` ist eine State Machine mit Prioritätsreihenfolge — wer als erstes `true` ist, gewinnt.

### `"answer"` vs `"single"` Highlight-Modus
Beide Modes dimmen alles außer den relevanten Ankern. Unterschied:
- `"answer"` → alle relevanten Dots voll sichtbar, gleiche Opacity
- `"single"` → ein Dot (active) ist extra-prominent (größer, goldener Stroke); die anderen relevanten Dots werden auf 0.4 Opacity gedimmt

`"single"` wird nur ausgelöst wenn ein konkreter Paragraphen-Card angeklickt wird.

### Muted Palette — gleiche Farbe für Rest und Active
`NODE_COLOR` hat nur eine Palette, nicht zwei. Visuelle Unterscheidung zwischen highlighted/gedimmt kommt **ausschließlich** aus der Group-Opacity (1 vs DIM=0.35), nicht aus Farbwechsel. Vermeidet visuelles Rauschen durch zwei konkurrierende Paletten.

---

## Netzwerk

### Simulation startet stopped (`alpha(0).stop()`)
Die Simulation wird erstellt, aber sofort gestoppt. Wenn `network_layout.json` vorhanden ist, haben alle Knoten bereits gute Positionen. Volle Alpha ab Start würde ein jarrendes Layout-Neuberechnen zeigen. Erst `recomputeGraph()` (durch Filter oder Tab-Öffnen) gibt der Simulation Leben.

### `_fitGraph` wird zweimal aufgerufen
Einmal sofort nach `rerender()` (ohne Animation) — setzt die initiale Zoom-Transform für den Fall dass die Simulation nie läuft (precomputed layout). Einmal via `sim.on("end.fit")` (animiert) — für den Fall dass die Simulation doch läuft (z.B. kein Layout-JSON vorhanden). Das zweite Event feuert einmalig und wird dann deregistriert (`_fitOnEnd` Flag).

### Parallele Kanten mit Offset
Wenn zwei Akteure mehrere Verbindungstypen haben (z.B. Kosten + Klage), bekommt jeder Typ eine eigene Linie mit perpendikularem Offset. Hit-Areas sind **separate transparente Linien**, eine pro Knotenpaar (nicht pro Kantentyp) — verhindert überlappende Klickziele.

### k-Core Pruning in `recomputeGraph`
Nicht einfaches Degree-Filter sondern iteratives Pruning: Knoten mit < minLinks sichtbaren Kanten werden entfernt, dann wird wiederholt bis stabil. Damit bleibt kein Knoten übrig der nur durch Verbindungen zu bereits-entfernten Knoten qualifiziert hätte.

### `_tempPinned` Pattern
Wenn neue Knoten durch Filter-Änderung auftauchen, werden bestehende sichtbare Knoten 500ms lang fixiert (fx/fy gesetzt), damit sie nicht wegdriften während neue Knoten sich einpendeln. Das `pinSnapshot` im `setTimeout` verhindert dass spätere `recomputeGraph`-Aufrufe die falsche Knoten-Menge entpinnen.

### `pairKey` mit `\x00` als Separator
`\x00` (Null-Byte) als Separator zwischen zwei Akteurnamen. Kann in Akteurnamen (aus CSV geladen) nicht vorkommen. Ein druckbares Zeichen wie `|` könnte theoretisch in einem Namen auftreten und eine falsche Kollision erzeugen.

---

## Panel

### `selectEntity` geht NICHT durch `showView`
`showView` hat eine Deduplizierungs-Guard: Wenn die gleiche Entity schon gezeigt wird, wird nur `_safeRender` aufgerufen — nicht `_renderView`. `_renderView` ist das was die CSS-Klasse `active` setzt. Wenn `#view-entity` gerade hidden war aber `currentView` schon diese Entity hatte, würde die View silently unsichtbar bleiben. `selectEntity` ruft deshalb immer `_renderView` direkt auf.

### `netFocusNode` wird VOR `selectEntity` gesetzt
Im `panel-content`-Click-Handler (Entity-Span-Klick) wird `netFocusNode = name` gesetzt, **bevor** `selectEntity(name)` aufgerufen wird. Grund: `selectEntity` ruft `setHighlight` auf, das sofort `applyNetworkState()` triggert. `applyNetworkState` prüft `netFocusNode` als erstes — ist es gesetzt, gewinnt der Ego-Graph-Modus. Wäre es danach gesetzt, würde für einen Frame der KI-Subgraph-Modus angezeigt.

### Drei Views immer im DOM
`view-chat`, `view-timeline`, `view-entity` existieren alle gleichzeitig im DOM. Nur die aktive hat `display: block` (CSS `.panel-view.active`). Das verhindert Flackern beim Tab-Wechsel und erlaubt Back-Navigation ohne Re-Render.

### Paragraphen-Einklapp-Mechanismus ab 800 Zeichen
Karten mit mehr als `PARA_COLLAPSE_CHARS = 800` Zeichen zeigen nur die ersten 800 Zeichen.
Der Rest liegt in `<span class="para-rest" hidden>`. Ein `<span class="para-toggle">`
(grau, klein, inline) schaltet `hidden` um und wechselt seinen Text zwischen
„… weiterlesen" und „einklappen".

Bewusst kein `<button>` — Inline-Span passt besser in den Textfluss und vermeidet
Button-Fokus-Styling. Der Click-Handler in `panel-content` fängt `.para-toggle`
als erstes ab (vor Card-Klick und Entity-Klick).

### `hlSnapshot` im ViewStack
Jeder View-Stack-Eintrag speichert eine Kopie von `hlState` zum Zeitpunkt des Navigierens. `goBack()` stellt diesen Snapshot wieder her — damit kehren Timeline-Dots und Netzwerk-Highlight zum Zustand vor der Entity-Navigation zurück.

---

## Chat & Suche

### `isAiMode` Heuristik
`?` im Text oder mehr als 4 Wörter → KI-Modus. Einfache Heuristik die bei Entity-Namen (1–3 Wörter, kein `?`) zuverlässig Volltextsuche auslöst, bei Fragen zuverlässig die KI. Bewusst nicht konfigurierbar — das Verhalten soll für den Nutzer transparent sein.

### `marked.js` Placeholder-Trick für `[pXX, YYYY]`
KI-Antworten enthalten Quellenbelege wie `[p59, 2003]`. `marked` würde diese als Reference-Style-Links interpretieren und entfernen. Vor dem Parsing werden sie durch `\x02SRCREF0\x03`-Platzhalter ersetzt (STX/ETX Control Characters, die marked nie emittiert), nach dem Parsing wieder eingesetzt als `<a href="#src-...">`.

### Quellkarten bekommen `id="src-..."`, Paragraphen-Karten `data-anchor`
KI-Antwort-Quellkarten brauchen DOM-IDs damit die `href="#src-pXX"`-Links im Antworttext per Scroll-Sprung funktionieren. Paragraphen-Karten aus Timeline/Entity-View verwenden `data-anchor` statt `id`, weil:
- IDs müssen im Dokument eindeutig sein
- Mehrere Views können gleichzeitig im DOM die gleiche Anchor-ID enthalten (inactive views werden nicht geleert)

---

## Daten & Boot

### `entriesByAnchor` vs `actorsByAnchor`
Beide Maps sind Anchor-keyed, dienen aber entgegengesetzten Lookup-Richtungen:
- `entriesByAnchor`: anchor → komplettes Entry-Objekt (für Quellkarten-Lookup im Chat)
- `actorsByAnchor`: anchor → Set von Akteurnamen (für Netzwerk-Highlight: welche Akteure stecken in diesen Artikeln)

### Netzwerk-Daten werden im Boot aufgebaut, nicht beim Tab-Öffnen
`netNodes` und `netLinks` werden in `boot.js` aus `data.json` berechnet. `drawNetwork` liest sie beim ersten Tab-Klick. Wenn der Nutzer zu früh auf Netzwerk klickt (vor Boot-Completion), zeichnet sich ein leeres Netzwerk — ohne Fehlermeldung. Akzeptierter Trade-off gegen die Komplexität eines Lade-Guards.

### `entities_summary.json` und `entities_seed.csv` haben `.catch(() => {})`
Beide fallen silent zurück auf leere Strukturen. Fehlt `entities_seed.csv`: `aliasMap` ist leer, Entity-Highlighting im Panel fehlt. Fehlt `entities_summary.json`: `summaryMap` ist leer, KI-Zusammenfassungen fehlen, Knoten erscheinen gestrichelt. Kein expliziter Error, kein Warning — Akzeptierter Trade-off für Robustheit bei partiell nicht erreichbaren Assets.

---

## Tutorial

### CSS-in-JS in `tutorial.js`
Alle Tutorial-Styles sind als `<style>`-Tag in `tutorial.js` injiziert, nicht in `style.css`. Bewusste Kapselung: Tutorial-Elemente (`#tutorial-overlay`, `#tutorial-bubble`, `.tut-*`) existieren nur solange tutorial.js läuft, und der gesamte Tutorial-Code lässt sich durch Löschen einer einzelnen Datei entfernen.

### Auto-Start mit 600ms Delay
`setTimeout(tutorialStart, 600)` nach `window load`. Delay gibt `drawChart` Zeit zu rendern, bevor das Overlay erscheint — sonst würde der Nutzer den Tutorial-Pfeil auf ein noch leeres `#chart-area` sehen.

### `localStorage.setItem("tutorial_seen", "1")` in `_end()`
Wird beim Schließen (Überspringen oder letztem Schritt) gesetzt, **nicht** beim Öffnen. Verhindert dass ein Nutzer der das Tutorial nie zu Ende gesehen hat es beim nächsten Besuch nicht mehr sieht.
