# Playwright – Setup & Erkenntnisse

## Server starten

Die Tests laufen gegen einen lokalen HTTP-Server. Vor jedem Testlauf starten:

```bash
python3 -m http.server 8765
```

aus dem **Projektroot** (nicht aus `viz/`). Die App ist dann unter `http://localhost:8765/viz/` erreichbar.

Der Pre-commit-Hook prüft automatisch ob der Server läuft und überspringt die Tests wenn nicht (`exit 0`).

---

## Tests ausführen

```bash
npm test
# oder direkt:
npx playwright test
```

Mit UI-Report nach dem Lauf:

```bash
npx playwright show-report
```

---

## Wichtige Konfiguration (`playwright.config.js`)

```js
workers: 1,   // Tests laufen sequenziell — sie teilen sich denselben laufenden Server
              // und greifen auf dieselbe globale App-State zu

use: {
  baseURL: 'http://localhost:8765/viz/',  // wird von goto('/') NICHT korrekt aufgelöst (siehe unten)
  headless: true,
  viewport: { width: 1280, height: 800 },
}
```

---

## Probleme und ihre Lösungen

### 1. `goto('/')` navigiert nicht zur App

**Problem:** Playwright löst `goto('/')` relativ zur *Origin* auf (`http://localhost:8765/`), nicht zur `baseURL` (`http://localhost:8765/viz/`). Die App-Seite liegt aber in `/viz/`, sodass die Tests auf einer leeren oder falschen Seite landen.

**Lösung:** In `waitForBoot()` immer die vollständige URL angeben:

```js
await page.goto('http://localhost:8765/viz/');
```

---

### 2. Tutorial-Overlay blockiert Klicks

**Problem:** Die App startet automatisch das Tutorial-Overlay (nach 600 ms) als `position:fixed; z-index:2000`-Element. Es intercept alle Pointer-Events, sodass Klicks auf Dots und andere Elemente nie ankommen.

**Lösung:** `addInitScript` injiziert localStorage-State *bevor* die Seite-Skripte laufen:

```js
async function waitForBoot(page) {
  await page.addInitScript(() => localStorage.setItem('tutorial_seen', '1'));
  await page.goto('http://localhost:8765/viz/');
  // ...
}
```

`localStorage.setItem` direkt nach `goto` wäre zu spät — die Skripte laufen sofort nach dem Laden.

---

### 3. Überlappende SVG-Elemente blockieren Klick-Hit-Testing

**Problem:** Mehrere `circle.dot`-Elemente liegen am selben x-Koordinate übereinander. Playwright verweigert den Klick wenn das Ziel-Element nicht das oberste im Stacking Order ist (`Element is not clickable at point`).

**Lösung:** `{ force: true }` bypasst Playwright's Klick-Heuristik und schickt das Event direkt ans Element:

```js
await page.locator('circle.dot').first().click({ force: true });
```

Dasselbe gilt für transparente Hit-Areas bei Netzwerk-Kanten (`line[stroke="transparent"]`).

---

### 4. Versteckte Elemente aus inaktiven Views

**Problem:** Das Panel hält drei Views gleichzeitig im DOM (`view-chat`, `view-timeline`, `view-entity`). Inaktive Views haben `display: none`. Ein Locator wie `#panel-content .ep-para` findet `.ep-para`-Elemente der *vorherigen* (jetzt versteckten) View zuerst und schlägt mit `hidden` fehl.

**Lösung:** Locator auf die aktive View einschränken:

```js
page.locator('.panel-view.active .ep-summary, .panel-view.active .ep-para').first()
```

---

## Pre-commit-Hook

`.git/hooks/pre-commit` führt die Tests automatisch aus wenn der Server läuft. Commit läuft durch wenn der Server nicht erreichbar ist (striktes Blockieren wäre zu viel Reibung im lokalen Entwicklungsworkflow).

Um den Hook zu umgehen (z.B. bei WIP-Commits):

```bash
git commit --no-verify
```
