// ── Network graph ─────────────────────────────────────────────────────────────
function nodeRadius(d) { return Math.max(5, Math.sqrt(d.count) * 3); }
function labelSize(d)  { return Math.max(7.5, Math.min(12, nodeRadius(d) * 0.4 + 5.5)); }

function drawNetwork(nodes, links, entriesByActor) {
  const svg = d3.select("#network");
  svg.selectAll("*").remove();

  const W = svg.node().clientWidth  || 800;
  const H = svg.node().clientHeight || 600;

  const g = svg.append("g");

  svg.call(d3.zoom()
    .scaleExtent([0.15, 5])
    .on("zoom", e => g.attr("transform", e.transform)));

  // Build adjacency map before D3 mutates link source/target to objects
  const neighbors = new Map();
  nodes.forEach(d => neighbors.set(d.id, new Set()));
  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source;
    const tid = typeof l.target === "object" ? l.target.id : l.target;
    if (neighbors.has(sid)) neighbors.get(sid).add(tid);
    if (neighbors.has(tid)) neighbors.get(tid).add(sid);
  });

  const sim = d3.forceSimulation(nodes)
    .force("link",    d3.forceLink(links).id(d => d.id).distance(80).strength(0.4))
    .force("charge",  d3.forceManyBody().strength(-220))
    .force("center",  d3.forceCenter(W / 2, H / 2))
    // Label half-width (chars × ~0.32 × fontSize) drives collision for all nodes
    .force("collide", d3.forceCollide(d =>
      Math.max(nodeRadius(d), d.id.length * labelSize(d) * 0.32) + 6));

  const link = g.append("g")
    .selectAll("line").data(links).join("line")
    .attr("stroke", "#bbb")
    .attr("stroke-opacity", 0.15)
    .attr("stroke-width", d => Math.min(5, 0.8 + Math.log(d.count + 1)));

  const node = g.append("g")
    .selectAll("g").data(nodes).join("g")
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end",   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  node.append("circle")
    .attr("r",                nodeRadius)
    .attr("fill",             d => NODE_COLOR[d.typ] || "#bbb")
    .attr("stroke",           "#fff")
    .attr("stroke-width",     1.5)
    .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");

  node.append("text")
    .attr("class",       "net-label")
    .attr("dy",          d => nodeRadius(d) + labelSize(d) + 2)
    .attr("text-anchor", "middle")
    .style("font-size",  d => `${labelSize(d)}px`)
    .text(d => d.id);

  node
    .on("mouseenter", (event, d) => {
      showTip(`${d.count} Nennungen`, event);
      if (hlState.mode !== "none") return;
      const nbrs = neighbors.get(d.id) || new Set();
      node.attr("opacity", n => (n.id === d.id || nbrs.has(n.id)) ? 1 : DIM);
      d3.select(event.currentTarget).select("circle")
        .attr("r",    nodeRadius(d) * 1.25)
        .attr("fill", NODE_COLOR_ACTIVE[d.typ] || "#999");
      link.attr("stroke-opacity", l => {
        const s = l.source.id ?? l.source, t = l.target.id ?? l.target;
        return (s === d.id || t === d.id) ? 0.6 : 0.05;
      });
    })
    .on("mousemove", moveTip)
    .on("mouseleave", (event, d) => {
      hideTip();
      if (hlState.mode !== "none") { _applyHighlight(); return; }
      d3.select(event.currentTarget).select("circle")
        .attr("r",    nodeRadius(d))
        .attr("fill", NODE_COLOR[d.typ] || "#bbb");
      node.attr("opacity", 1);
      link.attr("stroke-opacity", 0.15);
    })
    .on("click", (event, d) => {
      hideTip();
      selectEntity(d.id);
    });

  // Store selections; re-apply current highlight state after redraw
  netNodeSelection = node;
  netNeighbors     = neighbors;
  _applyHighlight();

  sim.on("tick", () => {
    link
      .attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  const netLegendEl = document.getElementById("net-legend");
  netLegendEl.innerHTML = Object.entries(NODE_COLOR_ACTIVE).map(([typ, color]) => `
    <div class="net-legend-item">
      <div class="net-legend-dot" style="background:${color}"></div>${typ}
    </div>`).join("");
}

// ── Tabs ──────────────────────────────────────────────────────────────────────
let networkDrawn  = false;
let netNodes = [], netLinks = [], entriesByActor = new Map();
let entriesByAnchor = new Map();

function switchTab(active) {
  ["timeline", "network"].forEach(id => {
    document.getElementById(`tab-${id}`).classList.toggle("active", id === active);
  });
  document.getElementById("chart-area").classList.toggle("hidden",  active !== "timeline");
  document.getElementById("network-area").classList.toggle("active", active === "network");
}

document.getElementById("tab-timeline").addEventListener("click", () => switchTab("timeline"));
document.getElementById("tab-network").addEventListener("click",  () => {
  switchTab("network");
  if (!networkDrawn) { drawNetwork(netNodes, netLinks, entriesByActor); networkDrawn = true; }
});
