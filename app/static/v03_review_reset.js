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

  const paintRow = (row, confirmed) => {
    // Fixed fee rows normally arrive from the server already confirmed. A fixed
    // amount that was manually changed is deliberately returned as confirmed=0
    // and must stay pending until the user confirms that row once.
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
    wholeReset = variableRows().some(row => row.dataset.confirmed === '0');
    root.classList.toggle('v03-whole-review-reset', wholeReset);
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
  syncResetCounters();

  new MutationObserver(() => {
    const current = reviewButton.getAttribute('aria-pressed');
    if (current === lastReviewState) return;

    if (lastReviewState === 'true' && current === 'false') {
      wholeReset = variableRows().length > 0;
      root.classList.toggle('v03-whole-review-reset', wholeReset);
      rows().forEach(row => {
        const confirmed = row.dataset.mode === 'fixed'
          ? row.dataset.confirmed === '1'
          : false;
        paintRow(row, confirmed);
      });
      syncResetCounters();
      refreshServerCounters();
    } else if (lastReviewState === 'false' && current === 'true') {
      rows().forEach(row => paintRow(row, true));
      wholeReset = false;
      root.classList.remove('v03-whole-review-reset');
      refreshServerCounters();
    }
    lastReviewState = current;
  }).observe(reviewButton, {attributes: true, attributeFilter: ['aria-pressed']});

  new MutationObserver(() => {
    normalizeFromData();
    if (wholeReset) syncResetCounters();
  }).observe(paymentList, {subtree: true, attributes: true, attributeFilter: ['data-confirmed']});
})();
