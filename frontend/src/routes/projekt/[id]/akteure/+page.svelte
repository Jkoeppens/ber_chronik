<script lang="ts">
	import { invalidate } from '$app/navigation';
	import {
		ApiFehler,
		aendereAkteur,
		erkenneAkteure,
		ladeAkteure,
		ladeKandidaten,
		ladeMarkierungen,
		legeAkteurAn,
		loescheFundstelle,
		loeseAliasHeraus,
		verfolgeLauf,
		verschmelzeAkteure,
		type AkteurTyp,
		type AkteurZeile,
		type Einheit,
		type LaufStand,
		type Markierung
	} from '$lib/api';
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();

	// Die Typfarben der alten Fläche, unverändert.
	const TYPEN: AkteurTyp[] = ['Person', 'Organisation', 'Ort', 'Konzept'];
	const FARBE: Record<string, string> = {
		Person: '#2563eb',
		Ort: '#16a34a',
		Organisation: '#d97706',
		Konzept: '#7c3aed'
	};

	let akteureNeu = $state<typeof data.akteure>(null);
	let markierungenNeu = $state<typeof data.markierungen>(null);
	let kandidatenNeu = $state<typeof data.kandidaten>(null);
	const stand = $derived(akteureNeu ?? data.akteure);
	const markierungen = $derived(markierungenNeu ?? data.markierungen);
	const kandidaten = $derived(kandidatenNeu ?? data.kandidaten);
	const einheiten = $derived(data.einheiten);
	const ladefehler = $derived(data.fehler);

	let fehler = $state<string | null>(null);
	let beschaeftigt = $state(false);

	/**
	 * Nach jeder Änderung alles neu laden — Akteure, Markierungen, Kandidaten.
	 * Die alte Fläche arbeitete mit Array-Plätzen: ein Verschmelzen verschob
	 * alle Indizes darüber, die Kandidatenpaare zeigten ins Leere, und sie gab
	 * mit "Neu laden um aktualisierte Kandidaten zu berechnen" auf. Hier zeigt
	 * alles auf Kennungen, und der Server räumt die überholten Paare beim
	 * Verschmelzen selbst weg.
	 */
	async function allesNeuLaden() {
		const [a, m, k] = await Promise.all([
			ladeAkteure(data.projektId),
			ladeMarkierungen(data.projektId),
			ladeKandidaten(data.projektId)
		]);
		akteureNeu = a;
		markierungenNeu = m;
		kandidatenNeu = k;
		// Die Reiterleiste zeigt Zahlen, die sich hier gerade geändert haben.
		await invalidate('app:kennzahlen');
	}

	async function versuche(was: () => Promise<unknown>) {
		beschaeftigt = true;
		fehler = null;
		try {
			await was();
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			beschaeftigt = false;
		}
	}

	// ── Erkennung ────────────────────────────────────────────────────────────
	let lauf = $state<LaufStand | null>(null);
	let laeuft = $state(false);

	async function erkennen() {
		laeuft = true;
		fehler = null;
		lauf = null;
		try {
			const begonnen = await erkenneAkteure(data.projektId);
			await verfolgeLauf(begonnen.lauf_id, (s) => (lauf = s));
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			laeuft = false;
		}
	}

	function laufText(s: LaufStand): string {
		const p = s.parameter as Record<string, unknown>;
		if (s.status === 'laeuft') return `läuft — Lauf ${s.id}, seit ${s.begonnen_am}`;
		if (s.status === 'fehler') return `fehlgeschlagen: ${s.fehler ?? 'ohne Meldung'}`;
		const zeilen = [
			`${p.akteure} Akteure aus ${p.funde} Funden, ${p.zuordnungen} Fundstellen`,
			`${p.embedding_modell} / ${p.gliner_modell}, Schwelle ${p.schwelle}`,
			`Lauf ${s.id}: ${s.begonnen_am} → ${s.beendet_am}`
		];
		const verdraengt = (p.verdraengt_von_manuell ?? []) as string[];
		if (verdraengt.length)
			zeilen.push(`von Handkorrekturen verdrängt: ${verdraengt.join(', ')}`);
		const unbekannt = (p.unbekannte_labels ?? {}) as Record<string, number>;
		const u = Object.entries(unbekannt);
		if (u.length) zeilen.push('unbekannte Labels: ' + u.map(([k, n]) => `${k} ${n}`).join(', '));
		return zeilen.join('\n');
	}

	// ── Reiter ───────────────────────────────────────────────────────────────
	let reiter = $state<'liste' | 'annotator' | 'duplikate'>('liste');

	// ── Reiter 1: Entitätenliste ─────────────────────────────────────────────
	const nachTyp = $derived.by(() => {
		const gruppen = new Map<string, AkteurZeile[]>();
		for (const t of TYPEN) gruppen.set(t, []);
		for (const a of stand?.akteure ?? []) {
			if (a.status === 'abgelehnt') continue;
			const t = a.typ ?? 'Konzept';
			if (!gruppen.has(t)) gruppen.set(t, []);
			gruppen.get(t)!.push(a);
		}
		return [...gruppen].filter(([, v]) => v.length);
	});

	const abgelehnte = $derived((stand?.akteure ?? []).filter((a) => a.status === 'abgelehnt'));

	let offeneNamen = $state<Set<number>>(new Set());
	function namenUmschalten(id: number) {
		const neu = new Set(offeneNamen);
		neu.has(id) ? neu.delete(id) : neu.add(id);
		offeneNamen = neu;
	}

	let neuerAlias = $state<Record<number, string>>({});

	function aliasEntfernen(a: AkteurZeile, alias: string) {
		// In der Liste heißt Entfernen: der Name geht, und seine Fundstellen
		// gehen mit. Der Server leitet sie aus Normalform und Aliasen ab.
		versuche(() => aendereAkteur(a.id, { aliase: a.aliase.filter((x) => x !== alias) }));
	}

	function aliasHinzufuegen(a: AkteurZeile) {
		const wert = (neuerAlias[a.id] ?? '').trim();
		if (!wert) return;
		neuerAlias = { ...neuerAlias, [a.id]: '' };
		versuche(() => aendereAkteur(a.id, { aliase: [...a.aliase, wert] }));
	}

	// ── Neuer Akteur ─────────────────────────────────────────────────────────
	let anlegenOffen = $state(false);
	let neuName = $state('');
	let neuTyp = $state<AkteurTyp>('Person');

	function anlegen() {
		const name = neuName.trim();
		if (!name) return;
		versuche(async () => {
			await legeAkteurAn(data.projektId, name, neuTyp);
			neuName = '';
			anlegenOffen = false;
		});
	}

	// ── Verschmelzen: zwei beliebige, nicht nur vorgeschlagene ───────────────
	let ausgewaehlt = $state<number[]>([]);
	let behalten = $state<number | null>(null);

	function auswahlUmschalten(id: number) {
		if (ausgewaehlt.includes(id)) {
			ausgewaehlt = ausgewaehlt.filter((x) => x !== id);
			if (behalten === id) behalten = ausgewaehlt[0] ?? null;
		} else {
			ausgewaehlt = [...ausgewaehlt, id];
			if (behalten === null) behalten = id;
		}
	}

	const ausgewaehlteAkteure = $derived(
		ausgewaehlt
			.map((id) => (stand?.akteure ?? []).find((a) => a.id === id))
			.filter((a): a is AkteurZeile => a !== undefined)
	);

	function verschmelzen(ids: number[], behaltenId: number) {
		versuche(async () => {
			await verschmelzeAkteure(ids, behaltenId);
			ausgewaehlt = [];
			behalten = null;
		});
	}

	// ── Reiter 2: Annotator ──────────────────────────────────────────────────
	let abdeckung = $state<'alle' | 'mit' | 'ohne'>('alle');
	let typfilter = $state<string>('');

	function stellen(e: Einheit): Markierung[] {
		return markierungen?.je_einheit?.[String(e.id)] ?? [];
	}

	const sichtbareEinheiten = $derived(
		einheiten.filter((e) => {
			const s = stellen(e);
			if (abdeckung === 'mit' && !s.length) return false;
			if (abdeckung === 'ohne' && s.length) return false;
			if (typfilter && !s.some((m) => (m.typ ?? 'Konzept') === typfilter)) return false;
			return true;
		})
	);

	/** Text in Stücke zerlegen: Klartext und Markierung, nach Zeichenposition. */
	function stuecke(e: Einheit): Array<{ text: string; marke: Markierung | null }> {
		const s = [...stellen(e)].sort((a, b) => a.start - b.start);
		const raus: Array<{ text: string; marke: Markierung | null }> = [];
		let zeiger = 0;
		for (const m of s) {
			if (m.start < zeiger) continue; // Überlappung: die erste gewinnt
			if (m.start > zeiger) raus.push({ text: e.text.slice(zeiger, m.start), marke: null });
			raus.push({ text: e.text.slice(m.start, m.ende), marke: m });
			zeiger = m.ende;
		}
		if (zeiger < e.text.length) raus.push({ text: e.text.slice(zeiger), marke: null });
		return raus;
	}

	let offeneMarke = $state<number | null>(null);

	function fundstelleWeg(id: number) {
		// Im Annotator heißt Entfernen: nur diese eine Stelle.
		offeneMarke = null;
		versuche(() => loescheFundstelle(id));
	}

	// ── Auswahl im Text → neuer Akteur ───────────────────────────────────────
	let auswahltext = $state('');

	function auswahlPruefen() {
		const sel = window.getSelection();
		const t = sel?.toString().trim() ?? '';
		auswahltext = t.length >= 2 ? t : '';
	}

	function ausAuswahlAnlegen(typ: AkteurTyp) {
		const name = auswahltext;
		auswahltext = '';
		window.getSelection()?.removeAllRanges();
		versuche(() => legeAkteurAn(data.projektId, name, typ));
	}

	// ── Reiter 3: Duplikate ──────────────────────────────────────────────────
	// Eine Liste, nach Stärke sortiert. Keine Gruppenüberschriften.
	const RANG: Record<string, number> = { alias: 0, schreibweise: 1, aehnlichkeit: 2 };
	/**
	 * `mass` bedeutet je Grund etwas anderes: bei 'aehnlichkeit' eine
	 * Kosinusähnlichkeit zwischen 0 und 1, bei 'schreibweise' einen
	 * Editierabstand in Zeichen, bei 'alias' nichts. Ein Prozentzeichen an
	 * alle zu hängen machte aus Abstand 2 die Angabe "200 %".
	 */
	function grundText(grund: string, mass: number | null): string {
		if (grund === 'alias') return 'gemeinsamer Alias';
		if (grund === 'schreibweise')
			return mass === null ? 'Schreibweise' : `Schreibweise, ${mass} Zeichen`;
		return mass === null ? 'ähnlich' : `${Math.round(mass * 100)} % ähnlich`;
	}

	const sortierteKandidaten = $derived(
		[...(kandidaten?.kandidaten ?? [])].sort((a, b) => {
			const r = (RANG[a.grund] ?? 9) - (RANG[b.grund] ?? 9);
			if (r !== 0) return r;
			return (b.mass ?? 0) - (a.mass ?? 0);
		})
	);
	let alleKandidaten = $state(false);
	const gezeigteKandidaten = $derived(
		alleKandidaten ? sortierteKandidaten : sortierteKandidaten.slice(0, 50)
	);
	let ignoriert = $state<Set<number>>(new Set());
