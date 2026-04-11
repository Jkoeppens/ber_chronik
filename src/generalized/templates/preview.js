const DATA = {{js_data}};

const INITIAL_OVERRIDES = {{js_initial_overrides}};

const PREC_COLOR = {
  exact: "#2563eb", heading: "#0891b2", event: "#16a34a",
  interpolated: "#9ca3af", decade: "#d97706",
  manual: "#7c3aed", null: "#dc2626"
};
const CAT_COLORS = {{js_cat_colors}};
const CATEGORIES = {{js_categories}};

// ── URL params (passed when embedded as iframe) ────────────────────────────
const _qp   = new URLSearchParams(location.search);
const _proj = _qp.get('project')  || '';
const _doc  = _qp.get('document') || '';
const _tok  = _qp.get('token')    || '';

const PREC_LABEL = {
  exact: "exact", heading: "heading", event: "event",
  interpolated: "interp.", decade: "decade",
  manual: "manual", null: "undated"
};

const YEAR_MIN = {{year_min}};
const YEAR_MAX = {{year_max}};

// ── Override state ────────────────────────────────────────────────────────────
// Map<segment_id, override_object>
const overrides = new Map(
  Object.entries(INITIAL_OVERRIDES).map(([k, v]) => [k, v])
);

function updateExportBtn() {
  document.getElementById("btn-export").disabled = overrides.size === 0;
}
updateExportBtn();

const btnExport    = document.getElementById("btn-export");
const btnRecompute = document.getElementById("btn-recompute");
const logEl        = document.getElementById("recompute-log");

// ── Overrides exportieren → POST /overrides ───────────────────────────────────
btnExport.addEventListener("click", async () => {
  const arr = [...overrides.values()];
  btnExport.disabled = true;
  btnExport.textContent = "Speichere…";
  try {
    const res = await fetch("/overrides", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(arr),
    });
    if (res.ok) {
      btnExport.textContent = "Gespeichert ✓";
      setTimeout(() => {
        btnExport.textContent = "Overrides exportieren";
        updateExportBtn();
      }, 1500);
    } else {
      btnExport.textContent = "Fehler – nochmal?";
      btnExport.disabled = false;
    }
  } catch {
    // Server nicht erreichbar → Fallback: Datei herunterladen
    btnExport.textContent = "Overrides exportieren";
    updateExportBtn();
    const blob = new Blob([JSON.stringify(arr, null, 2)], {type: "application/json"});
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href = url; a.download = "overrides.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
});

// ── Neu berechnen → POST /recompute (SSE-Stream) ─────────────────────────────
btnRecompute.addEventListener("click", async () => {
  btnRecompute.disabled = true;
  btnRecompute.textContent = "Läuft…";
  logEl.className = ""; // reset error class
  logEl.textContent = "";
  logEl.style.display = "block";

  try {
    const res = await fetch("/recompute", {method: "POST"});
    if (!res.ok || !res.body) throw new Error("Server-Fehler " + res.status);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = "";

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buf += decoder.decode(value, {stream: true});
      const lines = buf.split("\\n");
      buf = lines.pop(); // incomplete last line

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const msg = line.slice(6);
        if (msg === "__done__") {
          logEl.textContent += "\\n✓ Fertig – Seite wird neu geladen…";
          logEl.scrollTop = logEl.scrollHeight;
          setTimeout(() => window.location.reload(), 800);
          return;
        }
        if (msg.startsWith("__report__:")) {
          try {
            const rpt = JSON.parse(msg.slice(11));
            if (rpt.warnings && rpt.warnings.length) {
              logEl.textContent += "\\n⚠ " + rpt.warnings.join("\\n⚠ ");
            }
            logEl.textContent += `\\nKonfidenz niedrig: ${rpt.low_confidence} (${rpt.low_confidence_pct}%)`;
          } catch(_) {}
          logEl.scrollTop = logEl.scrollHeight;
          continue;
        }
        if (msg.startsWith("__error__")) {
          logEl.className = "error";
          logEl.textContent += "\\n" + msg.slice(9).trim();
          logEl.scrollTop = logEl.scrollHeight;
          btnRecompute.disabled = false;
          btnRecompute.textContent = "Neu berechnen";
          return;
        }
        logEl.textContent += (logEl.textContent ? "\\n" : "") + msg;
        logEl.scrollTop = logEl.scrollHeight;
      }
    }
  } catch (err) {
    logEl.className = "error";
    logEl.textContent += "\\nServer nicht erreichbar: " + err.message;
    btnRecompute.disabled = false;
    btnRecompute.textContent = "Neu berechnen";
  }
});

// ── Render cards ─────────────────────────────────────────────────────────────
const cardsEl = document.getElementById("cards");
const emptyEl = document.getElementById("empty");

// Map<segment_id, {seg, cardEl}>
const cardMap = new Map();

