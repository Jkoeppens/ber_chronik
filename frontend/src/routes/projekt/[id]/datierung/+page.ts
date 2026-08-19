import {
	ApiFehler,
	ladeDatierung,
	ladeEinheiten,
	type DatierungVerteilung,
	type Einheit
} from '$lib/api';

export const prerender = false;
export const ssr = false;

export interface Seitendaten {
	projektId: string;
	einheiten: Einheit[];
	verteilung: DatierungVerteilung | null;
	fehler: string | null;
}

export async function load({ params }: { params: { id: string } }): Promise<Seitendaten> {
	try {
		// Zwei Abfragen: die Einheiten in Dokumentreihenfolge, und woher ihre
		// Daten kommen. Die Belege stecken in der zweiten — sie sind der
		// Unterschied zur alten Vorschau, die nur das Ergebnis zeigte.
		const [einheiten, verteilung] = await Promise.all([
			ladeEinheiten(params.id, 'content'),
			ladeDatierung(params.id)
		]);
		return {
			projektId: params.id,
			einheiten: einheiten.einheiten,
			verteilung,
			fehler: null
		};
	} catch (e) {
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return { projektId: params.id, einheiten: [], verteilung: null, fehler: meldung };
	}
}
