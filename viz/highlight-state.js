// ── Entity + network highlight ────────────────────────────────────────────────
let selectedEntity   = null;
let netNodeSelection = null;
let netNeighbors     = null;   // Map<id, Set<id>> built in drawNetwork
let actorsByAnchor   = new Map();  // doc_anchor → Set<actor_name>; filled in boot

const DIM = 0.35;  // opacity for "rest" nodes when something is highlighted

// ── Timeline highlight state ──────────────────────────────────────────────────
// Three explicit modes, driven by a single central setter (setHighlight):
//
//   "none"   – all dots at rest; no dimming
//   "answer" – dots whose anchor is in `anchors` are highlighted, rest dimmed;
//              used for KI answers, entity selections, and edge-pair clicks
//   "single" – one dot (active) is extra-prominent (large, gold stroke);
//              other source dots are normal-highlighted; rest dimmed;
//              used when the user clicks a single paragraph card or src-ref
//
// `focusEntity` (optional) further highlights one actor across all views:
//   timeline: dots for that entity's articles get gold stroke
//   network:  the entity node gets enlarged + gold stroke
//   panel:    the entity's name spans in paragraph text use .entity-focus class
let chartDotSelection = null;  // D3 selection of all .dot circles; refreshed after each drawChart
let hlState = { mode: "none", anchors: null, active: null, focusEntity: null };

function setHighlight(mode, anchors = null, active = null, focusEntity = null) {
  hlState = { mode, anchors, active, focusEntity };
  _applyHighlight();
}

function _applyHighlight() {
  _applyTimelineHighlight();
  _applyNetworkHighlight();
  if (typeof _applyChartEntityHighlight === "function") _applyChartEntityHighlight();
}

function _applyTimelineHighlight() {
  if (!chartDotSelection) return;
  const { mode, anchors, active } = hlState;
  if (mode === "none" || !anchors || anchors.size === 0) {
    chartDotSelection
      .attr("r", 4).attr("opacity", null)
      .attr("stroke", "#fff").attr("stroke-width", 1.5);
    return;
  }
  const isSource  = v => v.anchorSet && [...anchors].some(a => v.anchorSet.has(a));
  const isFocused = v => active && v.anchorSet?.has(active);
  chartDotSelection
    .attr("r",            v => isFocused(v) ? 9 : isSource(v) ? 7 : 4)
    .attr("opacity",      v => isFocused(v) ? 1 : isSource(v) ? (mode === "single" ? 0.4 : 1) : DIM)
    .attr("stroke",       v => isFocused(v) ? "#f5c518" : "#fff")
    .attr("stroke-width", v => isFocused(v) ? 2.5 : 1.5);
}

function _applyNetworkHighlight() {
  if (typeof applyNetworkState === "function") { applyNetworkState(); return; }
}
