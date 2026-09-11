(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  /*
   * Compatibility placeholder only.
   *
   * This v0.3 patch used to clone the Foxmail button, probe the local helper and
   * attach its own compose listener. The later v0.3.1 workflow intentionally
   * clones that button again to detach every v0.3 listener, while
   * v031_workflow_actions.js owns the current Foxmail preparation path.
   *
   * Keeping both implementations active caused needless local bridge probes and
   * made event ownership dependent on script load order. Leave the asset in place
   * for deployment compatibility, but do not bind listeners or contact the bridge.
   */
  root.dataset.v03FoxmailLegacy = 'retired';
})();
