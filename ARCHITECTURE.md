# BER Chronik — Architektur

> Lies diese Datei vor jeder Änderung am viz/-Code. Sie beschreibt welche Funktionen welchen State setzen, welche Event-Handler welche Funktionen aufrufen, und wo die drei riskantesten Stellen im Code sind.

---

## Überblick

Alle JS-Dateien laufen im **globalen Browser-Scope** — keine Module, kein Build-Tool. Ladereihentolge in `index.html` ist zwingend:

```
highlight-state.js  → deklariert globale State-Variablen
highlight.js        → deklariert Hilfsfunktionen und Konstanten
panel.js            → deklariert View-State und Panel-Logik
chart.js            → deklariert drawChart
network.js          → deklariert drawNetwork, recomputeGraph
search.js           → Boot: lädt Daten, baut alle Strukturen, ruft drawChart
tutorial.js         → verdrahtet Tutorial-Button
```

---

## Globaler State

### highlight-state.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `hlState` | `{mode, anchors, active, focusEntity}` | Zentraler Highlight-Zustand. `mode`: `"none"` / `"answer"` / `"single"`. `anchors`: Set von doc_anchor-Strings. `active`: einzelner doc_anchor. `focusEntity`: Entitätsname. |
| `selectedEntity` | `string \| null` | Aktuell geöffnete Entität im Panel |
| `netNodeSelection` | D3 selection | D3-Auswahl aller Netzwerk-Knoten. `null` bis `drawNetwork` aufgerufen. |
| `netNeighbors` | `Map<id, Set<id>>` | Nachbarschaftsgraph (alle Links, unabhängig von Filtern) |
| `actorsByAnchor` | `Map<anchor, Set<name>>` | doc_anchor → Akteursnamen |
| `chartDotSelection` | D3 selection | D3-Auswahl aller Timeline-Punkte. Wird bei jedem `drawChart` neu gesetzt. |
| `DIM` | `0.35` | Konstante: Opacity für gedimmte Elemente |

### highlight.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `aliasMap` | `{[alias]: {normalform, typ}}` | Alias → kanonischer Name + Typ |
| `aliasesSorted` | `string[]` | Aliase absteigend nach Länge sortiert (für Regex-Matching) |
| `summaryMap` | `{[name]: {summary, count}}` | KI-Zusammenfassungen pro Entität |
| `EVENT_TYPES` | `string[]` | Vollständige Liste der Ereignistypen |
| `COLOR` | `{[type]: hex}` | Farbe pro Ereignistyp |
| `NODE_COLOR` | `{[typ]: hex}` | Farbe pro Entitätstyp (Person/Org/Gremium/Partei) |

### network.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `netFocusNode` | `string \| null` | ID des Ego-Knotens. Wenn gesetzt: Ego-Graph-Modus |
| `netFocusPair` | `{key, sid, tid} \| null` | Fokussiertes Knotenpaar. Wenn gesetzt: Edge-Focus-Modus |
| `activeNetThemes` | `Set<string>` | Aktuell sichtbare Ereignistypen (Legende = Filter) |
| `activeNodeTypes` | `Set<string>` | Aktuell sichtbare Entitätstypen |
| `netLinkSelection` | D3 selection | D3-Auswahl der sichtbaren Links |
| `_networkLayout` | object \| null | Vorberechnete Knotenpositionen (aus `layout.json`) |
| `networkDrawn` | boolean | True nach erstem `drawNetwork`-Aufruf |
| `netNodes` | `Node[]` | Alle Knoten (gesetzt in search.js Boot) |
| `netLinks` | `Link[]` | Alle Links (gesetzt in search.js Boot) |
| `entriesByActor` | `Map<name, Entry[]>` | Akteur → zugehörige Einträge |

### panel.js
| Variable | Typ | Bedeutung |
|---|---|---|
| `viewStack` | `View[]` | Stack für Back-Navigation. Jeder Eintrag hat `{type, title, renderFn, entityKey, hlSnapshot}` |
| `currentView` | `View` | Aktuell angezeigte View |
| `panelExpanded` | boolean | Ob Panel auf 2/3 Breite expandiert |
| `activeDot` | DOM element \| null | Aktuell aktiver Timeline-Punkt |
| `dimmedTypes` | `Set<string>` | Ausgeblendete Ereignistypen (Timeline-Legende) |

---

## State-Mutationen: wer setzt was

### `hlState` — nur über `setHighlight()`
```
sendChat()           → setHighlight("answer", anchors)
dot click            → setHighlight("answer", anchorSet, anchor, null)
entity click         → setHighlight("single", anchors, anchor, entity)
goHome()             → setHighlight("none")
goBack()             → setHighlight(snapshot.mode, ...)
tutorial step        → setHighlight("answer", anchors, null, "Hartmut Mehdorn")
hit-line click       → setHighlight("answer", sharedAnchors, null, null)
```
`setHighlight` ruft immer synchron `_applyHighlight()` → `_applyTimelineHighlight()` + `applyNetworkState()`.

### `selectedEntity` — über `selectEntity()`
```
node click           → selectEntity(id)          (network.js)
entity span click    → selectEntity(normalform)   (panel.js, via #panel-content click)
tutorial action      → selectEntity(node.id)
```
`selectEntity` ruft `showView("entity", ...)` und `setHighlight("single", ...)`.

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
  → setHighlight("answer", anchorSet)
    → _applyHighlight()
      → _applyTimelineHighlight()   (dimmt/hebt Punkte)
      → applyNetworkState()          (Netzwerk-Overlay)
