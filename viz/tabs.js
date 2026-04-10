// ── Tab state + shared data globals ───────────────────────────────────────────
// netNodes, netLinks, entriesByActor, entriesByAnchor are declared here so they
// are accessible to both boot.js (which populates them) and network.js (which reads them).

let networkDrawn    = false;
let netNodes        = [];
let netLinks        = [];
let entriesByActor  = new Map();
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
