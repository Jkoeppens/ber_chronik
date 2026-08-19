<script lang="ts">
	import {
		ApiFehler,
		klassifiziere,
		ladeEinheiten,
		ladeKategorien,
		schlageTaxonomieVor,
		setzeEinheitKategorie,
		speichereKategorien,
		verfolgeLauf,
		type Einheit,
		type KategorieEintrag,
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

	async function allesNeuLaden() {
		const [k, e] = await Promise.all([
			ladeKategorien(data.projektId),
			ladeEinheiten(data.projektId, 'content')
		]);
		nachgeladen = k;
		einheitenNeu = e.einheiten;
		entwurf = null; // der gespeicherte Stand ist jetzt der gültige
	}

	// ── Der Sprachmodell-Lauf ────────────────────────────────────────────────
	// Ein Knopf. Ob er vorschlägt oder verfeinert, entscheidet der Zustand —
	// und zwar Beschriftung UND Verhalten. Wer wirklich bei null anfangen will,
	// löscht die Kategorien vorher; das ist eine eigene Handlung.
	const hatKategorien = $derived((stand?.anzahl ?? 0) > 0);
	let nClusters = $state(7);
	let lauf = $state<LaufStand | null>(null);
	let laeuft = $state(false);

	async function themenlauf() {
		laeuft = true;
		fehler = null;
		lauf = null;
		try {
			const begonnen = await schlageTaxonomieVor(
				data.projektId,
				hatKategorien,
				hatKategorien ? undefined : nClusters
			);
			await verfolgeLauf(begonnen.lauf_id, (s) => (lauf = s));
			await allesNeuLaden();
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
			// Beim Embedden interessiert nur, wie viel davon gerechnet werden muss
			// — der Rest liegt gespeichert und kostet nichts.
			const vektoren =
				phase === 'embedding' && p.zu_rechnen !== undefined
					? ` · ${p.zu_rechnen} zu rechnen, ${p.aus_speicher} gespeichert`
					: '';
			return `läuft (${phase}${runde}${vektoren}) — Lauf ${s.id}, seit ${s.begonnen_am}`;
		}
		if (s.status === 'fehler') return `fehlgeschlagen: ${s.fehler ?? 'ohne Meldung'}`;
		if (s.schritt === 'klassifikation')
			return `zugeordnet — Lauf ${s.id}, ${s.begonnen_am} → ${s.beendet_am}`;
		const zeilen = [
			`${p.n_clusters} Kategorien nach ${p.llm_calls} Runden` +
				(p.fruehzeitig_beendet ? ' (früh stabil)' : ''),
			`${p.anzahl_zugeordnet} Einheiten zugeordnet, ${p.anzahl_geschuetzt} Handkorrekturen unberührt`,
			`${p.anzahl_unangetastet ?? 0} Kategorien von Hand gepflegt und nicht umgeschrieben`,
			...((p.warnungen ?? []) as string[]).map((w) => `⚠ ${w}`),
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

	// ── Der Editor: ein Entwurf, ein Speichern ───────────────────────────────
	// Solange nichts geändert ist, gibt es keinen Entwurf und der Knopf ist aus.
	// Es gibt keinen Zwischenstand: wer die Seite verlässt, verliert die Änderung.
	let entwurf = $state<KategorieEintrag[] | null>(null);

	const zeilen = $derived<KategorieEintrag[]>(
		entwurf ??
			(stand?.kategorien ?? []).map((k) => ({
				id: k.id,
				name: k.name,
				beschreibung: k.beschreibung,
				schlagworte: k.schlagworte
			}))
	);
	const geaendert = $derived(entwurf !== null);

	function bearbeite(index: number, feld: 'name' | 'beschreibung', wert: string) {
		const kopie = zeilen.map((z) => ({ ...z, schlagworte: [...z.schlagworte] }));
		kopie[index][feld] = wert;
		entwurf = kopie;
	}

	function schlagworteSetzen(index: number, wert: string) {
		const kopie = zeilen.map((z) => ({ ...z, schlagworte: [...z.schlagworte] }));
		kopie[index].schlagworte = wert
			.split(',')
			.map((w) => w.trim())
			.filter(Boolean);
		entwurf = kopie;
	}

	function zeileEntfernen(index: number) {
		const kopie = zeilen.map((z) => ({ ...z, schlagworte: [...z.schlagworte] }));
		kopie.splice(index, 1);
		entwurf = kopie;
	}

	function zeileHinzufuegen() {
		entwurf = [
			...zeilen.map((z) => ({ ...z, schlagworte: [...z.schlagworte] })),
			{ id: null, name: '', beschreibung: '', schlagworte: [] }
		];
	}

	function verwerfen() {
		entwurf = null;
	}

	let speicherLauf = $state<LaufStand | null>(null);
	let speichert = $state(false);

	async function speichern() {
		speichert = true;
		fehler = null;
		speicherLauf = null;
		try {
			const gespeichert = await speichereKategorien(data.projektId, zeilen);
			// Ohne Kategorien gibt es nichts zuzuordnen, also auch keinen Lauf.
			if (gespeichert.lauf_id !== null) {
				await verfolgeLauf(gespeichert.lauf_id, (s) => (speicherLauf = s));
			}
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			speichert = false;
		}
	}

	// ── Neu zuordnen — nur wenn es etwas zu tun gibt ─────────────────────────
	const offeneEinheiten = $derived(stand?.anzahl_ohne_kategorie ?? 0);

	// Wie viele Einheiten beim nächsten Zuordnen erst eingebettet werden müssen.
	// Sind es null, ist das Speichern in etwa einer Sekunde durch, und eine
	// angekündigte Dauer wäre eine Warnung vor nichts. null (unbekannt, kein
	// Anbieter) wird wie 0 behandelt: der Lauf scheitert dann ohnehin mit einer
	// Meldung, und eine geratene Sekundenzahl macht sie nicht verständlicher.
	const ohneVektor = $derived(stand?.einheiten_ohne_vektor ?? 0);
	let zuordnungsLauf = $state<LaufStand | null>(null);
	let ordnetZu = $state(false);

	async function neuZuordnen() {
		ordnetZu = true;
		fehler = null;
		zuordnungsLauf = null;
		try {
			const begonnen = await klassifiziere(data.projektId);
			await verfolgeLauf(begonnen.lauf_id, (s) => (zuordnungsLauf = s));
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			ordnetZu = false;
		}
	}

	async function kategorieSetzen(einheit: Einheit, wert: string) {
		fehler = null;
		try {
			await setzeEinheitKategorie(einheit.id, wert ? Number(wert) : null);
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	// Nur die ersten Einheiten zeigen — 949 Zeilen mit Auswahlfeld sind unbedienbar.
	let zeigeAlle = $state(false);
	const sichtbar = $derived(zeigeAlle ? einheiten : einheiten.slice(0, 50));
	const beschaeftigt = $derived(laeuft || speichert || ordnetZu);
</script>

<svelte:head><title>Taxonomie — {data.projektId}</title></svelte:head>

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<a href="/projekt/{encodeURIComponent(data.projektId)}" class="btn btn-sm">← Projekt</a>
		<span class="section-label" style="flex:1">Taxonomie und Zuordnung</span>
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
		<!-- ── Erst der Vorgang, der die Kategorien erzeugt ───────────────── -->
		<span class="section-label">Themen</span>
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
				<button
					class="btn btn-primary"
					disabled={beschaeftigt || geaendert}
					onclick={themenlauf}
				>
					{laeuft
						? 'Läuft …'
						: hatKategorien
							? 'Taxonomie verfeinern'
							: 'Themen vorschlagen'}
				</button>
				{#if !hatKategorien && !geaendert}
					<label class="leer" style="display:flex;gap:5px;align-items:center">
						Cluster
						<input
							class="input"
							style="width:60px"
							type="number"
							min="2"
							max="20"
							bind:value={nClusters}
							disabled={beschaeftigt}
						/>
					</label>
				{/if}
				<span class="leer" style="flex:1;min-width:260px">
					{#if geaendert}
						<!-- Der Lauf liest die Datenbank, der Entwurf steht daneben. Beides
						     gleichzeitig hieße, einen Lauf auf einen Stand loszulassen, den
						     der Historiker gerade nicht ansieht — und sein Ergebnis danach
						     den Entwurf ohne Nachfrage überschreiben zu lassen. -->
						<strong>Erst speichern.</strong> Der Lauf rechnet mit dem gespeicherten Stand, nicht
						mit den Änderungen im Editor.
					{:else if hatKategorien}
						Nimmt die {stand.anzahl} vorhandenen Kategorien als Ausgangspunkt und schärft sie.
						Von Hand gepflegte bleiben unangetastet. Um bei null anzufangen, erst alle
						Kategorien löschen.
					{:else}
						Findet Themen im Material und ordnet dabei jede Einheit zu — in einem Zug.
					{/if}
				</span>
			</div>
			{#if lauf}
				<div class="log-box" class:error={lauf.status === 'fehler'}>{fortschrittstext(lauf)}</div>
			{/if}
		</div>

		<!-- ── Dann die Kategorien selbst ─────────────────────────────────── -->
		<div style="display:flex;align-items:center;gap:10px">
			<span class="section-label" style="flex:1">Kategorien ({zeilen.length})</span>
			<button class="btn btn-sm btn-dashed" disabled={beschaeftigt} onclick={zeileHinzufuegen}>
				+ Kategorie
			</button>
			{#if geaendert}
				<button class="btn btn-sm" disabled={beschaeftigt} onclick={verwerfen}>Verwerfen</button>
			{/if}
			<button
				class="btn btn-sm btn-primary"
				disabled={!geaendert || beschaeftigt}
				onclick={speichern}
			>
				{speichert ? 'Speichert und ordnet zu …' : 'Speichern'}
			</button>
		</div>

		{#if geaendert}
			<span class="leer">
				Speichern schreibt die Beschreibungen und ordnet danach alle Einheiten neu zu.
				{#if ohneVektor > 0}
					{ohneVektor} Einheiten müssen dafür erst eingebettet werden, das dauert etwa
					{Math.max(5, Math.round(ohneVektor / 32))} Sekunden.
				{/if}
				Ohne Speichern geht die Änderung verloren.
			</span>
		{/if}

		<div class="zeilen">
			{#each zeilen as k, i (k.id ?? `neu-${i}`)}
				<div class="card" style="padding:10px 14px;display:flex;flex-direction:column;gap:6px">
					<div style="display:flex;gap:8px;align-items:center">
						<input
							class="input"
							style="flex:1;font-weight:600"
							placeholder="Name"
							value={k.name}
							disabled={beschaeftigt}
							oninput={(e) => bearbeite(i, 'name', (e.currentTarget as HTMLInputElement).value)}
						/>
						{#if k.id}
							{@const gespeichert = stand.kategorien.find((x) => x.id === k.id)}
							<span class="proj-card-meta">{gespeichert?.herkunft ?? ''}</span>
							<span class="proj-card-meta">{gespeichert?.anzahl_einheiten ?? 0} Einheiten</span>
						{:else}
							<span class="proj-card-meta" style="color:var(--c-primary)">neu</span>
						{/if}
						<button class="btn btn-sm" disabled={beschaeftigt} onclick={() => zeileEntfernen(i)}>
							Entfernen
						</button>
					</div>
					<textarea
						class="input"
						rows="2"
						placeholder="Beschreibung — sie bestimmt, was hierher zugeordnet wird"
						value={k.beschreibung}
						disabled={beschaeftigt}
						oninput={(e) =>
							bearbeite(i, 'beschreibung', (e.currentTarget as HTMLTextAreaElement).value)}
					></textarea>
					<input
						class="input"
						placeholder="Schlagworte, mit Komma"
						value={k.schlagworte.join(', ')}
						disabled={beschaeftigt}
						oninput={(e) => schlagworteSetzen(i, (e.currentTarget as HTMLInputElement).value)}
					/>
				</div>
			{:else}
				<span class="leer">Noch keine Kategorien — oben Themen vorschlagen lassen.</span>
			{/each}
		</div>

		{#if speicherLauf}
			<div class="log-box" class:error={speicherLauf.status === 'fehler'}>{speicherLauf.status ===
				'laeuft'
					? `speichert und ordnet zu — Lauf ${speicherLauf.id}, seit ${speicherLauf.begonnen_am}`
					: speicherLauf.status === 'fehler'
						? `fehlgeschlagen: ${speicherLauf.fehler}`
						: `gespeichert und zugeordnet — Lauf ${speicherLauf.id}, ${speicherLauf.begonnen_am} → ${speicherLauf.beendet_am}`}</div>
		{/if}

		<!-- ── Die Verteilung ─────────────────────────────────────────────── -->
		{#if stand.anzahl > 0}
			<span class="section-label">Verteilung</span>
			<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:6px">
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
				<span class="leer">
					{stand.anzahl_manuell_zugeordnet} Handkorrekturen, die kein Lauf anfasst
				</span>

				<!-- Der Knopf erscheint nur, wenn es etwas zu tun gibt. -->
				{#if offeneEinheiten > 0}
					<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px">
						<button class="btn btn-sm btn-outline" disabled={beschaeftigt} onclick={neuZuordnen}>
							{ordnetZu ? 'Ordnet zu …' : 'Neu zuordnen'}
						</button>
						<span class="leer">
							{offeneEinheiten} Einheiten ohne Kategorie — etwa nach einem neuen Ingest.
						</span>
					</div>
				{/if}
				{#if zuordnungsLauf}
					<div class="log-box" class:error={zuordnungsLauf.status === 'fehler'}>{zuordnungsLauf.status ===
						'laeuft'
							? `ordnet zu — Lauf ${zuordnungsLauf.id}`
							: zuordnungsLauf.status === 'fehler'
								? `fehlgeschlagen: ${zuordnungsLauf.fehler}`
								: `zugeordnet — Lauf ${zuordnungsLauf.id}`}</div>
				{/if}
			</div>
		{/if}

		<!-- ── Handkorrektur je Einheit ───────────────────────────────────── -->
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
					<span style="flex:1;font-size:12px">
						{e.text.slice(0, 150)}{e.text.length > 150 ? '…' : ''}
					</span>
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
						value={e.kategorie_id === null || e.kategorie_id === undefined
							? ''
							: String(e.kategorie_id)}
						disabled={beschaeftigt}
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