</script>

<!-- Am Dokument, nicht an einem div: die Auswahl kann über Kartengrenzen
     hinausgehen, und ein div mit Mauszeiger-Behandlung braucht eine ARIA-Rolle,
     die es nicht hat. Die alte Fläche hörte ebenfalls am Dokument. -->
<svelte:document onmouseup={auswahlPruefen} />

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<span class="section-label" style="flex:1">Akteure</span>
		{#if stand}
			<span class="leer">
				{stand.anzahl} Akteure · {stand.anzahl_manuell} von Hand geändert, bleiben
			</span>
		{/if}
		<button class="btn btn-sm btn-outline" disabled={laeuft || beschaeftigt} onclick={erkennen}>
			{laeuft ? 'Erkennt …' : 'Erkennung starten'}
		</button>
	</div>

	{#if ladefehler}<div class="fehler">{ladefehler}</div>{/if}
	{#if fehler}<div class="fehler">{fehler}</div>{/if}
	{#if lauf}
		<div class="log-box" class:error={lauf.status === 'fehler'}>{laufText(lauf)}</div>
	{/if}

	{#if stand}
		<nav class="reiter">
			<button class:aktiv={reiter === 'liste'} onclick={() => (reiter = 'liste')}>
				Entitätenliste ({stand.anzahl})
			</button>
			<button class:aktiv={reiter === 'annotator'} onclick={() => (reiter = 'annotator')}>
				Annotator ({einheiten.length})
			</button>
			<button class:aktiv={reiter === 'duplikate'} onclick={() => (reiter = 'duplikate')}>
				Duplikate ({sortierteKandidaten.length})
			</button>
		</nav>

		<!-- ══ Reiter 1: Entitätenliste ═══════════════════════════════════ -->
		{#if reiter === 'liste'}
			<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
				<button class="btn btn-sm btn-dashed" onclick={() => (anlegenOffen = !anlegenOffen)}>
					+ Akteur
				</button>
				{#if stand.anzahl_klumpen > 0}
					<span class="klumpen-hinweis">
						{stand.anzahl_klumpen} Klumpen — viele Namen, und der eigene trifft fast nie
					</span>
				{/if}
			</div>

			{#if anlegenOffen}
				<div class="card" style="padding:10px 14px;display:flex;gap:8px;align-items:center">
					<input class="input" style="flex:1" placeholder="Normalform" bind:value={neuName} />
					<select class="input" style="width:auto" bind:value={neuTyp}>
						{#each TYPEN as t (t)}<option value={t}>{t}</option>{/each}
					</select>
					<button class="btn btn-sm btn-primary" disabled={beschaeftigt} onclick={anlegen}>
						Anlegen
					</button>
				</div>
			{/if}

			{#if ausgewaehlt.length >= 1}
				<div class="card verschmelz-leiste">
					<span class="leer" style="flex:1">
						{ausgewaehlt.length} ausgewählt.
						{#if ausgewaehlt.length < 2}Noch einen wählen.{:else}Welche Normalform bleibt?{/if}
					</span>
					{#each ausgewaehlteAkteure as a (a.id)}
						<label class="behalten-wahl" class:gewaehlt={behalten === a.id}>
							<input type="radio" value={a.id} bind:group={behalten} />
							{a.normalform}
						</label>
					{/each}
					<button
						class="btn btn-sm btn-primary"
						disabled={ausgewaehlt.length < 2 || behalten === null || beschaeftigt}
						onclick={() => verschmelzen(ausgewaehlt, behalten!)}
					>
						Verschmelzen
					</button>
					<button
						class="btn btn-sm"
						onclick={() => {
							ausgewaehlt = [];
							behalten = null;
						}}>Abbrechen</button
					>
				</div>
			{/if}

			{#each nachTyp as [typ, liste] (typ)}
				<span class="section-label">{typ} ({liste.length})</span>
				<div class="zeilen">
					{#each liste as a (a.id)}
						<div class="card akteur-karte" class:gewaehlt={ausgewaehlt.includes(a.id)}>
							<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
								<input
									type="checkbox"
									checked={ausgewaehlt.includes(a.id)}
									onchange={() => auswahlUmschalten(a.id)}
									title="Zum Verschmelzen auswählen"
								/>
								<input
									class="input"
									style="flex:1;min-width:160px;font-weight:600"
									value={a.normalform}
									onchange={(e) =>
										versuche(() =>
											aendereAkteur(a.id, {
												normalform: (e.currentTarget as HTMLInputElement).value
											})
										)}
								/>
								<select
									class="input"
									style="width:auto"
									value={a.typ ?? 'Konzept'}
									onchange={(e) =>
										versuche(() =>
											aendereAkteur(a.id, {
												typ: (e.currentTarget as HTMLSelectElement).value as AkteurTyp
											})
										)}
								>
									{#each TYPEN as t (t)}<option value={t}>{t}</option>{/each}
								</select>
								<button
									class="zaehler"
									class:klumpen={a.ist_klumpen}
									onclick={() => namenUmschalten(a.id)}
									title="Namen und ihre Trefferzahlen"
								>
									{a.anzahl_fundstellen} Fundstellen
									{#if a.ist_klumpen}
										· ⚠ {Math.round((a.anteil_normalform ?? 0) * 100)} % auf den eigenen Namen
									{/if}
								</button>
								<span class="proj-card-meta">{a.herkunft}</span>
								<button
									class="btn btn-sm"
									disabled={beschaeftigt}
									title="Ablehnen — der nächste Lauf überspringt den Fehlfund"
									onclick={() => versuche(() => aendereAkteur(a.id, { status: 'abgelehnt' }))}
								>
									Ablehnen
								</button>
							</div>

							<div class="aliase">
								{#each a.aliase as alias (alias)}
									<span class="chip">
										{alias}
										<button
											title="Herauslösen — wird ein eigener Akteur"
											onclick={() => versuche(() => loeseAliasHeraus(a.id, alias))}>⤴</button
										>
										<button
											title="Entfernen — der Name geht, seine Fundstellen gehen mit"
											onclick={() => aliasEntfernen(a, alias)}>×</button
										>
									</span>
								{/each}
								<input
									class="input chip-eingabe"
									placeholder="Alias hinzufügen…"
									value={neuerAlias[a.id] ?? ''}
									oninput={(e) =>
										(neuerAlias = {
											...neuerAlias,
											[a.id]: (e.currentTarget as HTMLInputElement).value
										})}
									onkeydown={(e) => {
										if (e.key === 'Enter') {
											e.preventDefault();
											aliasHinzufuegen(a);
										}
									}}
								/>
							</div>

							{#if offeneNamen.has(a.id)}
								<table class="namen">
									<tbody>
										{#each a.namen as n (n.name)}
											<tr class:selbst={n.ist_normalform}>
												<td style="text-align:right;width:56px">{n.anzahl}×</td>
												<td>{n.name}{#if n.ist_normalform}<span class="proj-card-meta">
															Normalform</span
														>{/if}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{/if}
						</div>
					{/each}
				</div>
			{/each}

			{#if abgelehnte.length}
				<span class="section-label">Abgelehnt ({abgelehnte.length})</span>
				<div class="zeilen">
					{#each abgelehnte as a (a.id)}
						<div class="card" style="padding:8px 12px;display:flex;gap:8px;align-items:center">
							<span style="flex:1;color:var(--c-text-3)">{a.normalform}</span>
							<button
								class="btn btn-sm"
								disabled={beschaeftigt}
								onclick={() => versuche(() => aendereAkteur(a.id, { status: 'aktiv' }))}
							>
								Wieder aufnehmen
							</button>
						</div>
					{/each}
				</div>
			{/if}
		{/if}

		<!-- ══ Reiter 2: Annotator ════════════════════════════════════════ -->
		{#if reiter === 'annotator'}
			<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
				<select class="input" style="width:auto" bind:value={abdeckung}>
					<option value="alle">Alle Einheiten</option>
					<option value="mit">Nur mit Akteur</option>
					<option value="ohne">Nur ohne Akteur</option>
				</select>
				<select class="input" style="width:auto" bind:value={typfilter}>
					<option value="">Alle Typen</option>
					{#each TYPEN as t (t)}<option value={t}>{t}</option>{/each}
				</select>
				<span class="leer" style="flex:1">{sichtbareEinheiten.length} Einheiten</span>
			</div>

			{#if auswahltext}
				<div class="card auswahl-leiste">
					<span class="leer">„{auswahltext}" anlegen als</span>
					{#each TYPEN as t (t)}
						<button
							class="typ-knopf"
							style="background:{FARBE[t]}"
							disabled={beschaeftigt}
							onclick={() => ausAuswahlAnlegen(t)}>{t}</button
						>
					{/each}
					<button class="btn btn-sm" onclick={() => (auswahltext = '')}>×</button>
				</div>
			{/if}

			<div class="zeilen">
				{#each sichtbareEinheiten as e (e.id)}
					<div class="card" style="padding:10px 14px">
						<div style="display:flex;gap:8px;align-items:center">
							<span class="proj-card-meta">#{e.position}</span>
							{#if e.publikation}<span class="proj-card-meta">{e.publikation}</span>{/if}
							<span style="flex:1"></span>
							<span class="proj-card-meta">{stellen(e).length} Markierungen</span>
						</div>
						<div class="segmenttext">
							{#each stuecke(e) as st, i (i)}
								{#if st.marke}
									<button
										class="marke"
										style="--f:{FARBE[st.marke.typ ?? 'Konzept']}"
										onclick={() =>
											(offeneMarke = offeneMarke === st.marke!.id ? null : st.marke!.id)}
										>{st.text}</button
									>
									{#if offeneMarke === st.marke.id}
										<span class="marke-fenster">
											{st.marke.normalform} ({st.marke.typ ?? '?'})
											<button
												class="btn btn-sm"
												disabled={beschaeftigt}
												onclick={() => fundstelleWeg(st.marke!.id)}>Entfernen</button
											>
										</span>
									{/if}
								{:else}{st.text}{/if}
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{/if}

		<!-- ══ Reiter 3: Duplikate ════════════════════════════════════════ -->
		{#if reiter === 'duplikate'}
			<span class="leer">
				Nach Stärke sortiert: gemeinsamer Alias, dann Schreibweise, dann Ähnlichkeit.
			</span>
			<div class="zeilen">
				{#each gezeigteKandidaten as k (k.id)}
					{#if !ignoriert.has(k.id)}
						<div class="card dup-zeile">
							<span class="dup-name">{k.akteur_a}</span>
							<span class="dup-grund">{grundText(k.grund, k.mass)}</span>
							<span class="dup-name">{k.akteur_b}</span>
							<button
								class="btn btn-sm btn-primary"
								disabled={beschaeftigt}
								onclick={() => verschmelzen([k.akteur_a_id, k.akteur_b_id], k.akteur_a_id)}
							>
								{k.akteur_a} behalten
							</button>
							<button
								class="btn btn-sm"
								disabled={beschaeftigt}
								onclick={() => verschmelzen([k.akteur_a_id, k.akteur_b_id], k.akteur_b_id)}
							>
								{k.akteur_b} behalten
							</button>
							<button
								class="btn btn-sm"
								title="Ignorieren"
								onclick={() => (ignoriert = new Set([...ignoriert, k.id]))}>×</button
							>
						</div>
					{/if}
				{:else}
					<span class="leer">Keine Kandidaten. Der letzte Erkennungslauf hat keine gefunden.</span>
				{/each}
			</div>
			{#if !alleKandidaten && sortierteKandidaten.length > 50}
				<button class="btn btn-sm btn-dashed" onclick={() => (alleKandidaten = true)}>
					Die übrigen {sortierteKandidaten.length - 50} zeigen
				</button>
			{/if}
		{/if}
	{/if}
</main>

<style>
	.reiter {
		display: flex;
		gap: 0;
		border-bottom: 1px solid var(--c-border);
	}
	.reiter button {
		padding: 8px 16px;
		font-size: 12px;
		font-weight: 500;
		border: none;
		background: none;
		cursor: pointer;
		color: var(--c-text-3);
		border-bottom: 2px solid transparent;
		font-family: inherit;
	}
	.reiter button.aktiv {
		color: var(--c-primary);
		border-bottom-color: var(--c-primary);
	}
	.akteur-karte {
		padding: 8px 12px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.akteur-karte.gewaehlt {
		outline: 2px solid var(--c-primary-ring);
	}
	.aliase {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		align-items: center;
	}
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		background: var(--c-primary-tint);
		border-radius: 10px;
		padding: 2px 8px;
		font-size: 11px;
		color: #4c1d95;
	}
	.chip button {
		border: none;
		background: none;
		cursor: pointer;
		color: var(--c-primary);
		font-size: 12px;
		line-height: 1;
		padding: 0 1px;
	}
	.chip button:hover {
		color: var(--c-danger);
	}
	.chip-eingabe {
		width: 150px;
		padding: 2px 8px;
		font-size: 11px;
		border-radius: 10px;
	}
	.zaehler {
		font-size: 11px;
		color: var(--c-text-3);
		border: 1px solid var(--c-border);
		border-radius: 10px;
		padding: 2px 8px;
		background: none;
		cursor: pointer;
		font-family: inherit;
	}
	.zaehler.klumpen {
		background: #fffbeb;
		color: #92400e;
		border-color: #fcd34d;
		font-weight: 600;
	}
	.klumpen-hinweis {
		font-size: 11px;
		color: #92400e;
		background: #fffbeb;
		border: 1px solid #fcd34d;
		border-radius: 4px;
		padding: 3px 9px;
	}
	.namen {
		font-size: 11px;
		border-collapse: collapse;
		margin-top: 2px;
	}
	.namen td {
		padding: 1px 8px 1px 0;
		color: var(--c-text-2);
	}
	.namen tr.selbst td {
		font-weight: 600;
		color: var(--c-text);
	}
	.verschmelz-leiste {
		padding: 8px 12px;
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		position: sticky;
		top: 8px;
		z-index: 5;
	}
	.behalten-wahl {
		font-size: 11px;
		border: 1px solid var(--c-border);
		border-radius: 10px;
		padding: 2px 9px;
		cursor: pointer;
		display: inline-flex;
		gap: 4px;
		align-items: center;
	}
	.behalten-wahl.gewaehlt {
		border-color: var(--c-primary);
		background: var(--c-primary-tint);
	}
	.segmenttext {
		font-size: 13px;
		line-height: 1.7;
		white-space: pre-wrap;
		word-break: break-word;
		margin-top: 4px;
	}
	.marke {
		border: none;
		border-radius: 2px;
		padding: 0 2px;
		cursor: pointer;
		font: inherit;
		background: color-mix(in srgb, var(--f) 13%, transparent);
		color: var(--f);
	}
	.marke:hover {
		filter: brightness(0.85);
	}
	.marke-fenster {
		display: inline-flex;
		gap: 6px;
		align-items: center;
		font-size: 11px;
		background: var(--c-surface);
		border: 1px solid var(--c-border);
		border-radius: 6px;
		padding: 2px 6px;
		margin: 0 3px;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
	}
	.auswahl-leiste {
		padding: 8px 12px;
		display: flex;
		gap: 6px;
		align-items: center;
		flex-wrap: wrap;
		position: sticky;
		top: 8px;
		z-index: 5;
	}
	.typ-knopf {
		padding: 4px 10px;
		border: none;
		border-radius: 4px;
		font-size: 11px;
		font-weight: 600;
		cursor: pointer;
		color: #fff;
		font-family: inherit;
	}
	.dup-zeile {
		padding: 8px 12px;
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
	}
	.dup-name {
		font-size: 13px;
		font-weight: 500;
		flex: 1;
		min-width: 100px;
	}
	.dup-grund {
		font-size: 11px;
		font-weight: 600;
		color: #92400e;
		background: #fffbeb;
		border: 1px solid #fcd34d;
		border-radius: 10px;
		padding: 2px 8px;
		white-space: nowrap;
	}
</style>
