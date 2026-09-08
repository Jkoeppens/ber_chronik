// @ts-check
import { defineConfig } from '@playwright/test';

/**
 * Die Specs zum alten System. Nur auf Zuruf:
 *
 *     npm run test:alt
 *
 * Sie prüfen den Wizard-Server auf 8001 und lesen Dateien unter
 * data/projects/. Beide Adressen stehen fest in den Specs, deshalb hat diese
 * Fassung keine baseURL — geerbt würde sonst die der viz-Specs (8765), was
 * irreführend wäre.
 *
 * Voraussetzungen:
 *   uvicorn src.generalized.dev_server:app --port 8001
 *   INVITE_TOKEN aus data/invites.json (sonst greift der Fallback in den Specs)
 *
 * Zwei Tests scheitern zurzeit unabhängig von jeder Änderung: sie brauchen
 * data/projects/damaskus/, das im Arbeitsbaum gelöscht ist, und heading-
 * Segmente in baseline_obsidian_dropbox, die es dort nicht gibt.
 *
 * Weg damit, sobald 8001 abgeschaltet ist — dann fällt auch diese Datei weg.
 */
export default defineConfig({
  testDir: './tests',
  testMatch: ['api_coverage.spec.js', 'ingest.spec.js'],
  timeout: 30_000,
  retries: 0,
  workers: 1,
  use: {
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  reporter: [['list']],
});
