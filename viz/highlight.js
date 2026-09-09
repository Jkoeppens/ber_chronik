// ── marked.js config ──────────────────────────────────────────────────────────
marked.use({ breaks: true, gfm: true });

// ── Project routing (set once from URL; used by boot.js, network.js, search.js) ──
const PAGE_PROJECT = new URLSearchParams(location.search).get("project") ?? null;
// data/exporte/ und nicht data/projects/: dort schreibt der alte Wizard, und
// drei Kennungen gibt es in beiden Datenbanken. Ohne ?project= bleibt die Basis
// leer — dann liest viz/ die fünf eingecheckten Dateien neben sich.
const DATA_BASE    = PAGE_PROJECT ? `../data/exporte/${PAGE_PROJECT}/` : "";

// ── Constants ─────────────────────────────────────────────────────────────────
const _EVENT_TYPES_FALLBACK = [
  "Kosten","Termin","Klage","Technik",
  "Personalie","Beschluss","Vertrag","Planung","Claim",
];
let EVENT_TYPES = [..._EVENT_TYPES_FALLBACK];

// Fallback palettes used when project_meta.json is absent or has no color_map.
const _COLOR_FALLBACK = {
  Kosten:    "#B84040",
  Termin:    "#3A6EA8",
  Klage:     "#4A8F5C",
  Technik:   "#B87A30",
  Personalie:"#7A5A9A",
  Planung:   "#2A8A9A",
  Vertrag:   "#7A4A30",
  Beschluss: "#5A7A30",
  Claim:     "#888880",
};
// Muted palette — same colors for rest and active states.
// Visual distinction between highlighted and dimmed nodes comes from the
// group opacity attribute (1 vs DIM=0.35) set in applyNetworkState.
const _NODE_COLOR_FALLBACK = {
  Person:  "#3A6EA8",
  Org:     "#B87A30",
  Gremium: "#7A5A9A",
  Partei:  "#B84040",
};

let COLOR      = { ..._COLOR_FALLBACK };
let NODE_COLOR = { ..._NODE_COLOR_FALLBACK };

function initColors(meta) {
  if (meta && meta.taxonomy && meta.taxonomy.length) {
    EVENT_TYPES = meta.taxonomy.map(c => c.name);
  }
  if (meta && meta.color_map && Object.keys(meta.color_map).length) {
    COLOR = { ...meta.color_map };
  }
  if (meta && meta.node_color_map && Object.keys(meta.node_color_map).length) {
    NODE_COLOR = { ...meta.node_color_map };
  }
}

// ── Entity lookup ─────────────────────────────────────────────────────────────
let projectMeta   = null;
let aliasMap      = {};
let aliasesSorted = [];
let summaryMap    = {};

function buildAliasMap(csvText) {
  const lines = csvText.split("\n").slice(1);
  let loaded = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(",");
    if (parts.length < 3) { console.warn("[entity] skipping line:", trimmed); continue; }
    const alias      = parts[0].trim();
    const normalform = parts.slice(1, parts.length - 1).join(",").trim();
    const typ        = parts[parts.length - 1].trim();
    if (!alias || !normalform || !typ) continue;
    aliasMap[alias.toLowerCase()] = { normalform, typ };
    loaded++;
  }
  aliasesSorted = Object.keys(aliasMap).sort((a, b) => b.length - a.length);
  console.log(`[entity] aliasMap built: ${loaded} aliases`);
}

// ── Text helpers ──────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightEntities(text) {
  return highlightWithKeywords(text, []);
}

// Das Hervorheben steht vollständig in highlight-state.js: hlState,
// setHighlight, _applyHighlight, _applyTimelineHighlight und die Größen, an
// denen sie hängen (selectedEntity, netNodeSelection, netNeighbors,
// actorsByAnchor, DIM, chartDotSelection).
//
// Hier standen dieselben drei Funktionen ein zweites Mal. Sie liefen nie:
// index.html lädt highlight-state.js danach, und deren Deklarationen
// überschreiben diese. Gleich waren sie auch nicht — die tote Fassung von
// _applyHighlight rief applyNetworkState() statt _applyNetworkHighlight().
// Wer die Hervorhebung anfasste, las also mit einiger Wahrscheinlichkeit die
// falsche.

// ── Text helpers ──────────────────────────────────────────────────────────────
function highlightWithKeywords(text, keywords, focusNormalform = null) {
  const kwSet = new Set(keywords.map(k => k.toLowerCase()));
  const allPatterns = [
    ...aliasesSorted.map(escapeRegex),
    ...keywords.map(escapeRegex),
  ];
  if (!allPatterns.length) { console.warn("[highlightWithKeywords] allPatterns empty – aliasMap not loaded?"); return escapeHtml(text); }

  const pattern = allPatterns.join("|");
  const re = new RegExp(`(?<![\\p{L}\\d])(?:${pattern})(?![\\p{L}\\d])`, "giu");

  let result = "", lastIdx = 0;
  for (const match of text.matchAll(re)) {
    const m    = match[0];
    const info = aliasMap[m.toLowerCase()];
    result += escapeHtml(text.slice(lastIdx, match.index));
    if (info) {
      if (focusNormalform && info.normalform === focusNormalform) {
        result += `<span class="entity-focus" data-typ="${info.typ}" data-name="${escapeHtml(info.normalform)}">${escapeHtml(m)}</span>`;
      } else {
        result += `<span class="entity" data-typ="${info.typ}" data-name="${escapeHtml(info.normalform)}">${escapeHtml(m)}</span>`;
      }
    } else if (kwSet.has(m.toLowerCase())) {
      result += `<mark class="kw-hit">${escapeHtml(m)}</mark>`;
    } else {
      result += escapeHtml(m);
    }
    lastIdx = match.index + m.length;
  }
  return result + escapeHtml(text.slice(lastIdx));
}
