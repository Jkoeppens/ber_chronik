// @ts-check
import { defineConfig } from '@playwright/test';

/**
 * Der Standardlauf: nur die viz-Specs.
 *
 * api_coverage.spec.js und ingest.spec.js prüfen den alten Server auf 8001 und
 * dessen Dateien unter data/projects/. Zwei von ihnen scheitern unabhängig von
 * jeder Änderung, weil data/projects/damaskus/ im Arbeitsbaum fehlt — im
 * pre-commit-Hook blockierten sie damit jeden Commit. Sie bleiben liegen,
 * solange 8001 läuft, aber sie laufen nur noch auf Zuruf:
 *
 *     npm run test:alt
 *
 * Voraussetzung dafür: uvicorn src.generalized.dev_server:app --port 8001
 * und ein Token aus data/invites.json (INVITE_TOKEN, sonst der Fallback).
 */
export default defineConfig({
  testDir: './tests',
  testMatch: 'viz.spec.js',
  timeout: 30_000,
  retries: 0,
  workers: 1,          // sequential – tests share a running server
  use: {
    baseURL: 'http://localhost:8765/viz/',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  reporter: [['list'], ['html', { open: 'never' }]],
});
