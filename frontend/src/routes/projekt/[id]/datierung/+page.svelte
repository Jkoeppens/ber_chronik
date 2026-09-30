<script lang="ts">
	import { tick } from 'svelte';
	import { invalidate } from '$app/navigation';
	import {
		ApiFehler,
		datiere,
		ladeDatierung,
		ladeEinheiten,
		setzeDatierung,
		setzeEinheitText,
		type Anker,
		type DatierungAntwort,
		type DatierungVerteilung,
		type Einheit
	} from '$lib/api';
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();

	let einheitenNeu = $state<Einheit[] | null>(null);
	let verteilungNeu = $state<DatierungVerteilung | null>(null);
	const einheiten = $derived(einheitenNeu ?? data.einheiten);
	const verteilung = $derived(verteilungNeu ?? data.verteilung);
	const ladefehler = $derived(data.fehler);

	let fehler = $state<string | null>(null);

	async function allesNeuLaden() {
		const [e, v] = await Promise.all([
			ladeEinheiten(data.projektId, 'content'),
			ladeDatierung(data.projektId)
		]);
		einheitenNeu = e.einheiten;
		verteilungNeu = v;
		offen = null;
		// Die Reiterleiste zeigt Zahlen, die sich hier gerade geändert haben.
		await invalidate('app:kennzahlen');
	}

	// ── Die Herkunft: Farbe und Beschriftung ────────────────────────────────
	// Die alte Vorschau hatte eine Spalte `precision`, die zwei Fragen mischte:
	// wie genau (exact/decade) und woher (heading/event). Hier sind es zwei
	// Spalten und zwei Reihen von Filtern.
	const HERKUNFT_FARBE: Record<string, string> = {
		text: '#2563eb',
		ueberschrift: '#0891b2',
		quellennotation: '#0284c7',
		frontmatter: '#0369a1',
		ereignis: '#16a34a',
		interpoliert: '#9ca3af',
		manuell: '#7c3aed',
		undatiert: '#dc2626'
	};
	const HERKUNFT_TEXT: Record<string, string> = {
		text: 'Jahreszahl im Text',
		ueberschrift: 'Jahres-Überschrift',
		quellennotation: 'Quellennotation',
		frontmatter: 'Frontmatter',
		ereignis: 'Ereignis',
		interpoliert: 'interpoliert',
		manuell: 'von Hand',
		undatiert: 'undatiert'
	};
	const REIHENFOLGE = [
		'text',
		'quellennotation',
		'frontmatter',
		'ueberschrift',
		'ereignis',
		'interpoliert',
		'manuell',
		'undatiert'
	];

	function herkunftVon(e: Einheit): string {
		return e.datierung_herkunft ?? 'undatiert';
	}

	function zeitLabel(e: Einheit): string {
		if (e.jahr_von === null || e.jahr_von === undefined) return 'undatiert';
		if (e.datum && e.datum.includes('/')) return e.datum.replace('/', ' – ');
		if (e.jahr_bis !== null && e.jahr_bis !== e.jahr_von) return `${e.jahr_von}–${e.jahr_bis}`;
		return e.datum ?? String(e.jahr_von);
	}

	// ── Verteilung, mit denselben Balken wie auf der Taxonomiefläche ────────
	const balken = $derived(
		REIHENFOLGE.map((h) => ({
			herkunft: h,
			anzahl: verteilung?.je_herkunft?.[h] ?? 0,
			farbe: HERKUNFT_FARBE[h]
		})).filter((b) => b.anzahl > 0)
	);

	// ── Ausreißer ───────────────────────────────────────────────────────────
	const ausreisserIds = $derived(new Set(verteilung?.ausreisser?.einheiten ?? []));

	// ── Filter und Reihenfolge ──────────────────────────────────────────────
	// Dokumentreihenfolge ist die Vorgabe: nur in ihr sieht man, zwischen
	// welchen Ankern ein interpolierter Absatz liegt. Die alte Vorschau konnte
	// nur chronologisch.
	let sortierung = $state<'dokument' | 'chronologisch'>('dokument');
	let filterHerkunft = $state<string>('');
	let nurAusreisser = $state(false);
	let quellenfilter = $state<string>('');

	const quellen = $derived([...new Set(einheiten.map((e) => e.quelle_id))].sort());

	const sichtbar = $derived.by(() => {
		let liste = einheiten.filter((e) => {
			if (nurAusreisser && !ausreisserIds.has(e.id)) return false;
			if (filterHerkunft && herkunftVon(e) !== filterHerkunft) return false;
			if (quellenfilter && e.quelle_id !== quellenfilter) return false;
			return true;
		});
		if (sortierung === 'chronologisch') {
			liste = [...liste].sort((a, b) => {
				const av = a.jahr_von ?? 99999;
				const bv = b.jahr_von ?? 99999;
				if (av !== bv) return av - bv;
				return (a.jahr_bis ?? av) - (b.jahr_bis ?? bv);
			});
		}
		return liste;
	});

	// Nur die ersten 60 zeigen — 949 Karten mit Formular sind unbedienbar.
	let zeigeAlle = $state(false);
	const gezeigt = $derived(zeigeAlle ? sichtbar : sichtbar.slice(0, 60));

	// ── Die Jahresachse links ───────────────────────────────────────────────
	//
	// Nur bei chronologischer Sortierung. In Dokumentreihenfolge wird sie
	// ausgeblendet, und die Liste bekommt die Breite: eine Jahresachse neben
	// einer Liste, die nicht nach Jahren geordnet ist, ist schlimmer als keine.
	// Der Marker spränge bei jedem Scrollen vor und zurück, und ein Klick
	// führte an eine Stelle, die mit dem Getroffenen nichts zu tun hat — die
	// Achse behauptete eine Ordnung, die es gerade nicht gibt.
	//
	// Nicht durch etwas anderes ersetzt: das naheliegende wäre ein Streifen
	// nach Quelldokument, aber jedes Projekt hier hat genau eine Quelle, und
	// ein Streifen aus einem Block sagt nichts. Ein Fortschrittsbalken wäre die
	// Bildlaufleiste noch einmal. Der Umschalter steht direkt darüber.
	const achseAktiv = $derived(sortierung === 'chronologisch');

	const jahre = $derived(
		einheiten.map((e) => e.jahr_von).filter((j): j is number => j !== null && j !== undefined)
	);
	const achseVon = $derived(jahre.length ? Math.floor(Math.min(...jahre) / 10) * 10 : 1900);
	const achseBis = $derived(jahre.length ? Math.ceil(Math.max(...jahre) / 10) * 10 : 2000);
	const achseSpanne = $derived(Math.max(1, achseBis - achseVon));

	/** Wo ein Jahr auf der Achse liegt, in Prozent von oben. */
	function jahrAnteil(jahr: number): number {
		return Math.min(100, Math.max(0, ((jahr - achseVon) / achseSpanne) * 100));
	}

	// Die Beschriftungen werden jetzt NACH ihrem Jahr gesetzt, nicht
	// gleichmäßig verteilt. Vorher stand darüber ein justify-content:
	// space-between und darunter ein angehängter letzter Wert, dessen Abstand
	// vom vorletzten kleiner war als alle anderen — die Achse war also gar
	// nicht linear. Für einen Zierstreifen egal, für ein Navigationsmittel
	// nicht: Marker und Klick rechnen beide mit der Linearität.
	const ticks = $derived.by(() => {
		const schritt = Math.max(1, Math.ceil(achseSpanne / 8 / 10) * 10);
		const werte: number[] = [];
		for (let j = achseVon; j <= achseBis; j += schritt) werte.push(j);
		return werte;
	});

	// ── Marker und Sprung ───────────────────────────────────────────────────
	// Beides hängt an derselben Zuordnung Karte↔Jahr. Die alte Vorschau
	// (export_preview.py) hatte den mitwandernden Marker schon; beim Umbau auf
	// Svelte ist er liegengeblieben, und die Achse war seitdem ein Zierstreifen.

	let achseEl = $state<HTMLElement | null>(null);
	let listeEl = $state<HTMLElement | null>(null);
	/** Das Jahr, an dem der Blick gerade steht — null, solange nichts sichtbar ist. */
	let markerJahr = $state<number | null>(null);
	/** True, wenn die Karte an der Bezugslinie gar kein Datum hat. */
	let markerUndatiert = $state(false);

	function markerNachfuehren() {
		if (!achseAktiv || !achseEl || !listeEl) return;
		// Die Bezugslinie ist die Oberkante der Achse. Sie klebt am oberen Rand,
		// also ist sie genau die Höhe, auf der man liest.
		const linie = achseEl.getBoundingClientRect().top;
		const karten = listeEl.querySelectorAll<HTMLElement>('[data-jahr]');
		let treffer: HTMLElement | null = null;
		for (const k of karten) {
			// Die erste Karte, deren Unterkante noch unter der Linie liegt:
			// die, die man an dieser Höhe gerade sieht.
			if (k.getBoundingClientRect().bottom > linie) {
				treffer = k;
				break;
			}
		}
		// Keine gefunden heißt: ganz nach unten gescrollt, alles liegt darüber.
		if (!treffer) treffer = karten[karten.length - 1] ?? null;
		if (!treffer) return;
		const roh = treffer.dataset.jahr;
		markerUndatiert = roh === '';
		markerJahr = roh ? Number(roh) : null;
	}

	/** Gedrosselt auf einen Bildaufbau: scroll feuert sonst dutzendfach je Ruck. */
	let angefordert = false;
	function beimScrollen() {
		if (angefordert) return;
		angefordert = true;
		requestAnimationFrame(() => {
			angefordert = false;
			markerNachfuehren();
		});
	}

	$effect(() => {
		// achseAktiv und gezeigt mitlesen, damit der Marker nach einem Wechsel
		// der Sortierung oder nach 'alle zeigen' sofort stimmt.
		void achseAktiv;
		void gezeigt.length;
		markerNachfuehren();
	});

	/** Klick auf die Achse: an das getroffene Jahr springen. */
	async function zumJahrSpringen(ereignis: MouseEvent) {
		if (!achseEl) return;
		const kasten = achseEl.getBoundingClientRect();
		const anteil = (ereignis.clientY - kasten.top) / kasten.height;
		const jahr = achseVon + anteil * achseSpanne;

		// Die erste Einheit, die nicht mehr davor liegt. sichtbar ist
		// chronologisch sortiert, also ist das die Sprungstelle.
		let stelle = sichtbar.findIndex(
			(e) => e.jahr_von !== null && e.jahr_von !== undefined && e.jahr_von >= jahr
		);
		// Nichts dahinter: die Achse reicht bis zum aufgerundeten Jahrzehnt, die
		// Daten enden früher — bei ber bis 2020 gegen 2017. Ein Klick in diese
		// letzten Prozent fand nichts und verpuffte stumm. Jetzt führt er an das
		// letzte Datierte, denn das ist, was 'ganz nach hinten' heißt.
		if (stelle < 0) {
			stelle = sichtbar.findLastIndex(
				(e) => e.jahr_von !== null && e.jahr_von !== undefined
			);
		}
		if (stelle < 0) return;   // gar nichts datiert — dann gibt es kein Ziel

		// Liegt das Ziel hinter den ersten 60, muss erst der Rest da sein —
		// sonst springt es an eine Karte, die es im DOM nicht gibt.
		if (stelle >= gezeigt.length) {
			zeigeAlle = true;
			await tick();
		}
		const ziel = listeEl?.querySelectorAll<HTMLElement>('[data-jahr]')[stelle];
		ziel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	// ── Neu datieren ────────────────────────────────────────────────────────
	let laeuft = $state(false);
	let laufbericht = $state<DatierungAntwort | null>(null);

	async function neuDatieren() {
		laeuft = true;
		fehler = null;
		laufbericht = null;
		try {
			laufbericht = await datiere(data.projektId, 'alle');
			await allesNeuLaden();
		} catch (e) {
			fehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			laeuft = false;
		}
	}

	// ── Das Korrekturformular ───────────────────────────────────────────────
	let offen = $state<number | null>(null);
	let entwurfVon = $state('');
	let entwurfBis = $state('');
	let entwurfGrund = $state('');
	let entwurfText = $state('');
	let undatierbar = $state(false);
	let speichert = $state(false);
	let textBericht = $state<string | null>(null);

	function oeffnen(e: Einheit) {
		if (offen === e.id) {
			offen = null;
			return;
		}
		offen = e.id;
		textBericht = null;
		fehler = null;
		undatierbar = e.jahr_von === null || e.jahr_von === undefined;
		const roh = e.datum ?? (e.jahr_von !== null ? String(e.jahr_von) : '');
		if (roh.includes('/')) {
			[entwurfVon, entwurfBis] = roh.split('/');
		} else {
			entwurfVon = roh;
			entwurfBis =
				e.jahr_bis !== null && e.jahr_bis !== undefined && e.jahr_bis !== e.jahr_von
					? String(e.jahr_bis)
					: '';
		}
		entwurfGrund = handBegruendung(e.id);
		entwurfText = e.text;
	}

	function anker(id: number): Anker[] {
		return verteilung?.anker?.[String(id)] ?? [];
	}

	function handBegruendung(id: number): string {
		const a = anker(id).find((x) => x.herkunft === 'manuell');
		return a?.fundstelle ?? '';
	}

	async function korrekturSpeichern(e: Einheit) {
		speichert = true;
		fehler = null;
		textBericht = null;
		try {
			if (entwurfText !== e.text) {
				const t = await setzeEinheitText(e.id, entwurfText);
				textBericht =
					`Text geändert — ${t.fundstellen_geloescht} Akteursfundstellen dieser Einheit ` +
					`gelöscht, ${t.datierung_neu} Einheiten neu datiert.`;
			}
			await setzeDatierung(
				e.id,
				undatierbar ? null : entwurfVon,
				undatierbar ? null : entwurfBis,
				entwurfGrund
			);
			await allesNeuLaden();
		} catch (err) {
			fehler = err instanceof ApiFehler ? err.message : 'Unbekannter Fehler.';
		} finally {
			speichert = false;
		}
	}

	const beschaeftigt = $derived(laeuft || speichert);
</script>

<svelte:window onscroll={beimScrollen} onresize={beimScrollen} />

<main class="inhalt">
	<div style="display:flex;align-items:center;gap:10px">
		<span class="section-label" style="flex:1">Datierung</span>
		<button class="btn btn-sm btn-outline" disabled={beschaeftigt} onclick={neuDatieren}>
			{laeuft ? 'Datiert …' : 'Neu datieren'}
		</button>
	</div>

	{#if ladefehler}<div class="fehler">{ladefehler}</div>{/if}
	{#if fehler}<div class="fehler">{fehler}</div>{/if}

	{#if verteilung}
		<!-- ── Woher die Daten kommen ─────────────────────────────────────── -->
		<span class="section-label">Verteilung</span>
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:6px">
			{#each balken as b (b.herkunft)}
				<div style="display:flex;gap:8px;align-items:center;font-size:12px">
					<span style="flex:1">{HERKUNFT_TEXT[b.herkunft] ?? b.herkunft}</span>
					<span style="color:var(--c-text-3)">{b.anzahl}</span>
					<span
						style="height:8px;border-radius:4px;flex-shrink:0;background:{b.farbe}"
						style:width="{Math.round((b.anzahl / Math.max(1, verteilung.anzahl)) * 260)}px"
					></span>
				</div>
			{/each}
			{#if verteilung.anzahl_interpoliert > 0}
				<span class="leer">
					<strong>{verteilung.anzahl_interpoliert} von {verteilung.anzahl}</strong> Einheiten sind
					interpoliert — aus den Ankern davor und danach abgeleitet, also geraten. Sie tragen
					kein Datum aus dem Material. Wo der Anker davor später ist als der danach, gilt der
					davor als Zeitpunkt; aufgespannt wird nur vorwärts.
				</span>
			{/if}
			{#if verteilung.ausreisser.einheiten.length > 0}
				<span class="leer" style="color:var(--c-danger)">
					{verteilung.ausreisser.einheiten.length} Einheiten liegen außerhalb von
					{verteilung.ausreisser.unten}–{verteilung.ausreisser.oben} und ziehen den Zeitraum des
					Projekts mit sich.
				</span>
			{/if}
			{#if laufbericht}
				<div class="log-box">{laufbericht.anzahl_datiert} von {laufbericht.anzahl_einheiten} datiert,
{laufbericht.anzahl_anker} Anker, Lauf {laufbericht.lauf_id}{laufbericht.warnungen.length
						? '\n' + laufbericht.warnungen.join('\n')
						: ''}</div>
			{/if}
		</div>

		<!-- ── Filter ─────────────────────────────────────────────────────── -->
		<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
			<button
				class="btn btn-sm"
				class:btn-primary={!filterHerkunft && !nurAusreisser}
				onclick={() => {
					filterHerkunft = '';
					nurAusreisser = false;
				}}
			>
				Alle {verteilung.anzahl}
			</button>
			{#each balken as b (b.herkunft)}
				<button
					class="btn btn-sm"
					class:btn-primary={filterHerkunft === b.herkunft}
					onclick={() => {
						filterHerkunft = filterHerkunft === b.herkunft ? '' : b.herkunft;
						nurAusreisser = false;
					}}
				>
					{HERKUNFT_TEXT[b.herkunft] ?? b.herkunft}
					{b.anzahl}
				</button>
			{/each}
			{#if verteilung.ausreisser.einheiten.length > 0}
				<button
					class="btn btn-sm"
					class:btn-primary={nurAusreisser}
					style="border-color:var(--c-danger);color:{nurAusreisser ? '' : 'var(--c-danger)'}"
					onclick={() => {
						nurAusreisser = !nurAusreisser;
						filterHerkunft = '';
					}}
				>
					Ausreißer {verteilung.ausreisser.einheiten.length}
				</button>
			{/if}
		</div>

		<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
			<label class="leer" style="display:flex;gap:5px;align-items:center">
				Reihenfolge
				<select class="input" style="width:auto;padding:3px 7px" bind:value={sortierung}>
					<option value="dokument">im Dokument</option>
					<option value="chronologisch">chronologisch</option>
				</select>
			</label>
			{#if quellen.length > 1}
				<label class="leer" style="display:flex;gap:5px;align-items:center">
					Quelle
					<select class="input" style="width:auto;padding:3px 7px" bind:value={quellenfilter}>
						<option value="">alle {quellen.length}</option>
						{#each quellen as q (q)}<option value={q}>{q}</option>{/each}
					</select>
				</label>
			{/if}
			<span class="leer" style="flex:1">{sichtbar.length} Einheiten</span>
		</div>

		<!-- ── Achse links, Karten rechts ─────────────────────────────────── -->
		<div style="display:flex;gap:12px;align-items:flex-start">
			{#if achseAktiv}
				<!-- Ein Knopf und kein div: die Achse ist bedienbar, also muss sie
				     auch mit der Tastatur erreichbar sein. -->
				<button
					class="achse"
					bind:this={achseEl}
					type="button"
					onclick={zumJahrSpringen}
					title="Klicken, um an ein Jahr zu springen"
					aria-label="Jahresachse — klicken, um an ein Jahr zu springen"
				>
					{#each ticks as j (j)}
						<span class="achse-tick" style="top:{jahrAnteil(j)}%">{j}</span>
					{/each}

					{#if markerJahr !== null}
						<span class="achse-marker" style="top:{jahrAnteil(markerJahr)}%">
							<span class="achse-marker-wert">{markerJahr}</span>
						</span>
					{:else if markerUndatiert}
						<!-- Undatierte Einheiten stehen chronologisch am Ende und haben
						     keinen Ort auf der Achse. Den Marker dort trotzdem
						     irgendwohin zu setzen wäre eine Behauptung. -->
						<span class="achse-marker achse-marker--ohne" style="top:100%">
							<span class="achse-marker-wert">undatiert</span>
						</span>
					{/if}
				</button>
			{/if}

			<div class="zeilen" bind:this={listeEl} style="flex:1;min-width:0">
				{#each gezeigt as e (e.id)}
					{@const h = herkunftVon(e)}
					<!-- data-jahr trägt die Zuordnung Karte↔Jahr, an der Marker und
					     Sprung beide hängen. Leer heißt undatiert — und das ist
					     etwas anderes als 'kein data-jahr'. -->
					<div
						class="card datum-karte"
						class:ausreisser={ausreisserIds.has(e.id)}
						data-jahr={e.jahr_von ?? ''}
						style="--rand:{HERKUNFT_FARBE[h] ?? '#ccc'}"
					>
						<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
							<span style="font-size:15px;font-weight:700">{zeitLabel(e)}</span>
							<span class="marke" style="background:{HERKUNFT_FARBE[h] ?? '#888'}">
								{HERKUNFT_TEXT[h] ?? h}
							</span>
							{#if e.praezision && e.praezision !== 'keine'}
								<span class="proj-card-meta">{e.praezision}</span>
							{/if}
							{#if ausreisserIds.has(e.id)}
								<span class="marke" style="background:var(--c-danger)">Ausreißer</span>
							{/if}
							<span style="flex:1"></span>
							<span class="proj-card-meta">#{e.position}</span>
							<button class="btn btn-sm" disabled={beschaeftigt} onclick={() => oeffnen(e)}>
								Bearbeiten
							</button>
						</div>

						<div style="font-size:12px;color:var(--c-text-2);margin-top:4px">
							{e.text}{#if e.seite}<span class="proj-card-meta"> S. {e.seite}</span>{/if}
						</div>

						{#if anker(e.id).length}
							<div class="belege">
								{#each anker(e.id) as a, i (i)}
									<span class="beleg" style="border-color:{HERKUNFT_FARBE[a.herkunft] ?? '#ccc'}">
										{HERKUNFT_TEXT[a.herkunft] ?? a.herkunft}{a.jahr !== null ? `: ${a.jahr}` : ''}
										{#if a.fundstelle}<em>„{a.fundstelle}"</em>{/if}
									</span>
								{/each}
							</div>
						{/if}

						{#if offen === e.id}
							<div class="formular">
								<div>
									<div class="feldname">Text</div>
									<textarea class="input" rows="3" bind:value={entwurfText}></textarea>
									<span class="leer">
										Ändern löscht die Akteursfundstellen dieser Einheit — ihre Zeichenpositionen
										zeigten sonst auf andere Wörter. Der nächste Akteurslauf legt sie neu an.
									</span>
								</div>
								<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
									<span class="feldname" style="width:70px">Zeitraum</span>
									<input
										class="input"
										style="width:130px"
										placeholder="2012-07-30"
										bind:value={entwurfVon}
										disabled={undatierbar}
									/>
									<span class="leer">–</span>
									<input
										class="input"
										style="width:130px"
										placeholder="leer = Zeitpunkt"
										bind:value={entwurfBis}
										disabled={undatierbar}
									/>
									<label class="leer" style="display:flex;gap:5px;align-items:center">
										<input type="checkbox" bind:checked={undatierbar} />
										Undatierbar
									</label>
								</div>
								<span class="leer" style="margin-left:78px;margin-top:-4px">
									2012, 2012-07 oder 2012-07-30 — die Genauigkeit folgt daraus.
								</span>
								<div style="display:flex;gap:8px;align-items:center">
									<span class="feldname" style="width:70px">Begründung</span>
									<input
										class="input"
										style="flex:1"
										placeholder="Warum — steht danach als Beleg an der Einheit"
										bind:value={entwurfGrund}
									/>
								</div>
								<div style="display:flex;gap:8px">
									<button
										class="btn btn-sm btn-primary"
										disabled={speichert}
										onclick={() => korrekturSpeichern(e)}
									>
										{speichert ? 'Speichert …' : 'Speichern'}
									</button>
									<button class="btn btn-sm" disabled={speichert} onclick={() => (offen = null)}>
										Abbrechen
									</button>
								</div>
								{#if textBericht}<div class="log-box">{textBericht}</div>{/if}
							</div>
						{/if}
					</div>
				{:else}
					<span class="leer">Keine Einheiten mit diesen Filtern.</span>
				{/each}

				{#if sichtbar.length > gezeigt.length}
					<button class="btn btn-sm btn-dashed" onclick={() => (zeigeAlle = true)}>
						Alle {sichtbar.length} zeigen
					</button>
				{/if}
			</div>
		</div>
	{/if}
</main>

<style>
	/* Die Achse ist ein Knopf, sieht aber keiner sein: sie trägt nichts von
	   dem, was ein Knopf sonst mitbringt. Bedienbar muss sie trotzdem sein. */
	.achse {
		flex: 0 0 62px;
		position: sticky;
		top: 12px;
		height: 70vh;
		border: 0;
		border-right: 1px solid var(--c-border);
		background: none;
		padding: 0 8px 0 0;
		font: inherit;
		text-align: right;
		cursor: pointer;
	}
	.achse:hover {
		border-right-color: var(--c-text-4);
	}
	/* Absolut nach Jahr gesetzt, nicht gleichmäßig verteilt: sonst wäre die
	   Achse nicht linear, und Marker wie Sprung rechneten daneben. */
	.achse-tick {
		position: absolute;
		right: 8px;
		transform: translateY(-50%);
		font-size: 10px;
		color: var(--c-text-3);
		pointer-events: none;
		user-select: none;
	}
	.achse-marker {
		position: absolute;
		right: -1px;
		width: 22px;
		height: 0;
		border-top: 2px solid var(--c-primary);
		transform: translateY(-1px);
		pointer-events: none;
	}
	.achse-marker-wert {
		position: absolute;
		right: 26px;
		top: -8px;
		background: var(--c-primary);
		color: #fff;
		font-size: 10px;
		font-variant-numeric: tabular-nums;
		padding: 1px 5px;
		border-radius: 3px;
		white-space: nowrap;
	}
	/* Undatiertes hat keinen Ort auf einer Jahresachse. Der Marker steht am
	   Fuß und sagt das, statt eine Jahreszahl zu behaupten. */
	.achse-marker--ohne {
		border-top-color: var(--c-text-4);
	}
	.achse-marker--ohne .achse-marker-wert {
		background: var(--c-text-4);
	}
	.datum-karte {
		padding: 8px 12px;
		border-left: 4px solid var(--rand);
	}
	.datum-karte.ausreisser {
		background: var(--c-danger-bg, #fef2f2);
	}
	.marke {
		font-size: 10px;
		color: #fff;
		padding: 1px 6px;
		border-radius: 10px;
	}
	.belege {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 6px;
	}
	.beleg {
		font-size: 10px;
		color: var(--c-text-3);
		border: 1px solid;
		border-radius: 3px;
		padding: 1px 5px;
	}
	.beleg em {
		color: var(--c-text-2);
		font-style: normal;
	}
	.formular {
		margin-top: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--c-border);
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.feldname {
		font-size: 11px;
		color: var(--c-text-3);
	}
</style>
