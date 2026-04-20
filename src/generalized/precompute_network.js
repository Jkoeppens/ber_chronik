/**
 * Precompute D3 force-simulation layout for a project's network graph.
 * Uses identical parameters to viz/network.js.
 *
 * Usage:  node src/generalized/precompute_network.js --project <name>
 * Input:  data/projects/{project}/exploration/data.json
 *         data/projects/{project}/exploration/entities_seed.csv  (optional)
 * Output: data/projects/{project}/exploration/network_layout.json
 */

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

const __dir = dirname(fileURLToPath(import.meta.url));
const ROOT  = resolve(__dir, "../..");

// ── Parse --project argument ───────────────────────────────────────────────────
const projectIdx = process.argv.indexOf("--project");
if (projectIdx === -1 || !process.argv[projectIdx + 1]) {
  console.error("Usage: node src/generalized/precompute_network.js --project <name>");
  process.exit(1);
}
const project = process.argv[projectIdx + 1];

const PROJ_DIR = resolve(ROOT, "data", "projects", project, "exploration");
const DATA     = resolve(PROJ_DIR, "data.json");
const SEED     = resolve(PROJ_DIR, "entities_seed.csv");
const OUT      = resolve(PROJ_DIR, "network_layout.json");

// ── Same helpers as network.js ────────────────────────────────────────────────
function nodeRadius(d) { return Math.max(5, Math.sqrt(d.count) * 3); }
function labelSize(d)  { return Math.max(7.5, Math.min(12, nodeRadius(d) * 0.4 + 5.5)); }
function collideR(d)   { return Math.max(nodeRadius(d), d.id.length * labelSize(d) * 0.32) + 6; }

// ── Canvas size: fixed reference matching a typical 1440px-wide screen ────────
const W = 1100;   // chart-area width minus panel (~300px)
const H = 600;

// ── Load data ─────────────────────────────────────────────────────────────────
let dataJson;
try {
  dataJson = JSON.parse(await readFile(DATA, "utf8"));
} catch (e) {
  console.error(`Cannot read ${DATA}: ${e.message}`);
  process.exit(1);
}
const { entries } = dataJson;

// Build alias → typ map from CSV (optional)
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

// ── Build nodes and links ──────────────────────────────────────────────────────
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

// LINK_MIN_COUNT = 2 — muss mit boot.js übereinstimmen
const LINK_MIN_COUNT = 2;
const links = [...edgeCounts.entries()]
  .filter(([, count]) => count >= LINK_MIN_COUNT)
  .map(([key, count]) => {
    const [source, target] = key.split("\x00");
    return { source, target, count };
  });

console.log(`[precompute] project=${project}  ${nodes.length} nodes, ${links.length} links`);

// ── Run simulation to convergence ─────────────────────────────────────────────
const sim = forceSimulation(nodes)
  .force("link",    forceLink(links).id(d => d.id).distance(80).strength(0.4))
  .force("charge",  forceManyBody().strength(-220))
  .force("center",  forceCenter(W / 2, H / 2))
  .force("collide", forceCollide(collideR))
  .stop();

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
