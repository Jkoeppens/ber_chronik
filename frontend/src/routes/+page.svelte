<script lang="ts">
	import {
		ApiFehler,
		exportiere,
		ladeProjekte,
		legeProjektAn,
		leseDateiEin,
		lesePfadEin,
		vizAdresse,
		type IngestAntwort,
		type ProjektZeile,
		type Quellformat
	} from '$lib/api';
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();

	// Der geladene Stand kommt aus data; nach einem Einlesen oder Export wird er
	// hier ersetzt. $derived statt einer Kopie: sonst zeigte die Seite nach einem
	// Wechsel den alten Stand weiter.
	let nachgeladen = $state<ProjektZeile[] | null>(null);
	const projekte = $derived(nachgeladen ?? data.projekte);
	const ladefehler = $derived(data.fehler);

	// ── Neues Projekt ────────────────────────────────────────────────────────
	let formularOffen = $state(false);
	let titel = $state('');
	let quellformat = $state<Quellformat>('literaturexzerpt');
	let datei = $state<File | null>(null);
	let ordner = $state('');
	let laeuft = $state(false);
	let fehler = $state<string | null>(null);
	let ergebnis = $state<IngestAntwort | null>(null);

	// Eine Pressesammlung kommt als Obsidian-Ordner, die beiden anderen als DOCX.
	const istSammlung = $derived(quellformat === 'pressesammlung');
	const bereit = $derived(
		titel.trim().length > 0 && (istSammlung ? ordner.trim().length > 0 : datei !== null)
	);

	function zuruecksetzen() {
		titel = '';
		datei = null;
		ordner = '';
		quellformat = 'literaturexzerpt';
		fehler = null;
		ergebnis = null;
	}

	function dateiGewaehlt(ereignis: Event) {
		const ziel = ereignis.target as HTMLInputElement;
		datei = ziel.files?.[0] ?? null;
	}

	async function anlegenUndEinlesen() {
		laeuft = true;
		fehler = null;
		ergebnis = null;
		try {
			const projekt = await legeProjektAn(titel.trim());
			// Zwei Schritte, ein Knopf: erst die Zeile, dann die Quelle. Schlägt das
			// Einlesen fehl, bleibt das leere Projekt stehen — sichtbar in der Liste,
			// und ein zweiter Versuch braucht keinen neuen Namen.
			ergebnis = istSammlung
				? await lesePfadEin(projekt.id, ordner.trim(), quellformat)
				: await leseDateiEin(projekt.id, datei as File, quellformat);
			nachgeladen = (await ladeProjekte()).projekte;
			titel = '';
			datei = null;
			ordner = '';
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
			try {
				nachgeladen = (await ladeProjekte()).projekte;
			} catch {
				// Wenn schon das Nachladen scheitert, bleibt die alte Liste stehen.
			}
		} finally {
			laeuft = false;
		}
	}

	// ── Exportieren aus der Liste ────────────────────────────────────────────
	let exportiertGerade = $state<string | null>(null);

	async function exportierenUndNachladen(projektId: string) {
		exportiertGerade = projektId;
		fehler = null;
		try {
			await exportiere(projektId);
			nachgeladen = (await ladeProjekte()).projekte;
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler beim Export.';
		} finally {
			exportiertGerade = null;
		}
	}

	/** Das Ergebnis des Einlesens als Text — je Zeile eine Aussage. */
	function berichtstext(e: IngestAntwort): string {
		const zeilen = [
			`Projekt ${e.projekt_id}, Quelle ${e.quelle_id} (${e.quellformat})`,
			`${e.anzahl_einheiten} Einheiten`,
			...Object.entries(e.anzahl_je_typ).map(([typ, n]) => `  ${typ}: ${n}`),
			`Lauf ${e.lauf_id}: ${e.status}`
		];
		const inhalt = e.anzahl_je_typ['content'] ?? 0;
		if (inhalt === 0) {
			zeilen.push(
				'',
				'Hinweis: keine content-Einheiten. Datierung, Kategorien und Export',
				'brauchen welche — dieses Dokument liefert nur ' +
					Object.keys(e.anzahl_je_typ).join(', ') + '.'
			);
		}
		return zeilen.join('\n');
	}

	function zeitraum(p: ProjektZeile): string {
		if (p.jahr_von === null || p.jahr_von === undefined) return 'undatiert';
		return p.jahr_von === p.jahr_bis ? `${p.jahr_von}` : `${p.jahr_von}–${p.jahr_bis}`;
	}
