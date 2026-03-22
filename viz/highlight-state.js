// ── Entity + network highlight ────────────────────────────────────────────────
let selectedEntity   = null;
let netNodeSelection = null;
let netNeighbors     = null;   // Map<id, Set<id>> built in drawNetwork
let actorsByAnchor   = new Map();  // doc_anchor → Set<actor_name>; filled in boot

const DIM = 0.35;  // opacity for "rest" nodes when something is highlighted

// ── Timeline highlight ────────────────────────────────────────────────────────
// Three explicit states, one central setter:
//   "none"   – all dots at rest
//   "answer" – source dots highlighted, rest dimmed
//   "single" – one dot extra-prominent, other source dots normal-highlighted, rest dimmed
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
  if (!netNodeSelection) return;
  const { mode, anchors, active } = hlState;
  // Reset radius first (hover or previous state may have changed it)
  netNodeSelection.select("circle").attr("r", nodeRadius);
  if (mode === "none" || !anchors || anchors.size === 0) {
    netNodeSelection.attr("opacity", 1);
    netNodeSelection.select("circle")
      .attr("fill",             d => NODE_COLOR[d.typ] || "#bbb")
      .attr("stroke",           "#fff")
      .attr("stroke-width",     1.5)
      .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");
    return;
  }
  // Build actor sets for answer anchors and the focused single anchor
  const { focusEntity } = hlState;
  const answerActors = new Set([...anchors].flatMap(a => [...(actorsByAnchor.get(a) || [])]));
  const activeActors = active ? (actorsByAnchor.get(active) || new Set()) : new Set();
  netNodeSelection.attr("opacity", d => answerActors.has(d.id) ? 1 : DIM);
  netNodeSelection.select("circle")
    .attr("fill",         d => answerActors.has(d.id) ? (NODE_COLOR_ACTIVE[d.typ] || "#999") : (NODE_COLOR[d.typ] || "#bbb"))
    .attr("r",            d => d.id === focusEntity ? nodeRadius(d) * 1.4 : activeActors.has(d.id) ? nodeRadius(d) * 1.25 : nodeRadius(d))
    .attr("stroke",       d => d.id === focusEntity ? "#f5c518" : activeActors.has(d.id) ? "#f5c518" : "#fff")
    .attr("stroke-width", d => d.id === focusEntity ? 3 : activeActors.has(d.id) ? 2.5 : 1.5)
    .attr("stroke-dasharray", d => (d.id === focusEntity || activeActors.has(d.id)) ? null : (summaryMap[d.id] ? null : "4,3"));
}

function _baseStroke(_d) { return "#fff"; }