// source helpers: accept string or {name, date} object
function srcName(src) {
  return (src && typeof src === "object") ? (src.name || "") : (src || "");
}
function srcLabel(src) {
  if (!src) return "";
  if (typeof src === "object") {
    return [src.name, src.date].filter(Boolean).join(" \u00b7 ");
  }
  return src;
}

DATA.forEach(seg => {
  const ov    = overrides.get(seg.id);
  const prec  = (ov?.action === "set_anchor" ? "manual"
               : ov?.action === "undatable"  ? null
               : seg.precision) ?? "null";
  const tf    = ov?.action === "set_anchor" ? ov.time_from
               : ov?.action === "undatable"  ? null
               : seg.time_from;
  const tt    = ov?.action === "set_anchor" ? ov.time_to
               : ov?.action === "undatable"  ? null
               : seg.time_to;
  const color = PREC_COLOR[prec] ?? "#999";
  const label = PREC_LABEL[prec] ?? prec;
  const numTl = tf == null ? "undatiert"
                : tt && tt !== tf ? tf + "\\u2013" + tt : String(tf);
  const tl    = (!ov && seg.date_raw) ? seg.date_raw : numTl;
  const displayText = (ov?.action === "set_anchor" && ov.text) ? ov.text : seg.text;
  const page  = seg.page ? `<span class="card-page">S.\\u202f${seg.page}</span>` : "";
  const noteHtml = ov?.note
    ? `<div class="card-note">\u270f ${esc(ov.note)}</div>` : "";

  const div = document.createElement("div");
  div.className = "card" + (ov ? " has-override" : "");
  div.dataset.prec   = prec === null ? "null" : prec;
  div.dataset.source = srcName(seg.source);
  div.dataset.year   = tf ?? 9999;
  div.dataset.id     = seg.id;
  div.dataset.cat    = seg.category || "";
  div.style.setProperty("--prec-color", color);
  const catBadge = seg.category
    ? `<span class="cat-badge" style="background:${CAT_COLORS[seg.category]||'#888'}" title="${esc(seg.category)}">${esc(seg.category)}</span>`
    : '';
  const srcLbl = srcLabel(seg.source);
  div.innerHTML = `
    <button class="btn-edit" data-id="${seg.id}">Bearbeiten</button>
    <div class="card-source" title="${srcLbl.replace(/"/g,'&quot;')}">${esc(srcLbl)}</div>
    <div class="card-meta">
      <span class="card-time">${tl}</span>
      <span class="badge" style="background:${color}">${label}</span>
      ${catBadge}
    </div>
    <div class="card-text">${esc(displayText)}${page}</div>
    ${noteHtml}`;
  cardsEl.appendChild(div);
  cardMap.set(seg.id, {seg, cardEl: div});
});

