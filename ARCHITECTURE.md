# BER Chronik — Architektur

> Lies diese Datei vor jeder Änderung am viz/-Code. Sie beschreibt welche Funktionen welchen State setzen, welche Event-Handler welche Funktionen aufrufen, und wo die drei riskantesten Stellen im Code sind.

---

## Überblick

Alle JS-Dateien laufen im **globalen Browser-Scope** — keine Module, kein Build-Tool. Ladereihenfolge in `index.html` ist zwingend:

```
highlight.js        → Konstanten, aliasMap, Highlight-State, setHighlight()
panel.js            → View-State, Panel-Logik, renderParaCard(), Tooltip
chart.js            → drawChart(), _applyChartEntityHighlight()
utils.js            → pairKey()
tabs.js             → Tab-State, geteilte Daten-Globals (netNodes etc.), switchTab()
network.js          → applyNetworkState(), drawNetwork()
search.js           → sendChat(), fulltextSearch(), renderChatAnswer()
boot.js             → Promise.all: Daten laden, drawChart aufrufen, netNodes/netLinks befüllen
tutorial.js         → Tutorial-Overlay, STEPS, tutorialStart()
```

---

## Globaler State

### highlight.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `hlState` | `{mode, anchors, active, focusEntity}` | Zentraler Highlight-Zustand. `mode`: `"none"` / `"answer"` / `"single"`. `anchors`: Set von doc_anchor-Strings. `active`: einzelner doc_anchor. `focusEntity`: Entitätsname. |
| `selectedEntity` | `string \| null` | Aktuell geöffnete Entität im Panel |
| `netNodeSelection` | D3 selection | D3-Auswahl aller Netzwerk-Knoten. `null` bis `drawNetwork` aufgerufen. |
| `netNeighbors` | `Map<id, Set<id>>` | Nachbarschaftsgraph (alle Links, unabhängig von Filtern) |
| `actorsByAnchor` | `Map<anchor, Set<name>>` | doc_anchor → Akteursnamen |
| `chartDotSelection` | D3 selection | D3-Auswahl aller Timeline-Punkte. Wird bei jedem `drawChart` neu gesetzt. |
| `DIM` | `0.35` | Konstante: Opacity für gedimmte Elemente |
| `aliasMap` | `{[alias]: {normalform, typ}}` | Alias → kanonischer Name + Typ |
| `aliasesSorted` | `string[]` | Aliase absteigend nach Länge sortiert (für Regex-Matching) |
| `summaryMap` | `{[name]: {summary, count}}` | KI-Zusammenfassungen pro Entität |
| `EVENT_TYPES` | `string[]` | Vollständige Liste der Ereignistypen |
| `COLOR` | `{[type]: hex}` | Farbe pro Ereignistyp |
| `NODE_COLOR` | `{[typ]: hex}` | Farbe pro Entitätstyp (Person/Org/Gremium/Partei) |

### tabs.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `networkDrawn` | boolean | True nach erstem `drawNetwork`-Aufruf |
| `netNodes` | `Node[]` | Alle Knoten (befüllt in boot.js) |
| `netLinks` | `Link[]` | Alle Links (befüllt in boot.js) |
| `entriesByActor` | `Map<name, Entry[]>` | Akteur → zugehörige Einträge (befüllt in boot.js) |
| `entriesByAnchor` | `Map<anchor, Entry>` | doc_anchor → Entry-Objekt (befüllt in boot.js) |

### network.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `netFocusNode` | `string \| null` | ID des Ego-Knotens. Wenn gesetzt: Ego-Graph-Modus |
| `netFocusPair` | `{key, sid, tid} \| null` | Fokussiertes Knotenpaar. Wenn gesetzt: Edge-Focus-Modus |
| `activeNetThemes` | `Set<string>` | Aktuell sichtbare Ereignistypen (Legende = Filter) |
| `activeNodeTypes` | `Set<string>` | Aktuell sichtbare Entitätstypen |
| `netLinkSelection` | D3 selection | D3-Auswahl der sichtbaren Links |
| `_networkLayout` | object \| null | Vorberechnete Knotenpositionen (aus `layout.json`) |

### panel.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `viewStack` | `View[]` | Stack für Back-Navigation. Jeder Eintrag hat `{type, title, renderFn, entityKey, hlSnapshot}` |
| `currentView` | `View` | Aktuell angezeigte View |
| `panelExpanded` | boolean | Ob Panel auf 2/3 Breite expandiert |
| `activeDot` | DOM element \| null | Aktuell aktiver Timeline-Punkt |
| `dimmedTypes` | `Set<string>` | Ausgeblendete Ereignistypen (Timeline-Legende) |

### search.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `allEntries` | `Entry[]` | Alle geladenen Einträge (befüllt in boot.js) |

---

