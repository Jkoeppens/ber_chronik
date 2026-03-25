// ── Network graph ─────────────────────────────────────────────────────────────
const EDGE_STEP = 4;  // px between parallel edges of the same pair
let netFocusNode     = null;      // ego-graph focus; null = no ego state
let netFocusPair     = null;      // focused edge pair { key, sid, tid }; null = none
let activeNetThemes  = new Set(); // edge event-types currently visible
let activeNodeTypes  = new Set(); // entity types currently visible
let netLinkSelection = null;      // D3 selection of all <line> elements

function nodeRadius(d) { return Math.max(5, Math.min(28, Math.log(d.count + 1) * 7)); }
function labelSize(d)  { return nodeRadius(d) >= 12 ? 11 : 10; }

// Fetch precomputed layout eagerly so it's ready before first tab-open
let _networkLayout = null;
fetch("network_layout.json").then(r => r.json()).then(l => { _networkLayout = l; }).catch(() => {});

// ── Unified network state machine ─────────────────────────────────────────────
// Priority order (highest wins):
//
//   1. Ego-graph   (netFocusNode set) — node click / focusActor().
//      Clicked node + immediate neighbours visible; everything else dimmed.
//      Ego node is pinned (fx/fy) so it stays put while forces settle.
//
//   2. Edge-focus  (netFocusPair set) — hit-area line click.
//      All parallel edges between the pair are highlighted; pair endpoints
//      stay full-opacity; all other nodes and edges dimmed.
//
//   3. KI-subgraph (hlState.mode === "answer") — set by setHighlight() on AI
//      answers, entity selections, fulltext results, and edge-pair clicks.
//      Nodes in the answer's source articles are highlighted; others dimmed.
//      An optional focusEntity within the answer gets extra visual prominence.
//
//   4. Default     — all nodes and edges at rest opacity.
//
// Called by _applyNetworkHighlight() on every setHighlight() and directly after
// mutating netFocusNode / netFocusPair.
function applyNetworkState() {
  if (!netNodeSelection || !netLinkSelection) return;
  const { mode, anchors, active, focusEntity } = hlState;

  // Reset radius (hover may have changed it)
  netNodeSelection.select("circle").attr("r", nodeRadius);

  const defaultWidth = l => Math.max(1, Math.log((l.count || 1) + 1));

  // ── 1. Ego-graph ───────────────────────────────────────────────────────────
  if (netFocusNode) {
    const nbrs = netNeighbors.get(netFocusNode) || new Set();
    const inEgo = d => d.id === netFocusNode || nbrs.has(d.id);
    netNodeSelection
      .attr("opacity", d => inEgo(d) ? 1 : DIM);
    netNodeSelection.select("circle")
      .attr("fill",         d => NODE_COLOR[d.typ] || "#bbb")
      .attr("r",            d => d.id === netFocusNode ? nodeRadius(d) * 1.4 : nodeRadius(d))
      .attr("stroke",       d => d.id === netFocusNode ? "#f5c518" : "#F7F5F0")
      .attr("stroke-width", d => d.id === netFocusNode ? 3 : 2)
      .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");
    netLinkSelection
      .attr("stroke-width", defaultWidth)
      .attr("stroke-opacity", l => {
        const sid = l.source?.id ?? l.source, tid = l.target?.id ?? l.target;
        return (inEgo({ id: sid }) && inEgo({ id: tid }) && activeNetThemes.has(l.event_type))
          ? 0.85 : 0.05;
      });
    return;
  }

  // ── 2. Edge-pair focus ─────────────────────────────────────────────────────
  if (netFocusPair) {
    const { key: focusKey, sid: fsid, tid: ftid } = netFocusPair;
    const isPairNode = d => d.id === fsid || d.id === ftid;
    netNodeSelection.attr("opacity", d => isPairNode(d) ? 1 : DIM);
    netNodeSelection.select("circle")
      .attr("fill",         d => NODE_COLOR[d.typ] || "#bbb")
      .attr("r",            nodeRadius)
      .attr("stroke",       "#F7F5F0")
      .attr("stroke-width", 2)
      .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");
    netLinkSelection
      .attr("stroke-opacity", l => {
        const sk = [l.source?.id ?? l.source, l.target?.id ?? l.target].sort().join("\x00");
        return sk === focusKey ? 0.85 : 0.05;
      })
      .attr("stroke-width", l => {
        const sk = [l.source?.id ?? l.source, l.target?.id ?? l.target].sort().join("\x00");
        return sk === focusKey ? Math.max(2, Math.log((l.count || 1) + 1) * 1.5) : defaultWidth(l);
      });
    return;
  }

  // ── 3/4. KI-subgraph or default ────────────────────────────────────────────
  if (mode === "none" || !anchors || anchors.size === 0) {
    netNodeSelection.attr("opacity", 1);
    netNodeSelection.select("circle")
      .attr("fill",             d => NODE_COLOR[d.typ] || "#bbb")
      .attr("stroke",           "#F7F5F0")
      .attr("stroke-width",     2)
      .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");
    netLinkSelection
      .attr("stroke-width",   defaultWidth)
      .attr("stroke-opacity", 0.5);
    return;
  }

  // ── 3. KI-subgraph ─────────────────────────────────────────────────────────
  // Highlight entities from hlState.anchors
  const answerActors = new Set([...anchors].flatMap(a => [...(actorsByAnchor.get(a) || [])]));
  const activeActors = active ? (actorsByAnchor.get(active) || new Set()) : new Set();
  netNodeSelection.attr("opacity", d => answerActors.has(d.id) ? 1 : DIM);
  netNodeSelection.select("circle")
    .attr("fill",         d => NODE_COLOR[d.typ] || "#bbb")
    .attr("r",            d => d.id === focusEntity ? nodeRadius(d) * 1.4 : activeActors.has(d.id) ? nodeRadius(d) * 1.25 : nodeRadius(d))
    .attr("stroke",       d => (d.id === focusEntity || activeActors.has(d.id)) ? "#f5c518" : "#F7F5F0")
    .attr("stroke-width", d => d.id === focusEntity ? 3 : activeActors.has(d.id) ? 2.5 : 2)
    .attr("stroke-dasharray", d => (d.id === focusEntity || activeActors.has(d.id)) ? null : (summaryMap[d.id] ? null : "4,3"));
  netLinkSelection
    .attr("stroke-width",   defaultWidth)
    .attr("stroke-opacity", l => {
      const sid = l.source?.id ?? l.source, tid = l.target?.id ?? l.target;
      return (answerActors.has(sid) && answerActors.has(tid)) ? 0.85 : 0.05;
    });
}

