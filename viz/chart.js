// ── Timeline chart ────────────────────────────────────────────────────────────
function drawChart(series, years) {
  const svg    = d3.select("#chart");
  const margin = { top: 16, right: 20, bottom: 36, left: 38 };
  svg.selectAll("*").remove();

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
    .call(d3.axisLeft(y).ticks(5).tickSize(4));

  const line = d3.line()
    .x(v => x(v.year)).y(v => y(v.count))
    .curve(d3.curveMonotoneX);

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

  // Store dot selection; re-apply current highlight state after redraw
  chartDotSelection = svg.selectAll("circle.dot");
  _applyHighlight();

  // Click on empty chart area resets timeline highlighting
  svg.on("click.reset", (event) => {
    if (event.target.tagName !== "circle") setHighlight("none");
  });
}
