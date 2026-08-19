/**
 * api.ts — der einzige Ort, an dem diese Anwendung das Netz anfasst.
 *
 * Komponenten rufen die Funktionen hier auf und bekommen fertige Werte oder
 * einen ApiFehler mit lesbarer Meldung. Kein fetch außerhalb dieser Datei.
 *
 * Die Seite wird vom selben Server ausgeliefert wie die API, deshalb sind die
 * Pfade relativ — ein Ursprung, kein CORS.
 *
 * Die Gestalten kommen aus api-typen.ts, das aus dem OpenAPI-Schema des Servers
 * erzeugt wird (`npm run typen`). Hier steht keine von Hand geschriebene
 * Antwortgestalt: eine Umbenennung in src/neu/modelle.py soll den Build
 * scheitern lassen und nicht erst im Browser auffallen.
 */

import type { components, paths } from './api-typen';

/** Kurznamen für die Gestalten, die diese Anwendung benutzt. */
export type Einheit = components['schemas']['Einheit'];
export type EinheitenListe = components['schemas']['EinheitenListe'];
export type ProjektZeile = components['schemas']['ProjektZeile'];
export type ProjektListe = components['schemas']['ProjektListe'];
export type Kennzahlen = components['schemas']['Kennzahlen'];
export type Lauf = components['schemas']['Lauf'];
export type IngestAntwort = components['schemas']['IngestAntwort'];
export type ExportAntwort = components['schemas']['ExportAntwort'];
export type Quellformat = components['schemas']['QuelleAnlegen']['quellformat'];
export type DropboxStand = components['schemas']['DropboxStand'];
export type AnmeldungBeginn = components['schemas']['AnmeldungBeginn'];
export type DropboxOrdnerListe = components['schemas']['DropboxOrdnerListe'];
export type LaufStand = components['schemas']['LaufStand'];
export type LaufBegonnen = components['schemas']['LaufBegonnen'];
export type KategorieZeile = components['schemas']['KategorieZeile'];
export type KategorienListe = components['schemas']['KategorienListe'];
export type KategorieEintrag = components['schemas']['KategorieEintrag'];
export type KategorienGespeichert = components['schemas']['KategorienGespeichert'];
export type Konfiguration = components['schemas']['KonfigurationAntwort'];

/** Die eine Fehlergestalt des Servers — auch sie kommt aus dem Schema. */
type ServerFehler = components['schemas']['FehlerAntwort'];

/**
 * Der Abfrageparameter von GET …/einheiten, direkt aus dem Pfad gelesen.
 * Ändert der Server den Namen, bricht es hier.
 */
type EinheitenAbfrage = NonNullable<
	paths['/api/projekt/{projekt_id}/einheiten']['get']['parameters']['query']
>;

/** Was diese Datei nach außen wirft. Immer mit einer Meldung, die man anzeigen kann. */
export class ApiFehler extends Error {
	constructor(
		message: string,
		readonly code: string,
		readonly status: number | null
	) {
		super(message);
		this.name = 'ApiFehler';
	}
}

/** Ein Aufruf. Wirft bei jedem Fehlschlag einen ApiFehler mit lesbarer Meldung. */
async function ruf<T>(pfad: string, optionen?: RequestInit): Promise<T> {
	let antwort: Response;
	try {
		antwort = await fetch(pfad, optionen);
	} catch {
		// Server aus, Netz weg, DNS kaputt — fetch wirft ohne Status.
		throw new ApiFehler(
			`Der Server unter ${location.origin} antwortet nicht. Läuft er noch?`,
			'server_nicht_erreichbar',
			null
		);
	}

	if (!antwort.ok) {
		let meldung = `Der Server antwortete mit ${antwort.status}.`;
		let code = 'unbekannter_fehler';
		try {
			const koerper = (await antwort.json()) as ServerFehler;
			if (koerper?.fehler?.meldung) {
				meldung = koerper.fehler.meldung;
				code = koerper.fehler.code;
			}
		} catch {
			// Antwort war kein JSON — die Statusmeldung von oben genügt.
		}
		throw new ApiFehler(meldung, code, antwort.status);
	}

	return (await antwort.json()) as T;
}

const alsJson = (rumpf: unknown): RequestInit => ({
	method: 'POST',
	headers: { 'Content-Type': 'application/json' },
	body: JSON.stringify(rumpf)
});

