<script lang="ts">
	import {
		ApiFehler,
		exportiere,
		ladeKennzahlen,
		vizAdresse,
		type ExportAntwort,
		type Kennzahlen
	} from '$lib/api';
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();

	// Wie in der Übersicht: der geladene Stand kommt aus data, ein Export
	// ersetzt ihn.
	let nachgeladen = $state<Kennzahlen | null>(null);
	const zahlen = $derived(nachgeladen ?? data.kennzahlen);
	const ladefehler = $derived(data.fehler);

	let laeuft = $state(false);
	let fehler = $state<string | null>(null);
	let bericht = $state<ExportAntwort | null>(null);

	async function exportieren() {
		laeuft = true;
		fehler = null;
		bericht = null;
		try {
			bericht = await exportiere(data.projektId);
			nachgeladen = await ladeKennzahlen(data.projektId);
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

<svelte:head><title>{zahlen?.titel ?? data.projektId} — BER Chronik</title></svelte:head>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<a href="/" class="btn btn-sm">← Projekte</a>
		<span class="section-label" style="flex:1">{zahlen?.titel ?? data.projektId}</span>
		{#if zahlen?.hat_export}
			<a class="btn btn-sm btn-outline" href={vizAdresse(data.projektId)} target="_blank" rel="noreferrer">
				Viz öffnen ↗
			</a>
		{/if}
	</div>

	{#if ladefehler}
		<div class="fehler">{ladefehler}</div>
	{/if}

	{#if zahlen}
		<dl class="zahlen">
			<div class="zahl">
				<dt>Quellformat</dt>
				<dd style="font-size:12px">{zahlen.quellformate.join(' + ') || '—'}</dd>
			</div>
			<div class="zahl">
				<dt>Einheiten</dt>
				<dd>{zahlen.anzahl_einheiten}</dd>
			</div>
			<div class="zahl">
				<dt>Datiert</dt>
				<dd>{zahlen.anzahl_datiert} <small>/ {zahlen.anzahl_ohne_datum} ohne</small></dd>
			</div>
			<div class="zahl">
				<dt>Zeitraum</dt>
				<dd style="font-size:13px">{spanne(zahlen.jahr_von, zahlen.jahr_bis)}</dd>
			</div>
			<div class="zahl">
				<dt>Kategorien</dt>
				<dd>{zahlen.anzahl_kategorien} <small>/ {zahlen.anzahl_klassifiziert} zugeordnet</small></dd>
			</div>
			<div class="zahl">
				<dt>Akteure</dt>
				<dd>{zahlen.anzahl_akteure} <small>/ {zahlen.anzahl_fundstellen} Fundstellen</small></dd>
			</div>
			{#if zahlen.anzahl_perioden > 0}
				<div class="zahl">
					<dt>Perioden</dt>
					<dd>{zahlen.anzahl_perioden}</dd>
				</div>
			{/if}
		</dl>

		<div style="display:flex;align-items:center;gap:10px">
			<button class="btn btn-primary" disabled={laeuft} onclick={exportieren}>
				{laeuft ? 'Exportiert …' : 'Exportieren'}
			</button>
			<span class="leer">
				Erzeugt die Dateien, die die Visualisierung liest.
			</span>
		</div>

		{#if fehler}
			<div class="fehler">{fehler}</div>
		{/if}

		{#if bericht}
			<div class="log-box">{bericht.anzahl_einheiten} Einheiten, davon {bericht.anzahl_mit_datum} mit Datum, {bericht.anzahl_ohne_datum} ohne
{bericht.anzahl_ohne_kategorie} ohne Kategorie, {bericht.anzahl_mit_akteur} mit mindestens einem Akteur
Zeitraum: {spanne(bericht.jahr_min, bericht.jahr_max)}
Netzwerk: {bericht.anzahl_knoten} Knoten, {bericht.anzahl_kanten} Kanten
Perioden: {bericht.anzahl_perioden}
Dateien: {bericht.dateien.join(', ')}
Lauf {bericht.lauf_id}: {bericht.status}</div>
		{/if}

		{#if zahlen.laeufe.length}
			<span class="section-label">Läufe</span>
			<div class="zeilen">
				{#each zahlen.laeufe as lauf (lauf.id)}
					<div class="proj-card" style="padding:6px 14px">
						<span class="proj-card-title" style="font-weight:500">{lauf.schritt}</span>
						<span class="proj-card-meta">
							{lauf.status === 'erfolg' ? '✓' : lauf.status === 'fehler' ? '✗' : '…'}
							{lauf.status} · {lauf.beendet_am ?? lauf.begonnen_am}
						</span>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</main>
