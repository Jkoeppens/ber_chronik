// @ts-check
/**
 * api_coverage.spec.js — API-Tests für Kern-Endpunkte
 *
 * Voraussetzungen:
 *   - dev_server läuft auf localhost:8001
 *   - ADMIN_KEY nicht gesetzt (dev mode) oder als Env-Variable übergeben
 *   - invites.json enthält den Token INVITE_TOKEN
 *
 * Tests:
 *   B) doc_status — year_min/year_max aus anchors_interpolated.json
 *   C) Taxonomy + Entity Persistenz — save/load Roundtrip
 *   D) Export-Pipeline Fehlerfall — __error__ ohne __link__
 */

import { test, expect }                    from '@playwright/test';
import { mkdirSync, writeFileSync, rmSync } from 'fs';
import { join }                             from 'path';

const API    = 'http://localhost:8001';
const INVITE = process.env.INVITE_TOKEN || 'f4f41e679927cd4e';
const ADMIN  = process.env.ADMIN_KEY    || '';
const ROOT   = process.cwd();

// Festes Dokument-ID für alle API-Coverage-Tests (gültiges 8-hex-Format)
const DOC_ID = 'a1b2c3d4';

function adminHeaders() {
  return ADMIN ? { Authorization: `Bearer ${ADMIN}` } : {};
}

async function createProject(request, title, docType = 'buchnotizen') {
  const r = await request.post(`${API}/api/projects?invite=${INVITE}`, {
    headers: { ...adminHeaders(), 'Content-Type': 'application/json' },
    data:    { title, doc_type: docType },
  });
  expect(r.ok(), `Projekt anlegen fehlgeschlagen: ${await r.text()}`).toBe(true);
  const body = await r.json();
  return { id: body.id, token: body.token };
}

async function deleteProject(request, id) {
  const r = await request.delete(`${API}/api/projects/${id}?invite=${INVITE}`, {
    headers: { ...adminHeaders(), 'Content-Type': 'application/json' },
    data:    { confirm: true },
  });
  // Fehler beim Cleanup nur warnen, nicht den Test fehlschlagen lassen
  if (!r.ok()) {
    console.warn(`Cleanup fehlgeschlagen für ${id}: ${await r.text()}`);
  }
}

function seedDir(projectId, docId) {
  const dir = join(ROOT, 'data', 'projects', projectId, 'documents', docId);
  mkdirSync(dir, { recursive: true });
  return dir;
}

// ─── Test B: doc_status — year_min / year_max ─────────────────────────────────

test('B — doc_status liefert year_min und year_max aus anchors_interpolated', async ({ request }) => {
  const { id, token } = await createProject(request, 'api-test-b-doc-status', 'presseartikel');

  try {
    // Seed: anchors_interpolated.json mit zwei content-Segmenten
    const dir = seedDir(id, DOC_ID);
    const anchors = [
      { segment_id: 's1', type: 'content', time_from: 2010, time_to: 2010, precision: 'exact' },
      { segment_id: 's2', type: 'content', time_from: 2015, time_to: 2015, precision: 'exact' },
      { segment_id: 's3', type: 'content', time_from: 2020, time_to: 2020, precision: 'exact' },
    ];
    writeFileSync(join(dir, 'anchors_interpolated.json'), JSON.stringify(anchors));

    const r = await request.get(
      `${API}/ingest/doc_status?project=${id}&document=${DOC_ID}&token=${token}&invite=${INVITE}`
    );
    expect(r.ok(), `doc_status fehlgeschlagen: ${await r.text()}`).toBe(true);

    const status = await r.json();
    expect(status.anchors).toBe(true);
    expect(typeof status.year_min).toBe('number');
    expect(typeof status.year_max).toBe('number');
    expect(status.year_min).toBe(2010);
    expect(status.year_max).toBe(2020);
  } finally {
    await deleteProject(request, id);
  }
});

// ─── Test C: Taxonomy + Entity Persistenz ─────────────────────────────────────

