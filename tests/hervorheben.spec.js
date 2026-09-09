// @ts-check
/**
 * hervorheben.spec.js — das Netz unter der Hervorhebung
 *
 * Zwölf Fälle, jeder gegen alle drei Ansichten: Zeitachse, Netzwerk, Panel.
 * Die vorhandenen sechs Tests in viz.spec.js prüfen ausschließlich den
 * Paneltitel — sie wären grün, auch wenn das Hervorheben vollständig kaputt
 * wäre.
 *
 * WAS IST, NICHT WAS RICHTIG WÄRE. Vier der Fälle halten Merkwürdigkeiten
 * fest, die niemand so entworfen hat (sie sind unten je einzeln benannt). Sie
 * stehen hier, damit ein Umbau sie sichtbar macht statt sie stillschweigend
 * mitzunehmen. Wer eine davon behebt, ändert den Test — und begründet es dabei.
 *
 * Gelaufen wird gegen data/exporte/pruefstueck/, einen eingefrorenen
 * ber-Export. Die Zahlen unten hängen an ihm; ändert er sich, schlägt
 * tests/test_neu_pruefstueck.py an, bevor hier etwas rätselhaft wird.
 *
 * Zum Klicken im Netzwerk durchweg dispatchEvent statt click(): ein echter
 * Mausklick wird über Bildschirmkoordinaten aufgelöst, und die durchsichtige
 * Trefferlinie einer Kante liegt oft unter einem Knoten. Gemessen: ein echter
 * Klick auf die erste Kante landete auf dem Knoten 'Lütke Daldrup'. Das ist
 * ein echter Mangel der Fläche, aber keiner der Hervorhebung — Fall 12 hält
 * ihn getrennt fest.
 */
import { test, expect } from '@playwright/test';

const PRUEFSTUECK = '/viz/?project=pruefstueck';

/** Der ganze sichtbare Zustand auf einmal — alle drei Ansichten. */
async function zustand(page) {
  return page.evaluate(() => ({
    // Zustandsmaschine
    mode:   hlState.mode,
    anker:  hlState.anchors ? hlState.anchors.size : null,
    active: hlState.active,
    focus:  hlState.focusEntity,
    // Netzwerk — nicht Teil von hlState, schlägt es aber in vier Zweigen
    netFocusNode: typeof netFocusNode !== 'undefined' ? netFocusNode : undefined,
    netFocusPair: typeof netFocusPair !== 'undefined' && netFocusPair ? netFocusPair.key : null,
    // Zeitachse
    punkte:   document.querySelectorAll('circle.dot').length,
    gedimmt:  [...document.querySelectorAll('circle.dot')]
                .filter(d => d.getAttribute('opacity') === '0.35').length,
    gross:    [...document.querySelectorAll('circle.dot')]
                .filter(d => +d.getAttribute('r') >= 7).length,
    gold:     [...document.querySelectorAll('circle.dot')]
                .filter(d => d.getAttribute('stroke') === '#f5c518').length,
    // Panel
    titel:    document.getElementById('panel-title').textContent,
    ansicht:  [...document.querySelectorAll('.panel-view')]
                .find(e => e.classList.contains('active'))?.id,
    karten:   document.querySelectorAll('#panel-content .ep-para').length,
  }));
}

async function laden(page) {
  await page.addInitScript(() => localStorage.setItem('tutorial_seen', '1'));
  await page.goto(PRUEFSTUECK);
  await page.locator('circle.dot').first().waitFor({ state: 'visible', timeout: 20_000 });
}

async function netzOeffnen(page) {
  await page.locator('#tab-network').click();
  await page.locator('#network g[cursor="pointer"]').first()
    .waitFor({ state: 'visible', timeout: 20_000 });
}

const klick = (ort) => ort.dispatchEvent('click', { bubbles: true, cancelable: true });

// ── 1 · Ausgangszustand ───────────────────────────────────────────────────────

