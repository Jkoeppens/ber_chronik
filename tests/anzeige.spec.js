// @ts-check
/**
 * anzeige.spec.js — die vier Anzeigefehler aus Schritt D
 *
 * Anders als hervorheben.spec.js hält diese Datei fest, was RICHTIG ist, nicht
 * was war: jeder Test hier prüft eine Änderung, die absichtlich am Verhalten
 * gemacht wurde.
 *
 * Gelaufen wird gegen data/exporte/pruefstueck/ (ber, 949 Einträge, 7
 * Kategorien, Spanne 1989–2017) und teils gegen data/exporte/damaskus/
 * (215 Jahre, 216 Bins) — der Fall, an dem die Beschriftungsdichte auffiel.
 */
import { test, expect } from '@playwright/test';

const PRUEFSTUECK = '/viz/?project=pruefstueck';
const DAMASKUS    = '/viz/?project=damaskus';

async function laden(page, adresse = PRUEFSTUECK) {
  await page.addInitScript(() => localStorage.setItem('tutorial_seen', '1'));
  await page.goto(adresse);
  await page.locator('circle.dot').first().waitFor({ state: 'visible', timeout: 20_000 });
}

/** Die Jahreszahlen an der x-Achse. */
async function achsenbeschriftung(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll('#chart g.axis')]
      .map(g => [...g.querySelectorAll('text')].map(t => t.textContent))
      .find(a => a.some(s => /\d{4}/.test(s))) ?? []);
}

// ── 1 · Beschriftungsdichte ───────────────────────────────────────────────────

test('D1 · die Zeitachse bekommt etwa sechs Beschriftungen, nicht eine je Bin',
  async ({ page }) => {
    await laden(page);
    const ticks = await achsenbeschriftung(page);
    // 1989–2017 sind 29 Bins. Vorher: 29 Beschriftungen.
    expect(ticks.length).toBeLessThanOrEqual(8);
    expect(ticks.length).toBeGreaterThanOrEqual(4);
    expect(ticks).toEqual(['1990', '1995', '2000', '2005', '2010', '2015']);
  });

test('D1 · auch bei 216 Bins — der Fall, an dem es auffiel', async ({ page }) => {
  await laden(page, DAMASKUS);
  const ticks = await achsenbeschriftung(page);
  // damaskus: 1780–1995, 216 Bins auf rund 900 Pixel, 147 Punkte.
  expect(ticks.length).toBeLessThanOrEqual(8);
  expect(ticks).toEqual(['1800', '1850', '1900', '1950']);
});

test('D1 · beim Zoom kommt die Zielzahl aus der SICHTBAREN Spanne',
  async ({ page }) => {
    // Stünde dort die ganze Domäne, spränge die Achse beim ersten Zoom auf
    // die alte Dichte zurück — genau der Grund, warum beide Aufrufstellen
    // geändert werden mussten.
    await laden(page);
    const vorher = await achsenbeschriftung(page);

    await page.locator('svg#chart').hover();
    for (let i = 0; i < 8; i++) await page.mouse.wheel(0, -120);
    await page.waitForTimeout(400);
    const nachher = await achsenbeschriftung(page);

    expect(nachher.length).toBeLessThanOrEqual(8);
    // Hineingezoomt: engerer Ausschnitt, andere Jahre, feinere Schrittweite.
    expect(nachher).not.toEqual(vorher);
    const schritt = Number(nachher[1]) - Number(nachher[0]);
    const schrittVorher = Number(vorher[1]) - Number(vorher[0]);
    expect(schritt).toBeLessThan(schrittVorher);
  });

// ── 2 · Farben aus dem Namen ──────────────────────────────────────────────────