## State-Mutationen: wer setzt was

### `hlState` — nur über `setHighlight()`
```
sendChat()           → setHighlight("answer", anchors)
dot click            → setHighlight("answer", anchorSet, anchor, null)
entity click         → setHighlight("answer", anchors, null, entity)
goHome()             → setHighlight("none")
goBack()             → setHighlight(snapshot.mode, ...)
tutorial step        → setHighlight("answer", anchors, null, "Hartmut Mehdorn")
hit-line click       → setHighlight("answer", sharedAnchors, null, null)
```
`setHighlight` ruft immer synchron `_applyHighlight()` → `_applyTimelineHighlight()` + `applyNetworkState()` + `_applyChartEntityHighlight()`.

### `selectedEntity` — über `selectEntity()`
```
node click           → selectEntity(id)          (network.js)
entity span click    → selectEntity(normalform)   (panel.js, via #panel-content click)
tutorial action      → selectEntity(node.id)
```
`selectEntity` ruft `_renderView("entity", ...)` und `setHighlight("answer", ...)`.

### `netFocusNode` — direkt in network.js
```
node click           → netFocusNode = d.id, dann applyNetworkState()
SVG click (leer)     → netFocusNode = null, dann applyNetworkState()
```

### `netFocusPair` — direkt in network.js
```
hit-line click       → netFocusPair = {key, sid, tid}, dann applyNetworkState()
SVG click (leer)     → netFocusPair = null, dann applyNetworkState()
```

### `activeNetThemes` / `activeNodeTypes` / `topN` / `minLinks`
```
Legende-Klick        → Set add/delete, recomputeGraph()
Slider #net-slider   → topN = value, recomputeGraph()
Slider #net-minlinks → minLinks = value (nur on mouseup), recomputeGraph()
```

### `viewStack` / `currentView`
```
showView()           → push currentView, replace currentView
goBack()             → pop viewStack, restore currentView
goHome()             → viewStack = [], currentView = chat
```

---

## Zentrale Aufrufketten

### Timeline-Punkt klicken
```
dot.click
  → activeDot.classList.add("active")
  → showView("timeline", year+type, renderFn)
    → _renderView() → renderFn(el)
      → renderParaList(entries) → renderParaCard() × n
  → setHighlight("answer", anchorSet)
    → _applyHighlight()
      → _applyTimelineHighlight()   (dimmt/hebt Punkte)
      → applyNetworkState()          (Netzwerk-Overlay)
      → _applyChartEntityHighlight() (Linien-Overlay)
```

### Entitäts-Span im Panel klicken
```
#panel-content.click (delegiert)
  → netFocusNode = name          ← VOR selectEntity setzen!
  → selectEntity(normalform)
    → _renderView("entity", ...)
      → renderEntityView() → renderParaCard() × n
    → setHighlight("answer", anchors, null, name)
      → _applyHighlight() → applyNetworkState()
```

### Netzwerk-Knoten klicken
```
node.click
  → d.fx = d.x; d.fy = d.y  (pinnen)
  → netFocusNode = d.id
  → selectEntity(d.id)        (öffnet Panel)
  → applyNetworkState()       (Ego-Graph-Modus)
  → svg.transition().call(zoomBehavior.translateTo, d.x, d.y)
```

### Chat/Suche absenden
```
sendChat()
  → (falls nicht chat view) _renderView("chat", ...)
  → setHighlight("none")
  → fetch API stream ODER fulltextSearch()
  → renderChatAnswer()
    → renderParaCard() × n   (Quellkarten mit id="src-...")
    → setHighlight("answer", sources)
```

### Filter im Netzwerk ändern
```
Legende / Slider
  → recomputeGraph()
    → k-core Pruning (iterativ)
    → sim.nodes(visibleNodes)
    → sim.force("link").links(newSimLinks)
    → sim.alpha(0.05 | 0.1).restart()
    → node.attr("display", ...)
    → computeOffsets()
    → rerender()
    → applyNetworkState()
```

---

## renderParaCard — zentrale Karten-Funktion

Definiert in `panel.js`. Rendert ein einzelnes Paragraphen-Card. Wird von drei Stellen aufgerufen:

| Aufrufer | `id` | `anchor` | `highlightFn` |
|---|---|---|---|
| `renderParaList` (Timeline/Entity-View) | — | `p.doc_anchor` | `highlightEntities` oder `highlightWithKeywords(..., focusEntity)` |
| `renderChatAnswer` — KI-Quellkarten | `src-{anchor}` | — | `highlightEntities` |
| `renderChatAnswer` — Volltext-Treffer | — | — | `highlightWithKeywords(..., keywords)` |

`id` und `anchor` sind exklusiv: `id` erzeugt ein DOM-`id`-Attribut (für `href="#src-..."` Links aus KI-Antworten); `anchor` erzeugt `data-anchor` (für Highlight-Sync).

