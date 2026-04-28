// ── Timeline chart ────────────────────────────────────────────────────────────
let _chartG = null, _clipG = null, _xAxisG = null;
let _x = null, _y = null, _h = 0, _w = 0;
let _series = [], _area = null, _defs = null;

// Returns [{start, end}] for runs of ms-timestamps within one bin-interval gap
function getContiguousSegments(timestamps) {
  if (!timestamps || timestamps.length === 0) return [];
  const bi  = window._binInterval;
  const gap = bi === d3.timeYear  ? 366 * 24 * 3600 * 1000 :
              bi === d3.timeMonth ?  32 * 24 * 3600 * 1000 :
                                      2 * 24 * 3600 * 1000;
  const sorted = [...timestamps].sort((a, b) => a - b);
  const segs = [];
  let s = sorted[0], e = sorted[0];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i] - sorted[i - 1] <= gap) { e = sorted[i]; }
    else { segs.push({ start: s, end: e }); s = e = sorted[i]; }
  }
  segs.push({ start: s, end: e });
  return segs;
}

function _fmtBinDate(d) {
  if (!d) return "";
  const bi = window._binInterval;
  if (bi === d3.timeYear)  return d3.timeFormat("%Y")(d);
  if (bi === d3.timeMonth) return d3.timeFormat("%b %Y")(d);
  return d3.timeFormat("%d.%m.")(d);
}

