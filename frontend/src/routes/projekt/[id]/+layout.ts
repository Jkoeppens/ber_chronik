import { ApiFehler, ladeKennzahlen, type Kennzahlen } from '$lib/api';

export const prerender = false;
export const ssr = false;

export interface Layoutdaten {
	projektId: string;
	kennzahlen: Kennzahlen | null;
	fehler: string | null;
}

export async function load({
	params,
	depends
}: {
	params: { id: string };
	depends: (id: string) => void;
}): Promise<Layoutdaten> {
	// Ein eigener Abhängigkeitsschlüssel: eine Fläche, die etwas geändert hat,
	// ruft invalidate('app:kennzahlen') und lässt damit NUR diese Ladefunktion
	// neu laufen. invalidateAll() würde auch die Seite selbst neu laden, die
	// ihre Daten ohnehin schon von Hand nachzieht.
	depends('app:kennzahlen');
	try {
		return { projektId: params.id, kennzahlen: await ladeKennzahlen(params.id), fehler: null };
	} catch (e) {
		return {
			projektId: params.id,
			kennzahlen: null,
			fehler: e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.'
		};
	}
}