test('1 · frisch geladen ist nichts hervorgehoben', async ({ page }) => {
  await laden(page);
  const z = await zustand(page);

  expect(z.mode).toBe('none');
  expect(z.anker).toBeNull();
  expect(z.netFocusNode).toBeNull();
  expect(z.netFocusPair).toBeNull();
  // Zeitachse: alle Punkte in Ruhe
  expect(z.punkte).toBeGreaterThan(100);
  expect(z.gedimmt).toBe(0);
  expect(z.gross).toBe(0);
  expect(z.gold).toBe(0);
  // Panel: Suche
  expect(z.titel).toBe('Suche');
  expect(z.ansicht).toBe('view-chat');
});

// ── 2 · Zeitachsenpunkt ───────────────────────────────────────────────────────

test('2 · Klick auf einen Punkt hebt seinen Anker hervor und dimmt den Rest',
  async ({ page }) => {
    await laden(page);
    await page.locator('circle.dot').first().click({ force: true });
    const z = await zustand(page);

    expect(z.mode).toBe('answer');
    expect(z.anker).toBeGreaterThan(0);
    expect(z.active).toBeNull();          // kein einzelner Absatz im Fokus
    // Zeitachse: der Punkt groß, viele andere gedimmt
    expect(z.gross).toBeGreaterThan(0);
    expect(z.gedimmt).toBeGreaterThan(50);
    expect(z.gold).toBe(0);
    // Netzwerk: unberührt
    expect(z.netFocusNode).toBeNull();
    expect(z.netFocusPair).toBeNull();
    // Panel: Jahr · Kategorie, mit Karten
    expect(z.titel).toContain('·');
    expect(z.ansicht).toBe('view-timeline');
    expect(z.karten).toBeGreaterThan(0);
  });

// ── 3 · Mehrfachauswahl ───────────────────────────────────────────────────────

test('3 · MERKWÜRDIG — ein zweiter Punktklick ersetzt, er vereinigt nicht',
  async ({ page }) => {
    // Wer zwei Punkte anklickt, erwartet beide hervorgehoben. Der zweite
    // Klick wirft die Auswahl des ersten weg. Eine Mehrfachauswahl gibt es
    // nicht — das ist kein Fehler im Code, sondern eine fehlende Möglichkeit.
    await laden(page);
    const punkte = page.locator('circle.dot');
    const anker = () => page.evaluate(() => [...(hlState.anchors ?? [])]);

    await punkte.nth(0).click({ force: true });
    const erst = await anker();
    const erstZ = await zustand(page);
    await punkte.nth(5).click({ force: true });
    const dann = await anker();
    const dannZ = await zustand(page);

    expect(erstZ.mode).toBe('answer');
    expect(dannZ.mode).toBe('answer');
    expect(erst.length).toBeGreaterThan(0);
    expect(dann.length).toBeGreaterThan(0);
    expect(dannZ.titel).not.toBe(erstZ.titel);

    // Der Beweis: kein einziger Anker des ersten Klicks ist noch dabei.
    // Eine Vereinigung enthielte sie alle.
    expect(dann.filter(a => erst.includes(a))).toEqual([]);
    expect(dann.length).toBeLessThan(erst.length + dann.length);
    expect(dannZ.ansicht).toBe('view-timeline');
  });

// ── 4 · Absatzkarte im Panel ──────────────────────────────────────────────────

test('4 · Klick auf eine Karte schaltet auf single und setzt einen goldenen Punkt',
  async ({ page }) => {
    await laden(page);
    await page.locator('circle.dot').first().click({ force: true });
    await page.locator('#panel-content .ep-para').first().waitFor({ state: 'visible' });
    await page.locator('#panel-content .ep-para').first().click();
    const z = await zustand(page);

    expect(z.mode).toBe('single');
    expect(z.active).toBeTruthy();        // genau ein Absatz im Fokus
    expect(z.active).toContain('-e');     // Ankerform des neuen Exports
    // Zeitachse: der Fokuspunkt gold umrandet
    expect(z.gold).toBe(1);
    expect(z.gross).toBeGreaterThan(0);
    // Netzwerk: unberührt
    expect(z.netFocusNode).toBeNull();
    expect(z.netFocusPair).toBeNull();
    // Panel: bleibt auf derselben Liste
    expect(z.ansicht).toBe('view-timeline');
  });

// ── 5 · Entitätsname im Panel ─────────────────────────────────────────────────

