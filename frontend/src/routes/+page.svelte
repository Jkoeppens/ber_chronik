<script lang="ts">
	import {
		ApiFehler,
		beginneDropboxAnmeldung,
		exportiere,
		ladeDropboxOrdner,
		ladeDropboxStand,
		ladeProjekte,
		legeProjektAn,
		leseDateiEin,
		leseDropboxEin,
		lesePfadEin,
		setzeDropboxOrdner,
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

	// Bei einer Sammlung gibt es zwei Wege: Dropbox oder ein lokaler Ordner.
	let weg = $state<'dropbox' | 'lokal'>('dropbox');
	let dbProjekt = $state<string | null>(null);   // angelegt, sobald verbunden wird
	let dbVerbunden = $state(false);
	let dbOrdnerListe = $state<string[]>([]);
	let dbWartet = $state(false);

	const bereit = $derived(
		titel.trim().length > 0 &&
			(istSammlung
				? weg === 'dropbox'
					? dbVerbunden && ordner.trim().length > 0
					: ordner.trim().length > 0
				: datei !== null)
	);

	function zuruecksetzen() {
		titel = '';
		datei = null;
		ordner = '';
		quellformat = 'literaturexzerpt';
		weg = 'dropbox';
		dbProjekt = null;
		dbVerbunden = false;
		dbOrdnerListe = [];
		fehler = null;
		ergebnis = null;
	}

	/**
	 * Verbindet mit Dropbox. Das Projekt muss dafür schon bestehen — der Token
	 * gehört einem Projekt, nicht einer Sitzung. Es wird deshalb hier angelegt
	 * und bleibt stehen, auch wenn die Anmeldung abbricht: sichtbar in der
	 * Liste, und ein zweiter Versuch braucht keinen neuen Namen.
	 */
	async function mitDropboxVerbinden() {
		laeuft = true;
		fehler = null;
		try {
			if (!dbProjekt) {
				dbProjekt = (await legeProjektAn(titel.trim())).id;
				nachgeladen = (await ladeProjekte()).projekte;
			}
			const beginn = await beginneDropboxAnmeldung(dbProjekt);
			window.open(beginn.auth_url, 'dropbox', 'width=680,height=760');
			await aufVerbindungWarten(dbProjekt);
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			laeuft = false;
		}
	}

	/**
	 * Wartet, bis die Rückleitung angekommen ist. Das Fenster schließt sich
	 * selbst und kann der Seite nichts sagen; gefragt wird deshalb der Server,
	 * bei dem der Token landet.
	 */
	async function aufVerbindungWarten(projektId: string) {
		dbWartet = true;
		try {
			for (let versuch = 0; versuch < 150; versuch++) {
				await new Promise((r) => setTimeout(r, 2000));
				const stand = await ladeDropboxStand(projektId);
				if (stand.verbunden) {
					dbVerbunden = true;
					dbOrdnerListe = (await ladeDropboxOrdner(projektId)).ordner;
					if (dbOrdnerListe.length === 1) ordner = dbOrdnerListe[0];
					return;
				}
			}
			fehler =
				'Die Anmeldung ist nach fünf Minuten nicht angekommen. ' +
				'Sie können sie über das Projekt erneut beginnen.';
		} finally {
			dbWartet = false;
		}
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
			// Zwei Schritte, ein Knopf: erst die Zeile, dann die Quelle. Schlägt das
			// Einlesen fehl, bleibt das leere Projekt stehen — sichtbar in der Liste,
			// und ein zweiter Versuch braucht keinen neuen Namen.
			const projektId = dbProjekt ?? (await legeProjektAn(titel.trim())).id;
			if (istSammlung && weg === 'dropbox') {
				await setzeDropboxOrdner(projektId, ordner.trim());
				ergebnis = await leseDropboxEin(projektId);
			} else if (istSammlung) {
				ergebnis = await lesePfadEin(projektId, ordner.trim(), quellformat);
			} else {
				ergebnis = await leseDateiEin(projektId, datei as File, quellformat);
			}
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

			{#if istSammlung}
				<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
					<label style="display:flex;gap:5px;align-items:center;font-size:12px">
						<input type="radio" bind:group={weg} value="dropbox" disabled={laeuft} />
						Aus Dropbox
					</label>
					<label style="display:flex;gap:5px;align-items:center;font-size:12px">
						<input type="radio" bind:group={weg} value="lokal" disabled={laeuft} />
						Lokaler Ordner
					</label>
				</div>
			{/if}

			<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
				{#if istSammlung && weg === 'dropbox'}
					{#if !dbVerbunden}
						<button
							class="btn btn-outline"
							disabled={!titel.trim() || laeuft || dbWartet}
							onclick={mitDropboxVerbinden}
						>
							{dbWartet ? 'Warte auf die Anmeldung …' : 'Mit Dropbox verbinden'}
						</button>
						<span class="leer">
							{dbWartet
								? 'Das Fenster schließt sich nach der Zustimmung von selbst.'
								: 'Legt das Projekt an und öffnet die Dropbox-Anmeldung.'}
						</span>
					{:else}
						<select class="input" style="flex:1;min-width:240px" bind:value={ordner} disabled={laeuft}>
							<option value="" disabled>Ordner auswählen …</option>
							{#each dbOrdnerListe as o (o)}
								<option value={o}>{o}</option>
							{/each}
						</select>
					{/if}
				{:else if istSammlung}
					<input
						class="input"
						style="flex:1;min-width:280px"
						placeholder="Absoluter Pfad, z.B. /Users/…/Dropbox/Apps/ber-chronik/Dropbox_test1"
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
				{#if !(istSammlung && weg === 'dropbox' && !dbVerbunden)}
					<button class="btn btn-primary" disabled={!bereit || laeuft} onclick={anlegenUndEinlesen}>
						{laeuft ? 'Liest ein …' : dbProjekt ? 'Einlesen' : 'Anlegen und einlesen'}
					</button>
				{/if}
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
