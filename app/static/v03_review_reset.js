(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  /*
   * Compatibility placeholder only.
   *
   * Review/workflow state used to be repainted here by observing aria-pressed
   * and data-confirmed mutations. That made this legacy v0.3 layer a second
   * writer competing with the current v0.3.1 runtime and DOM guard, which is
   * exactly the kind of cross-writing that caused row-confirmation regressions.
   *
   * Current ownership is now intentionally single-source:
   *   - server: authoritative row/workflow state
   *   - v031_workflow_runtime_fix.js: four-stage workflow rendering/refresh
   *   - v031_workflow_dom_guard.js: row control/DOM consistency enforcement
   *
   * Keep this file temporarily because deployment/asset contracts still refer
   * to it. It must not mutate payment rows, counters, or workflow buttons.
   */
  root.dataset.v03ReviewResetLegacy = 'retired';
})();
