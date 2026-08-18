import { ApiFehler, ladeKennzahlen, type Kennzahlen } from '$lib/api';

// Ein Projekt je Kennung — nichts, was sich vorab erzeugen ließe.
// Der Server liefert dafür die Ausweichseite (fallback), siehe vite.config.ts.
export const prerender = false;
export const ssr = false;

export interface Seitendaten {
	projektId: string;
	kennzahlen: Kennzahlen | null;
	fehler: string | null;
}

export async function load({ params }: { params: { id: string } }): Promise<Seitendaten> {
	try {
		return { projektId: params.id, kennzahlen: await ladeKennzahlen(params.id), fehler: null };
	} catch (e) {
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return { projektId: params.id, kennzahlen: null, fehler: meldung };
	}
}