test('5 · Klick auf einen Namen im Text öffnet den Akteur in allen drei Ansichten',
  async ({ page }) => {
    await laden(page);
    await page.locator('circle.dot').first().click({ force: true });
    await page.locator('#panel-content .ep-para').first().waitFor({ state: 'visible' });

    const span = page.locator('#panel-content .entity').first();
    test.skip(await span.count() === 0, 'keine Entität in der ersten Karte');
    const name = await span.getAttribute('data-name');
    await span.click();
    const z = await zustand(page);

    expect(z.mode).toBe('answer');
    expect(z.focus).toBe(name);
    // Netzwerk: derselbe Akteur wird zum Ego-Knoten
    expect(z.netFocusNode).toBe(name);
    expect(z.netFocusPair).toBeNull();
    // Zeitachse: alle Absätze dieses Akteurs hervorgehoben
    expect(z.anker).toBeGreaterThan(1);
    expect(z.gross).toBeGreaterThan(1);
    // Panel: Akteursansicht
    expect(z.titel).toBe(name);
    expect(z.ansicht).toBe('view-entity');
  });

// ── 6 · Netzknoten ────────────────────────────────────────────────────────────

test('6 · Klick auf einen Knoten setzt den Ego-Knoten und hebt seine Absätze hervor',
  async ({ page }) => {
    await laden(page);
    await netzOeffnen(page);
    const knoten = page.locator('#network g[cursor="pointer"]').first();
    const name = (await knoten.locator('text').textContent())?.trim();
    await klick(knoten);
    const z = await zustand(page);

    expect(z.mode).toBe('answer');
    expect(z.netFocusNode).toBe(name);
    expect(z.netFocusPair).toBeNull();
    expect(z.focus).toBe(name);
    // Zeitachse: die Absätze des Akteurs
    expect(z.anker).toBeGreaterThan(1);
    expect(z.gross).toBeGreaterThan(1);
    // Panel: Akteursansicht unter seinem Namen
    expect(z.titel).toBe(name);
    expect(z.ansicht).toBe('view-entity');
  });

// ── 7 · Netzkante ─────────────────────────────────────────────────────────────

test('7 · Klick auf eine Kante setzt das Paar und zeigt die gemeinsamen Absätze',
  async ({ page }) => {
    await laden(page);
    await netzOeffnen(page);
    await klick(page.locator('#network line[stroke="transparent"]').first());
    const z = await zustand(page);

    expect(z.mode).toBe('answer');
    expect(z.netFocusPair).toBeTruthy();
    expect(z.netFocusNode).toBeNull();
    expect(z.focus).toBeNull();
    // Zeitachse: die gemeinsamen Absätze
    expect(z.anker).toBeGreaterThan(0);
    expect(z.gross).toBeGreaterThan(0);
    // Panel: 'A + B · alle Verbindungen'
    expect(z.titel).toContain('+');
    expect(z.titel).toContain('·');
    expect(z.ansicht).toBe('view-timeline');
  });

// ── 8 · Kante nach Knoten ─────────────────────────────────────────────────────

test('8 · eine Kante nach einem Knoten löst den Ego-Knoten wieder', async ({ page }) => {
    await laden(page);
    await netzOeffnen(page);
    await klick(page.locator('#network g[cursor="pointer"]').first());
    const vorher = await zustand(page);
    expect(vorher.netFocusNode).toBeTruthy();

    await klick(page.locator('#network line[stroke="transparent"]').first());
    const z = await zustand(page);

    expect(z.netFocusNode).toBeNull();     // gelöst
    expect(z.netFocusPair).toBeTruthy();   // Paar tritt an seine Stelle
    expect(z.focus).toBeNull();
    expect(z.mode).toBe('answer');
    expect(z.ansicht).toBe('view-timeline');
  });

// ── 9 · Leere Zeitachse ───────────────────────────────────────────────────────

