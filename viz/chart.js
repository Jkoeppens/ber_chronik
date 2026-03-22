// ── Timeline chart ────────────────────────────────────────────────────────────
let _chartG = null, _x = null, _y = null, _w = 0, _h = 0;
let _series = [], _area = null, _defs = null;

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
      .attr("d", line);

    g.selectAll(null)
      .data(s.values.filter(v => v.count > 0))
      .join("circle")
      .attr("class", "dot" + (dimmedTypes.has(s.et) ? " dimmed" : ""))
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
        if (activeDot) activeDot.classList.remove("active");
        activeDot = event.currentTarget;
        activeDot.classList.add("active");
        const sorted = [...v.entries].sort((a, b) =>
          (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
        showView("timeline", `${v.year} · ${s.et}`,
          viewEl => { viewEl.innerHTML = renderParaList(sorted); });
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

  // Click on empty chart area resets timeline highlighting
  svg.on("click.reset", (event) => {
    if (event.target.tagName !== "circle") setHighlight("none");
  });
}

function _applyChartEntityHighlight() {
  if (!_chartG) return;
  const normalform = hlState.focusEntity;

  // Remove previous segment overlays and clip paths
  _chartG.selectAll(".hl-area, .hl-line").remove();
  _defs.selectAll(".hl-clip").remove();

  if (!normalform || hlState.mode === "none") {
    _chartG.selectAll(".line-path").style("opacity", null).style("stroke", null);
    _chartG.selectAll(".area-path").style("opacity", null);
    _chartG.selectAll(".line-label").style("opacity", null);
    return;
  }

  // Which event types does this entity appear in?
  const entries = (typeof entriesByActor !== "undefined" ? entriesByActor : new Map())
    .get(normalform) || [];
  const byType = {};
  entries.forEach(e => {
    if (!e.year || !e.event_type) return;
    if (!byType[e.event_type]) byType[e.event_type] = [e.year, e.year];
    else {
      byType[e.event_type][0] = Math.min(byType[e.event_type][0], e.year);
      byType[e.event_type][1] = Math.max(byType[e.event_type][1], e.year);
    }
  });

  const relevantTypes = new Set(Object.keys(byType));
  const step = _x(1990) - _x(1989);  // one year in pixels

  // Dim non-relevant lines and collapse their areas completely
  _chartG.selectAll(".line-path")
    .style("opacity", function() {
      return relevantTypes.has(this.id.replace("line-", "")) ? 1 : 0.06;
    })
    .style("stroke", function() {
      return relevantTypes.has(this.id.replace("line-", "")) ? null : "#cccccc";
    });
  _chartG.selectAll(".area-path")
    .style("opacity", function() {
      return relevantTypes.has(this.id.replace("area-", "")) ? 1 : 0;
    });

  // Dim all labels; restore only relevant ones
  _chartG.selectAll(".line-label").style("opacity", 0.1);
  relevantTypes.forEach(et => {
    _chartG.selectAll(`.line-label-${et.replace(/\s/g, '-')}`).style("opacity", 1);
  });

  // Add highlighted segments with half-year clipPath for clean boundaries
  Object.entries(byType).forEach(([et, [startYear, endYear]]) => {
    const color = COLOR[et] || "#999";
    const s = _series.find(s => s.et === et);
    if (!s) return;

    // Include one data point beyond range so the curve doesn't abruptly end
    const segData = s.values.filter(v => v.year >= startYear - 1 && v.year <= endYear + 1);
    if (!segData.length) return;

    // ClipPath cuts exactly at ±half-year around the relevant range
    const clipId = `hl-clip-${et.replace(/\s/g, '-')}`;
    _defs.append("clipPath")
      .attr("class", "hl-clip")
      .attr("id", clipId)
      .append("rect")
        .attr("x",      _x(startYear) - step / 2)
        .attr("y",      -10)
        .attr("width",  _x(endYear) - _x(startYear) + step)
        .attr("height", _h + 20);

    // Gradient (created once per event type, reused across entity changes)
    const gradId = `hl-grad-${et}`;
    if (_defs.select(`#${gradId}`).empty()) {
      const grad = _defs.append("linearGradient")
        .attr("id", gradId)
        .attr("x1","0").attr("y1","0").attr("x2","0").attr("y2","1");
      grad.append("stop").attr("offset","0%").attr("stop-color", color).attr("stop-opacity", 0.28);
      grad.append("stop").attr("offset","100%").attr("stop-color", color).attr("stop-opacity", 0.02);
    }

    _chartG.append("path").datum(segData)
      .attr("class", "hl-area")
      .attr("clip-path", `url(#${clipId})`)
      .attr("fill", `url(#${gradId})`)
      .attr("d", _area);

    _chartG.append("path").datum(segData)
      .attr("class", "hl-line")
      .attr("clip-path", `url(#${clipId})`)
      .attr("fill", "none")
      .attr("stroke", color)
      .attr("stroke-width", 2.5)
      .attr("d", d3.line().x(v => _x(v.year)).y(v => _y(v.count)).curve(d3.curveMonotoneX));
  });
}
