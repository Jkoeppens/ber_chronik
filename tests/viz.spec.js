// @ts-check
import { test, expect } from '@playwright/test';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Wait until the boot Promise.all has completed and the chart is drawn. */
async function waitForBoot(page) {
  // Suppress the auto-start tutorial so the overlay never blocks clicks
  await page.addInitScript(() => localStorage.setItem('tutorial_seen', '1'));
  await page.goto('http://localhost:8765/viz/');
  // Dots only exist after drawChart() — proxy for data loaded
  await page.locator('circle.dot').first().waitFor({ state: 'visible', timeout: 20_000 });
}

/** Switch to the Netzwerk tab and wait until nodes are rendered. */
async function openNetwork(page) {
  await page.locator('#tab-network').click();
  // Network nodes appear as <g> elements with cursor:pointer inside #network
  await page.locator('#network g[cursor="pointer"]').first()
    .waitFor({ state: 'visible', timeout: 20_000 });
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test('Timeline dot click → panel shows article list for that year and type', async ({ page }) => {
  await waitForBoot(page);

  // Click the first visible timeline dot
  const dot = page.locator('circle.dot').first();
  await dot.click({ force: true });

  // Panel title takes the form "1997 · Kosten" (year · type)
  const title = page.locator('#panel-title');
  await expect(title).toContainText('·', { timeout: 5_000 });

  // At least one paragraph card is shown
  await expect(page.locator('#panel-content .ep-para').first())
    .toBeVisible({ timeout: 5_000 });
});

test('Entity span click in panel → panel shows actor summary', async ({ page }) => {
  await waitForBoot(page);

  // Click a dot to populate the panel with paragraph cards
  await page.locator('circle.dot').first().click({ force: true });
  await page.locator('#panel-content .ep-para').first().waitFor({ state: 'visible' });

  // Find the first entity span (highlighted actor name)
  const entitySpan = page.locator('#panel-content .entity').first();
  // Skip test gracefully if the first paragraph has no entities
  const count = await entitySpan.count();
  test.skip(count === 0, 'No entity spans in first dot paragraphs');

  const entityName = await entitySpan.getAttribute('data-name');
  await entitySpan.click();

  // Panel title should now be the entity's canonical name
  await expect(page.locator('#panel-title'))
    .toHaveText(entityName, { timeout: 5_000 });

  // Entity view shows a summary box or paragraph list
  await expect(
    page.locator('.panel-view.active .ep-summary, .panel-view.active .ep-para').first()
  ).toBeVisible({ timeout: 5_000 });
});

test('Network node click → panel shows actor summary', async ({ page }) => {
  await waitForBoot(page);
  await openNetwork(page);

  // Click the first node group
  const firstNode = page.locator('#network g[cursor="pointer"]').first();
  // Read label text before clicking so we can verify the panel title
  const labelText = await firstNode.locator('text').textContent();
  await firstNode.click();

  // Panel title should match the clicked node's label
  if (labelText) {
    await expect(page.locator('#panel-title'))
      .toHaveText(labelText.trim(), { timeout: 5_000 });
  }

  // Entity view: summary and/or para list
  await expect(
    page.locator('#panel-content .ep-summary, #panel-content .ep-para').first()
  ).toBeVisible({ timeout: 5_000 });
});

test('Network edge click → panel shows article list for connected actors', async ({ page }) => {
  await waitForBoot(page);
  await openNetwork(page);

  // Hit areas are transparent <line> elements with stroke-width 14 and cursor:pointer.
  // force:true is needed because the stroke is transparent (invisible to hit-testing heuristics).
  const hitLine = page.locator('#network line[stroke="transparent"]').first();
  await hitLine.click({ force: true });

  // Panel title takes the form "A + B · alle Verbindungen"
  await expect(page.locator('#panel-title'))
    .toContainText('·', { timeout: 5_000 });
  await expect(page.locator('#panel-title'))
    .toContainText('+', { timeout: 5_000 });

  // At least one paragraph card or "Keine gemeinsamen Artikel" message
  await expect(
    page.locator('#panel-content .ep-para, #panel-content .chat-params').first()
  ).toBeVisible({ timeout: 5_000 });
});

test('KI question → answer appears in panel', async ({ page }) => {
  await waitForBoot(page);

  await page.locator('#chat-input').fill('Wann sollte der BER ursprünglich eröffnen?');
  await page.locator('#chat-send').click();

  // Wait for the send button to re-enable — proxy for "response complete"
  await expect(page.locator('#chat-send')).toBeEnabled({ timeout: 60_000 });

  // Either an AI answer (chat-answer-text with content) or a falltext result (ep-para cards)
  const answerText = page.locator('.chat-answer-text');
  const hitCards   = page.locator('#panel-content .ep-para');

  const hasAnswer = await answerText.count() > 0 &&
    (await answerText.first().textContent())?.trim().length > 0;
  const hasCards  = await hitCards.count() > 0;

  expect(hasAnswer || hasCards).toBe(true);
});

test('Click on empty chart area → highlights reset, panel back to Suche', async ({ page }) => {
  await waitForBoot(page);

  // First set some state: click a dot
  await page.locator('circle.dot').first().click({ force: true });
  await page.locator('#panel-content .ep-para').first().waitFor({ state: 'visible' });

  // Click the SVG background (not a dot or line)
  // Use a point near the top-left of the chart that is unlikely to contain a dot
  const chartSvg = page.locator('svg#chart');
  await chartSvg.click({ position: { x: 10, y: 10 } });

  // Panel title should reset to "Suche"
  await expect(page.locator('#panel-title')).toHaveText('Suche', { timeout: 5_000 });

  // Chat view should be active (no ep-para cards from the previous click)
  await expect(page.locator('#view-chat')).toHaveClass(/active/);
});
