import { redirect } from '@sveltejs/kit';

export const prerender = false;
export const ssr = false;

/**
 * /projekt/[id] hat keinen eigenen Inhalt mehr. Die Projektseite war ein
 * Verteiler mit drei gleich aussehenden Links ohne Reihenfolge; an ihre Stelle
 * ist die Reiterleiste getreten. Was dort stand, trägt jetzt der Reiter
 * "Quelle" — dorthin geht auch, wer die alte Adresse aufruft.
 */
export function load({ params }: { params: { id: string } }): never {
	redirect(307, `/projekt/${encodeURIComponent(params.id)}/quelle`);
}
