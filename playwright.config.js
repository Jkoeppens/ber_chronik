// @ts-check
import { defineConfig } from '@playwright/test';

/**
 * Der Standardlauf: nur die viz-Specs, gegen das eingefrorene Prüfstück.
 *
 * api_coverage.spec.js und ingest.spec.js prüfen den alten Server auf 8001 und
 * dessen Dateien unter data/projects/. Zwei von ihnen scheitern unabhängig von
 * jeder Änderung, weil data/projects/damaskus/ im Arbeitsbaum fehlt — im
 * pre-commit-Hook blockierten sie damit jeden Commit. Sie bleiben liegen,
 * solange 8001 läuft, aber sie laufen nur noch auf Zuruf:
 *
 *     npm run test:alt
 *
 * webServer: Playwright fährt den Dienst selbst hoch. Vorher setzte die
 * Konfiguration einen von Hand gestarteten voraus, und der pre-commit-Hook
 * übersprang seinen Playwright-Teil, wenn keiner lief — also bei fast jedem
 * Commit. Ein Hook, der sich selbst überspringt, ist kein Hook.
 *
 * Absichtlich python3 -m http.server und nicht der Leseserver auf 8002: die
 * Tests brauchen nur viz/ und data/exporte/pruefstueck/, beides sind Dateien.
 * Über 8002 hinge jeder Lauf an data/neu.db, und die KI-Frage riefe ein
 * Sprachmodell — langsam, teuer und von Lauf zu Lauf anders.
 */
export default defineConfig({
  testDir: './tests',
  testMatch: ['viz.spec.js', 'hervorheben.spec.js', 'anzeige.spec.js'],
  timeout: 30_000,
  retries: 0,
  workers: 1,          // sequential – tests share a running server
  use: {
    // Nur der Ursprung: die Specs setzen den Pfad selbst, weil sie das
    // Prüfstück über ?project= wählen.
    baseURL: 'http://localhost:8765',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    // Aus der Wurzel: viz/ und data/exporte/ müssen beide erreichbar sein.
    command: 'python3 -m http.server 8765',
    url: 'http://localhost:8765/viz/',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    // Beide still: http.server schreibt für JEDE Datei eine Zeile ins
    // Zugriffsprotokoll, und zwar auf stderr. Mit 'pipe' waren das rund
    // 37 KB Rauschen vor jedem Commit, in dem die Testliste unterging.
    // Startet der Dienst gar nicht, meldet Playwright das ohnehin über die
    // url-Prüfung.
    stdout: 'ignore',
    stderr: 'ignore',
  },
  reporter: [['list'], ['html', { open: 'never' }]],
});
