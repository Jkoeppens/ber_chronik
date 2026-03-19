// ── marked.js config ──────────────────────────────────────────────────────────
marked.use({ breaks: true, gfm: true });

// ── Constants ─────────────────────────────────────────────────────────────────
const EVENT_TYPES = [
  "Kosten","Termin","Klage","Technik",
  "Personalie","Beschluss","Vertrag","Planung","Claim",
];
const COLOR = {
  Kosten:"#f28e2b", Termin:"#e15759", Klage:"#b07aa1", Technik:"#17becf",
  Personalie:"#4e79a7", Beschluss:"#59a14f", Vertrag:"#8cd17d",
  Planung:"#ff9da7", Claim:"#999",
};
// Pastel tones for rest state; full saturation for hover / highlight
const NODE_COLOR = {
  Person:  "#7fa8c9",
  Org:     "#c9a87a",
  Gremium: "#a08ab5",
  Partei:  "#c47a7a",
};
const NODE_COLOR_ACTIVE = {
  Person:  "#4e79a7",
  Org:     "#f28e2b",
  Gremium: "#9467bd",
  Partei:  "#e15759",
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

function highlightEntityOnly(text, normalform) {
  // Collect only aliases that resolve to this normalform, longest first
  const aliases = aliasesSorted.filter(a => aliasMap[a]?.normalform === normalform);
  if (!aliases.length) return escapeHtml(text);
  const re = new RegExp(
    `(?<![\\p{L}\\d])(?:${aliases.map(escapeRegex).join("|")})(?![\\p{L}\\d])`, "giu"
  );
  const info = aliasMap[normalform.toLowerCase()] || { typ: "Person", normalform };
  let result = "", lastIdx = 0;
  for (const match of text.matchAll(re)) {
    result += escapeHtml(text.slice(lastIdx, match.index));
    result += `<span class="entity-self" data-typ="${info.typ}">${escapeHtml(match[0])}</span>`;
    lastIdx = match.index + match[0].length;
  }
  return result + escapeHtml(text.slice(lastIdx));
}

function highlightWithKeywords(text, keywords, focusNormalform = null) {
  const kwSet = new Set(keywords.map(k => k.toLowerCase()));
  const allPatterns = [
    ...aliasesSorted.map(escapeRegex),
    ...keywords.map(escapeRegex),
  ];
  if (!allPatterns.length) return escapeHtml(text);

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
