// ── marked.js config ──────────────────────────────────────────────────────────
marked.use({ breaks: true, gfm: true });

// ── Constants ─────────────────────────────────────────────────────────────────
const EVENT_TYPES = [
  "Kosten","Termin","Klage","Technik",
  "Personalie","Beschluss","Vertrag","Planung","Claim",
];
const COLOR = {
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
const NODE_COLOR = {
  Person:  "#3A6EA8",
  Org:     "#B87A30",
  Gremium: "#7A5A9A",
  Partei:  "#B84040",
};
const NODE_COLOR_ACTIVE = {
  Person:  "#3A6EA8",
  Org:     "#B87A30",
  Gremium: "#7A5A9A",
  Partei:  "#B84040",
};

// ── Entity lookup ─────────────────────────────────────────────────────────────
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
