// ── Panel view state machine ──────────────────────────────────────────────────
let viewStack   = [];
let currentView = { type: "chat", title: "Suche", renderFn: null, entityKey: null };

function _safeRender(renderFn, el) {
  if (!renderFn) return;
  try { renderFn(el); }
  catch (err) { console.error("[panel] render error:", err); }
}

function _renderView({ type, title, renderFn, entityKey }) {
  document.getElementById("panel-title").textContent = title;
  document.getElementById("panel-back").classList.toggle("visible", viewStack.length > 0);
  document.querySelectorAll(".panel-view").forEach(el => el.classList.remove("active"));
  document.getElementById(`view-${type}`).classList.add("active");
  _safeRender(renderFn, document.getElementById(`view-${type}`));
  document.getElementById("panel-content").scrollTop = 0;
  // Returning to chat: drop single-ref focus but keep answer highlight
  if (type === "chat" && hlState.mode === "single") setHighlight("answer", hlState.anchors);
}

function showView(type, title, renderFn, entityKey) {
  // Same entity already showing – just re-render in place
  if (currentView && currentView.type === type && currentView.entityKey === entityKey && entityKey) {
    _safeRender(renderFn, document.getElementById(`view-${type}`));
    return;
  }
  // Save current highlight state so goBack can restore it
  if (currentView) viewStack.push({ ...currentView, hlSnapshot: { ...hlState } });
  currentView = { type, title, renderFn, entityKey };
  _renderView(currentView);
}

function goBack() {
  if (!viewStack.length) return;
  const { hlSnapshot, ...view } = viewStack.pop();
  currentView = view;
  _renderView(currentView);
  selectedEntity = currentView.entityKey || null;
  // Restore highlight that was active before we navigated away (covers both timeline + network)
  if (hlSnapshot) setHighlight(hlSnapshot.mode, hlSnapshot.anchors, hlSnapshot.active, hlSnapshot.focusEntity || null);
}

function goHome() {
  viewStack      = [];
  selectedEntity = null;
  // Highlight preserved – cleared only by clicking empty chart area
  if (activeDot) { activeDot.classList.remove("active"); activeDot = null; }
  currentView = { type: "chat", title: "Suche", renderFn: null, entityKey: null };
  _renderView(currentView);
  setHighlight("none");  // reset chart entity highlight
}

document.getElementById("panel-back").addEventListener("click", goBack);
document.getElementById("panel-close").onclick = goHome;
document.addEventListener("keydown", e => { if (e.key === "Escape") goHome(); });

// ── Panel collapse/expand ─────────────────────────────────────────────────────
const panelEl    = document.getElementById("panel");
const panelMin   = document.getElementById("panel-min");
let panelExpanded = false;

panelMin.addEventListener("click", () => {
  panelExpanded = !panelExpanded;
  panelEl.classList.toggle("expanded", panelExpanded);
  panelMin.textContent = panelExpanded ? "→" : "←";
  panelMin.title       = panelExpanded ? "Einklappen" : "Ausklappen";
});

// ── Para list helpers ─────────────────────────────────────────────────────────
let activeDot = null, dimmedTypes = new Set();

function formatDate(p) {
  const raw  = p.date_raw || "";
  const year = p.year ? String(p.year) : "";
  if (!raw) return year;
  if (/\d{4}/.test(raw)) return raw;   // date_raw already contains a year
  return year ? `${raw} ${year}` : raw; // e.g. "März" + " 2013"
}

function renderParaList(entries, focusEntity = null) {
  return entries.map(p => {
    const et    = p.event_type || "?";
    const color = COLOR[et] || "#999";
    const date  = formatDate(p);
    const src   = [p.source_name, p.source_date].filter(Boolean).join(", ");
    const textHtml = focusEntity
      ? highlightWithKeywords(p.text || "", [], focusEntity)
      : highlightEntities(p.text || "");
    return `<div class="ep-para" data-anchor="${escapeHtml(p.doc_anchor || '')}">
      <div class="para-date">${escapeHtml(date)}</div>
      <span class="para-label" style="background:${color}">${et}</span>
      <div class="para-text">${textHtml}</div>
      ${src ? `<div class="para-source">${escapeHtml(src)}</div>` : ""}
    </div>`;
  }).join("");
}

