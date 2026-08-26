<script lang="ts">
	import { invalidate } from '$app/navigation';
	import {
		ApiFehler,
		beginneDropboxAnmeldung,
		ladeDropboxStand,
		leseDropboxEin,
		setzeDropboxOrdner,
		type DropboxStand,
		type IngestAntwort
	} from '$lib/api';
	import type { Layoutdaten } from '../+layout';

	// Die Zahlen kommen aus dem Layout — dieselbe Abfrage, die auch die
	// Reiterleiste füllt. Kein zweiter Aufruf für dieselbe Auskunft.
	let { data }: { data: Layoutdaten } = $props();
	const zahlen = $derived(data.kennzahlen);

	// ── Dropbox ──────────────────────────────────────────────────────────────
	let dropbox = $state<DropboxStand | null>(null);
	let ordner = $state('');
	let dbLaeuft = $state(false);
	let dbFehler = $state<string | null>(null);
	let dbBericht = $state<IngestAntwort | null>(null);

	async function standHolen() {
		dbFehler = null;
		try {
			dropbox = await ladeDropboxStand(data.projektId);
			ordner = dropbox.ordner ?? '';
		} catch (e) {
			dbFehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		}
	}

	async function anmelden() {
		dbLaeuft = true;
		dbFehler = null;
		try {
			const beginn = await beginneDropboxAnmeldung(data.projektId);
			// Das Fenster kommt mit dem Ergebnis zurück und schließt sich selbst;
			// der Stand steht danach in der Datenbank, nicht in diesem Reiter.
			window.open(beginn.auth_url, 'dropbox', 'width=680,height=760');
		} catch (e) {
			dbFehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			dbLaeuft = false;
		}
	}

	async function ordnerSpeichern() {
		dbLaeuft = true;
		dbFehler = null;
		try {
			dropbox = await setzeDropboxOrdner(data.projektId, ordner.trim());
		} catch (e) {
			dbFehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			dbLaeuft = false;
		}
	}

	async function dropboxEinlesen() {
		dbLaeuft = true;
		dbFehler = null;
		dbBericht = null;
		try {
			dbBericht = await leseDropboxEin(data.projektId);
			await invalidate('app:kennzahlen');
		} catch (e) {
			dbFehler = e instanceof ApiFehler ? e.message : 'Unbekannter Fehler.';
		} finally {
			dbLaeuft = false;
		}
	}

	/** Der Bericht eines Laufs — je Zeile eine Aussage. */
	function ingestText(e: IngestAntwort): string {
		const zeilen = [
			e.fortgesetzt
				? `Quelle ${e.quelle_id} fortgeführt`
				: `Quelle ${e.quelle_id} angelegt (${e.quellformat})`,
			`${e.anzahl_neu} neu, ${e.anzahl_uebersprungen} übersprungen`,
			`${e.anzahl_einheiten} Einheiten in der Quelle`
		];
		if (e.geaenderte_dateien.length) {
			zeilen.push(
				'',
				`${e.geaenderte_dateien.length} Datei(en) haben sich geändert und wurden`,
				'NICHT angefasst:',
				...e.geaenderte_dateien.map((d) => `  ${d}`)
			);
		}
		for (const h of e.hinweise) zeilen.push('', h);
		zeilen.push(`Lauf ${e.lauf_id}: ${e.status}`);
		return zeilen.join('\n');
	}

	function spanne(von: number | null, bis: number | null): string {
		if (von === null || von === undefined) return '—';
		return von === bis ? `${von}` : `${von}–${bis}`;
	}
</script>

<main class="inhalt">
	{#if zahlen}
		<dl class="zahlen">
			<div class="zahl">
				<dt>Quellformat</dt>
				<dd style="font-size:12px">{zahlen.quellformate.join(' + ') || '—'}</dd>
			</div>
			<div class="zahl">
				<dt>Quellen</dt>
				<dd>{zahlen.anzahl_quellen}</dd>
			</div>
			<div class="zahl">
				<dt>Einheiten</dt>
				<dd>{zahlen.anzahl_einheiten}</dd>
			</div>
			<div class="zahl">
				<dt>Zeitraum</dt>
				<dd style="font-size:13px">{spanne(zahlen.jahr_von, zahlen.jahr_bis)}</dd>
			</div>
		</dl>

		{#if Object.keys(zahlen.anzahl_je_typ).length}
			<span class="leer">
				{#each Object.entries(zahlen.anzahl_je_typ) as [typ, n], i (typ)}{i > 0
						? ' · '
						: ''}{typ}: {n}{/each}
			</span>
		{/if}

		<span class="section-label">Dropbox</span>
		<div class="card" style="padding:14px;display:flex;flex-direction:column;gap:10px">
			{#if dropbox === null}
				<button class="btn btn-sm" disabled={dbLaeuft} onclick={standHolen}>
					Stand abfragen
				</button>
			{:else}
				<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
					<span class="leer" style="flex:1">
						{dropbox.verbunden ? '● verbunden' : '○ nicht verbunden'}
						{#if !dropbox.anbieter_bereit}
							· DROPBOX_APP_KEY/SECRET fehlen
						{/if}
					</span>
					<button
						class="btn btn-sm btn-outline"
						disabled={dbLaeuft || !dropbox.anbieter_bereit}
						onclick={anmelden}
					>
						{dropbox.verbunden ? 'Neu anmelden' : 'Mit Dropbox anmelden'}
					</button>
					<button class="btn btn-sm" disabled={dbLaeuft} onclick={standHolen}>↻</button>
				</div>
				<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
					<input
						class="input"
						style="flex:1;min-width:200px"
						placeholder="Ordner im App-Ordner, z.B. /Dropbox_test1"
						bind:value={ordner}
						disabled={dbLaeuft}
					/>
					<button
						class="btn btn-sm"
						disabled={dbLaeuft || !ordner.trim()}
						onclick={ordnerSpeichern}
					>
						Ordner merken
					</button>
					<button
						class="btn btn-sm btn-primary"
						disabled={dbLaeuft || !dropbox.verbunden || !dropbox.ordner}
						onclick={dropboxEinlesen}
					>
						{dbLaeuft ? 'Liest …' : 'Einlesen'}
					</button>
				</div>
			{/if}

			{#if dbFehler}
				<div class="fehler">{dbFehler}</div>
			{/if}
			{#if dbBericht}
				<div class="log-box">{ingestText(dbBericht)}</div>
			{/if}
		</div>

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
