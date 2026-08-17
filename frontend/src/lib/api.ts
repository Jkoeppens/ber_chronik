/**
 * api.ts — der einzige Ort, an dem diese Anwendung das Netz anfasst.
 *
 * Komponenten rufen die Funktionen hier auf und bekommen fertige Werte oder
 * einen ApiFehler mit lesbarer Meldung. Kein fetch außerhalb dieser Datei.
 *
 * Die Seite wird vom selben Server ausgeliefert wie die API, deshalb sind die
 * Pfade relativ — ein Ursprung, kein CORS.
 */

/** Antwortgestalt des Servers, siehe src/neu/modelle.py */
export interface Einheit {
	id: number;
	quelle_id: string;
	position: number;
	typ: string;
	text: string;
}

export interface EinheitenListe {
	projekt_id: string;
	anzahl: number;
	typ_filter: string | null;
	einheiten: Einheit[];
}

/** Die eine Fehlergestalt des Servers. */
interface ServerFehler {
	fehler: { code: string; meldung: string; status: number };
}

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
export function ladeEinheiten(projektId: string, typ?: string): Promise<EinheitenListe> {
	const abfrage = typ ? `?typ=${encodeURIComponent(typ)}` : '';
	return hole<EinheitenListe>(`/api/projekt/${encodeURIComponent(projektId)}/einheiten${abfrage}`);
}
