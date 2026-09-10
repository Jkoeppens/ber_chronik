// ── marked.js config ──────────────────────────────────────────────────────────
marked.use({ breaks: true, gfm: true });

// ── Project routing (set once from URL; used by boot.js, network.js, search.js) ──
const PAGE_PROJECT = new URLSearchParams(location.search).get("project") ?? null;
// data/exporte/ und nicht data/projects/: dort schreibt der alte Wizard, und
// drei Kennungen gibt es in beiden Datenbanken. Ohne ?project= bleibt die Basis
// leer — und ohne Projekt lädt viz/ gar nichts (siehe boot.js).
const DATA_BASE    = PAGE_PROJECT ? `../data/exporte/${PAGE_PROJECT}/` : "";

// ── Constants ─────────────────────────────────────────────────────────────────
const _EVENT_TYPES_FALLBACK = [
  "Kosten","Termin","Klage","Technik",
  "Personalie","Beschluss","Vertrag","Planung","Claim",
];
let EVENT_TYPES = [..._EVENT_TYPES_FALLBACK];

// ── Farben ────────────────────────────────────────────────────────────────────
// Vergeben wird hier, nicht im Export. Bis September 2026 rechnete
// export/kern.farbzuordnung sie nach Listenplatz aus und legte sie als
// color_map in project_meta.json — wer eine Kategorie in der Mitte löschte,
// verschob alle nachfolgenden Farben. Eine Farbe ist Darstellung; sie gehört
// nicht durch die Datenbank und nicht durch den Export.
//
// Die Zuordnung hängt am NAMEN, nicht an der Position: der Name bestimmt über
// einen Hash den Palettenplatz. Zwei Namen können denselben treffen, und bei
// sieben Kategorien auf zwölf Plätzen ist das eher die Regel als die Ausnahme
// — deshalb probiert jeder Name der Reihe nach hash(name, 0), hash(name, 1),
// … bis ein freier Platz kommt.
//
// Damit hängt die Zuordnung an der MENGE der Namen, nicht an ihrer
// Reihenfolge: verarbeitet wird in einer Folge, die sich aus den Namen selbst
// ergibt (nach Hash sortiert). Was das kostet, sei gesagt: eine Kategorie zu
// löschen kann die Farbe derer ändern, die mit ihr um einen Platz gerungen
// haben — gemessen an ber eine von sechs, wo es vorher drei von sechs waren.
// Vollständige Unverschiebbarkeit ginge nur mit einer reinen Funktion des
// Namens, und die ist unbrauchbar: gemessen liegen dann in JEDEM der sieben
// Projekte zwei Kategorien unter 20° Farbtonabstand, in ber unter 2°.
const PALETTE = [
  "#3b82f6", "#f59e0b", "#10b981", "#8b5cf6", "#ef4444", "#06b6d4",
  "#f97316", "#6366f1", "#14b8a6", "#a855f7", "#84cc16", "#ec4899",
];

// FNV-1a, 32 Bit. Klein, ohne Abhängigkeit, und für jeden Namen derselbe Wert
// in jedem Browser — das ist die einzige Anforderung.
function _hash(text, runde = 0) {
  let h = (0x811c9dc5 ^ runde) >>> 0;
  for (let i = 0; i < text.length; i++) {
    h ^= text.codePointAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

function farbzuordnung(namen, palette = PALETTE) {
  const eindeutig = [...new Set(namen)].filter(Boolean);
  // Die Verarbeitungsfolge kommt aus den Namen selbst, nicht aus der Eingabe.
  const reihe = eindeutig.sort((a, b) => _hash(a) - _hash(b) || (a < b ? -1 : 1));
  const belegt = new Set();
  const zuordnung = {};
  for (const name of reihe) {
    let platz = null;
    for (let runde = 0; runde < palette.length; runde++) {
      const p = _hash(name, runde) % palette.length;
      if (!belegt.has(p)) { platz = p; break; }
    }
    // Mehr Namen als Farben: dann teilen sich zwei eine. Besser als keine.
    if (platz === null) platz = _hash(name) % palette.length;
    belegt.add(platz);
    zuordnung[name] = palette[platz];
  }
  return zuordnung;
}

// Akteurstypen sind ein fester Wertevorrat (src/neu/vokabular.py: AkteurTyp),
// keine Namen aus dem Material. Vier feste Farben, kein Hash — und deshalb
// brauchte auch node_color_map nie durch den Export zu gehen.
const NODE_COLOR_VORRAT = {
  Person:       "#3A6EA8",
  Organisation: "#B87A30",
  Ort:          "#4A8F5C",
  Konzept:      "#7A5A9A",
};
let COLOR      = farbzuordnung(_EVENT_TYPES_FALLBACK);
let NODE_COLOR = { ...NODE_COLOR_VORRAT };

function initColors(meta) {
  if (meta && meta.taxonomy && meta.taxonomy.length) {
    EVENT_TYPES = meta.taxonomy.map(c => c.name);
  }
  COLOR = farbzuordnung(EVENT_TYPES);
  NODE_COLOR = { ...NODE_COLOR_VORRAT };
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
