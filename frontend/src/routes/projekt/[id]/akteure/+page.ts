import {
	ApiFehler,
	ladeAkteure,
	ladeEinheiten,
	ladeKandidaten,
	ladeMarkierungen,
	type AkteurListe,
	type Einheit,
	type KandidatenListe,
	type MarkierungenListe
} from '$lib/api';

export const prerender = false;
export const ssr = false;

export interface Seitendaten {
	projektId: string;
	akteure: AkteurListe | null;
	einheiten: Einheit[];
	markierungen: MarkierungenListe | null;
	kandidaten: KandidatenListe | null;
	fehler: string | null;
}

export async function load({ params }: { params: { id: string } }): Promise<Seitendaten> {
	try {
		// Vier Abfragen, drei Reiter. Die Markierungen kommen mit den Einheiten
		// zusammen, weil der Annotator ohne beide nichts zeigen kann.
		const [akteure, einheiten, markierungen, kandidaten] = await Promise.all([
			ladeAkteure(params.id),
			ladeEinheiten(params.id, 'content'),
			ladeMarkierungen(params.id),
			ladeKandidaten(params.id)
		]);
		return {
			projektId: params.id,
			akteure,
			einheiten: einheiten.einheiten,
			markierungen,
			kandidaten,
			fehler: null
		};
	} catch (e) {
		const meldung = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Laden.';
		return {
			projektId: params.id,
			akteure: null,
			einheiten: [],
			markierungen: null,
			kandidaten: null,
			fehler: meldung
		};
	}
}