---

## applyNetworkState — State Machine

Wird aus `_applyHighlight()` und direkt aus network.js-Handlern aufgerufen. Vier exklusive Modi, geprüft in dieser Reihenfolge:

1. **Ego-Graph** (`netFocusNode !== null`) — fokussiert Nachbarn eines Knotens
2. **Edge-Focus** (`netFocusPair !== null`) — fokussiert ein Knotenpaar und ihre Links
3. **Default** (`mode === "none"` oder keine Anchors) — alle Knoten/Links voll sichtbar
4. **KI-Subgraph** — hebt Akteure aus `hlState.anchors` hervor

Wichtig: `applyNetworkState` liest `netFocusNode`, `netFocusPair`, `hlState`, `activeNetThemes` alle gleichzeitig. Wenn mehrere davon gesetzt sind, gewinnt immer die **erste** Bedingung.

---

## Boot-Sequenz (boot.js)

```
Promise.all([data.json, entities_seed.csv, entities_summary.json])
  → buildAliasMap(csvText)          (füllt aliasMap, aliasesSorted)
  → summaryMap = summaries
  → allEntries = entries
  → füllt entriesByAnchor, actorsByAnchor
  → baut Timeline-Series
  → drawChart(series, years)
  → new ResizeObserver(drawChart)
  → baut netNodes, netLinks, entriesByActor
```
`drawNetwork` wird **nicht** beim Boot aufgerufen — erst beim ersten Klick auf den Netzwerk-Tab (in `tabs.js`).

---

## Die drei riskantesten Stellen

### 1. `recomputeGraph` + `_tempPinned` setTimeout-Race

**Datei:** `network.js`, Funktion `recomputeGraph()`

Beim Aufruf werden bestehende `_tempPinned`-Knoten zuerst entpinnt, dann neue gepinnt, und nach 500ms per `setTimeout` wieder freigegeben. Das `setTimeout` schließt eine `pinSnapshot`-Kopie ein.

**Problem:** Wenn `recomputeGraph` innerhalb von 500ms zweimal aufgerufen wird (z.B. schnelles Ziehen am Slider), laufen zwei `setTimeout`-Callbacks. Der erste Callback unpinnt Knoten anhand seines `pinSnapshot` — unabhängig davon was der zweite Aufruf bereits gesetzt hat. Das Ergebnis: Knoten die eigentlich gepinnt bleiben sollten werden vorzeitig freigegeben, der Graph "zuckt".

**Vorsichtsmaßnahme:** Slider `#net-minlinks` feuert nur auf `mouseup`, nicht auf `input`. Der Top-N-Slider feuert auf `input` — bei schnellem Ziehen kann das Race trotzdem auftreten.

---

### 2. `setHighlight` → `applyNetworkState` während Simulation läuft

**Dateien:** `highlight.js` → `network.js`

`setHighlight` ist synchron und ruft sofort `applyNetworkState()` auf. `applyNetworkState` mutiert D3 Selections (`.attr("opacity", ...)`, `.attr("stroke", ...)`). Die D3 Force-Simulation läuft asynchron und ruft bei jedem Tick `rerender()` auf, das ebenfalls auf dieselben Elemente schreibt (`.attr("transform", ...)`).

**Problem:** Wenn `setHighlight` während eines laufenden Sim-Ticks aufgerufen wird, überschreibt `rerender()` im nächsten Tick eventuell Attribute die `applyNetworkState` gerade gesetzt hat — oder umgekehrt. In der Praxis entsteht ein einziges visuell falsches Frame, das im nächsten Tick korrigiert wird. Sichtbar als kurzes Flackern bei gleichzeitigem Filtern und Entity-Klick.

**Vorsichtsmaßnahme:** `applyNetworkState` wird am Ende von `recomputeGraph()` explizit nochmals aufgerufen, sodass der finale Zustand konsistent ist.

---

### 3. Boot-Abhängigkeit: `netNodes`/`netLinks` in boot.js gesetzt, in network.js gelesen

**Dateien:** `boot.js` → `tabs.js` (Globals) → `network.js` (`drawNetwork`)

`netNodes`, `netLinks` und `entriesByActor` sind in `tabs.js` als leere Globals deklariert, werden in `boot.js`'s `Promise.all`-Boot befüllt, und von `drawNetwork` beim ersten Tab-Klick gelesen.

**Problem 1:** Wenn der Nutzer auf "Netzwerk" klickt bevor der Boot-Promise aufgelöst ist, ist `netNodes = []` und das Netzwerk zeichnet sich leer — ohne Fehlermeldung.

