# BER Chronik — Designentscheidungen

Designentscheidungen die nicht aus dem Code hervorgehen. Warum etwas so ist wie es ist.

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
