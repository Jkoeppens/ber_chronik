// ── Shared utilities ──────────────────────────────────────────────────────────

/** Canonical sort key for an undirected pair of node IDs. */
function pairKey(a, b) {
  return [a, b].sort().join("\x00");
}
