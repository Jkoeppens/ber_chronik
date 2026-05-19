// ── Boot ──────────────────────────────────────────────────────────────────────
const _v = `v=${Date.now()}`;
Promise.all([
  fetch(`${DATA_BASE}data.json?${_v}`).then(r => r.json()),
  fetch(`${DATA_BASE}entities_seed.csv?${_v}`).then(r => r.text())
    .catch(() => ""),
  fetch(`${DATA_BASE}entities_summary.json?${_v}`).then(r => r.json())
    .catch(() => ({})),
  fetch(`${DATA_BASE}project_meta.json?${_v}`).then(r => r.json())
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
  // date_js bevorzugt; Fallback auf year für ältere Exporte ohne date_js
  const _entryDate = e => e.date_js ? new Date(e.date_js) :
                          e.year != null ? new Date(e.year + "-01-01") : null;

  // dMin/dMax aus config.json (via project_meta.json year_min/year_max);
  // Fallback: extent der tatsächlichen Entry-Daten, dann hardcoded.
  let dMin, dMax;
  if (meta && meta.year_min != null && meta.year_max != null) {
    dMin = new Date(meta.year_min, 0, 1);
    dMax = new Date(meta.year_max, 11, 31);
  } else {
    const dateParsed = entries.map(_entryDate).filter(Boolean);
    [dMin, dMax] = d3.extent(dateParsed);
    if (!dMin) { dMin = new Date(1989, 0, 1); dMax = new Date(2017, 11, 31); }
  }

  // Automatische Bin-Größe nach Zeitspanne in Tagen
  const MS_DAY = 24 * 3600 * 1000;
  const spanMs = dMax - dMin;
  let binInterval;
  if      (spanMs <=   50 * MS_DAY) binInterval = d3.timeDay;
  else if (spanMs <=  350 * MS_DAY) binInterval = d3.timeWeek;
  else if (spanMs <= 1500 * MS_DAY) binInterval = d3.timeMonth;
  else                              binInterval = d3.timeYear;
  window._binInterval = binInterval;

  const binThresholds = binInterval.range(dMin, dMax);
  const rawBins = d3.bin()
    .domain([dMin, dMax])
    .value(e => _entryDate(e))
    .thresholds(binThresholds)(entries.filter(e => _entryDate(e)));

  const byBin = new Map(rawBins.map(bin => [bin.x0, bin]));

  const series = EVENT_TYPES.map(et => ({
    et,
    values: rawBins.map(bin => {
      const ents = bin.filter(e => e.event_type === et);
      return {
        year:      bin.x0,
        count:     ents.length,
        entries:   ents,
        anchorSet: new Set(ents.map(e => e.doc_anchor).filter(Boolean)),
      };
    }),
  }));

  const binDates = rawBins.map(b => b.x0);
  drawChart(series, binDates);
  new ResizeObserver(() => drawChart(series, binDates)).observe(
    document.getElementById("chart"));

  const legend = document.getElementById("legend");
  EVENT_TYPES.forEach(et => {
    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<div class="legend-swatch" style="background:${COLOR[et]}"></div>${et}`;
    item.addEventListener("click", () => {
      dimmedTypes.has(et) ? dimmedTypes.delete(et) : dimmedTypes.add(et);
      drawChart(series, binDates);
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
    typ: aliasMap[id.toLowerCase()]?.typ ||
         Object.keys(NODE_COLOR).find(k => /org/i.test(k)) ||
         Object.keys(NODE_COLOR)[0] || "Org",
  }));

  // LINK_MIN_COUNT = 2 — muss mit precompute_network.js übereinstimmen
  const LINK_MIN_COUNT = 2;
  netLinks = [];
  for (const [key, byType] of edgesByType) {
    const total = [...byType.values()].reduce((s, c) => s + c, 0);
    if (total < LINK_MIN_COUNT) continue;
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