**Problem 2:** Wenn `entities_seed.csv` nicht erreichbar ist, liefert das `.catch(() => "")` einen leeren String an `buildAliasMap`. Das Ergebnis: `aliasMap` ist leer, alle Entitäts-Highlights im Panel fehlen schweigend.

**Problem 3:** `entities_summary.json` hat ebenfalls ein `.catch(() => ({}))`. Fehlt die Datei, ist `summaryMap` leer — Knoten im Netzwerk erscheinen gestrichelt (korrekt), aber im Panel erscheinen keine KI-Zusammenfassungen.

---

---

## Ingest-Pipeline

### Übersicht

```
DOCX-Datei
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

`extract_entities_v2.py` ist **nicht Teil von `ingest/run`** — wird separat über Wizard Step 6 oder CLI angestoßen.

---

### Pipeline-Schritte (Input → Output)

| Schritt | Skript | Input | Output |
|---------|--------|-------|--------|
| 1 | `parse_document.py` | DOCX-Datei | `segments.json` |
| 2 | `propose_taxonomy.py` | `segments.json` | `taxonomy_proposal.json` |
| 3 | `detect_anchors.py` | `segments.json` | `anchors.json` |
| 4 | `interpolate_anchors.py` | `anchors.json`, optional `overrides.json` | `anchors_interpolated.json` |
| 5 | `classify_segments.py` | `segments.json` + Taxonomie | `classified.json` |
| — | `extract_entities_v2.py` | `segments.json`, optional `entities_seed.json` | `entities_proposal.json` |
| 6 | `match_entities.py` | `segments.json` + `classified.json` + Entities | `classified.json` (+actors) |
| 7 | `export_preview.py` | `anchors_interpolated.json` + `classified.json` | `preview.html` |
| 8 | `export_exploration.py` | alle Doc-Outputs + `config.json` | `exploration/` |

Schritte 1–2 + 5–8 laufen via `ingest/run`. Schritt 2 (Taxonomy) hat einen eigenen Proposal-Step. Entity-Extraktion ist ein separater manueller Schritt.

---

### Dateistruktur (Projekt)

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
          taxonomy_proposal.json    LLM-Kategorienvorschlag
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

### Entity-Pipeline (4 LLM-Schritte)

`extract_entities_v2.py` orchestriert vier Schritte über `entity_llm.py`:

| Schritt | Funktion | Modus |
|---------|----------|-------|
| 1 — Stichprobe | `_llm_sample_iteration` | immer (50 zufällige Segmente) |
| 2 — Vollextraktion | `_llm_full_extract` | nur `--mode full` + Seed vorhanden |
| 3 — Dedup | `_llm_dedup` | immer; alle Kandidatenpaare in einem LLM-Request |
| 4 — Normalform | `_llm_task1_normalize` | immer; Batches à 20, Retry + Fallback |

Checkpoint/Resume: Schritt 2 hat Sub-Batch-Resume (`step2_batch`/`step2_entities`). Schritte 1, 3, 4 über `_run_stage` (per-Step-Checkpoint).

Merge-Priorität bei Konflikten (`SOURCE_PRIORITY`): seed > llm > classifier/embedding.

---

### LLM-Provider-Abstraktion

`src/generalized/llm.py` — einheitliche Schnittstelle für alle Pipeline-Schritte:

```python
provider = get_provider(task=TASK_EXTRACT)   # liest LLM_PROVIDER + Modell-Override aus .env
text = provider.complete(prompt, system="…")
data = provider.complete_json(prompt, system="…")   # parst JSON automatisch
```

| Provider | Default-Modell | `max_concurrency` |
|----------|----------------|-------------------|
| `ollama` | `OLLAMA_MODEL` aus `.env` | 1 |
| `anthropic` | `claude-haiku-4-5-20251001` | 10 |

`complete_json` entfernt Code-Fences, überspringt führende Prosa, verwendet `json.JSONDecoder.raw_decode`.

---

## Dateistruktur (viz/)

```
viz/
  index.html           HTML-Struktur: #left-col (header + chart/network) | #panel
  style.css            Alle Styles; kein CSS-in-JS außer tutorial.js
  highlight.js         Konstanten, aliasMap, Highlight-State + setHighlight(), highlightEntities()
  panel.js             View-Stack, Panel-Navigation, renderParaCard(), selectEntity(), Tooltip
  chart.js             drawChart(), _applyChartEntityHighlight()
  utils.js             pairKey()
  tabs.js              Tab-State, geteilte Daten-Globals (netNodes/netLinks/entriesByActor), switchTab()
  network.js           applyNetworkState(), drawNetwork(), recomputeGraph()
  search.js            sendChat(), fulltextSearch(), renderChatAnswer()
  boot.js              App-Initialisierung: Daten laden, Timeline + Netzwerk aufbauen
  tutorial.js          Tutorial-Overlay, STEPS, tutorialStart()
```