// ── Projekte ────────────────────────────────────────────────────────────────

/** Alle Projekte mit ihren gerechneten Zahlen. */
export function ladeProjekte(): Promise<ProjektListe> {
	return ruf<ProjektListe>('/api/projekte');
}

/** Legt ein leeres Projekt an. Die Kennung entsteht aus dem Titel. */
export function legeProjektAn(titel: string, id?: string): Promise<ProjektZeile> {
	return ruf<ProjektZeile>('/api/projekte', alsJson(id ? { titel, id } : { titel }));
}

/** Die Kennzahlen eines Projekts, alles aus der Datenbank gerechnet. */
export function ladeKennzahlen(projektId: string): Promise<Kennzahlen> {
	return ruf<Kennzahlen>(`/api/projekt/${encodeURIComponent(projektId)}/kennzahlen`);
}

// ── Schritte ────────────────────────────────────────────────────────────────

/** Lädt eine Datei hoch und liest sie ein. */
export function leseDateiEin(
	projektId: string,
	datei: File,
	quellformat: Quellformat
): Promise<IngestAntwort> {
	const daten = new FormData();
	daten.append('datei', datei);
	daten.append('quellformat', quellformat);
	return ruf<IngestAntwort>(`/api/projekt/${encodeURIComponent(projektId)}/quelle/datei`, {
		method: 'POST',
		body: daten
	});
}

/** Liest einen Pfad unterhalb von data/raw/ ein — Datei oder Obsidian-Ordner. */
export function lesePfadEin(
	projektId: string,
	pfad: string,
	quellformat: Quellformat
): Promise<IngestAntwort> {
	return ruf<IngestAntwort>(
		`/api/projekt/${encodeURIComponent(projektId)}/quelle`,
		alsJson({ pfad, quellformat })
	);
}

/** Erzeugt die Dateien, die die Visualisierung liest. */
export function exportiere(projektId: string): Promise<ExportAntwort> {
	return ruf<ExportAntwort>(
		`/api/projekt/${encodeURIComponent(projektId)}/exportieren`,
		alsJson({ zusammenfassungen: false })
	);
}

/** Die Einheiten eines Projekts, nach Quelle und Position sortiert. */
export function ladeEinheiten(
	projektId: string,
	typ?: EinheitenAbfrage['typ']
): Promise<EinheitenListe> {
	const abfrage = typ ? `?typ=${encodeURIComponent(typ)}` : '';
	return ruf<EinheitenListe>(`/api/projekt/${encodeURIComponent(projektId)}/einheiten${abfrage}`);
}

// ── Lange Läufe ─────────────────────────────────────────────────────────────

/** Der Stand eines Schritts. Abgefragt, nicht gestreamt. */
export function ladeLauf(laufId: number): Promise<LaufStand> {
	return ruf<LaufStand>(`/api/lauf/${laufId}`);
}

/**
 * Fragt den Stand, bis der Lauf zu Ende ist. `melde` bekommt jeden
 * Zwischenstand — auch den ersten, damit die Fläche sofort etwas zeigt.
 */
export async function verfolgeLauf(
	laufId: number,
	melde: (stand: LaufStand) => void,
	abstandMs = 1500
): Promise<LaufStand> {
	for (;;) {
		const stand = await ladeLauf(laufId);
		melde(stand);
		if (stand.status !== 'laeuft') return stand;
		await new Promise((r) => setTimeout(r, abstandMs));
	}
}

/** Stößt den Taxonomievorschlag an. Kommt sofort mit einer lauf_id zurück. */
export function schlageTaxonomieVor(
	projektId: string,
	warmStart: boolean,
	nClusters?: number
): Promise<LaufBegonnen> {
	return ruf<LaufBegonnen>(
		`/api/projekt/${encodeURIComponent(projektId)}/taxonomie/vorschlagen`,
		alsJson(warmStart ? { warm_start: true } : { warm_start: false, n_clusters: nClusters })
	);
}

/**
 * Stößt die Zuordnung an. Kommt sofort mit einer lauf_id zurück.
 *
 * Kein Umfang: zugeordnet wird immer alles, Handkorrekturen bleiben stehen.
 */
export function klassifiziere(projektId: string): Promise<LaufBegonnen> {
	return ruf<LaufBegonnen>(
		`/api/projekt/${encodeURIComponent(projektId)}/klassifizieren`,
		alsJson({ verfahren: 'bge' })
	);
}

