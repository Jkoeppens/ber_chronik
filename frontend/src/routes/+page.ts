import { ApiFehler, ladeEinheiten, type Einheit } from '$lib/api';

// Statischer Build: eine Seite, die ihre Daten im Browser holt.
// ssr = false hält die API aus dem Buildlauf heraus — sonst müsste der
// Server beim Bauen laufen.
export const prerender = true;
export const ssr = false;

const PROJEKT = 'damaskus';
const TYP = 'content';

export interface Seitendaten {
	projekt: string;
	einheiten: Einheit[];
	fehler: string | null;
}

export async function load(): Promise<Seitendaten> {
	try {
		const liste = await ladeEinheiten(PROJEKT, TYP);
		return { projekt: PROJEKT, einheiten: liste.einheiten, fehler: null };
	} catch (e) {
		// Kein Werfen: eine sichtbare Meldung ist besser als die Fehlerseite.
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return { projekt: PROJEKT, einheiten: [], fehler: meldung };
	}
}
