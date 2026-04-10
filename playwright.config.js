// @ts-check
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
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
