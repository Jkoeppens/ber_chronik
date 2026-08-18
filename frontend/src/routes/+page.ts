import { ApiFehler, ladeProjekte, type ProjektZeile } from '$lib/api';

// Statischer Build: die Seite holt ihre Daten im Browser.
// ssr = false hält die API aus dem Buildlauf heraus — sonst müsste der
// Server beim Bauen laufen.
export const prerender = true;
export const ssr = false;

export interface Seitendaten {
	projekte: ProjektZeile[];
	fehler: string | null;
}

export async function load(): Promise<Seitendaten> {
	try {
		const liste = await ladeProjekte();
		return { projekte: liste.projekte, fehler: null };
	} catch (e) {
		// Kein Werfen: eine sichtbare Meldung ist besser als die Fehlerseite.
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return { projekte: [], fehler: meldung };
	}
}
