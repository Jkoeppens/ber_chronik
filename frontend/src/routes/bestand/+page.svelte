<script lang="ts">
	/**
	 * Was auf dem Laufwerk liegt.
	 *
	 * Eine eigene Seite und kein Kasten auf der Startseite: die Auskunft hat
	 * fünf Abschnitte, und sie ist keine, die man beim Anlegen eines Projekts
	 * braucht. Auf der Startseite steht nur die Zahl, die zum Hinsehen bringt.
	 *
	 * Der Anlass: GLiNER wiegt 1,1 GB, bge-m3 4,3 GB. Auf dem 5-GB-Laufwerk der
	 * Railway-Vorgabe passen die beiden nicht zusammen, und ein Umschalten von
	 * voyage auf local im Betrieb füllt es — gemessen von 1,2 GB auf 5,4 GB,
	 * ohne eine einzige Meldung.
	 */
	import { ApiFehler, ladeBestand, loescheVektoren, type Bestand } from '$lib/api';

	let bestand = $state<Bestand | null>(null);
	let fehler = $state<string | null>(null);
	let raeumtGerade = $state<string | null>(null);

	/** Binär und nicht dezimal: df und der Finder rechnen so, und die Zahlen
	 *  sollen mit denen übereinstimmen, die der Nutzer sonst sieht. */
	function groesse(bytes: number): string {
		if (bytes === 0) return '—';
		const einheiten = ['B', 'KB', 'MB', 'GB', 'TB'];
		let wert = bytes;
		let i = 0;
		while (wert >= 1024 && i < einheiten.length - 1) {
			wert /= 1024;
			i++;
		}
		return `${wert.toFixed(wert < 10 && i > 1 ? 1 : 0)} ${einheiten[i]}`;
	}

	function anteil(teil: number, ganz: number): number {
		return ganz > 0 ? Math.min(100, (teil / ganz) * 100) : 0;
	}

	const belegtAnteil = $derived(
		bestand ? anteil(bestand.laufwerk_belegt, bestand.laufwerk_bytes) : 0
	);

	/** Vom Server, nicht hier gerechnet: die Grenze gehört zur Sache, nicht zur
	 *  Anzeige, und sonst stünde sie zweimal da (bestand.KNAPP_BYTES). */
	const knapp = $derived(bestand?.platz_knapp ?? false);

	const modelleSumme = $derived(
		bestand ? bestand.modelle.reduce((s, m) => s + m.bytes, 0) : 0
	);
	const rohdatenSumme = $derived(
		bestand ? bestand.rohdaten.reduce((s, m) => s + m.bytes, 0) : 0
	);
	const exporteSumme = $derived(
		bestand ? bestand.exporte.reduce((s, m) => s + m.bytes, 0) : 0
	);
	const vektorenSumme = $derived(
		bestand ? bestand.vektoren.reduce((s, m) => s + m.bytes, 0) : 0
	);

	async function laden() {
		fehler = null;
		try {
			bestand = await ladeBestand();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Bestand nicht abrufbar.';
		}
	}

	async function vektorenWegraeumen(modell: string, bytes: number) {
		if (
			!confirm(
				`Vektoren von '${modell}' wegräumen?\n\n` +
					`${groesse(bytes)} in der Datenbank.\n\n` +
					`Sie bleiben sonst liegen, damit ein Zurückschalten auf dieses Modell ` +
					`nicht neu rechnen muss. Wer sie löscht, kauft den Platz mit der ` +
					`Rechenzeit des nächsten Laufs.`
			)
		)
			return;
		raeumtGerade = modell;
		fehler = null;
		try {
			await loescheVektoren(modell);
			await laden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Wegräumen fehlgeschlagen.';
		} finally {
			raeumtGerade = null;
		}
	}

	$effect(() => {
		laden();
	});
</script>