function drawNetwork(nodes, links) {
  netFocusNode    = null;
  netFocusPair    = null;
  activeNetThemes = new Set(EVENT_TYPES);
  activeNodeTypes = new Set(Object.keys(NODE_COLOR));

  const svg = d3.select("#network");
  svg.selectAll("*").remove();

  const W = svg.node().clientWidth  || 800;
  const H = svg.node().clientHeight || 600;

  const g = svg.append("g");

  const zoomBehavior = d3.zoom()
    .scaleExtent([0.15, 5])
    .on("zoom", e => g.attr("transform", e.transform));
  svg.call(zoomBehavior);

  // Click on empty SVG area: exit ego-graph or edge-focus
  svg.on("click.egoreset", event => {
    if (event.target === svg.node() || event.target.tagName === "svg") {
      let changed = false;
      if (netFocusNode) {
        const prev = nodes.find(n => n.id === netFocusNode);
        if (prev) { prev.fx = null; prev.fy = null; }
        netFocusNode = null;
        changed = true;
      }
      if (netFocusPair) { netFocusPair = null; changed = true; }
      if (changed) applyNetworkState();
    }
  });

  // Build adjacency map (all links, irrespective of theme)
  const neighbors = new Map();
  nodes.forEach(d => neighbors.set(d.id, new Set()));
  links.forEach(l => {
    const sid = typeof l.source === "object" ? l.source.id : l.source;
    const tid = typeof l.target === "object" ? l.target.id : l.target;
    if (neighbors.has(sid)) neighbors.get(sid).add(tid);
    if (neighbors.has(tid)) neighbors.get(tid).add(sid);
  });

  // Apply precomputed positions
  const nodeById = new Map(nodes.map(n => [n.id, n]));
  if (_networkLayout) {
    const sx = W / _networkLayout.width;
    const sy = H / _networkLayout.height;
    const posMap = new Map(_networkLayout.nodes.map(n => [n.id, n]));
    nodes.forEach(d => {
      const p = posMap.get(d.id);
      if (p) { d.x = p.x * sx; d.y = p.y * sy; }
      else   { d.x = W / 2;    d.y = H / 2;    }
    });
  } else {
    nodes.forEach(d => {
      d.x = W / 2 + (Math.random() - 0.5) * W * 0.8;
      d.y = H / 2 + (Math.random() - 0.5) * H * 0.8;
    });
  }

  // Resolve source/target strings → node objects
  links.forEach(l => {
    if (typeof l.source === "string") l.source = nodeById.get(l.source);
    if (typeof l.target === "string") l.target = nodeById.get(l.target);
  });

  // Annotate nodes with unique-neighbour count (across ALL links, before any filter)
  nodes.forEach(d => { d.linkCount = neighbors.get(d.id)?.size || 0; });

  // Globally isolated nodes (no links in dataset at all) are excluded from the sim
  const connectedNodes = nodes.filter(d => d.linkCount > 0);

  // ── Simulation: one link per pair (avoids duplicate forces) ─────────────────
  const pairSeen = new Set();
  const simLinks = links.filter(l => {
    const sid = l.source?.id ?? l.source;
    const tid = l.target?.id ?? l.target;
    const k = [sid, tid].sort().join("\x00");
    if (pairSeen.has(k)) return false;
    pairSeen.add(k); return true;
  });

  const sim = d3.forceSimulation(connectedNodes)
    .force("link",    d3.forceLink(simLinks).id(d => d.id).distance(80).strength(0.3))
    .force("charge",  d3.forceManyBody()
                        .strength(d => -30 - d.linkCount * 8)
                        .distanceMax(250))
    .force("center",  d3.forceCenter(W / 2, H / 2).strength(0.08))
    .force("collide", d3.forceCollide(d =>
      Math.max(nodeRadius(d), d.id.length * labelSize(d) * 0.32) + 12))
    .alphaDecay(0.05)
    .alpha(0).stop();

  // Track visible set across calls so recomputeGraph can detect new/removed nodes
  let _lastVisibleIds = new Set(connectedNodes.map(d => d.id));
  let _tempPinned     = [];  // nodes temporarily fixed during a transition

  // ── Parallel edge offsets ────────────────────────────────────────────────────
  function pairKey(l) {
    const sid = l.source?.id ?? l.source, tid = l.target?.id ?? l.target;
    return [sid, tid].sort().join("\x00");
  }

  function computeOffsets(visibleLinks) {
    const groups = new Map();
    visibleLinks.forEach(l => {
      const k = pairKey(l);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(l);
    });
    visibleLinks.forEach(l => {
      const grp = groups.get(pairKey(l));
      l._offsetTotal = grp.length;
      l._offsetIndex = grp.indexOf(l);
    });
  }

  computeOffsets(links);

  // ── Per-pair data for hit areas and tooltips ─────────────────────────────────
  // One hit-line per canonical pair covers all parallel edges of that pair.
  const pairTotalCount = new Map(); // pairKey → total co-occurrence count
  const pairEventTypes = new Map(); // pairKey → Set<event_type>
  links.forEach(l => {
    const k = pairKey(l);
    pairTotalCount.set(k, (pairTotalCount.get(k) || 0) + l.count);
    if (!pairEventTypes.has(k)) pairEventTypes.set(k, new Set());
    pairEventTypes.get(k).add(l.event_type);
  });
  // Deduplicated: one representative link per pair
  const pairSeen2 = new Set();
  const hitLinks  = links.filter(l => {
    const k = pairKey(l);
    if (pairSeen2.has(k)) return false;
    pairSeen2.add(k); return true;
  });

  // ── Visible lines (no pointer events — hit layer handles interaction) ─────────
  const linkG   = g.append("g");
  const linkSel = linkG
    .selectAll("line").data(links).join("line")
    .attr("stroke",         d => COLOR[d.event_type] || "#bbb")
    .attr("stroke-opacity", 0.5)
    .attr("stroke-width",   d => Math.max(1, Math.log(d.count + 1)))
    .attr("pointer-events", "none");

  // ── Invisible hit areas (one per pair, wide stroke, carries all handlers) ─────
  const hitG   = g.append("g");
  const hitSel = hitG
    .selectAll("line").data(hitLinks).join("line")
    .attr("stroke",         "transparent")
    .attr("stroke-width",   14)
    .attr("fill",           "none")
    .attr("cursor",         "pointer")
    .on("mouseenter", (event, d) => {
      const sid = d.source?.id ?? d.source, tid = d.target?.id ?? d.target;
      const k   = pairKey(d);
      const n   = pairTotalCount.get(k) || 0;
      showTip(
        `<div class="tip-entry" style="gap:4px">` +
        `<span>${escapeHtml(sid)} + ${escapeHtml(tid)}</span>` +
        `<span style="color:#888">· ${n}×</span></div>`,
        event);
      // Brighten all visible parallel lines in this pair
      linkSel.filter(l => pairKey(l) === k).attr("stroke-opacity", 0.85);
    })
    .on("mousemove", moveTip)
    .on("mouseleave", (event, d) => {
      hideTip();
      const k = pairKey(d);
      if (netFocusNode || hlState.mode !== "none") { applyNetworkState(); return; }
      linkSel.filter(l => pairKey(l) === k).attr("stroke-opacity", 0.5);
    })
    .on("click", (event, d) => {
      hideTip();
      // Release any pinned ego node
      if (netFocusNode) {
        const prev = nodes.find(n => n.id === netFocusNode);
        if (prev) { prev.fx = null; prev.fy = null; }
        netFocusNode = null;
      }
      const sid = d.source?.id ?? d.source, tid = d.target?.id ?? d.target;
      const key = [sid, tid].sort().join("\x00");
      netFocusPair = { key, sid, tid };
      const shared = (entriesByActor.get(sid) || [])
        .filter(e => Array.isArray(e.actors) && e.actors.includes(tid))
        .sort((a, b) => (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
      const title = `${sid} + ${tid} · alle Verbindungen`;
      showView("timeline", title, viewEl => {
        viewEl.innerHTML = shared.length
          ? renderParaList(shared)
          : `<div class="chat-params">Keine gemeinsamen Artikel.</div>`;
      });
      // setHighlight triggers applyNetworkState; netFocusPair is already set so edge branch wins
      setHighlight("answer", new Set(shared.map(e => e.doc_anchor).filter(Boolean)));
    });

  function rerender() {
    linkSel.each(function(d) {
      const src = d.source, tgt = d.target;
      if (!src || !tgt) return;
      const dx = tgt.x - src.x, dy = tgt.y - src.y;
      const len = Math.sqrt(dx*dx + dy*dy) || 1;
      const ux = dx / len, uy = dy / len;          // unit vector src→tgt
      // Trim endpoints to node circumferences
      const rSrc = nodeRadius(src), rTgt = nodeRadius(tgt);
      // Perpendicular offset for parallel edges
      const N = d._offsetTotal || 1, idx = d._offsetIndex || 0;
      const off = (idx - (N - 1) / 2) * EDGE_STEP;
      const ox = -uy * off, oy = ux * off;
      d3.select(this)
        .attr("x1", src.x + ux * rSrc + ox).attr("y1", src.y + uy * rSrc + oy)
        .attr("x2", tgt.x - ux * rTgt + ox).attr("y2", tgt.y - uy * rTgt + oy);
    });
    // Hit lines: centre of bundle, also trimmed at node radii
    hitSel.each(function(d) {
      const src = d.source, tgt = d.target;
      if (!src || !tgt) return;
      const dx = tgt.x - src.x, dy = tgt.y - src.y;
      const len = Math.sqrt(dx*dx + dy*dy) || 1;
      const ux = dx / len, uy = dy / len;
      const rSrc = nodeRadius(src), rTgt = nodeRadius(tgt);
      d3.select(this)
        .attr("x1", src.x + ux * rSrc).attr("y1", src.y + uy * rSrc)
        .attr("x2", tgt.x - ux * rTgt).attr("y2", tgt.y - uy * rTgt);
    });
    node.attr("transform", d => `translate(${d.x},${d.y})`);
  }

  // ── Node slider ──────────────────────────────────────────────────────────────
  const sortedNodes = [...nodes].sort((a, b) => b.count - a.count);
  const rankById    = new Map(sortedNodes.map((d, i) => [d.id, i + 1]));
  let topN      = nodes.length;
  let minLinks  = 2;

  // ── Diagnostic: why are specific nodes not connected? ────────────────────────
  ["Gerkan Marg und Partner", "Karsten Mühlenfeld"].forEach(id => {
    const n = nodes.find(d => d.id === id);
    if (!n) { console.log(`[diag] "${id}" — not in nodes array`); return; }
    const rank = rankById.get(id);
    const nLinks = links.filter(l => {
      const sid = l.source?.id ?? l.source, tid = l.target?.id ?? l.target;
      return sid === id || tid === id;
    });
    console.log(`[diag] "${id}" — rank:${rank}/${nodes.length}, linkCount:${n.linkCount}, dataset links:${nLinks.length}`);
    nLinks.forEach(l => {
      const sid = l.source?.id ?? l.source, tid = l.target?.id ?? l.target;
      const other = sid === id ? tid : sid;
      const otherNode = nodes.find(d => d.id === other);
      const otherRank = rankById.get(other);
      const visNode  = n.linkCount > 0 && rank <= topN && activeNodeTypes.has(n.typ);
      const visOther = otherNode && otherNode.linkCount > 0 && otherRank <= topN && activeNodeTypes.has(otherNode.typ);
      const visEdge  = visNode && visOther && activeNetThemes.has(l.event_type);
      console.log(`  → "${other}" rank:${otherRank} et:${l.event_type} count:${l.count}`
        + (visEdge ? " ✓" : ` ✗ (self:${visNode} other:${visOther} theme:${activeNetThemes.has(l.event_type)})`));
    });
  });

  // Base visibility: rank + type filters only (edge-count checked separately)
  function baseVisible(d) {
    return d.linkCount > 0 && rankById.get(d.id) <= topN && activeNodeTypes.has(d.typ);
  }

  // Unified filter + physics update — called by all filter controls.
  // Iteratively prunes nodes with < minLinks visible edges until stable (k-core style),
  // then restarts the simulation with the resulting subgraph.
  function recomputeGraph() {
    // Seed: all base-visible nodes
    let visibleIds = new Set(nodes.filter(baseVisible).map(d => d.id));

    // Iterative pruning: remove nodes with < minLinks visible edges until stable
    for (;;) {
      const edgeCnt = new Map([...visibleIds].map(id => [id, 0]));
      links.forEach(l => {
        if (visibleIds.has(l.source.id) && visibleIds.has(l.target.id) &&
            activeNetThemes.has(l.event_type)) {
          edgeCnt.set(l.source.id, edgeCnt.get(l.source.id) + 1);
          edgeCnt.set(l.target.id, edgeCnt.get(l.target.id) + 1);
        }
      });
      const next = new Set([...visibleIds].filter(id => (edgeCnt.get(id) || 0) >= minLinks));
      if (next.size === visibleIds.size) break;
      visibleIds = next;
    }

    const visibleNodes = nodes.filter(d => visibleIds.has(d.id));
    const visibleLinks = links.filter(l =>
      visibleIds.has(l.source.id) && visibleIds.has(l.target.id) &&
      activeNetThemes.has(l.event_type));

    // Sim links: one per pair
    const seen = new Set();
    const newSimLinks = visibleLinks.filter(l => {
      const k = [l.source.id, l.target.id].sort().join("\x00");
      if (seen.has(k)) return false;
      seen.add(k); return true;
    });

    // Detect what changed vs previous call
    const prevVisibleIds = _lastVisibleIds;
    _lastVisibleIds = visibleIds;
    const nodesAdded   = [...visibleIds].some(id => !prevVisibleIds.has(id));
    const nodesChanged = nodesAdded || [...prevVisibleIds].some(id => !visibleIds.has(id));

    // Clear any still-pending temporary pins from the previous call
    _tempPinned.forEach(d => { if (d.id !== netFocusNode) { d.fx = null; d.fy = null; } });
    _tempPinned = [];

    if (nodesChanged) {
      // Newly visible nodes: spawn at a visible neighbor's position to avoid flying in from (0,0)
      if (nodesAdded) {
        visibleNodes.forEach(d => {
          if (prevVisibleIds.has(d.id)) return;
          const nbr = links
            .map(l => l.source.id === d.id ? l.target : l.target.id === d.id ? l.source : null)
            .find(n => n && visibleIds.has(n.id) && n.x != null);
          if (nbr) {
            d.x = nbr.x + (Math.random() - 0.5) * 20;
            d.y = nbr.y + (Math.random() - 0.5) * 20;
          }
        });
      }
      // Temporarily pin existing visible nodes so they stay put while new nodes settle in
      visibleNodes.forEach(d => {
        if (d.id !== netFocusNode && prevVisibleIds.has(d.id) && d.fx == null) {
          d.fx = d.x; d.fy = d.y;
          _tempPinned.push(d);
        }
      });
      const pinSnapshot = [..._tempPinned];
      setTimeout(() => {
        pinSnapshot.forEach(d => { if (d.id !== netFocusNode) { d.fx = null; d.fy = null; } });
      }, 500);
    }

    sim.nodes(visibleNodes);
    sim.force("link").links(newSimLinks);
    // Theme-only change → tiny nudge; node set change → light warmup
    sim.alpha(nodesChanged ? 0.1 : 0.05).restart();

    node.attr("display", d => visibleIds.has(d.id) ? null : "none");
    linkSel.attr("display", l =>
      (visibleIds.has(l.source.id) && visibleIds.has(l.target.id) &&
       activeNetThemes.has(l.event_type)) ? null : "none");
    hitSel.attr("display", l => {
      if (!visibleIds.has(l.source.id) || !visibleIds.has(l.target.id)) return "none";
      const anyTheme = [...(pairEventTypes.get(pairKey(l)) || [])].some(et => activeNetThemes.has(et));
      return anyTheme ? null : "none";
    });

    computeOffsets(visibleLinks);
    rerender();
    applyNetworkState();
  }

  const nodeG = g.append("g");
  const node  = nodeG
    .selectAll("g").data(nodes).join("g")
    .attr("cursor", "pointer")
    .call(d3.drag()
      .on("start", (e, d) => { if (!e.active) sim.alpha(0.1).restart(); d.fx = d.x; d.fy = d.y; })
      .on("drag",  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on("end",   (e, d) => {
        if (!e.active) sim.alphaTarget(0);
        // Keep ego-node pinned; release all others after drag
        if (d.id !== netFocusNode) { d.fx = null; d.fy = null; }
      }));

  node.append("circle")
    .attr("r",                nodeRadius)
    .attr("fill",             d => NODE_COLOR[d.typ] || "#bbb")
    .attr("stroke",           "#F7F5F0")
    .attr("stroke-width",     2)
    .attr("stroke-dasharray", d => summaryMap[d.id] ? null : "4,3");

  node.append("text")
    .attr("class",       "net-label")
    .attr("dy",          d => nodeRadius(d) + labelSize(d) + 4)
    .attr("text-anchor", "middle")
    .style("font-size",  d => `${labelSize(d)}px`)
    .text(d => d.id);

  node
    .on("mouseenter", (event, d) => {
      showTip(`${d.count} Nennungen`, event);
      // Suppress hover effect when ego or KI highlight is active
      if (netFocusNode || hlState.mode !== "none") return;
      const nbrs = neighbors.get(d.id) || new Set();
      node.attr("opacity", n => (n.id === d.id || nbrs.has(n.id)) ? 1 : DIM);
      d3.select(event.currentTarget).select("circle")
        .attr("r",    nodeRadius(d) * 1.25)
        .attr("fill", NODE_COLOR_ACTIVE[d.typ] || "#999");
      linkSel.attr("stroke-opacity", l => {
        const s = l.source?.id ?? l.source, t = l.target?.id ?? l.target;
        return (s === d.id || t === d.id) ? 0.85 : 0.05;
      });
    })
    .on("mousemove", moveTip)
    .on("mouseleave", (event, d) => {
      hideTip();
      if (netFocusNode || hlState.mode !== "none") { applyNetworkState(); return; }
      d3.select(event.currentTarget).select("circle")
        .attr("r",    nodeRadius(d))
        .attr("fill", NODE_COLOR[d.typ] || "#bbb");
      node.attr("opacity", 1);
      linkSel.attr("stroke-opacity", 0.5);
    })
    .on("click", (event, d) => {
      hideTip();
      // Release any previously pinned ego node; clear edge-focus state
      if (netFocusNode && netFocusNode !== d.id) {
        const prev = nodes.find(n => n.id === netFocusNode);
        if (prev) { prev.fx = null; prev.fy = null; }
      }
      netFocusPair = null;
      // Pin clicked node so it stays put during the ego transition
      d.fx = d.x; d.fy = d.y;
      netFocusNode = d.id;
      selectEntity(d.id);
      applyNetworkState();
      // Smoothly pan so the focused node is centred in the viewport
      svg.transition().duration(300).call(zoomBehavior.translateTo, d.x, d.y);
    });

  function _fitGraph(animated) {
    const visNodes = sim.nodes().filter(d => d.x != null && d.y != null);
    if (!visNodes.length) return;
    const pad = 40;
    const x0 = d3.min(visNodes, d => d.x) - pad, x1 = d3.max(visNodes, d => d.x) + pad;
    const y0 = d3.min(visNodes, d => d.y) - pad, y1 = d3.max(visNodes, d => d.y) + pad;
    const scale = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0), 1.2);
    const tx = (W - scale * (x0 + x1)) / 2;
    const ty = (H - scale * (y0 + y1)) / 2;
    const t = d3.zoomIdentity.translate(tx, ty).scale(scale);
    if (animated) svg.transition().duration(600).call(zoomBehavior.transform, t);
    else          svg.call(zoomBehavior.transform, t);
  }

  let _fitOnEnd = true;
  sim.on("tick", rerender);
  sim.on("end.fit", () => {
    if (!_fitOnEnd) return;
    _fitOnEnd = false;
    _fitGraph(true);
  });
  rerender();
  _fitGraph(false);

  // Store selections for highlight system
  netNodeSelection = node;
  netNeighbors     = neighbors;
  netLinkSelection = linkSel;
  _applyHighlight();

  // ── Legend: entity-type filter + theme filter (Stefaner style) ───────────────
  const netLegendEl = document.getElementById("net-legend");
  netLegendEl.innerHTML = `
    <div class="nl-section">
      <div class="nl-title">Entitätstyp</div>
      <div class="nl-items">
        ${Object.entries(NODE_COLOR).map(([typ, color]) =>
          `<div class="nl-item active" data-typ="${typ}">
            <span class="nl-dot" style="background:${color}"></span>
            <span class="nl-label">${typ}</span>
          </div>`).join("")}
      </div>
    </div>
    <div class="nl-section">
      <div class="nl-title">Thema</div>
      <div class="nl-items">
        ${EVENT_TYPES.map(et =>
          `<div class="nl-item active" data-et="${et}">
            <span class="nl-bar" style="background:${COLOR[et]}"></span>
            <span class="nl-label">${et}</span>
          </div>`).join("")}
      </div>
    </div>
  `;

  netLegendEl.querySelectorAll(".nl-item[data-typ]").forEach(item => {
    item.addEventListener("click", () => {
      const typ = item.dataset.typ;
      if (activeNodeTypes.has(typ)) { activeNodeTypes.delete(typ); item.classList.remove("active"); }
      else                          { activeNodeTypes.add(typ);    item.classList.add("active");    }
      recomputeGraph();
    });
  });

  netLegendEl.querySelectorAll(".nl-item[data-et]").forEach(item => {
    item.addEventListener("click", () => {
      const et = item.dataset.et;
      if (activeNetThemes.has(et)) { activeNetThemes.delete(et); item.classList.remove("active"); }
      else                         { activeNetThemes.add(et);    item.classList.add("active");    }
      recomputeGraph();
    });
  });

  // ── Sliders: Top-N actors + Min. connections ─────────────────────────────────
  const hintEl = document.getElementById("net-hint");
  hintEl.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:4px;font-size:0.72rem;color:#888">
      <label style="display:flex;align-items:center;gap:6px;">
        Top&nbsp;<input id="net-slider" type="range" min="5" max="${nodes.length}"
                        value="${nodes.length}" style="width:80px;vertical-align:middle">
        &nbsp;<span id="net-slider-val">${nodes.length}</span>&nbsp;Akteure
      </label>
      <label style="display:flex;align-items:center;gap:6px;">
        Min.&nbsp;<input id="net-minlinks" type="range" min="1" max="10" value="2"
                         style="width:80px;vertical-align:middle">
        &nbsp;<span id="net-minlinks-val">2</span>&nbsp;Verbindungen
      </label>
    </div>`;

  document.getElementById("net-slider").addEventListener("input", e => {
    topN = +e.target.value;
    document.getElementById("net-slider-val").textContent = topN;
    recomputeGraph();
  });

  const minLinksEl = document.getElementById("net-minlinks");
  minLinksEl.addEventListener("input", e => {
    document.getElementById("net-minlinks-val").textContent = e.target.value;
  });
  ["mouseup", "touchend"].forEach(evt => {
    minLinksEl.addEventListener(evt, () => {
      minLinks = +minLinksEl.value;
      recomputeGraph();
    });
  });
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
  if (!networkDrawn) { drawNetwork(netNodes, netLinks); networkDrawn = true; }
});