function esc(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

// ── Edit form ─────────────────────────────────────────────────────────────────
let activeEditId = null;
let activeFormEl = null;

function closeActiveForm() {
  if (activeFormEl) {
    activeFormEl.remove();
    activeFormEl = null;
  }
  if (activeEditId) {
    const {cardEl} = cardMap.get(activeEditId) || {};
    if (cardEl) cardEl.querySelector(".btn-edit")?.classList.remove("active");
    activeEditId = null;
  }
}

function openEdit(segId) {
  if (activeEditId === segId) { closeActiveForm(); return; }
  closeActiveForm();

  const {seg, cardEl} = cardMap.get(segId) || {};
  if (!seg || !cardEl) return;

  const ov = overrides.get(segId);
  const isUndatable = ov?.action === "undatable";
  const curText = (ov?.action === "set_anchor" && ov.text != null) ? ov.text : seg.text;
  const curFrom = ov?.action === "set_anchor" ? ov.time_from : seg.time_from;
  const curTo   = ov?.action === "set_anchor" ? ov.time_to   : seg.time_to;
  const curNote = ov?.note ?? "";

  activeEditId = segId;
  cardEl.querySelector(".btn-edit").classList.add("active");

  const catOptions = CATEGORIES.map(c =>
    `<option value="${esc(c)}"${c === seg.category ? ' selected' : ''}>${esc(c)}</option>`
  ).join('');

  const form = document.createElement("div");
  form.className = "edit-form";
  form.innerHTML = `
    <div>
      <div class="ef-label" style="margin-bottom:4px">Text</div>
      <textarea class="ef-textarea" id="ef-text">${esc(curText)}</textarea>
    </div>
    <div class="ef-row">
      <span class="ef-label">Zeitraum</span>
      <input class="ef-input" id="ef-from" type="number" placeholder="von"
             value="${curFrom ?? ""}" ${isUndatable ? "disabled" : ""}>
      <span style="font-size:11px;color:#888">–</span>
      <input class="ef-input" id="ef-to" type="number" placeholder="bis"
             value="${curTo ?? ""}" ${isUndatable ? "disabled" : ""}>
      <label class="ef-check">
        <input type="checkbox" id="ef-undatable" ${isUndatable ? "checked" : ""}>
        Undatierbar
      </label>
    </div>
    ${CATEGORIES.length ? `
    <div class="ef-row">
      <span class="ef-label">Kategorie</span>
      <select id="ef-category" style="flex:1;padding:3px 7px;border:1px solid #d1d5db;border-radius:3px;font-size:12px">
        <option value="">— keine —</option>
        ${catOptions}
      </select>
    </div>` : ''}
    <div class="ef-row">
      <span class="ef-label">Notiz</span>
      <input class="ef-input-wide" id="ef-note" type="text" placeholder="Begründung…"
             value="${esc(curNote)}">
    </div>
    <div class="ef-actions">
      <button class="btn-save" id="ef-save">Speichern</button>
      <button class="btn-cancel" id="ef-cancel">Abbrechen</button>
    </div>`;

  cardEl.appendChild(form);
  activeFormEl = form;

  // Toggle time fields when undatable checkbox changes
  form.querySelector("#ef-undatable").addEventListener("change", e => {
    const dis = e.target.checked;
    form.querySelector("#ef-from").disabled = dis;
    form.querySelector("#ef-to").disabled   = dis;
  });

  form.querySelector("#ef-cancel").addEventListener("click", closeActiveForm);

  form.querySelector("#ef-save").addEventListener("click", () => {
    const text      = form.querySelector("#ef-text").value;
    const undatable = form.querySelector("#ef-undatable").checked;
    const fromVal   = form.querySelector("#ef-from").value;
    const toVal     = form.querySelector("#ef-to").value;
    const note      = form.querySelector("#ef-note").value.trim();
    const catEl     = form.querySelector("#ef-category");
    const catVal    = catEl ? catEl.value : (seg.category || "");

    let override;
    if (undatable) {
      override = { segment_id: segId, action: "undatable", note: note || undefined };
    } else {
      const tf = fromVal !== "" ? parseInt(fromVal, 10) : null;
      const tt = toVal   !== "" ? parseInt(toVal, 10)   : null;
      override = {
        segment_id: segId,
        action: "set_anchor",
        time_from: tf,
        time_to:   tt,
        precision: "manual",
        text:      text !== seg.text ? text : undefined,
        note:      note || undefined,
      };
      // Remove undefined keys
      Object.keys(override).forEach(k => override[k] === undefined && delete override[k]);
    }

    overrides.set(segId, override);

    // Persist category change to classified.json
    if (catVal !== (seg.category || "")) {
      seg.category = catVal || undefined;
      const qs = new URLSearchParams({project: _proj, document: _doc, token: _tok}).toString();
      fetch("/ingest/classified/update?" + qs, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({segment_id: segId, category: catVal}),
      }).catch(() => {});
    }

    updateExportBtn();
    closeActiveForm();
    refreshCard(segId);
  });
}

function refreshCard(segId) {
  const {seg, cardEl} = cardMap.get(segId) || {};
  if (!seg || !cardEl) return;

  const ov    = overrides.get(segId);
  const prec  = ov?.action === "set_anchor" ? "manual"
               : ov?.action === "undatable"  ? null
               : seg.precision;
  const tf    = ov?.action === "set_anchor" ? ov.time_from
               : ov?.action === "undatable"  ? null
               : seg.time_from;
  const tt    = ov?.action === "set_anchor" ? ov.time_to
               : ov?.action === "undatable"  ? null
               : seg.time_to;
  const color = PREC_COLOR[prec ?? "null"] ?? "#999";
  const label = PREC_LABEL[prec ?? "null"] ?? String(prec);
  const numTlR = tf == null ? "undatiert"
                : tt && tt !== tf ? tf + "\\u2013" + tt : String(tf);
  const tl     = (!ov && seg.date_raw) ? seg.date_raw : numTlR;
  const displayText = (ov?.action === "set_anchor" && ov.text) ? ov.text : seg.text;
  const page  = seg.page ? `<span class="card-page">S.\\u202f${seg.page}</span>` : "";
  const noteHtml = ov?.note ? `<div class="card-note">\u270f ${esc(ov.note)}</div>` : "";

  cardEl.dataset.prec = prec === null ? "null" : (prec ?? "null");
  cardEl.dataset.year = tf ?? 9999;
  cardEl.dataset.cat  = seg.category || "";
  cardEl.style.setProperty("--prec-color", color);
  cardEl.classList.toggle("has-override", !!ov);

  const catBadgeR = seg.category
    ? `<span class="cat-badge" style="background:${CAT_COLORS[seg.category]||'#888'}" title="${esc(seg.category)}">${esc(seg.category)}</span>`
    : '';
  const srcLblR = srcLabel(seg.source);
  cardEl.innerHTML = `
    <button class="btn-edit" data-id="${segId}">Bearbeiten</button>
    <div class="card-source" title="${srcLblR.replace(/"/g,'&quot;')}">${esc(srcLblR)}</div>
    <div class="card-meta">
      <span class="card-time">${tl}</span>
      <span class="badge" style="background:${color}">${label}</span>
      ${catBadgeR}
    </div>
    <div class="card-text">${esc(displayText)}${page}</div>
    ${noteHtml}`;
}

