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
 * Antwortgestalt mehr: eine Umbenennung in src/neu/modelle.py soll den Build
 * scheitern lassen und nicht erst im Browser auffallen.
 */

import type { components, paths } from './api-typen';

/** Kurznamen für die Gestalten, die diese Anwendung benutzt. */
export type Einheit = components['schemas']['Einheit'];
export type EinheitenListe = components['schemas']['EinheitenListe'];
export type EinheitTyp = NonNullable<EinheitenListe['typ_filter']>;

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

async function hole<T>(pfad: string): Promise<T> {
	let antwort: Response;
	try {
		antwort = await fetch(pfad);
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

/** Die Einheiten eines Projekts, nach Quelle und Position sortiert. */
export function ladeEinheiten(
	projektId: string,
	typ?: EinheitenAbfrage['typ']
): Promise<EinheitenListe> {
	const abfrage = typ ? `?typ=${encodeURIComponent(typ)}` : '';
	return hole<EinheitenListe>(`/api/projekt/${encodeURIComponent(projektId)}/einheiten${abfrage}`);
}