</script>

<svelte:head><title>Projekte — BER Chronik</title></svelte:head>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<span class="section-label" style="flex:1">Projekte</span>
		<button
			class="btn btn-dashed btn-sm"
			onclick={() => {
				formularOffen = !formularOffen;
				if (!formularOffen) zuruecksetzen();
			}}
		>
			{formularOffen ? 'Abbrechen' : '+ Neues Projekt'}
		</button>
	</div>

	{#if formularOffen}
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
				<input
					class="input"
					style="flex:1;min-width:200px"
					placeholder="Name des Projekts"
					bind:value={titel}
					disabled={laeuft}
				/>
				<select class="input" bind:value={quellformat} disabled={laeuft}>
					<option value="literaturexzerpt">Literaturexzerpt (DOCX)</option>
					<option value="presseexzerpt">Presseexzerpt (DOCX)</option>
					<option value="pressesammlung">Pressesammlung (Obsidian-Ordner)</option>
				</select>
			</div>

			<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
				{#if istSammlung}
					<input
						class="input"
						style="flex:1;min-width:240px"
						placeholder="Ordner unterhalb von data/raw/"
						bind:value={ordner}
						disabled={laeuft}
					/>
				{:else}
					<input
						class="input"
						style="flex:1;min-width:240px"
						type="file"
						accept=".docx"
						onchange={dateiGewaehlt}
						disabled={laeuft}
					/>
				{/if}
				<button class="btn btn-primary" disabled={!bereit || laeuft} onclick={anlegenUndEinlesen}>
					{laeuft ? 'Liest ein …' : 'Anlegen und einlesen'}
				</button>
			</div>

			{#if fehler}
				<div class="fehler">{fehler}</div>
			{/if}

			{#if ergebnis}
				<div class="log-box">{berichtstext(ergebnis)}</div>
			{/if}
		</div>
	{/if}

	{#if ladefehler}
		<div class="fehler">{ladefehler}</div>
	{/if}

	<div class="zeilen">
		{#each projekte as p (p.id)}
			<div class="proj-card">
				<a class="proj-card-title" href="/projekt/{encodeURIComponent(p.id)}">{p.titel}</a>
				<span class="proj-card-meta">
					{p.quellformate.join(' + ') || '—'} · {p.anzahl_einheiten} Einheiten · {zeitraum(p)}
				</span>
				{#if p.hat_export}
					<a class="proj-card-viz" href={vizAdresse(p.id)} target="_blank" rel="noreferrer">
						Viz öffnen ↗
					</a>
				{:else if p.anzahl_einheiten > 0}
					<button
						class="btn btn-sm btn-outline"
						disabled={exportiertGerade !== null}
						onclick={() => exportierenUndNachladen(p.id)}
					>
						{exportiertGerade === p.id ? 'Exportiert …' : 'Exportieren'}
					</button>
				{:else}
					<span class="proj-card-viz proj-card-viz--disabled">Viz öffnen ↗</span>
				{/if}
				<a class="proj-card-open" href="/projekt/{encodeURIComponent(p.id)}">öffnen →</a>
			</div>
		{:else}
			{#if !ladefehler}
				<span class="leer">Noch keine Projekte vorhanden.</span>
			{/if}
		{/each}
	</div>
</main>
