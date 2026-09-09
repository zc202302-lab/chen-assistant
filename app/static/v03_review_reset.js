(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const paymentList = document.getElementById('paymentSortable');
  const reviewButton = root.querySelector('[data-v03-flow-action="review"]');
  if (!paymentList || !reviewButton) return;

  const rows = () => [...paymentList.querySelectorAll('[data-payment-row]')];
  let wholeReset = false;
  let lastReviewState = reviewButton.getAttribute('aria-pressed');

  const paintRow = (row, confirmed) => {
    const next = confirmed ? '1' : '0';
    if (row.dataset.confirmed !== next) row.dataset.confirmed = next;
    row.classList.toggle('is-confirmed', !!confirmed);
    row.classList.toggle('is-pending', !confirmed);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      const symbol = confirmed ? '✓' : '○';
      if (state.textContent !== symbol) state.textContent = symbol;
      state.classList.toggle('confirmed', !!confirmed);
      state.classList.toggle('pending', !confirmed);
      const label = confirmed ? '已核对' : '未核对';
      if (state.getAttribute('aria-label') !== label) state.setAttribute('aria-label', label);
    }
  };

  const normalizeFromData = () => {
    rows().forEach(row => paintRow(row, row.dataset.confirmed === '1'));
  };

  const detectPersistedWholeReset = () => {
    wholeReset = rows().some(row => row.dataset.mode === 'fixed' && row.dataset.confirmed === '0');
    root.classList.toggle('v03-whole-review-reset', wholeReset);
  };

  const syncResetCounters = () => {
    if (!wholeReset) return;
    const all = rows();
    const unconfirmed = all.filter(row => row.dataset.confirmed !== '1').length;
    const required = document.getElementById('requiredCount');
    const pending = document.getElementById('pendingCount');
    const readiness = document.getElementById('paymentReadiness');
    if (required) required.textContent = String(all.length);
    if (pending) pending.textContent = String(unconfirmed);
    if (readiness) {
      readiness.textContent = unconfirmed
        ? `整批核对已撤销，还有 ${unconfirmed} 项待重新确认`
        : '本月金额已重新确认，可再次完成金额核对';
    }
  };

  const refreshServerCounters = async () => {
    const customerId = root.dataset.customerId || '';
    if (!customerId) return;
    try {
      const r = await fetch(`/customers/${customerId}/workflow-state-v03`, {credentials: 'same-origin'});
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
          : '本月应缴业务金额已全部核对';
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
      wholeReset = true;
      root.classList.add('v03-whole-review-reset');
      rows().forEach(row => paintRow(row, false));
      syncResetCounters();
    } else if (lastReviewState === 'false' && current === 'true') {
      // The backend only allows this transition after every variable row has been
      // rechecked; fixed rows are re-confirmed automatically as part of this action.
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
