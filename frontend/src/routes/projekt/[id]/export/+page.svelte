<script lang="ts">
	import { invalidate } from '$app/navigation';
	import { ApiFehler, exportiere, vizAdresse, type ExportAntwort } from '$lib/api';
	import type { Layoutdaten } from '../+layout';

	let { data }: { data: Layoutdaten } = $props();
	const zahlen = $derived(data.kennzahlen);

	let laeuft = $state(false);
	let fehler = $state<string | null>(null);
	let bericht = $state<ExportAntwort | null>(null);

	// „Mit ausgeben", nicht „jetzt erzeugen": geschrieben wird, was in
	// akteur.zusammenfassung steht. Erzeugt werden sie auf der Akteursfläche —
	// hier hinge sonst ein Modellaufruf je Akteur an einem Knopf, der schnell
	// sein soll.
	let mitZusammenfassungen = $state(false);

	async function exportieren() {
		laeuft = true;
		fehler = null;
		bericht = null;
		try {
			bericht = await exportiere(data.projektId, mitZusammenfassungen);
			await invalidate('app:kennzahlen');
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Export.';
		} finally {
			laeuft = false;
		}
	}

	function spanne(von: number | null, bis: number | null): string {
		if (von === null || von === undefined) return '—';
		return von === bis ? `${von}` : `${von}–${bis}`;
	}
</script>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
		<button class="btn btn-primary" disabled={laeuft} onclick={exportieren}>
			{laeuft ? 'Exportiert …' : 'Exportieren'}
		</button>
		<span class="leer" style="flex:1">Erzeugt die Dateien, die die Visualisierung liest.</span>
		{#if zahlen?.hat_export}
			<a
				class="btn btn-sm btn-outline"
				href={vizAdresse(data.projektId)}
				target="_blank"
				rel="noreferrer"
			>
				Viz öffnen ↗
			</a>
		{/if}
	</div>

	<label class="schalter">
		<input type="checkbox" bind:checked={mitZusammenfassungen} disabled={laeuft} />
		Zusammenfassungen der Akteure mit ausgeben
		<span class="leer">
			— schreibt entities_summary.json aus dem, was schon dasteht. Erzeugt werden
			sie auf dem Reiter „Akteure".
		</span>
	</label>

	{#if zahlen?.export_am}
		<span class="leer">Zuletzt exportiert: {zahlen.export_am}</span>
	{:else}
		<span class="leer">Noch nicht exportiert — die Visualisierung hat noch nichts zu lesen.</span>
	{/if}

	{#if fehler}
		<div class="fehler">{fehler}</div>
	{/if}

	{#if bericht}
		<div class="log-box">{bericht.anzahl_einheiten} Einheiten, davon {bericht.anzahl_mit_datum} mit Datum, {bericht.anzahl_ohne_datum} ohne
{bericht.anzahl_ohne_kategorie} ohne Kategorie, {bericht.anzahl_mit_akteur} mit mindestens einem Akteur
Zeitraum: {spanne(bericht.jahr_min, bericht.jahr_max)}
Netzwerk: {bericht.anzahl_knoten} Knoten, {bericht.anzahl_kanten} Kanten
Dateien: {bericht.dateien.join(', ')}
Lauf {bericht.lauf_id}: {bericht.status}</div>
	{/if}
</main>

<style>
	.schalter {
		display: flex;
		align-items: baseline;
		gap: 7px;
		font-size: 12px;
		flex-wrap: wrap;
	}
	.schalter input {
		margin: 0;
	}
</style>
