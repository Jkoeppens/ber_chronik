<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import '$lib/stil.css';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<header class="app-header">
	<h1><a href="/" style="color:inherit;font-size:inherit">BER Chronik</a></h1>
	<span class="app-status">data/neu.db</span>
</header>

{@render children()}
