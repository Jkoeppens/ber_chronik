<script lang="ts">
	import type { Seitendaten } from './+page';

	let { data }: { data: Seitendaten } = $props();
</script>

<h1>{data.projekt}</h1>

{#if data.fehler}
	<p class="fehler" role="alert">{data.fehler}</p>
{:else}
	<p>{data.einheiten.length} Einheiten</p>

	<ol>
		{#each data.einheiten as einheit (einheit.id)}
			<li>
				<span class="kopf">{einheit.position} · {einheit.typ}</span>
				<p>{einheit.text}</p>
			</li>
		{/each}
	</ol>
{/if}

<style>
	/* Nur, was Lesbarkeit erfordert: Zeilenlänge, Abstand, Fehler erkennbar. */
	:global(body) {
		max-width: 42rem;
		margin: 2rem auto;
		padding: 0 1rem;
		line-height: 1.5;
		font-family: system-ui, sans-serif;
	}

	ol {
		padding-left: 2.5rem;
	}

	li {
		margin-bottom: 1.5rem;
	}

	.kopf {
		font-size: 0.85em;
		color: #555;
	}

	li p {
		margin: 0.25rem 0 0;
	}

	.fehler {
		border: 1px solid #b00;
		padding: 1rem;
		color: #b00;
	}
</style>
