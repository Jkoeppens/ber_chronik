import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) => filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// fallback: Die Route /projekt/[id] lässt sich nicht vorab erzeugen —
			// es gibt beliebig viele Kennungen. Der Server liefert für jeden Pfad,
			// den er nicht als Datei kennt, diese Seite aus (siehe src/neu/server.py).
			adapter: adapter({ fallback: '200.html' })
		})
	]
});