// Delegate edit button clicks
cardsEl.addEventListener("click", e => {
  const btn = e.target.closest(".btn-edit");
  if (btn) openEdit(btn.dataset.id);
});

// ── Filters ──────────────────────────────────────────────────────────────────
let activePrec   = "";
let activeSrc    = "";
let activeCat    = "";

function applyFilters() {
  let visible = 0;
  document.querySelectorAll(".card").forEach(c => {
    const matchPrec = !activePrec || c.dataset.prec === activePrec;
    const matchSrc  = !activeSrc  || c.dataset.source === activeSrc;
    const matchCat  = !activeCat  || c.dataset.cat === activeCat;
    const show = matchPrec && matchSrc && matchCat;
    c.classList.toggle("hidden", !show);
    if (show) visible++;
  });
  emptyEl.style.display = visible === 0 ? "block" : "none";
  updateMarker();
}

document.querySelectorAll(".fb").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".fb").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activePrec = btn.dataset.prec === "null" ? "null"
               : btn.dataset.prec === ""     ? ""
               : btn.dataset.prec;
    applyFilters();
  });
});

document.querySelectorAll(".cf").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".cf").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeCat = btn.dataset.cat;
    applyFilters();
  });
});

document.getElementById("src-filter").addEventListener("change", e => {
  activeSrc = e.target.value;
  applyFilters();
});

// ── Quality report ────────────────────────────────────────────────────────────
const QUALITY_REPORT = {{js_quality_report}};
(function renderQualityReport() {
  const qr = QUALITY_REPORT;
  if (!qr || !qr.total) return;
  const el = document.getElementById("quality-report");
  const body = document.getElementById("qr-body");
  el.style.display = "block";
  const lines = [];
  if (qr.warnings && qr.warnings.length) {
    qr.warnings.forEach(w => {
      lines.push(`<div class="qr-warn">⚠ ${esc(w)}</div>`);
    });
  }
  lines.push(`<div class="qr-low">Niedrige Konfidenz: ${qr.low_confidence} (${qr.low_confidence_pct} %)</div>`);
  const cats = Object.entries(qr.categories || {})
    .map(([c, p]) => `${esc(c)} ${p}%`).join(" · ");
  if (cats) lines.push(`<div class="qr-low" style="margin-top:4px">${cats}</div>`);
  body.innerHTML = lines.join("");
})();

// ── Timeline marker ───────────────────────────────────────────────────────────
const tlEl       = document.getElementById("timeline");
const markerEl   = document.getElementById("tl-marker");
const yearLblEl  = document.getElementById("tl-year-label");

// Mark decades visually
document.querySelectorAll(".tick").forEach(t => {
  const yr = parseInt(t.dataset.year);
  if (yr % 20 === 0) t.setAttribute("data-decade", "");
});

function yearToFrac(yr) {
  return Math.max(0, Math.min(1, (yr - YEAR_MIN) / (YEAR_MAX - YEAR_MIN)));
}

function updateMarker() {
  const cards = [...document.querySelectorAll(".card:not(.hidden)")];
  if (!cards.length) return;

  // Find first visible card in the scroll viewport
  const panelRect = cardsEl.getBoundingClientRect();
  let topCard = null;
  for (const c of cards) {
    const r = c.getBoundingClientRect();
    if (r.bottom > panelRect.top) { topCard = c; break; }
  }
  const yr = topCard ? parseInt(topCard.dataset.year) : null;
  if (!yr || yr === 9999) return;

  const frac = yearToFrac(yr);
  const tlH  = tlEl.clientHeight;
  const topPx = frac * tlH;

  markerEl.style.top   = topPx + "px";
  yearLblEl.style.top  = topPx + "px";
  yearLblEl.textContent = yr;
}

cardsEl.addEventListener("scroll", updateMarker);
updateMarker();

// ── Timeline click → scroll to year ──────────────────────────────────────────
tlEl.addEventListener("click", e => {
  const tick = e.target.closest(".tick");
  if (!tick) return;
  const yr = parseInt(tick.dataset.year);
  const cards = [...document.querySelectorAll(".card:not(.hidden)")];
  // find first card >= yr
  const target = cards.find(c => parseInt(c.dataset.year) >= yr);
  if (target) target.scrollIntoView({behavior:"smooth", block:"start"});
});
