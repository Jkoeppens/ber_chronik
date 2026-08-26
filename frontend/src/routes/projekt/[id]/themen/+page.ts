import {
	ApiFehler,
	ladeEinheiten,
	ladeKategorien,
	ladeKonfiguration,
	type Einheit,
	type KategorienListe,
	type Konfiguration
} from '$lib/api';

export const prerender = false;
export const ssr = false;

export interface Seitendaten {
	projektId: string;
	kategorien: KategorienListe | null;
	einheiten: Einheit[];
	konfiguration: Konfiguration | null;
	fehler: string | null;
}

export async function load({ params }: { params: { id: string } }): Promise<Seitendaten> {
	try {
		// Drei Abfragen, eine Seite: Kategorien, Einheiten, und womit gerechnet wird.
		const [kategorien, einheiten, konfiguration] = await Promise.all([
			ladeKategorien(params.id),
			ladeEinheiten(params.id, 'content'),
			ladeKonfiguration()
		]);
		return {
			projektId: params.id,
			kategorien,
			einheiten: einheiten.einheiten,
			konfiguration,
			fehler: null
		};
	} catch (e) {
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return {
			projektId: params.id,
			kategorien: null,
			einheiten: [],
			konfiguration: null,
			fehler: meldung
		};
	}
}