/**
 * Speichert die ganze Kategorienliste und ordnet danach neu zu.
 * Kommt sofort zurück — das Zuordnen dauert. `lauf_id` ist null, wenn die
 * Liste leer war: dann gibt es nichts zuzuordnen und nichts zu verfolgen.
 */
export function speichereKategorien(
	projektId: string,
	kategorien: KategorieEintrag[]
): Promise<KategorienGespeichert> {
	return ruf<KategorienGespeichert>(`/api/projekt/${encodeURIComponent(projektId)}/kategorien`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ kategorien })
	});
}

// ── Kategorien ──────────────────────────────────────────────────────────────

export function ladeKategorien(projektId: string): Promise<KategorienListe> {
	return ruf<KategorienListe>(`/api/projekt/${encodeURIComponent(projektId)}/kategorien`);
}

export function legeKategorieAn(
	projektId: string,
	name: string,
	beschreibung = '',
	schlagworte: string[] = []
): Promise<KategorieZeile> {
	return ruf<KategorieZeile>(
		`/api/projekt/${encodeURIComponent(projektId)}/kategorien`,
		alsJson({ name, beschreibung, schlagworte })
	);
}

export function aendereKategorie(
	kategorieId: number,
	felder: { name?: string; beschreibung?: string; schlagworte?: string[] }
): Promise<KategorieZeile> {
	return ruf<KategorieZeile>(`/api/kategorie/${kategorieId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(felder)
	});
}

export function loescheKategorie(kategorieId: number): Promise<unknown> {
	return ruf<unknown>(`/api/kategorie/${kategorieId}`, { method: 'DELETE' });
}

/** Setzt die Kategorie einer Einheit von Hand — danach 'manuell'. */
export function setzeEinheitKategorie(
	einheitId: number,
	kategorieId: number | null
): Promise<unknown> {
	return ruf<unknown>(`/api/einheit/${einheitId}/kategorie`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ kategorie_id: kategorieId })
	});
}

// ── Projekt ─────────────────────────────────────────────────────────────────

export function loescheProjekt(projektId: string): Promise<unknown> {
	return ruf<unknown>(`/api/projekt/${encodeURIComponent(projektId)}`, {
		method: 'DELETE'
	});
}

/** Welche Anbieter und Modelle gerade gelten. */
export function ladeKonfiguration(): Promise<Konfiguration> {
	return ruf<Konfiguration>('/api/konfiguration');
}

// ── Dropbox ─────────────────────────────────────────────────────────────────

/** Ob das Projekt verbunden ist und gegen welchen Ordner. */
export function ladeDropboxStand(projektId: string): Promise<DropboxStand> {
	return ruf<DropboxStand>(`/api/projekt/${encodeURIComponent(projektId)}/dropbox`);
}

/** Trägt den Ordner ein, gegen den gelesen wird. */
export function setzeDropboxOrdner(projektId: string, ordner: string): Promise<DropboxStand> {
	return ruf<DropboxStand>(`/api/projekt/${encodeURIComponent(projektId)}/dropbox`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ ordner })
	});
}

/** Beginnt die Anmeldung. Der Vorgang liegt danach in der Datenbank. */
export function beginneDropboxAnmeldung(projektId: string): Promise<AnmeldungBeginn> {
	return ruf<AnmeldungBeginn>(
		`/api/projekt/${encodeURIComponent(projektId)}/dropbox/anmeldung`,
		{ method: 'POST' }
	);
}

/** Die Ordner im App-Ordner — zur Auswahl statt zum Tippen. */
export function ladeDropboxOrdner(projektId: string): Promise<DropboxOrdnerListe> {
	return ruf<DropboxOrdnerListe>(`/api/projekt/${encodeURIComponent(projektId)}/dropbox/ordner`);
}

/** Liest den eingestellten Dropbox-Ordner ein — beim zweiten Mal fortsetzend. */
export function leseDropboxEin(projektId: string): Promise<IngestAntwort> {
	return ruf<IngestAntwort>(`/api/projekt/${encodeURIComponent(projektId)}/quelle/dropbox`, {
		method: 'POST'
	});
}

/** Wohin die Visualisierung eines Projekts zeigt. */
export function vizAdresse(projektId: string): string {
	return `/viz/?project=${encodeURIComponent(projektId)}`;
}