```

### Entitäts-Span im Panel klicken
```
#panel-content.click (delegiert)
  → selectEntity(normalform)
    → showView("entity", name, renderEntityView)
    → setHighlight("single", anchors, null, name)
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
  → (falls nicht chat view) showView("chat", ...)
  → setHighlight("none")
  → fetch API stream ODER fulltextSearch()
  → renderChatAnswer()
    → highlightEntities() auf Quell-Paragraphen
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

## applyNetworkState — State Machine

Wird direkt aus `_applyHighlight()` und aus network.js-Handlern aufgerufen. Vier exklusive Modi, geprüft in dieser Reihenfolge:

1. **Ego-Graph** (`netFocusNode !== null`) — fokussiert Nachbarn eines Knotens
2. **Edge-Focus** (`netFocusPair !== null`) — fokussiert ein Knotenpaar und ihre Links
3. **Default** (`mode === "none"` oder keine Anchors) — alle Knoten/Links voll sichtbar
4. **KI-Subgraph** — hebt Akteure aus `hlState.anchors` hervor

Wichtig: `applyNetworkState` liest `netFocusNode`, `netFocusPair`, `hlState`, `activeNetThemes` alle gleichzeitig. Wenn mehrere davon gesetzt sind, gewinnt immer die **erste** Bedingung.

---

## Boot-Sequenz (search.js)

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
`drawNetwork` wird **nicht** beim Boot aufgerufen — erst beim ersten Klick auf den Netzwerk-Tab.

---

## Die drei riskantesten Stellen

### 1. `recomputeGraph` + `_tempPinned` setTimeout-Race

**Datei:** `network.js`, Funktion `recomputeGraph()`

Beim Aufruf werden bestehende `_tempPinned`-Knoten zuerst entpinnt, dann neue gepinnt, und nach 500ms per `setTimeout` wieder freigegeben. Das `setTimeout` schließt eine `pinSnapshot`-Kopie ein.

**Problem:** Wenn `recomputeGraph` innerhalb von 500ms zweimal aufgerufen wird (z.B. schnelles Ziehen am Slider), laufen zwei `setTimeout`-Callbacks. Der erste Callback unpinnt Knoten anhand seines `pinSnapshot` — unabhängig davon was der zweite Aufruf bereits gesetzt hat. Das Ergebnis: Knoten die eigentlich gepinnt bleiben sollten werden vorzeitig freigegeben, der Graph "zuckt".

**Vorsichtsmaßnahme:** Slider `#net-minlinks` feuert nur auf `mouseup`, nicht auf `input`. Der Top-N-Slider feuert auf `input` — bei schnellem Ziehen kann das Race trotzdem auftreten.

---

### 2. `setHighlight` → `applyNetworkState` während Simulation läuft

**Dateien:** `highlight-state.js` → `network.js`

`setHighlight` ist synchron und ruft sofort `applyNetworkState()` auf. `applyNetworkState` mutiert D3 Selections (`.attr("opacity", ...)`, `.attr("stroke", ...)`). Die D3 Force-Simulation läuft asynchron und ruft bei jedem Tick `rerender()` auf, das ebenfalls auf dieselben Elemente schreibt (`.attr("transform", ...)`).

**Problem:** Wenn `setHighlight` während eines laufenden Sim-Ticks aufgerufen wird, überschreibt `rerender()` im nächsten Tick eventuell Attribute die `applyNetworkState` gerade gesetzt hat — oder umgekehrt. In der Praxis entsteht ein einziges visuell falsches Frame, das im nächsten Tick korrigiert wird. Sichtbar als kurzes Flackern bei gleichzeitigem Filtern und Entity-Klick.

**Vorsichtsmaßnahme:** `applyNetworkState` wird am Ende von `recomputeGraph()` explizit nochmals aufgerufen, sodass der finale Zustand konsistent ist.

---

### 3. Boot-Abhängigkeit: `netNodes`/`netLinks` in search.js gesetzt, in network.js gelesen

**Dateien:** `search.js` (Boot) → `network.js` (`drawNetwork`)

`netNodes`, `netLinks` und `entriesByActor` sind in `network.js` als leere Globals deklariert, werden aber in `search.js`'s `Promise.all`-Boot befüllt. `drawNetwork` liest diese Variablen beim ersten Tab-Klick.

**Problem 1:** Wenn der Nutzer auf "Netzwerk" klickt bevor der Boot-Promise aufgelöst ist, ist `netNodes = []` und das Netzwerk zeichnet sich leer — ohne Fehlermeldung.

**Problem 2:** Wenn `entities_seed.csv` nicht erreichbar ist, liefert das `.catch(() => "")` einen leeren String an `buildAliasMap`. Das Ergebnis: `aliasMap` ist leer, alle Entitäts-Highlights im Panel fehlen schweigend. Kein Error, kein Warning.

**Problem 3:** `entities_summary.json` hat ebenfalls ein `.catch(() => ({}))`. Fehlt die Datei, ist `summaryMap` leer — Knoten im Netzwerk erscheinen gestrichelt (korrekt), aber im Panel erscheinen keine KI-Zusammenfassungen.

---

## Dateistruktur

```
viz/
  index.html           HTML-Struktur: #left-col (header + chart/network) | #panel
  style.css            Alle Styles; kein CSS-in-JS außer tutorial.js
  highlight-state.js   Globaler State + setHighlight() + _applyHighlight()
  highlight.js         Konstanten, aliasMap, highlightEntities()
  panel.js             View-Stack, Panel-Navigation, selectEntity(), Tooltip
  chart.js             drawChart(), Timeline-Dots, _applyChartEntityHighlight()
  network.js           drawNetwork(), recomputeGraph(), applyNetworkState()
  search.js            Boot, sendChat(), fulltextSearch(), renderChatAnswer()
  tutorial.js          Tutorial-Overlay, STEPS, tutorialStart()
```