<svelte:head><title>Bestand — BER Chronik</title></svelte:head>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<span class="section-label" style="flex:1">Bestand</span>
		<a class="btn btn-sm btn-outline" href="/">← Projekte</a>
	</div>

	{#if fehler}
		<div class="fehler">{fehler}</div>
	{/if}

	{#if bestand}
		<!-- Das Laufwerk zuerst: es ist die Grenze, in der alles andere steht. -->
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;align-items:baseline;gap:8px">
				<strong>Laufwerk</strong>
				<code class="pfad">{bestand.daten_wurzel}</code>
				<span style="flex:1"></span>
				<span class:knapp style="font-variant-numeric:tabular-nums">
					{groesse(bestand.laufwerk_frei)} frei von {groesse(bestand.laufwerk_bytes)}
				</span>
			</div>
			<div class="balken" title="{belegtAnteil.toFixed(0)} % belegt">
				<!-- Zwei Segmente: was diesem System gehört, und was sonst auf der
				     Platte liegt. Ohne die Trennung sähe eine 94 % voll gemeldete
				     Entwicklungsmaschine aus wie ein volles Laufwerk. -->
				<div
					class="balken-teil balken-eigen"
					style="width:{anteil(bestand.gezaehlt_bytes, bestand.laufwerk_bytes)}%"
					title="BER Chronik: {groesse(bestand.gezaehlt_bytes)}"
				></div>
				<div
					class="balken-teil balken-fremd"
					style="width:{anteil(
						bestand.laufwerk_belegt - bestand.gezaehlt_bytes,
						bestand.laufwerk_bytes
					)}%"
					title="Anderes auf derselben Platte"
				></div>
			</div>
			<span class="hinweis">
				Davon BER Chronik: <strong>{groesse(bestand.gezaehlt_bytes)}</strong> — Modelle
				{groesse(modelleSumme)}, Datenbank {groesse(bestand.datenbank.bytes)}, Rohdaten
				{groesse(rohdatenSumme)}, Exporte {groesse(exporteSumme)}.
			</span>
		</div>

		{#each bestand.warnungen as w (w)}
			<div class="warnung">{w}</div>
		{/each}

		<!-- Modellgewichte -->
		<div class="card" style="padding:14px">
			<div class="abschnitt-kopf">
				<strong>Modellgewichte</strong>
				<span class="summe">{groesse(modelleSumme)}</span>
			</div>
			<div class="hinweis" style="margin-bottom:8px">
				<code class="pfad">{bestand.modelle_wurzel}</code>
				{#if !bestand.modelle_auf_datenwurzel}
					<span class="knapp"> — nicht auf der Datenwurzel</span>
				{/if}
			</div>
			{#each bestand.modelle as m (m.name)}
				<div class="posten">
					<span class="posten-name">{m.name}</span>
					<div class="posten-balken">
						<div style="width:{anteil(m.bytes, modelleSumme)}%"></div>
					</div>
					<span class="posten-wert">{groesse(m.bytes)}</span>
				</div>
			{:else}
				<span class="leer">Noch kein Modell geladen.</span>
			{/each}
		</div>

		<!-- Vektoren. Der Abschnitt, in dem etwas zu entscheiden ist. -->
		<div class="card" style="padding:14px">
			<div class="abschnitt-kopf">
				<strong>Vektoren in der Datenbank</strong>
				<span class="summe">{groesse(vektorenSumme)}</span>
			</div>
			<div class="hinweis" style="margin-bottom:8px">
				Vektoren ungenutzter Modelle bleiben absichtlich liegen: sie sind der Grund,
				warum ein Zurückschalten auf einen Anbieter nicht neu rechnet. Wegräumen nur,
				wenn der Platz gebraucht wird.
			</div>
			{#each bestand.vektoren as v (v.modell)}
				<div class="posten">
					<span class="posten-name">
						{v.modell}
						<span class="posten-meta">{v.einheiten} Einheiten · {v.masse} Dim.</span>
					</span>
					{#if v.benutzt}
						<span class="marke marke-benutzt">eingestellt</span>
					{:else}
						<button
							class="btn btn-sm"
							disabled={raeumtGerade !== null}
							onclick={() => vektorenWegraeumen(v.modell, v.bytes)}
						>
							{raeumtGerade === v.modell ? 'Räumt …' : 'Wegräumen'}
						</button>
					{/if}
					<span class="posten-wert">{groesse(v.bytes)}</span>
				</div>
			{:else}
				<span class="leer">Noch keine Vektoren berechnet.</span>
			{/each}
		</div>

		<!-- Datenbank, Rohdaten, Exporte -->
		<div class="card" style="padding:14px">
			<div class="abschnitt-kopf">
				<strong>Datenbank</strong>
				<span class="summe">{groesse(bestand.datenbank.bytes)}</span>
			</div>
			<span class="hinweis">
				{bestand.datenbank.name}{bestand.datenbank.hinweis
					? ` + ${bestand.datenbank.hinweis}`
					: ''}
			</span>
		</div>

		<div class="card" style="padding:14px">
			<div class="abschnitt-kopf">
				<strong>Rohdateien je Projekt</strong>
				<span class="summe">{groesse(rohdatenSumme)}</span>
			</div>
			{#each bestand.rohdaten as m (m.name)}
				<div class="posten">
					<span class="posten-name">
						{m.name}
						<span class="posten-meta">
							{m.dateien} Datei(en){m.hinweis ? ` · ${m.hinweis}` : ''}
						</span>
					</span>
					<div class="posten-balken">
						<div style="width:{anteil(m.bytes, rohdatenSumme)}%"></div>
					</div>
					<span class="posten-wert">{groesse(m.bytes)}</span>
				</div>
			{:else}
				<span class="leer">Keine Rohdateien.</span>
			{/each}
		</div>

		<div class="card" style="padding:14px">
			<div class="abschnitt-kopf">
				<strong>Exporte je Projekt</strong>
				<span class="summe">{groesse(exporteSumme)}</span>
			</div>
			{#each bestand.exporte as m (m.name)}
				<div class="posten">
					<span class="posten-name">
						{m.name}
						<span class="posten-meta">{m.dateien} Datei(en)</span>
					</span>
					<div class="posten-balken">
						<div style="width:{anteil(m.bytes, exporteSumme)}%"></div>
					</div>
					<span class="posten-wert">{groesse(m.bytes)}</span>
				</div>
			{:else}
				<span class="leer">Noch nichts exportiert.</span>
			{/each}
		</div>
	{:else if !fehler}
		<span class="leer">Wird erhoben …</span>
	{/if}
</main>

<style>
	.balken {
		display: flex;
		height: 10px;
		border-radius: 5px;
		overflow: hidden;
		background: var(--c-border);
	}
	.balken-teil {
		height: 100%;
	}
	.balken-eigen {
		background: var(--c-primary);
	}
	.balken-fremd {
		background: var(--c-text-4);
	}
	.abschnitt-kopf {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin-bottom: 6px;
	}
	.summe {
		margin-left: auto;
		font-variant-numeric: tabular-nums;
		color: var(--c-text-2);
	}
	.posten {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 5px 0;
		border-top: 1px solid var(--c-border);
	}
	.posten-name {
		flex: 0 0 34%;
		min-width: 0;
		overflow-wrap: anywhere;
		font-size: 13px;
	}
	.posten-meta {
		display: block;
		color: var(--c-text-3);
		font-size: 11px;
	}
	.posten-balken {
		flex: 1;
		height: 6px;
		background: var(--c-border);
		border-radius: 3px;
		overflow: hidden;
	}
	.posten-balken > div {
		height: 100%;
		background: var(--c-primary-ring);
	}
	.posten-wert {
		flex: 0 0 5.5em;
		text-align: right;
		font-variant-numeric: tabular-nums;
		font-size: 13px;
	}
	.pfad {
		font-size: 11px;
		color: var(--c-text-3);
		background: var(--c-code-bg);
		border: 1px solid var(--c-code-border);
		border-radius: 3px;
		padding: 1px 4px;
	}
	.hinweis {
		font-size: 12px;
		color: var(--c-text-2);
	}
	.knapp {
		color: var(--c-danger);
		font-weight: 600;
	}
	.warnung {
		background: var(--c-danger-bg);
		border: 1px solid var(--c-danger-border);
		border-radius: 6px;
		padding: 8px 10px;
		font-size: 13px;
	}
	.marke {
		font-size: 11px;
		padding: 2px 6px;
		border-radius: 3px;
	}
	.marke-benutzt {
		background: var(--c-primary-tint);
		color: var(--c-primary-h);
	}
</style>
