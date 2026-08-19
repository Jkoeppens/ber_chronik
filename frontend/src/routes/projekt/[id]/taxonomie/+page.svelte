<script lang="ts">
	import {
		ApiFehler,
		aendereKategorie,
		klassifiziere,
		ladeEinheiten,
		ladeKategorien,
		legeKategorieAn,
		loescheKategorie,
		schlageTaxonomieVor,
		setzeEinheitKategorie,
		verfolgeLauf,
		type Einheit,
		type KategorieZeile,
		type KategorienListe,
		type LaufStand
	} from '$lib/api';
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();

	let nachgeladen = $state<KategorienListe | null>(null);
	let einheitenNeu = $state<Einheit[] | null>(null);
	const stand = $derived(nachgeladen ?? data.kategorien);
	const einheiten = $derived(einheitenNeu ?? data.einheiten);
	const ladefehler = $derived(data.fehler);
	const konfiguration = $derived(data.konfiguration);

	let fehler = $state<string | null>(null);

	async function kategorienNeuLaden() {
		nachgeladen = await ladeKategorien(data.projektId);
	}
	async function einheitenNeuLaden() {
		einheitenNeu = (await ladeEinheiten(data.projektId, 'content')).einheiten;
	}

	// ── 1. Kategorien pflegen ────────────────────────────────────────────────
	let bearbeitet = $state<number | null>(null);
	let eName = $state('');
	let eBeschreibung = $state('');
	let eSchlagworte = $state('');

	function bearbeiten(k: KategorieZeile) {
		bearbeitet = k.id;
		eName = k.name;
		eBeschreibung = k.beschreibung;
		eSchlagworte = k.schlagworte.join(', ');
	}

	function felder() {
		return {
			name: eName.trim(),
			beschreibung: eBeschreibung.trim(),
			schlagworte: eSchlagworte
				.split(',')
				.map((w) => w.trim())
				.filter(Boolean)
		};
	}

	async function speichern(id: number) {
		fehler = null;
		try {
			await aendereKategorie(id, felder());
			bearbeitet = null;
			await kategorienNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	let neuOffen = $state(false);
	async function anlegen() {
		fehler = null;
		try {
			const f = felder();
			await legeKategorieAn(data.projektId, f.name, f.beschreibung, f.schlagworte);
			neuOffen = false;
			eName = eBeschreibung = eSchlagworte = '';
			await kategorienNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	async function loeschen(k: KategorieZeile) {
		if (
			!confirm(
				`'${k.name}' löschen?\n\n` +
					`${k.anzahl_einheiten} Einheiten verlieren dadurch ihre Kategorie. ` +
					`Sie bleiben erhalten.`
			)
		)
			return;
		fehler = null;
		try {
			await loescheKategorie(k.id);
			await Promise.all([kategorienNeuLaden(), einheitenNeuLaden()]);
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	// ── 2. Vorschlagen und verfeinern ────────────────────────────────────────
	let nClusters = $state(7);
	let lauf = $state<LaufStand | null>(null);
	let laeuft = $state(false);

	async function starte(warmStart: boolean) {
		laeuft = true;
		fehler = null;
		lauf = null;
		try {
			const begonnen = await schlageTaxonomieVor(data.projektId, warmStart, nClusters);
			await verfolgeLauf(begonnen.lauf_id, (s) => (lauf = s));
			await kategorienNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			laeuft = false;
		}
	}

	/** Was während des Laufs zu sehen ist — aus der lauf-Zeile, nicht aus einem Strom. */
	function fortschrittstext(s: LaufStand): string {
		const p = s.parameter as Record<string, unknown>;
		if (s.status === 'laeuft') {
			const phase = String(p.phase ?? 'beginnt');
			const runde = p.runde ? ` · Runde ${p.runde}/${p.runden_max}` : '';
			return `läuft (${phase}${runde}) — Lauf ${s.id}, seit ${s.begonnen_am}`;
		}
		if (s.status === 'fehler') return `fehlgeschlagen: ${s.fehler ?? 'ohne Meldung'}`;
		const zeilen = [
			`${p.n_clusters} Kategorien nach ${p.llm_calls} Runden` +
				(p.fruehzeitig_beendet ? ' (früh stabil)' : ''),
			`eingefroren: ${JSON.stringify(p.eingefroren ?? [])}`,
			`${p.embedding_modell} / ${p.llm_modell}`,
			`${p.in_tokens} Token ein, ${p.out_tokens} aus — $${Number(p.kosten_usd ?? 0).toFixed(4)}`,
			`Lauf ${s.id}: ${s.begonnen_am} → ${s.beendet_am}`
		];
		const traj = (p.trajektorie ?? []) as Record<string, unknown>[];
		if (traj.length) {
			zeilen.push('', 'Trajektorie:');
			for (const r of traj)
				zeilen.push(
					`  Runde ${r.llm_runde}  Änderung ${r.aenderungsanteil}  ` +
						`eingefroren ${r.eingefroren_gesamt}`
				);
		}
		return zeilen.join('\n');
	}

	// ── 3. Klassifizieren ────────────────────────────────────────────────────
	let klassLauf = $state<LaufStand | null>(null);
	let klassLaeuft = $state(false);

	async function klassifizierenStarten() {
		klassLaeuft = true;
		fehler = null;
		klassLauf = null;
		try {
			const begonnen = await klassifiziere(data.projektId, 'alle');
			await verfolgeLauf(begonnen.lauf_id, (s) => (klassLauf = s));
			await Promise.all([kategorienNeuLaden(), einheitenNeuLaden()]);
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			klassLaeuft = false;
		}
	}

	async function kategorieSetzen(einheit: Einheit, wert: string) {
		fehler = null;
		try {
			await setzeEinheitKategorie(einheit.id, wert ? Number(wert) : null);
			await Promise.all([kategorienNeuLaden(), einheitenNeuLaden()]);
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	// Nur die ersten Einheiten zeigen — 949 Zeilen mit Auswahlfeld sind unbedienbar.
	let zeigeAlle = $state(false);
	const sichtbar = $derived(zeigeAlle ? einheiten : einheiten.slice(0, 50));
	const nameJeId = $derived(
		new Map((stand?.kategorien ?? []).map((k) => [k.id, k.name]))
	);
</script>

<svelte:head><title>Taxonomie — {data.projektId}</title></svelte:head>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<a href="/projekt/{encodeURIComponent(data.projektId)}" class="btn btn-sm">← Projekt</a>
		<span class="section-label" style="flex:1">Taxonomie und Klassifikation</span>
		{#if konfiguration}
			<span class="leer">
				{konfiguration.llm.modell ?? 'kein Sprachmodell'} ·
				{konfiguration.embedding.modell ?? 'kein Embedding'}
			</span>
		{/if}
	</div>

	{#if ladefehler}
		<div class="fehler">{ladefehler}</div>
	{/if}
	{#if fehler}
		<div class="fehler">{fehler}</div>
	{/if}

	{#if stand}
		<!-- ── 1. Die Kategorien ─────────────────────────────────────────── -->
		<div style="display:flex;align-items:center;gap:10px">
			<span class="section-label" style="flex:1">
				Kategorien ({stand.anzahl})
			</span>
			<button class="btn btn-dashed btn-sm" onclick={() => {
				neuOffen = !neuOffen;
				bearbeitet = null;
				eName = eBeschreibung = eSchlagworte = '';
			}}>
				{neuOffen ? 'Abbrechen' : '+ Kategorie'}
			</button>
		</div>

		{#if neuOffen}
			<div class="card" style="padding:12px;display:flex;gap:8px;flex-wrap:wrap">
				<input class="input" style="flex:1;min-width:160px" placeholder="Name" bind:value={eName} />
				<input class="input" style="flex:2;min-width:200px" placeholder="Beschreibung" bind:value={eBeschreibung} />
				<input class="input" style="flex:1;min-width:140px" placeholder="Schlagworte, mit Komma" bind:value={eSchlagworte} />
				<button class="btn btn-sm btn-primary" disabled={!eName.trim()} onclick={anlegen}>Anlegen</button>
			</div>
		{/if}

		<div class="zeilen">
			{#each stand.kategorien as k (k.id)}
				{#if bearbeitet === k.id}
					<div class="card" style="padding:12px;display:flex;gap:8px;flex-wrap:wrap">
						<input class="input" style="flex:1;min-width:160px" bind:value={eName} />
						<input class="input" style="flex:2;min-width:200px" bind:value={eBeschreibung} />
						<input class="input" style="flex:1;min-width:140px" bind:value={eSchlagworte} />
						<button class="btn btn-sm btn-primary" onclick={() => speichern(k.id)}>Speichern</button>
						<button class="btn btn-sm" onclick={() => (bearbeitet = null)}>Abbrechen</button>
					</div>
				{:else}
					<div class="proj-card" style="align-items:flex-start">
						<div style="flex:1;display:flex;flex-direction:column;gap:2px">
							<span class="proj-card-title">{k.name}</span>
							{#if k.beschreibung}
								<span class="proj-card-meta">{k.beschreibung}</span>
							{/if}
							{#if k.schlagworte.length}
								<span class="proj-card-meta">{k.schlagworte.join(' · ')}</span>
							{/if}
						</div>
						<span class="proj-card-meta">{k.herkunft}</span>
						<span class="proj-card-meta">{k.anzahl_einheiten} Einheiten</span>
						<button class="btn btn-sm" onclick={() => bearbeiten(k)}>Bearbeiten</button>
						<button class="btn btn-sm" onclick={() => loeschen(k)}>Löschen</button>
					</div>
				{/if}
			{:else}
				<span class="leer">Noch keine Kategorien — links vorschlagen lassen.</span>
			{/each}
		</div>

		<!-- ── 2. Vorschlagen und verfeinern ─────────────────────────────── -->
		<span class="section-label">Vorschlagen</span>
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
				<button class="btn btn-primary" disabled={laeuft} onclick={() => starte(false)}>
					Themen vorschlagen
				</button>
				<label class="leer" style="display:flex;gap:5px;align-items:center">
					Cluster
					<input class="input" style="width:60px" type="number" min="2" max="20" bind:value={nClusters} disabled={laeuft} />
				</label>
				<span style="flex:1"></span>
				<button
					class="btn btn-outline"
					disabled={laeuft || stand.anzahl === 0}
					onclick={() => starte(true)}
				>
					Taxonomie verfeinern
				</button>
			</div>
			<span class="leer">
				Vorschlagen fängt bei null an und verwirft die vorhandenen Kategorien.
				Verfeinern nimmt sie als Ausgangspunkt; die Clusterzahl ist dann ihre Anzahl.
			</span>
			{#if lauf}
				<div class="log-box" class:error={lauf.status === 'fehler'}>{fortschrittstext(lauf)}</div>
			{/if}
		</div>

		<!-- ── 3. Klassifizieren ─────────────────────────────────────────── -->
		<span class="section-label">Klassifizieren</span>
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
				<button
					class="btn btn-primary"
					disabled={klassLaeuft || stand.anzahl === 0}
					onclick={klassifizierenStarten}
				>
					{klassLaeuft ? 'Klassifiziert …' : 'Klassifizieren'}
				</button>
				<span class="leer">
					Ordnet jeder Einheit eine Kategorie zu. Handkorrekturen bleiben unberührt —
					derzeit {stand.anzahl_manuell_zugeordnet}.
				</span>
			</div>
			{#if klassLauf}
				<div class="log-box" class:error={klassLauf.status === 'fehler'}>{klassLauf.status === 'laeuft'
					? `läuft — Lauf ${klassLauf.id}, seit ${klassLauf.begonnen_am}`
					: klassLauf.status === 'fehler'
						? `fehlgeschlagen: ${klassLauf.fehler}`
						: `fertig — Lauf ${klassLauf.id}, ${klassLauf.begonnen_am} → ${klassLauf.beendet_am}`}</div>
			{/if}

			<!-- Verteilung -->
			<div class="zeilen">
				{#each stand.kategorien as k (k.id)}
					<div style="display:flex;gap:8px;align-items:center;font-size:12px">
						<span style="flex:1">{k.name}</span>
						<span style="color:var(--c-text-3)">{k.anzahl_einheiten}</span>
						<span
							style="height:8px;border-radius:4px;background:var(--c-primary);flex-shrink:0"
							style:width="{Math.round(
								(k.anzahl_einheiten / Math.max(1, einheiten.length)) * 260
							)}px"
						></span>
					</div>
				{/each}
				{#if stand.anzahl_ohne_kategorie > 0}
					<div style="display:flex;gap:8px;align-items:center;font-size:12px">
						<span style="flex:1;color:var(--c-text-3)">ohne Kategorie</span>
						<span style="color:var(--c-text-3)">{stand.anzahl_ohne_kategorie}</span>
					</div>
				{/if}
			</div>
		</div>

		<!-- Handkorrektur je Einheit -->
		<div style="display:flex;align-items:center;gap:10px">
			<span class="section-label" style="flex:1">
				Einheiten ({sichtbar.length} von {einheiten.length})
			</span>
			{#if einheiten.length > 50}
				<button class="btn btn-sm" onclick={() => (zeigeAlle = !zeigeAlle)}>
					{zeigeAlle ? 'Weniger' : 'Alle zeigen'}
				</button>
			{/if}
		</div>
		<div class="zeilen">
			{#each sichtbar as e (e.id)}
				<div class="proj-card" style="align-items:flex-start;gap:8px">
					<span class="proj-card-meta" style="width:40px;flex-shrink:0">{e.position}</span>
					<span style="flex:1;font-size:12px">{e.text.slice(0, 150)}{e.text.length > 150 ? '…' : ''}</span>
					{#if e.kategorie_herkunft === 'manuell'}
						<span
							class="proj-card-meta"
							style="color:var(--c-primary);font-weight:600"
							title="Von Hand gesetzt — bleibt bei jedem Neulauf stehen"
						>
							manuell
						</span>
					{:else if e.kategorie_herkunft}
						<span class="proj-card-meta">{e.kategorie_herkunft}</span>
					{/if}
					<select
						class="input"
						style="width:210px;flex-shrink:0"
						value={e.kategorie_id === null || e.kategorie_id === undefined ? '' : String(e.kategorie_id)}
						onchange={(ereignis) =>
							kategorieSetzen(e, (ereignis.currentTarget as HTMLSelectElement).value)}
					>
						<option value="">— ohne —</option>
						{#each stand.kategorien as k (k.id)}
							<option value={String(k.id)}>{k.name.slice(0, 40)}</option>
						{/each}
					</select>
				</div>
			{/each}
		</div>
	{/if}
</main>