function drawChart(series, binDates) {
  const svg    = d3.select("#chart");
  const margin = { top: 16, right: 90, bottom: 36, left: 38 };
  svg.selectAll("*").remove();

  const W = svg.node().clientWidth  || 800;
  const H = svg.node().clientHeight || 380;
  const w = W - margin.left - margin.right;
  const h = H - margin.top  - margin.bottom;

  const defs = svg.append("defs");

  // Gradient defs for background area fills
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

  // Clip path: masks zoomable content to the chart area
  defs.append("clipPath").attr("id", "chart-clip")
    .append("rect")
      .attr("x", 0).attr("y", -10)
      .attr("width", w).attr("height", h + 20);

  const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
  window._binDates = binDates;
  const x = d3.scaleTime().domain([binDates[0], binDates[binDates.length - 1]]).range([0, w]);
  const y = d3.scaleLinear()
    .domain([0, d3.max(series, s => d3.max(s.values, v => v.count))]).nice()
    .range([h, 0]);

  // ── Non-zoomable: grid, axes, baseline ──────────────────────────────────────
  g.append("g").attr("class","grid")
    .call(d3.axisLeft(y).ticks(5).tickSize(-w).tickFormat(""));

  const xAxisG = g.append("g").attr("class","axis").attr("transform",`translate(0,${h})`);
  xAxisG.call(d3.axisBottom(x).ticks(window._binInterval).tickFormat(d => _fmtBinDate(d)).tickSize(4));

  g.append("g").attr("class","axis")
    .call(d3.axisLeft(y).ticks(5).tickSize(4).tickPadding(6));

  g.append("line")
    .attr("class", "baseline")
    .attr("x1", 0).attr("x2", w)
    .attr("y1", h).attr("y2", h)
    .attr("stroke", "#999").attr("stroke-width", 0.75);

  // ── Generators (keep originals; zoom creates rescaled copies) ───────────────
  const line = d3.line()
    .x(v => x(v.year)).y(v => y(v.count))
    .curve(d3.curveMonotoneX);

  const area = d3.area()
    .x(v => x(v.year)).y0(y(0)).y1(v => y(v.count))
    .curve(d3.curveMonotoneX);

  // ── Zoomable content group (clipped) ────────────────────────────────────────
  const clipG = g.append("g").attr("clip-path", "url(#chart-clip)");

  // Area fills (behind lines)
  series.forEach(s => {
    if (dimmedTypes.has(s.et)) return;
    clipG.append("path").datum(s.values)
      .attr("class", "area-path")
      .attr("id", `area-${s.et}`)
      .attr("fill", `url(#grad-${s.et})`)
      .attr("d", area);
  });

  // Lines and dots
  series.forEach(s => {
    clipG.append("path").datum(s.values)
      .attr("class", "line-path" + (dimmedTypes.has(s.et) ? " dimmed" : ""))
      .attr("id", `line-${s.et}`)
      .attr("stroke", COLOR[s.et])
      .attr("d", line)
      .on("click", (event) => {
        if (hlState.mode === "none") return;
        event.stopPropagation();
        const entries = s.values.flatMap(v => v.entries)
          .sort((a, b) => (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
        showView("timeline", s.et, viewEl => { viewEl.innerHTML = renderParaList(entries); });
      });

    clipG.selectAll(null)
      .data(s.values.filter(v => v.count > 0))
      .join("circle")
      .attr("class", `dot dot-${s.et.replace(/\s/g, '-')}` + (dimmedTypes.has(s.et) ? " dimmed" : ""))
      .attr("cx", v => x(v.year)).attr("cy", v => y(v.count))
      .attr("r", 4)
      .attr("fill", COLOR[s.et]).attr("stroke", "#fff").attr("stroke-width", 1.5)
      .on("mouseenter", (event, v) => {
        const c = COLOR[s.et] || "#999";
        showTip(`<div class="tip-year">${_fmtBinDate(v.year)}</div><div class="tip-entry"><span class="tip-dot" style="background:${c}"></span><span>${s.et} · ${v.count}</span></div>`, event);
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
        showView("timeline", `${_fmtBinDate(v.year)} · ${s.et}`,
          viewEl => { viewEl.innerHTML = renderParaList(sorted); });
        setHighlight("answer", v.anchorSet);
      });
  });

  // ── Labels (outside clip so they render in right margin) ────────────────────
  const labelsG = g.append("g");

  const labelData = series
    .filter(s => !dimmedTypes.has(s.et))
    .map(s => {
      const last = [...s.values].reverse().find(v => v.count > 0);
      if (!last) return null;
      return { et: s.et, x: x(last.year) + 8, y: y(last.count), year: last.year };
    })
    .filter(Boolean)
    .sort((a, b) => a.y - b.y);

  // Collision resolution
  for (let i = 1; i < labelData.length; i++) {
    if (labelData[i].y - labelData[i-1].y < 14)
      labelData[i].y = labelData[i-1].y + 14;
  }
  for (let i = 0; i < labelData.length; i++) {
    if (labelData[i].y > h - 5) labelData[i].y = h - 5;
  }

  labelData.forEach(l => {
    labelsG.append("text")
      .datum(l)   // bind for zoom repositioning
      .attr("class", `line-label line-label-${l.et.replace(/\s/g, '-')}`)
      .attr("x", l.x)
      .attr("y", l.y)
      .attr("dominant-baseline", "central")
      .attr("fill", COLOR[l.et] || "#999")
      .text(l.et);
  });

  // ── Store module-level state ─────────────────────────────────────────────────
  _chartG = g; _clipG = clipG; _xAxisG = xAxisG;
  _x = x; _y = y; _h = h; _w = w;
  _series = series; _defs = defs; _area = area;

  chartDotSelection = svg.selectAll("circle.dot");
  _applyHighlight();

  svg.on("click.reset", (event) => {
    const tgt = event.target;
    if (tgt.classList?.contains("hl-area")) return;
    goHome();
  });

  // ── Zoom ─────────────────────────────────────────────────────────────────────
  const zoom = d3.zoom()
    .scaleExtent([1, 20])
    .translateExtent([[0, 0], [w, h]])
    .extent([[0, 0], [w, h]])
    .on("zoom", (event) => {
      const xNew = event.transform.rescaleX(x);
      _x = xNew;

      // X axis
      xAxisG.call(d3.axisBottom(xNew).ticks(window._binInterval).tickFormat(d => _fmtBinDate(d)).tickSize(4));

      // Updated generators
      const lineNew = d3.line().x(v => xNew(v.year)).y(v => y(v.count)).curve(d3.curveMonotoneX);
      const areaNew = d3.area().x(v => xNew(v.year)).y0(y(0)).y1(v => y(v.count)).curve(d3.curveMonotoneX);
      _area = areaNew;

      clipG.selectAll(".area-path").attr("d", areaNew);
      clipG.selectAll(".line-path").attr("d", lineNew);
      clipG.selectAll(".dot").attr("cx", v => xNew(v.year));
      clipG.selectAll(".hl-area").attr("d", areaNew);

      // Reposition hl-clip rects (timestamp range stored as data attributes)
      const _hlStep = (window._binDates && window._binDates.length > 1)
        ? xNew(window._binDates[1]) - xNew(window._binDates[0]) : 4;
      defs.selectAll(".hl-clip rect").each(function() {
        const ds = new Date(+this.getAttribute("data-start"));
        const de = new Date(+this.getAttribute("data-end"));
        d3.select(this)
          .attr("x",     xNew(ds) - _hlStep / 2)
          .attr("width", xNew(de) - xNew(ds) + _hlStep);
      });

      // Reposition labels
      labelsG.selectAll("text").each(function(d) {
        if (d && d.year != null) d3.select(this).attr("x", xNew(d.year) + 8);
      });
    });

  // Attach zoom; override dblclick to reset
  svg.call(zoom);
  svg.on("dblclick.zoom", () =>
    svg.transition().duration(400).call(zoom.transform, d3.zoomIdentity)
  );
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

  if (mode === "none") { _resetChartStyles(); return; }

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

  const byType = {};
  relevantEntries.forEach(e => {
    if (!e.event_type) return;
    const ts = e.date_js ? new Date(e.date_js).getTime() :
               e.year    ? new Date(e.year + "-01-01").getTime() : null;
    if (ts == null) return;
    if (!byType[e.event_type]) byType[e.event_type] = new Set();
    byType[e.event_type].add(ts);
  });

  const relevantTypes = new Set(Object.keys(byType));
  const step = (window._binDates && window._binDates.length > 1)
    ? _x(window._binDates[1]) - _x(window._binDates[0]) : 4;

  _chartG.selectAll(".line-path")
    .style("opacity",      function() { return relevantTypes.has(this.id.replace("line-", "")) ? 0.15 : 0.2; })
    .style("stroke",       function() { return relevantTypes.has(this.id.replace("line-", "")) ? null : "#cccccc"; })
    .style("stroke-width", function() { return relevantTypes.has(this.id.replace("line-", "")) ? "1px" : null; });
  _chartG.selectAll(".area-path")
    .style("opacity", function() { return relevantTypes.has(this.id.replace("area-", "")) ? 0.3 : 0; });

  _chartG.selectAll(".line-label").style("opacity", 0.1);
  relevantTypes.forEach(et => {
    _chartG.selectAll(`.line-label-${CSS.escape(et.replace(/\s/g, '-'))}`).style("opacity", 1);
  });

  if (focusEntity) {
    _chartG.selectAll(".dot").style("opacity", 0.2).style("fill", "#cccccc");
    relevantTypes.forEach(et => {
      _chartG.selectAll(`.dot-${et.replace(/\s/g, '-')}`).style("opacity", null).style("fill", null);
    });
  } else {
    _chartG.selectAll(".dot").style("opacity", null).style("fill", null);
  }

  Object.entries(byType).forEach(([et, yearSet]) => {
    const color = COLOR[et] || "#999";
    const s = _series.find(s => s.et === et);
    if (!s) return;

    getContiguousSegments([...yearSet]).forEach(({ start, end }) => {
      const etSafe  = et.replace(/\s/g, '-');
      const clipId  = `hl-clip-${etSafe}-${start}-${end}`;
      const gradId  = `hl-grad-${etSafe}-${start}-${end}`;
      const dStart  = new Date(start);
      const dEnd    = new Date(end);

      _defs.append("clipPath")
        .attr("class", "hl-clip")
        .attr("id", clipId)
        .append("rect")
          .attr("data-start", start)
          .attr("data-end",   end)
          .attr("x",      _x(dStart) - step / 2)
          .attr("y",      -10)
          .attr("width",  _x(dEnd) - _x(dStart) + step)
          .attr("height", _h + 20);

      const peakCount = d3.max(s.values.filter(v => v.year && v.year.getTime() >= start && v.year.getTime() <= end), v => v.count) || 0;
      const gradY1 = _y(peakCount);
      const grad = _defs.append("linearGradient")
        .attr("class", "hl-grad")
        .attr("id", gradId)
        .attr("gradientUnits", "userSpaceOnUse")
        .attr("x1", 0).attr("y1", gradY1).attr("x2", 0).attr("y2", gradY1 + 80);
      grad.append("stop").attr("offset","0%").attr("stop-color", color).attr("stop-opacity", 0.25);
      grad.append("stop").attr("offset","100%").attr("stop-color", color).attr("stop-opacity", 0);

      // Append to _clipG so highlight is clipped with the rest of the content
      _clipG.append("path").datum(s.values)
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