function renderEntityView(normalform, viewEl) {
  const entries = entriesByActor.get(normalform) || [];
  const sorted  = [...entries].sort((a, b) =>
    (a.year || 0) - (b.year || 0) || (a.id || 0) - (b.id || 0));
  const info = summaryMap[normalform];
  let summaryHTML = "";
  if (info && info.summary) {
    let bodyHTML;
    try { bodyHTML = highlightWithKeywords(info.summary, [], normalform); }
    catch (err) { console.error("[renderEntityView:summary]", err); bodyHTML = escapeHtml(info.summary); }
    summaryHTML = `<div class="ep-summary">${bodyHTML}<div class="ep-summary-count">${info.count} Nennungen in der Chronik</div></div>`;
  }
  viewEl.innerHTML = summaryHTML + renderParaList(sorted, normalform);
}

function selectEntity(normalform) {
  selectedEntity = normalform;
  const renderFn = viewEl => renderEntityView(normalform, viewEl);
  // Always navigate to the entity view and always call _renderView.
  // We do NOT go through showView() because its deduplication early-return
  // only calls _safeRender (re-renders content) without calling _renderView
  // (which sets the active class). If #view-entity was hidden but currentView
  // already held this entity key, the view would silently stay invisible.
  // Push current state to stack only if we're not already on this exact entity.
  if (!(currentView.type === "entity" && currentView.entityKey === normalform)) {
    viewStack.push({ ...currentView, hlSnapshot: { ...hlState } });
  }
  currentView = { type: "entity", title: normalform, renderFn, entityKey: normalform };
  _renderView(currentView);
  const anchors = new Set(
    (entriesByActor.get(normalform) || []).map(e => e.doc_anchor).filter(Boolean)
  );
  setHighlight("answer", anchors, null, normalform);
}

// ── focusActor — chart/network sync without panel navigation ─────────────────────
// Updates the network ego-graph and timeline highlight for `name` without pushing
// a new panel view. Used when the calling context handles its own panel navigation
// (e.g. the tutorial), or when only the external views need updating.
// For entity-span clicks inside the panel use selectEntity() instead.
function focusActor(name) {
  // Network: ego-graph
  netFocusNode = name;
  if (typeof applyNetworkState === "function") applyNetworkState();

  // Chart: preserve KI anchors if active, otherwise switch to entity highlight.
  if (hlState.mode === "answer" && hlState.anchors?.size) {
    setHighlight(hlState.mode, hlState.anchors, hlState.active, name);
  } else {
    const anchors = new Set(
      (entriesByActor.get(name) || []).map(e => e.doc_anchor).filter(Boolean)
    );
    setHighlight("answer", anchors, null, name);
  }
}

document.getElementById("panel-content").addEventListener("click", e => {
  // Source-ref anchor: scroll target into view inside the panel container
  const ref = e.target.closest("a.src-ref");
  if (ref) {
    e.preventDefault();
    const targetId = ref.getAttribute("href").slice(1); // strip leading #
    document.getElementById(targetId)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
    const anchor   = targetId.replace(/^src-/, "");
    const allCards = document.querySelectorAll("#panel-content .ep-para[data-anchor], #panel-content .ep-para[id^='src-']");
    const anchors  = new Set([...allCards].map(c => c.dataset.anchor || c.id.replace(/^src-/, "")).filter(Boolean));
    setHighlight("single", anchors, anchor);
    return;
  }
  // Entity span click: navigate panel to entity summary + enter ego-graph in network.
  // Uses selectEntity() for panel navigation (same path as network node click).
  // netFocusNode is set before selectEntity so the ego-graph branch wins when
  // applyNetworkState fires inside setHighlight → _applyNetworkHighlight.
  const ent = e.target.closest(".entity");
  if (ent) {
    const name = ent.dataset.name;
    netFocusPair = null;
    netFocusNode = name;
    selectEntity(name);
    return;
  }
  // Para card click (source cards and entity view cards): single-dot highlight
  const card = e.target.closest(".ep-para[data-anchor], .ep-para[id^='src-']");
  if (card) {
    const anchor = card.dataset.anchor || card.id.replace(/^src-/, "");
    if (anchor) {
      // Collect anchors from all visible cards in the panel (works even without prior answer state)
      const allCards = document.querySelectorAll("#panel-content .ep-para[data-anchor], #panel-content .ep-para[id^='src-']");
      const anchors  = new Set([...allCards].map(c => c.dataset.anchor || c.id.replace(/^src-/, "")).filter(Boolean));
      setHighlight("single", anchors, anchor);
    }
  }
});

// ── Tooltip ───────────────────────────────────────────────────────────────────
const tip = document.getElementById("tooltip");
function showTip(html, e) { tip.innerHTML = html; tip.style.opacity = 1; moveTip(e); }
function moveTip(e) {
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top  = (e.clientY - 28) + "px";
}
function hideTip() { tip.style.opacity = 0; }