test('9 · Klick auf die leere Zeitachse nimmt alles zurück', async ({ page }) => {
  await laden(page);
  await page.locator('circle.dot').first().click({ force: true });
  await page.locator('#panel-content .ep-para').first().waitFor({ state: 'visible' });
  await page.locator('svg#chart').click({ position: { x: 10, y: 10 } });
  const z = await zustand(page);

  expect(z.mode).toBe('none');
  expect(z.anker).toBeNull();
  expect(z.active).toBeNull();
  expect(z.focus).toBeNull();
  expect(z.netFocusNode).toBeNull();
  expect(z.netFocusPair).toBeNull();
  // Zeitachse in Ruhe
  expect(z.gedimmt).toBe(0);
  expect(z.gross).toBe(0);
  expect(z.gold).toBe(0);
  // Panel zurück auf Suche
  expect(z.titel).toBe('Suche');
  expect(z.ansicht).toBe('view-chat');
});

// ── 10 · Leere Netzfläche ─────────────────────────────────────────────────────

test('10 · MERKWÜRDIG — die leere Netzfläche löscht hlState nicht', async ({ page }) => {
  // Das Gegenstück zu Fall 9 räumt nur netFocusNode und netFocusPair ab
  // (network.js, click.egoreset). Die Zeitachse bleibt hervorgehoben und das
  // Panel steht weiter auf der alten Liste — dieselbe Geste, zwei Ergebnisse.
  await laden(page);
  await page.locator('circle.dot').first().click({ force: true });
  const vorher = await zustand(page);
  await netzOeffnen(page);
  await page.locator('svg#network').click({ position: { x: 5, y: 5 } });
  const z = await zustand(page);

  expect(z.mode).toBe('answer');           // NICHT 'none'
  expect(z.anker).toBe(vorher.anker);
  expect(z.titel).toBe(vorher.titel);
  expect(z.ansicht).toBe('view-timeline');
  expect(z.netFocusNode).toBeNull();
  expect(z.netFocusPair).toBeNull();
});

// ── 11 · Zurücknehmen über goHome ─────────────────────────────────────────────

test('11 · MERKWÜRDIG — goHome() löscht hlState, aber nicht netFocusNode',
  async ({ page }) => {
    // panel.js:goHome setzt setHighlight("none"), rührt netFocusNode aber
    // nicht an. Das Netzwerk bleibt danach im Ego-Graphen stehen, während
    // Zeitachse und Panel zurückgesetzt sind. Escape und das × im Panel
    // nehmen denselben Weg.
    await laden(page);
    await netzOeffnen(page);
    const knoten = page.locator('#network g[cursor="pointer"]').first();
    const name = (await knoten.locator('text').textContent())?.trim();
    await klick(knoten);

    await page.evaluate(() => goHome());
    const z = await zustand(page);

    expect(z.mode).toBe('none');           // hlState zurück
    expect(z.anker).toBeNull();
    expect(z.gedimmt).toBe(0);
    expect(z.titel).toBe('Suche');
    expect(z.ansicht).toBe('view-chat');
    expect(z.netFocusNode).toBe(name);     // aber der Ego-Knoten steht noch
  });

// ── 12 · Reiterwechsel und Trefferauflösung ───────────────────────────────────

test('12 · der Reiterwechsel ändert den Zustand nicht', async ({ page }) => {
  await laden(page);
  await page.locator('circle.dot').first().click({ force: true });
  const vorher = await zustand(page);

  await netzOeffnen(page);
  await page.locator('#tab-timeline').click();
  const nachher = await zustand(page);

  expect(nachher).toEqual(vorher);
});

test('12b · MERKWÜRDIG — ein echter Mausklick auf eine Kante trifft oft einen Knoten',
  async ({ page }) => {
    // Die Trefferlinie einer Kante ist 14 px breit und durchsichtig, liegt
    // aber unter den Knoten. Ein Klick auf ihre Koordinaten wird deshalb
    // häufig auf einem Knoten aufgelöst — gemessen landete der erste auf
    // 'Lütke Daldrup' statt auf der Kante. Alle Kantentests oben umgehen das
    // mit dispatchEvent; hier steht der Fall selbst.
    await laden(page);
    await netzOeffnen(page);
    const linie = page.locator('#network line[stroke="transparent"]').first();
    await linie.click({ force: true });
    const z = await zustand(page);

    // Etwas ist passiert — aber nicht unbedingt das Kantenpaar.
    expect(z.mode).toBe('answer');
    const kanteGetroffen = z.netFocusPair !== null;
    const knotenGetroffen = z.netFocusNode !== null;
    expect(kanteGetroffen || knotenGetroffen).toBe(true);
  });
