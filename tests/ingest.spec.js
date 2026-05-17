// @ts-check
/**
 * ingest.spec.js — Tests für Dokumenttyp-Daten und Ingest-Wizard-UI
 *
 * Voraussetzungen:
 *   - dev_server läuft auf localhost:8001
 *   - invites.json enthält den Token INVITE_TOKEN (oder den Fallback-Token)
 *
 * Drei abgedeckte Dokumenttypen:
 *   A) presseartikel / docx  → BER Geicke-Chronik
 *   B) buchnotizen           → osmanisch, damaskus
 *   C) presseartikel / obsidian → Obsidian/Dropbox-Artikel
 *   D) UI-Prüfung            → ingest_wizard.html dropdown
 */

import { test, expect }              from '@playwright/test';
import { readFileSync, readdirSync, existsSync } from 'fs';
import { join }                       from 'path';

const API    = 'http://localhost:8001';
// Token aus invites.json (lokaler Test-Token, kein Produktions-Secret)
const INVITE = process.env.INVITE_TOKEN || 'f4f41e679927cd4e';
const ROOT   = process.cwd();   // Repo-Wurzel wenn mit `npx playwright test` gestartet

function readJson(relPath) {
  return JSON.parse(readFileSync(join(ROOT, relPath), 'utf8'));
}

// ─── Test A: Presseexzerpt (BER/Geicke-DOCX) ─────────────────────────────────

test('Presseexzerpt BER — doc_type=presseartikel, source-Felder, Timeline-Einträge', async ({ request }) => {
  // 1. doc_type über API
  const r = await request.get(`${API}/api/projects/ber?invite=${INVITE}`);
  expect(r.ok()).toBe(true);
  const proj = await r.json();
  expect(proj.doc_type).toBe('presseartikel');

  // 2. segments.json: alle content-Segs haben ingest_source="docx"
  const segs    = readJson('data/projects/ber/documents/main/segments.json');
  const content = segs.filter(s => s.type === 'content');
  expect(content.length).toBeGreaterThan(0);

  expect(
    content.every(s => s.ingest_source === 'docx'),
    'Nicht alle content-Segmente haben ingest_source=docx'
  ).toBe(true);

  // Mindestens 40 % haben eine Quellenangabe
  const withSource = content.filter(s => s.source !== null && s.source !== undefined);
  expect(withSource.length / content.length).toBeGreaterThan(0.4);

  // Pflichtfelder in jedem content-Segment
  for (const s of content.slice(0, 30)) {
    expect(s).toHaveProperty('source_date');
    expect(s).toHaveProperty('is_quote');
  }

  // is_quote muss boolean sein
  expect(typeof content[0].is_quote).toBe('boolean');

  // 3. exploration/data.json enthält Einträge
  const data = readJson('data/projects/ber/exploration/data.json');
  const count = data.count ?? data.entries?.length ?? 0;
  expect(count).toBeGreaterThan(0);
});

// ─── Test B: Literaturexzerpt (buchnotizen) ───────────────────────────────────

test('Literaturexzerpt osmanisch — doc_type=buchnotizen', async ({ request }) => {
  const r = await request.get(`${API}/api/projects/osmanisch?invite=${INVITE}`);
  expect(r.ok()).toBe(true);
  const proj = await r.json();
  expect(proj.doc_type).toBe('buchnotizen');
});

test('Literaturexzerpt damaskus — doc_type=buchnotizen', async ({ request }) => {
  const r = await request.get(`${API}/api/projects/damaskus?invite=${INVITE}`);
  expect(r.ok()).toBe(true);
  const proj = await r.json();
  expect(proj.doc_type).toBe('buchnotizen');
});

// ─── Test C: Pressesammlung (Obsidian) ────────────────────────────────────────

