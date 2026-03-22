// ── Timeline chart ────────────────────────────────────────────────────────────
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
      .on("mouseenter", (event, v) => showTip(`<b>${v.year}</b> · ${s.et}: ${v.count}`, event))
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
      .attr("class", "line-label")
      .attr("x", l.x)
      .attr("y", l.y)
      .attr("dominant-baseline", "central")
      .attr("fill", COLOR[l.et] || "#999")
      .text(l.et);
  });

  // Store dot selection; re-apply current highlight state after redraw
  chartDotSelection = svg.selectAll("circle.dot");
  _applyHighlight();

  // Click on empty chart area resets timeline highlighting
  svg.on("click.reset", (event) => {
    if (event.target.tagName !== "circle") setHighlight("none");
  });
}
