(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const paymentList = document.getElementById('paymentSortable');
  const reviewButton = root.querySelector('[data-v031-flow-action="review"], [data-v03-flow-action="review"]');
  if (!paymentList || !reviewButton) return;

  const rows = () => [...paymentList.querySelectorAll('[data-payment-row]')];
  const variableRows = () => rows().filter(row => row.dataset.mode === 'variable');
  let wholeReset = false;
  let lastReviewState = reviewButton.getAttribute('aria-pressed');
  let explicitWholeResetRequested = false;
  let explicitResetTimer = 0;

  const paintRow = (row, confirmed) => {
    // Row-level confirmation from the server is authoritative. Fixed amounts are
    // normally confirmed automatically, but a manually changed fixed amount is
    // allowed to remain pending until that single row is confirmed again.
    const next = confirmed ? '1' : '0';
    if (row.dataset.confirmed !== next) row.dataset.confirmed = next;
    row.classList.toggle('is-confirmed', !!confirmed);
    row.classList.toggle('is-pending', !confirmed);
    row.classList.toggle('v031-fixed-auto-confirmed', row.dataset.mode === 'fixed' && !!confirmed);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      const symbol = confirmed ? '✓' : '○';
      if (state.textContent !== symbol) state.textContent = symbol;
      state.classList.toggle('confirmed', !!confirmed);
      state.classList.toggle('pending', !confirmed);
      state.classList.toggle('v031-auto-confirmed', row.dataset.mode === 'fixed' && !!confirmed);
      const fixed = row.dataset.mode === 'fixed';
      const label = fixed
        ? (confirmed ? '固定金额自动已确认' : '固定金额已修改，待重新确认')
        : (confirmed ? '已核对' : '未核对');
      if (state.getAttribute('aria-label') !== label) state.setAttribute('aria-label', label);
      if (fixed) {
        state.disabled = !!confirmed;
        state.title = confirmed
          ? '固定缴费金额自动确认，无需人工核对'
          : '金额刚刚修改，请重新确认这一条';
      }
    }
  };

  const normalizeFromData = () => {
    rows().forEach(row => paintRow(row, row.dataset.confirmed === '1'));
  };

  const detectPersistedWholeReset = () => {
    wholeReset = root.classList.contains('v03-whole-review-reset');
  };

  const syncResetCounters = () => {
    if (!wholeReset) return;
    const variable = variableRows();
    const unconfirmed = variable.filter(row => row.dataset.confirmed !== '1').length;
    const required = document.getElementById('requiredCount');
    const pending = document.getElementById('pendingCount');
    const readiness = document.getElementById('paymentReadiness');
    if (required) required.textContent = String(variable.length);
    if (pending) pending.textContent = String(unconfirmed);
    if (readiness) {
      readiness.textContent = unconfirmed
        ? `还有 ${unconfirmed} 项变动金额待重新确认；固定金额已自动确认`
        : '变动金额已确认；固定金额自动确认，可完成金额核对';
    }
  };

  const refreshServerCounters = async () => {
    const customerId = root.dataset.customerId || '';
    if (!customerId) return;
    try {
      const r = await fetch(`/customers/${customerId}/payment-workflow-v031`, {credentials: 'same-origin', cache: 'no-store'});
      const data = await r.json();
      if (!r.ok || !data.ok) return;
      const required = document.getElementById('requiredCount');
      const pending = document.getElementById('pendingCount');
      const readiness = document.getElementById('paymentReadiness');
      if (required && data.stats?.required !== undefined) required.textContent = String(data.stats.required);
      if (pending && data.stats?.pending !== undefined) pending.textContent = String(data.stats.pending);
      if (readiness && data.stats?.pending !== undefined) {
        readiness.textContent = Number(data.stats.pending)
          ? `还有 ${data.stats.pending} 项金额未核对`
          : '本月金额已全部核对';
      }
    } catch (_) {}
  };

  normalizeFromData();
  detectPersistedWholeReset();
  if (wholeReset) syncResetCounters();

  // Distinguish an explicit "撤回金额核对" click from an automatic workflow
  // rollback caused by editing one amount. The latter must NEVER clear untouched
  // rows. Listen on document capture because the current workflow owner stops the
  // event at the flow element before legacy listeners can see it.
  document.addEventListener('click', event => {
    const btn = event.target.closest?.('[data-v031-flow-action="review"], [data-v03-flow-action="review"]');
    if (btn !== reviewButton) return;
    clearTimeout(explicitResetTimer);
    explicitWholeResetRequested = (
      reviewButton.getAttribute('aria-pressed') === 'true' &&
      variableRows().some(row => row.dataset.confirmed === '1')
    );
    explicitResetTimer = setTimeout(() => {
      explicitWholeResetRequested = false;
    }, 2000);
  }, true);

  new MutationObserver(() => {
    const current = reviewButton.getAttribute('aria-pressed');
    if (current === lastReviewState) return;

    if (lastReviewState === 'true' && current === 'false') {
      if (explicitWholeResetRequested) {
        // The server's explicit whole-review withdrawal resets variable rows only.
        // Mirror that known response immediately; fixed rows keep their own state.
        wholeReset = variableRows().length > 0;
        root.classList.toggle('v03-whole-review-reset', wholeReset);
        variableRows().forEach(row => paintRow(row, false));
        if (wholeReset) syncResetCounters();
      } else {
        // Automatic rollback after an amount edit is row-preserving. The amount
        // save/review endpoint has already painted the changed row, so only
        // normalize current authoritative data attributes and leave all others alone.
        wholeReset = false;
        root.classList.remove('v03-whole-review-reset');
        normalizeFromData();
      }
      explicitWholeResetRequested = false;
      clearTimeout(explicitResetTimer);
      refreshServerCounters();
    } else if (lastReviewState === 'false' && current === 'true') {
      explicitWholeResetRequested = false;
      clearTimeout(explicitResetTimer);
      wholeReset = false;
      root.classList.remove('v03-whole-review-reset');
      normalizeFromData();
      refreshServerCounters();
    }
    lastReviewState = current;
  }).observe(reviewButton, {attributes: true, attributeFilter: ['aria-pressed']});

  new MutationObserver(() => {
    normalizeFromData();
    if (wholeReset) syncResetCounters();
  }).observe(paymentList, {subtree: true, attributes: true, attributeFilter: ['data-confirmed']});
})();
