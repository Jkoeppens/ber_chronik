/**
 * Precompute D3 force-simulation layout for the BER network graph.
 * Uses identical parameters to viz/network.js.
 *
 * Usage:  npm run precompute-network
 * Output: viz/network_layout.json
 */

import { createReadStream } from "fs";
import { readFile, writeFile } from "fs/promises";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from "d3-force";

const __dir   = dirname(fileURLToPath(import.meta.url));
const ROOT    = resolve(__dir, "..");
const DATA    = resolve(ROOT, "viz", "data.json");
const SEED    = resolve(ROOT, "viz", "entities_seed.csv");
const OUT     = resolve(ROOT, "viz", "network_layout.json");

// ── Same helpers as network.js ────────────────────────────────────────────────
function nodeRadius(d) { return Math.max(5, Math.sqrt(d.count) * 3); }
function labelSize(d)  { return Math.max(7.5, Math.min(12, nodeRadius(d) * 0.4 + 5.5)); }
function collideR(d)   { return Math.max(nodeRadius(d), d.id.length * labelSize(d) * 0.32) + 6; }

// ── Canvas size: fixed reference matching a typical 1440px-wide screen ────────
const W = 1100;   // chart-area width minus panel (~300px)
const H = 600;

// ── Load data ─────────────────────────────────────────────────────────────────
const { entries } = JSON.parse(await readFile(DATA, "utf8"));

// Build alias → typ map from CSV
const aliasMap = {};
const csvText  = await readFile(SEED, "utf8").catch(() => "");
for (const line of csvText.split("\n").slice(1)) {
  const parts = line.trim().split(",");
  if (parts.length < 3) continue;
  const alias      = parts[0].trim().toLowerCase();
  const normalform = parts.slice(1, parts.length - 1).join(",").trim();
  const typ        = parts[parts.length - 1].trim();
  if (alias && typ) aliasMap[alias] = { normalform, typ };
}

// ── Build nodes and links (same logic as search.js boot section) ──────────────
const nodeCounts = new Map();
const edgeCounts = new Map();

for (const entry of entries) {
  const actors = Array.isArray(entry.actors) ? entry.actors : [];
  for (const a of actors) {
    nodeCounts.set(a, (nodeCounts.get(a) || 0) + 1);
  }
  for (let i = 0; i < actors.length; i++) {
    for (let j = i + 1; j < actors.length; j++) {
      const key = [actors[i], actors[j]].sort().join("\x00");
      edgeCounts.set(key, (edgeCounts.get(key) || 0) + 1);
    }
  }
}

const nodes = [...nodeCounts.entries()].map(([id, count]) => ({
  id, count,
  typ: aliasMap[id.toLowerCase()]?.typ || "Org",
}));

const links = [...edgeCounts.entries()]
  .filter(([, count]) => count >= 2)
  .map(([key, count]) => {
    const [source, target] = key.split("\x00");
    return { source, target, count };
  });

console.log(`[precompute] ${nodes.length} nodes, ${links.length} links`);

// ── Run simulation to convergence ─────────────────────────────────────────────
const sim = forceSimulation(nodes)
  .force("link",    forceLink(links).id(d => d.id).distance(80).strength(0.4))
  .force("charge",  forceManyBody().strength(-220))
  .force("center",  forceCenter(W / 2, H / 2))
  .force("collide", forceCollide(collideR))
  .stop();

// Tick until alpha drops below threshold (mirrors browser behaviour)
const n = Math.ceil(Math.log(sim.alphaMin()) / Math.log(1 - sim.alphaDecay()));
console.log(`[precompute] running ${n} ticks …`);
for (let i = 0; i < n; i++) sim.tick();
console.log(`[precompute] done  alpha=${sim.alpha().toFixed(4)}`);

// ── Write output ──────────────────────────────────────────────────────────────
const layout = {
  width:  W,
  height: H,
  nodes:  nodes.map(d => ({ id: d.id, x: +d.x.toFixed(2), y: +d.y.toFixed(2) })),
};

await writeFile(OUT, JSON.stringify(layout, null, 2), "utf8");
console.log(`[precompute] written → ${OUT}`);
