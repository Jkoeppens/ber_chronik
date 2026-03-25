// ── Timeline chart ────────────────────────────────────────────────────────────
let _chartG = null, _x = null, _y = null, _w = 0, _h = 0;
let _series = [], _area = null, _defs = null;

// Returns [{start, end}] for runs of years with no gap > 1
function getContiguousSegments(years) {
  if (!years || years.length === 0) return [];
  const sorted = [...years].sort((a, b) => a - b);
  const segs = [];
  let s = sorted[0], e = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] - sorted[i - 1] <= 1) { e = sorted[i]; }
    else { segs.push({ start: s, end: e }); s = e = sorted[i]; }
  }
  segs.push({ start: s, end: e });
  return segs;
}

function drawChart(series, years) {
  const svg    = d3.select("#chart");
  const margin = { top: 16, right: 90, bottom: 36, left: 38 };
  svg.selectAll("*").remove();

  const defs = svg.append("defs");
  series.forEach(s => {
    const color = COLOR[s.et] || "#999";
    const gradId = `grad-${s.et}`;
    const grad = defs.append("linearGradient")
      .attr("id", gradId)
      .attr("x1","0").attr("y1","0").attr("x2","0").attr("y2","1");
    grad.append("stop").attr("offset","0%")
      .attr("stop-color", color).attr("stop-opacity", 0.18);
    grad.append("stop").attr("offset","100%")
      .attr("stop-color", color).attr("stop-opacity", 0.02);
  });

  const W = svg.node().clientWidth  || 800;
  const H = svg.node().clientHeight || 380;
  const w = W - margin.left - margin.right;
  const h = H - margin.top  - margin.bottom;

  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
  const x = d3.scaleLinear().domain([1989, 2017]).range([0, w]);
  const y = d3.scaleLinear()
    .domain([0, d3.max(series, s => d3.max(s.values, v => v.count))]).nice()
    .range([h, 0]);

  g.append("g").attr("class","grid")
    .call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat(""));
  g.append("g").attr("class","axis").attr("transform",`translate(0,${h})`)
    .call(d3.axisBottom(x).tickFormat(d3.format("d")).ticks(15).tickSize(4));
  g.append("g").attr("class","axis")
    .call(d3.axisLeft(y).ticks(5).tickSize(4).tickPadding(6));
  g.append("line")
    .attr("class", "baseline")
    .attr("x1", 0).attr("x2", w)
    .attr("y1", h).attr("y2", h)
    .attr("stroke", "#999").attr("stroke-width", 0.75);

  const line = d3.line()
    .x(v => x(v.year)).y(v => y(v.count))
    .curve(d3.curveMonotoneX);

  const area = d3.area()
    .x(v => x(v.year)).y0(y(0)).y1(v => y(v.count))
    .curve(d3.curveMonotoneX);

  // First pass: area fills (behind lines)
  series.forEach(s => {
    if (dimmedTypes.has(s.et)) return;
    g.append("path").datum(s.values)
      .attr("class", "area-path")
      .attr("id", `area-${s.et}`)
      .attr("fill", `url(#grad-${s.et})`)
      .attr("d", area);
  });

  series.forEach(s => {
    g.append("path").datum(s.values)
      .attr("class", "line-path" + (dimmedTypes.has(s.et) ? " dimmed" : ""))
      .attr("id", `line-${s.et}`)
      .attr("stroke", COLOR[s.et])
      .attr("d", line)
      // Click on a line in highlight mode: open category panel, keep current highlight
      .on("click", (event) => {
        if (hlState.mode === "none") return;
        event.stopPropagation();
        const entries = s.values.flatMap(v => v.entries)
          .sort((a, b) => (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
        showView("timeline", s.et, viewEl => { viewEl.innerHTML = renderParaList(entries); });
      });

    g.selectAll(null)
      .data(s.values.filter(v => v.count > 0))
      .join("circle")
      .attr("class", `dot dot-${s.et.replace(/\s/g, '-')}` + (dimmedTypes.has(s.et) ? " dimmed" : ""))
      .attr("cx", v => x(v.year)).attr("cy", v => y(v.count))
      .attr("r", 4)
      .attr("fill", COLOR[s.et]).attr("stroke", "#fff").attr("stroke-width", 1.5)
      .on("mouseenter", (event, v) => {
        const c = COLOR[s.et] || "#999";
        showTip(`<div class="tip-year">${v.year}</div><div class="tip-entry"><span class="tip-dot" style="background:${c}"></span><span>${s.et} · ${v.count}</span></div>`, event);
      })
      .on("mousemove", moveTip).on("mouseleave", hideTip)
      .on("click", (event, v) => {
        hideTip();
        event.stopPropagation();
        if (activeDot) activeDot.classList.remove("active");
        activeDot = event.currentTarget;
        activeDot.classList.add("active");
        const sorted = [...v.entries].sort((a, b) =>
          (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
        showView("timeline", `${v.year} · ${s.et}`,
          viewEl => { viewEl.innerHTML = renderParaList(sorted); });
        // Replace current highlight with this dot's entries
        setHighlight("answer", v.anchorSet);
      });
  });

  // Inline labels at line ends
  const labelData = series
    .filter(s => !dimmedTypes.has(s.et))
    .map(s => {
      const last = [...s.values].reverse().find(v => v.count > 0);
      if (!last) return null;
      return { et: s.et, x: x(last.year) + 8, y: y(last.count) };
    })
    .filter(Boolean)
    .sort((a, b) => a.y - b.y);

  // Collision resolution: push overlapping labels down
  for (let i = 1; i < labelData.length; i++) {
    if (labelData[i].y - labelData[i-1].y < 14)
      labelData[i].y = labelData[i-1].y + 14;
  }
  // Clamp to chart height
  for (let i = 0; i < labelData.length; i++) {
    if (labelData[i].y > h - 5) labelData[i].y = h - 5;
  }

  labelData.forEach(l => {
    g.append("text")
      .attr("class", `line-label line-label-${l.et.replace(/\s/g, '-')}`)
      .attr("x", l.x)
      .attr("y", l.y)
      .attr("dominant-baseline", "central")
      .attr("fill", COLOR[l.et] || "#999")
      .text(l.et);
  });

  _chartG = g; _x = x; _y = y; _w = w; _h = h;
  _series = series; _defs = defs; _area = area;

  // Store dot selection; re-apply current highlight state after redraw
  chartDotSelection = svg.selectAll("circle.dot");
  _applyHighlight();

  // Click on empty chart area: reset highlight + close panel.
  // Dot and line clicks stop propagation so they never reach this handler.
  // hl-area (highlight overlay) clicks are also ignored here.
  svg.on("click.reset", (event) => {
    const tgt = event.target;
    if (tgt.classList?.contains("hl-area")) return;
    goHome();
  });
}

function _resetChartStyles() {
  _chartG.selectAll(".line-path").style("opacity", null).style("stroke", null).style("stroke-width", null);
  _chartG.selectAll(".area-path").style("opacity", null);
  _chartG.selectAll(".line-label").style("opacity", null);
  _chartG.selectAll(".dot").style("opacity", null).style("fill", null);
}

function _applyChartEntityHighlight() {
  if (!_chartG) return;
  const { focusEntity, mode, anchors } = hlState;

  _chartG.selectAll(".hl-area, .hl-line").remove();
  _defs.selectAll(".hl-clip, .hl-grad").remove();

  // ── Full reset ──────────────────────────────────────────────────────────────
  if (mode === "none") { _resetChartStyles(); return; }

  // ── Gather relevant entries — entity click OR answer anchors ────────────────
  let relevantEntries;
  if (focusEntity) {
    relevantEntries = (typeof entriesByActor !== "undefined" ? entriesByActor : new Map())
      .get(focusEntity) || [];
  } else if (anchors && anchors.size > 0) {
    const ea = typeof entriesByAnchor !== "undefined" ? entriesByAnchor : new Map();
    relevantEntries = [...anchors].map(a => ea.get(a)).filter(Boolean);
  } else {
    relevantEntries = [];
  }

  if (!relevantEntries.length) { _resetChartStyles(); return; }

  // Collect years per event type
  const byType = {};
  relevantEntries.forEach(e => {
    if (!e.year || !e.event_type) return;
    if (!byType[e.event_type]) byType[e.event_type] = new Set();
    byType[e.event_type].add(e.year);
  });

  const relevantTypes = new Set(Object.keys(byType));
  const step = _x(1990) - _x(1989);

  // ── Three-level dimming ──────────────────────────────────────────────────────
  // Level 1 (hl-area overlay): relevant category + relevant timespan — full color, 2.5px, full area
  // Level 2: relevant category + non-relevant timespan — original color, 0.15 opacity, 1px, area ~0.3
  // Level 3: non-relevant category — grey #cccccc, 0.2 opacity, pointer-events untouched
  _chartG.selectAll(".line-path")
    .style("opacity",      function() { return relevantTypes.has(this.id.replace("line-", "")) ? 0.15 : 0.2; })
    .style("stroke",       function() { return relevantTypes.has(this.id.replace("line-", "")) ? null : "#cccccc"; })
    .style("stroke-width", function() { return relevantTypes.has(this.id.replace("line-", "")) ? "1px" : null; });
  _chartG.selectAll(".area-path")
    .style("opacity", function() { return relevantTypes.has(this.id.replace("area-", "")) ? 0.3 : 0; });

  _chartG.selectAll(".line-label").style("opacity", 0.1);
  relevantTypes.forEach(et => {
    _chartG.selectAll(`.line-label-${et.replace(/\s/g, '-')}`).style("opacity", 1);
  });

  // Dots: non-relevant → grey fill + 0.2 opacity, pointer-events untouched.
  // Relevant → clear both overrides so _applyTimelineHighlight's attr takes over.
  if (focusEntity) {
    _chartG.selectAll(".dot").style("opacity", 0.2).style("fill", "#cccccc");
    relevantTypes.forEach(et => {
      _chartG.selectAll(`.dot-${et.replace(/\s/g, '-')}`).style("opacity", null).style("fill", null);
    });
  } else {
    _chartG.selectAll(".dot").style("opacity", null).style("fill", null);
  }

  // ── Segment overlays (entity focus + answer mode) ───────────────────────────

  Object.entries(byType).forEach(([et, yearSet]) => {
    const color = COLOR[et] || "#999";
    const s = _series.find(s => s.et === et);
    if (!s) return;

    getContiguousSegments([...yearSet]).forEach(({ start, end }) => {
      const etSafe  = et.replace(/\s/g, '-');
      const clipId  = `hl-clip-${etSafe}-${start}-${end}`;
      const gradId  = `hl-grad-${etSafe}-${start}-${end}`;

      // clipPath: ±half-year around the segment
      _defs.append("clipPath")
        .attr("class", "hl-clip")
        .attr("id", clipId)
        .append("rect")
          .attr("x",      _x(start) - step / 2)
          .attr("y",      -10)
          .attr("width",  _x(end) - _x(start) + step)
          .attr("height", _h + 20);

      // Per-segment gradient: y1 at the segment's peak so opacity 0.28 starts
      // right at the line, y2 at the baseline. Low and high segments get
      // identical fill intensity directly under the line.
      const peakCount = d3.max(s.values.filter(v => v.year >= start && v.year <= end), v => v.count) || 0;
      const gradY1 = _y(peakCount);
      const grad = _defs.append("linearGradient")
        .attr("class", "hl-grad")
        .attr("id", gradId)
        .attr("gradientUnits", "userSpaceOnUse")
        .attr("x1", 0).attr("y1", gradY1).attr("x2", 0).attr("y2", gradY1 + 80);
      grad.append("stop").attr("offset","0%").attr("stop-color", color).attr("stop-opacity", 0.25);
      grad.append("stop").attr("offset","100%").attr("stop-color", color).attr("stop-opacity", 0);

      // Full s.values so curveMonotoneX tangents match the background line-path
      _chartG.append("path").datum(s.values)
        .attr("class", "hl-area")
        .attr("clip-path", `url(#${clipId})`)
        .attr("fill", `url(#${gradId})`)
        .attr("stroke", color)
        .attr("stroke-width", 2.5)
        .attr("stroke-linejoin", "round")
        .attr("d", _area);
    });
  });
}
