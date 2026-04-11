// ── Boot ──────────────────────────────────────────────────────────────────────
Promise.all([
  fetch(`${DATA_BASE}data.json`).then(r => r.json()),
  fetch(`${DATA_BASE}entities_seed.csv`).then(r => r.text())
    .catch(() => ""),
  fetch(`${DATA_BASE}entities_summary.json`).then(r => r.json())
    .catch(() => ({})),
  fetch(`${DATA_BASE}project_meta.json`).then(r => r.json())
    .catch(() => null),
]).then(([{ entries }, csvText, summaries, meta]) => {

  initColors(meta);
  projectMeta = meta;
  if (meta && meta.title) {
    const titleEl = document.getElementById("project-title-text");
    if (titleEl) titleEl.textContent = meta.title;
    document.title = meta.title;
  }
  buildAliasMap(csvText);
  summaryMap = summaries;
  allEntries = entries;

  for (const e of entries) {
    if (e.doc_anchor) {
      entriesByAnchor.set(e.doc_anchor, e);
      const actors = Array.isArray(e.actors) ? e.actors : [];
      if (actors.length) actorsByAnchor.set(e.doc_anchor, new Set(actors));
    }
  }

  // ── Timeline series ──
  const entryYears = entries.map(e => e.year).filter(y => y != null);
  const yMin  = (meta && meta.year_min) || (entryYears.length ? d3.min(entryYears) : 1989);
  const yMax  = (meta && meta.year_max) || (entryYears.length ? d3.max(entryYears) : 2017);
  const years  = d3.range(yMin, yMax + 1);
  const byYear = d3.group(entries.filter(e => e.year), e => e.year);

  const series = EVENT_TYPES.map(et => ({
    et,
    values: years.map(year => {
      const ents = (byYear.get(year) || []).filter(e => e.event_type === et);
      return {
        year,
        count:     ents.length,
        entries:   ents,
        anchorSet: new Set(ents.map(e => e.doc_anchor).filter(Boolean)),
      };
    }),
  }));

  drawChart(series, years);
  new ResizeObserver(() => drawChart(series, years)).observe(
    document.getElementById("chart"));

  const legend = document.getElementById("legend");
  EVENT_TYPES.forEach(et => {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<div class="legend-swatch" style="background:${COLOR[et]}"></div>${et}`;
    item.addEventListener("click", () => {
      dimmedTypes.has(et) ? dimmedTypes.delete(et) : dimmedTypes.add(et);
      drawChart(series, years);
      document.querySelectorAll(".legend-item").forEach((el, i) =>
        el.classList.toggle("dimmed", dimmedTypes.has(EVENT_TYPES[i])));
    });
    legend.appendChild(item);
  });

  // ── Network data ──
  const nodeCounts  = new Map();
  const edgesByType = new Map();  // "A\x00B" → Map<event_type, count>

  for (const entry of entries) {
    const actors = Array.isArray(entry.actors) ? entry.actors : [];
    const et = entry.event_type || "?";
    for (const a of actors) {
      nodeCounts.set(a, (nodeCounts.get(a) || 0) + 1);
      if (!entriesByActor.has(a)) entriesByActor.set(a, []);
      entriesByActor.get(a).push(entry);
    }
    for (let i = 0; i < actors.length; i++) {
      for (let j = i + 1; j < actors.length; j++) {
        const key = pairKey(actors[i], actors[j]);
        if (!edgesByType.has(key)) edgesByType.set(key, new Map());
        const byType = edgesByType.get(key);
        byType.set(et, (byType.get(et) || 0) + 1);
      }
    }
  }

  netNodes = [...nodeCounts.entries()].map(([id, count]) => ({
    id, count,
    typ: aliasMap[id.toLowerCase()]?.typ || "Org",
  }));

  // One link per (pair, event_type); include all pairs (threshold = 1)
  netLinks = [];
  for (const [key, byType] of edgesByType) {
    const total = [...byType.values()].reduce((s, c) => s + c, 0);
    if (total < 1) continue;
    const [source, target] = key.split("\x00");
    for (const [event_type, count] of byType) {
      netLinks.push({ source, target, event_type, count });
    }
  }

}).catch(err => {
  document.getElementById("chart-area").innerHTML =
    `<p style="color:#c00;padding:20px">
      Fehler: ${err.message}<br><br>
      Starte mit: <code>python3 -m http.server 8765</code> (aus dem Projektordner)
    </p>`;
});