test('D2 · der Export liefert keine Farben mehr', async ({ page }) => {
  const antwort = await page.request.get('/data/exporte/pruefstueck/project_meta.json');
  const meta = await antwort.json();
  expect(Object.keys(meta).sort()).toEqual(
    ['taxonomy', 'title', 'year_max', 'year_min']);
  expect(JSON.stringify(meta)).not.toMatch(/#[0-9a-fA-F]{6}/);
});

test('D2 · viz/ vergibt jeder Kategorie eine eigene Farbe', async ({ page }) => {
  await laden(page);
  const { kategorien, farben } = await page.evaluate(() => ({
    kategorien: EVENT_TYPES,
    farben: EVENT_TYPES.map(k => COLOR[k]),
  }));
  expect(kategorien.length).toBe(7);
  expect(farben.every(f => /^#[0-9a-f]{6}$/i.test(f))).toBe(true);
  expect(new Set(farben).size).toBe(kategorien.length);   // keine Dublette
});

test('D2 · die Farbe hängt am Namen, nicht an der Position', async ({ page }) => {
  await laden(page);
  const gleich = await page.evaluate(() => {
    const namen = ['Alpha', 'Beta', 'Gamma'];
    const a = farbzuordnung(namen);
    const b = farbzuordnung([...namen].reverse());
    return namen.every(n => a[n] === b[n]);
  });
  expect(gleich).toBe(true);
});

test('D2 · eine Kategorie in der Mitte zu löschen verschiebt die übrigen nicht',
  async ({ page }) => {
    // Der eigentliche Zweck der Änderung. Vollständig verschiebungsfrei ist
    // nur eine reine Funktion des Namens, und die kollidiert (siehe den
    // Kommentar in highlight.js). Deshalb hier die messbare Zusage: es wandert
    // höchstens eine, statt aller nachfolgenden.
    await laden(page);
    const gewandert = await page.evaluate(() => {
      const namen = EVENT_TYPES;
      const vorher = farbzuordnung(namen);
      const ohne = namen.filter((_, i) => i !== 3);
      const nachher = farbzuordnung(ohne);
      return ohne.filter(n => vorher[n] !== nachher[n]);
    });
    expect(gewandert.length).toBeLessThanOrEqual(1);
  });

test('D2 · Akteurstypen kommen aus dem festen Wertevorrat', async ({ page }) => {
  await laden(page);
  const typen = await page.evaluate(() => Object.keys(NODE_COLOR));
  expect(typen.sort()).toEqual(['Konzept', 'Organisation', 'Ort', 'Person']);
});

// ── 3 · Monatsnamen ───────────────────────────────────────────────────────────

test('D3 · %b schreibt Mai, nicht May', async ({ page }) => {
  // Greift erst bei 350 bis 1500 Tagen Spanne — kein vorhandenes Projekt ist
  // so kurz, der Fall wäre also unsichtbar. Deshalb hier über _fmtBinDate
  // selbst, mit gesetztem Bin-Intervall.
  await laden(page);
  const beschriftungen = await page.evaluate(() => {
    const gemerkt = window._binInterval;
    window._binInterval = d3.timeMonth;
    const aus = [0, 4, 11].map(m => _fmtBinDate(new Date(2013, m, 1)));
    window._binInterval = gemerkt;
    return aus;
  });
  expect(beschriftungen).toEqual(['Jan 2013', 'Mai 2013', 'Dez 2013']);
});

test('D3 · die Lokalisierung gilt für jedes timeFormat auf der Seite',
  async ({ page }) => {
    await laden(page);
    const namen = await page.evaluate(() => ({
      monat: d3.timeFormat('%B')(new Date(2013, 2, 1)),
      tag:   d3.timeFormat('%A')(new Date(2013, 2, 4)),
    }));
    expect(namen.monat).toBe('März');
    expect(namen.tag).toBe('Montag');
  });

// ── 4 · Layout, Fehler und Rennen ─────────────────────────────────────────────

test('D4 · drawNetwork wartet auf das Layout, statt zu streuen', async ({ page }) => {
  // Der Abruf wird künstlich verzögert. Vorher hätte der Reiterklick in dieser
  // Zeit mit der Kraftsimulation gezeichnet; jetzt kommen die vorberechneten
  // Positionen an.
  await page.route('**/network_layout.json*', async route => {
    await new Promise(r => setTimeout(r, 1200));
    await route.continue();
  });
  await laden(page);
  await page.locator('#tab-network').click();
  await page.locator('#network g[cursor="pointer"]').first()
    .waitFor({ state: 'visible', timeout: 20_000 });

  const geladen = await page.evaluate(() => !!(_networkLayout && _networkLayout.nodes));
  expect(geladen).toBe(true);
});

test('D4 · ein fehlendes Layout wird gemeldet, nicht verschluckt', async ({ page }) => {
  const warnungen = [];
  page.on('console', m => { if (m.type() === 'warning') warnungen.push(m.text()); });
  await page.route('**/network_layout.json*', route => route.fulfill({ status: 404 }));

  await laden(page);
  await page.locator('#tab-network').click();
  await page.locator('#network g[cursor="pointer"]').first()
    .waitFor({ state: 'visible', timeout: 20_000 });

  const netz = warnungen.filter(w => w.includes('network_layout.json'));
  expect(netz.length).toBeGreaterThan(0);
  // Die Meldung nennt die Folge, nicht nur den Fehler.
  expect(netz[0]).toMatch(/Kraftsimulation|gestreut/);
  // Und das Netz wird trotzdem gezeichnet.
  expect(await page.locator('#network g[cursor="pointer"]').count()).toBeGreaterThan(0);
});