test('Pressesammlung Obsidian — heading + content, ingest_source=obsidian, date-Felder', () => {
  // Suche nach einem beliebigen Obsidian-Projekt mit segments.json
  const projectsDir = join(ROOT, 'data/projects');
  let obsSegs    = null;
  let obsProject = null;
  let obsDocId   = null;

  outer: for (const projName of readdirSync(projectsDir)) {
    const docsDir = join(projectsDir, projName, 'documents');
    if (!existsSync(docsDir)) continue;
    for (const docId of readdirSync(docsDir)) {
      const segsPath = join(docsDir, docId, 'segments.json');
      if (!existsSync(segsPath)) continue;
      try {
        const segs = JSON.parse(readFileSync(segsPath, 'utf8'));
        if (segs.length > 0 && segs[0]?.ingest_source === 'obsidian') {
          obsSegs = segs; obsProject = projName; obsDocId = docId;
          break outer;
        }
      } catch { /* skip */ }
    }
  }

  expect(obsSegs, 'Kein Obsidian-Projekt mit Segmenten gefunden').not.toBeNull();

  const headings = obsSegs.filter(s => s.type === 'heading');
  const content  = obsSegs.filter(s => s.type === 'content');

  expect(headings.length, `${obsProject}: keine heading-Segmente`).toBeGreaterThan(0);
  expect(content.length,  `${obsProject}: keine content-Segmente`).toBeGreaterThan(0);

  // Alle Segmente tragen ingest_source="obsidian"
  expect(
    obsSegs.every(s => s.ingest_source === 'obsidian'),
    'Nicht alle Segmente haben ingest_source=obsidian'
  ).toBe(true);

  // Heading-Segmente haben date-Feld aus Frontmatter
  for (const h of headings) {
    expect(h.date, `Heading ${h.segment_id} fehlt date-Feld`).toBeTruthy();
  }

  // anchors_interpolated.json prüfen wenn vorhanden
  const interpPath = join(ROOT, 'data/projects', obsProject, 'documents', obsDocId,
                          'anchors_interpolated.json');
  if (existsSync(interpPath)) {
    const interp   = JSON.parse(readFileSync(interpPath, 'utf8'));
    const interpContent = interp.filter(s => s.type === 'content');
    const dated = interpContent.filter(s => s.time_from !== null && s.time_from !== undefined);
    expect(
      dated.length,
      `${obsProject}: keine content-Segmente nach Interpolation datiert`
    ).toBeGreaterThan(0);
  }
});

// ─── Test D: UI — Dokumenttyp-Auswahl im Ingest-Wizard ───────────────────────

test('UI Wizard — nur Literaturexzerpt + Presseexzerpt, kein Transkripte/Anderes', async ({ page }) => {
  // Cookie setzen: JS-Code in ingest_wizard.html liest invite_token aus Cookie
  await page.context().addCookies([{
    name:   'invite_token',
    value:  INVITE,
    domain: 'localhost',
    path:   '/',
  }]);

  await page.goto(`${API}/ingest`);

  // "Neues Projekt +"-Karte öffnen damit das Panel sichtbar wird
  await page.locator('#new-proj-card').click();

  // ── Datei-Tab: <select id="np-doctype"> ──────────────────────────────────
  const select = page.locator('#np-doctype');
  await expect(select).toBeVisible({ timeout: 10_000 });

  const optionTexts = await select.locator('option').allTextContents();
  expect(optionTexts, 'Transkripte darf nicht mehr im Dropdown sein')
    .not.toContain('Transkripte');
  expect(optionTexts, 'Anderes darf nicht mehr im Dropdown sein')
    .not.toContain('Anderes');
  expect(optionTexts, 'Forschungsnotizen darf nicht mehr im Dropdown sein')
    .not.toContain('Forschungsnotizen');
  expect(optionTexts).toContain('Literaturexzerpt');
  expect(optionTexts).toContain('Presseexzerpt');

  const optionValues = await Promise.all(
    (await select.locator('option').all()).map(o => o.getAttribute('value'))
  );
  expect(optionValues).toContain('buchnotizen');
  expect(optionValues).toContain('presseartikel');

  // ── Step-2 doctype-grid (im DOM, auch wenn nicht sichtbar) ───────────────
  const cardLabels = await page.locator('.doctype-card strong').allTextContents();
  expect(cardLabels, 'Transkripte darf nicht in Step-2-Grid sein')
    .not.toContain('Transkripte');
  expect(cardLabels, 'Anderes darf nicht in Step-2-Grid sein')
    .not.toContain('Anderes');
  expect(cardLabels).toContain('Literaturexzerpt');
  expect(cardLabels).toContain('Presseexzerpt');

  const radioValues = await Promise.all(
    (await page.locator('input[name="doc-type"]').all()).map(r => r.getAttribute('value'))
  );
  expect(radioValues).toContain('buchnotizen');
  expect(radioValues).toContain('presseartikel');
  expect(radioValues).not.toContain('Transkripte');
  expect(radioValues).not.toContain('Anderes');
});