test('C — Taxonomy via /taxonomy/save und /taxonomy/data Roundtrip', async ({ request }) => {
  const { id, token } = await createProject(request, 'api-test-c-taxonomy', 'buchnotizen');

  try {
    const testTaxonomy = [
      { id: 'cat1', label: 'Bau',       description: 'Baumaßnahmen' },
      { id: 'cat2', label: 'Finanzen',  description: 'Kosten und Finanzierung' },
    ];

    // Speichern
    const saveR = await request.post(
      `${API}/taxonomy/save?project=${id}&invite=${INVITE}`,
      {
        headers: { 'X-Project-Token': token, 'Content-Type': 'application/json' },
        data:    testTaxonomy,
      }
    );
    expect(saveR.ok(), `taxonomy/save fehlgeschlagen: ${await saveR.text()}`).toBe(true);
    const saved = await saveR.json();
    expect(saved.ok).toBe(true);
    expect(saved.count).toBe(2);

    // Lesen
    const dataR = await request.get(
      `${API}/taxonomy/data?project=${id}&invite=${INVITE}`,
      { headers: { 'X-Project-Token': token } }
    );
    expect(dataR.ok(), `taxonomy/data fehlgeschlagen: ${await dataR.text()}`).toBe(true);
    const loaded = await dataR.json();
    expect(Array.isArray(loaded)).toBe(true);
    expect(loaded).toHaveLength(2);
    expect(loaded[0].label).toBe('Bau');
    expect(loaded[1].label).toBe('Finanzen');
  } finally {
    await deleteProject(request, id);
  }
});

test('C — Entities via /ingest/entities/save und /ingest/entities/data Roundtrip', async ({ request }) => {
  const { id, token } = await createProject(request, 'api-test-c-entities', 'buchnotizen');

  try {
    // Seed: leere segments.json im Dokument (entities/data braucht doc_id-Param)
    seedDir(id, DOC_ID);

    const testEntities = [
      { normalform: 'Flughafen Berlin Brandenburg', type: 'Ort' },
      { normalform: 'Willy Brandt', type: 'Person' },
    ];

    // Speichern
    const saveR = await request.post(
      `${API}/ingest/entities/save?project=${id}&document=${DOC_ID}&invite=${INVITE}`,
      {
        headers: { 'X-Project-Token': token, 'Content-Type': 'application/json' },
        data:    testEntities,
      }
    );
    expect(saveR.ok(), `entities/save fehlgeschlagen: ${await saveR.text()}`).toBe(true);
    const saved = await saveR.json();
    expect(saved.ok).toBe(true);
    expect(saved.count).toBe(2);

    // Lesen
    const dataR = await request.get(
      `${API}/ingest/entities/data?project=${id}&document=${DOC_ID}&invite=${INVITE}`,
      { headers: { 'X-Project-Token': token } }
    );
    expect(dataR.ok(), `entities/data fehlgeschlagen: ${await dataR.text()}`).toBe(true);
    const loaded = await dataR.json();
    expect(Array.isArray(loaded)).toBe(true);
    expect(loaded).toHaveLength(2);
    expect(loaded.map(e => e.normalform)).toContain('Flughafen Berlin Brandenburg');
    expect(loaded.map(e => e.normalform)).toContain('Willy Brandt');
  } finally {
    await deleteProject(request, id);
  }
});

// ─── Test D: Export-Pipeline Fehlerfall ───────────────────────────────────────

test('D — /ingest/run ohne Eingabedatei sendet __error__ und kein __link__', async ({ request }) => {
  const { id, token } = await createProject(request, 'api-test-d-pipeline-error', 'buchnotizen');

  try {
    // Kein segments.json, kein anchors_interpolated.json, keine Eingabedatei
    // → parse_document scheitert sofort wegen fehlender Quelldatei

    const r = await request.post(
      `${API}/ingest/run?project=${id}&document=${DOC_ID}&invite=${INVITE}`,
      {
        headers: { 'X-Project-Token': token, 'Content-Type': 'application/json' },
        data:    { project: id, document: DOC_ID, filename: '' },
        timeout: 20_000,
      }
    );
    expect(r.ok(), `ingest/run HTTP fehlgeschlagen: ${await r.text()}`).toBe(true);

    const text = await r.text();

    // Pipeline muss einen Fehler melden
    expect(text, 'Kein __error__ im SSE-Stream').toContain('__error__');

    // Nach einem Fehler darf kein Viz-Link kommen
    expect(text, '__link__ trotz Fehler im Stream').not.toContain('__link__');

    // Stream muss ordentlich abgeschlossen werden
    expect(text, 'Kein __done__ im SSE-Stream').toContain('__done__');
  } finally {
    await deleteProject(request, id);
  }
});
