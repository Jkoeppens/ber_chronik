<script lang="ts">
	import { page } from '$app/state';
	import type { Layoutdaten } from './+layout';

	let { data, children }: { data: Layoutdaten; children: import('svelte').Snippet } =
		$props();

	const z = $derived(data.kennzahlen);
	const basis = $derived(`/projekt/${encodeURIComponent(data.projektId)}`);

	/**
	 * Die fünf Schritte in der Reihenfolge, in der sie gemacht werden.
	 *
	 * Zwei Kennzeichnungen, die nicht dasselbe sagen: der Hintergrund sagt, ob
	 * ein Schritt schon etwas hervorgebracht hat, die Unterstreichung sagt, wo
	 * man gerade ist. Vorher trug die Projektseite drei gleich aussehende Links
	 * ohne Reihenfolge, und der einzige kräftige Knopf war der Export — der
	 * Schritt, der zuletzt kommt.
	 */
	const reiter = $derived([
		{
			pfad: `${basis}/quelle`,
			name: 'Quelle',
			zahl: z ? String(z.anzahl_einheiten) : '—',
			befuellt: (z?.anzahl_einheiten ?? 0) > 0
		},
		{
			pfad: `${basis}/themen`,
			name: 'Themen',
			zahl: z ? String(z.anzahl_kategorien) : '—',
			befuellt: (z?.anzahl_kategorien ?? 0) > 0
		},
		{
			pfad: `${basis}/datierung`,
			name: 'Datierung',
			zahl: z ? `${z.anzahl_datiert} / ${z.anzahl_einheiten}` : '—',
			befuellt: (z?.anzahl_datiert ?? 0) > 0
		},
		{
			pfad: `${basis}/akteure`,
			name: 'Akteure',
			zahl: z ? String(z.anzahl_akteure) : '—',
			befuellt: (z?.anzahl_akteure ?? 0) > 0
		},
		{
			pfad: `${basis}/export`,
			name: 'Export',
			zahl: z?.export_am ? z.export_am.slice(0, 10) : '—',
			befuellt: z?.hat_export ?? false
		}
	]);

	// Auf dem Pfad, nicht auf einem Zustand: ein Neuladen landet auf demselben
	// Reiter, und ein Reiter ist verlinkbar.
	const aktiv = $derived((pfad: string) => page.url.pathname === pfad);
</script>

<svelte:head><title>{z?.titel ?? data.projektId} — BER Chronik</title></svelte:head>

<div class="kopf">
	<a href="/" class="btn btn-sm">← Projekte</a>
	<span class="section-label" style="flex:1">{z?.titel ?? data.projektId}</span>
</div>

{#if data.fehler}
	<div class="inhalt"><div class="fehler">{data.fehler}</div></div>
{/if}

<nav class="reiterleiste">
	{#each reiter as r (r.pfad)}
		<a href={r.pfad} class="reiter" class:befuellt={r.befuellt} class:aktiv={aktiv(r.pfad)}>
			<span class="reiter-name">{r.name}</span>
			<span class="reiter-zahl">{r.zahl}</span>
		</a>
	{/each}
</nav>

{@render children()}

<style>
	.kopf {
		display: flex;
		align-items: center;
		gap: 10px;
		max-width: 1100px;
		margin: 0 auto;
		padding: 20px 24px 0;
	}
	.reiterleiste {
		display: flex;
		gap: 4px;
		max-width: 1100px;
		margin: 10px auto 0;
		padding: 0 24px;
		border-bottom: 1px solid var(--c-border);
		flex-wrap: wrap;
	}
	.reiter {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 7px 14px 6px;
		border-radius: 5px 5px 0 0;
		border-bottom: 2px solid transparent;
		text-decoration: none;
		color: var(--c-text-3);
		min-width: 92px;
	}
	.reiter:hover {
		background: var(--c-surface);
	}
	/* Befüllt: hat etwas hervorgebracht. Eine eigene Aussage — sie gilt auch
	   für Reiter, auf denen man gerade nicht steht. */
	.reiter.befuellt {
		background: #ecfdf5;
		color: #065f46;
	}
	.reiter.befuellt:hover {
		background: #d1fae5;
	}
	/* Aktiv: wo man gerade ist. Unabhängig von der Farbe. */
	.reiter.aktiv {
		border-bottom-color: var(--c-primary);
	}
	.reiter.aktiv .reiter-name {
		font-weight: 600;
	}
	.reiter-name {
		font-size: 12px;
	}
	.reiter-zahl {
		font-size: 11px;
		opacity: 0.75;
		font-variant-numeric: tabular-nums;
	}
</style>
