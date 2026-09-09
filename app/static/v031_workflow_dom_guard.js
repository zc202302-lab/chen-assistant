(() => {
  const root = document.querySelector('.v0211-workspace');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  if (!root || !workbench || !flow) return;

  let scheduled = false;

  const enforce = () => {
    scheduled = false;
    const paid = flow.querySelector('[data-v031-flow-action="paid"]')?.getAttribute('aria-pressed') === 'true';

    root.querySelectorAll('.quick-amount').forEach(input => {
      if (input.readOnly !== paid) input.readOnly = paid;
    });

    root.querySelectorAll('[data-payment-row]').forEach(row => {
      const fixed = row.dataset.mode === 'fixed';
      const review = row.querySelector('[data-review-toggle]');
      const fixedToggle = row.querySelector('[data-fixed-toggle]');
      const defer = row.querySelector('[data-defer-payment-v0212]');

      if (fixed) {
        if (row.dataset.confirmed !== '1') row.dataset.confirmed = '1';
        row.classList.add('is-confirmed', 'v031-fixed-auto-confirmed');
        row.classList.remove('is-pending');
        if (review) {
          review.disabled = true;
          review.textContent = '✓';
          review.title = '固定缴费金额自动确认，无需人工核对';
          review.classList.add('confirmed', 'v031-auto-confirmed');
          review.classList.remove('pending');
        }
      } else if (review && review.disabled !== paid) {
        review.disabled = paid;
      }

      if (fixedToggle && fixedToggle.disabled !== paid) fixedToggle.disabled = paid;
      if (defer && defer.disabled !== paid) defer.disabled = paid;
    });

    root.classList.toggle('v03-payment-locked', paid);
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(enforce);
  };

  // The four-stage flow is the authority. Any late legacy mutation of readonly /
  // disabled flags is corrected to match the final stage state.
  new MutationObserver(schedule).observe(flow, {
    subtree: true,
    attributes: true,
    attributeFilter: ['aria-pressed'],
  });
  new MutationObserver(schedule).observe(workbench, {
    subtree: true,
    attributes: true,
    attributeFilter: ['readonly', 'disabled', 'data-confirmed'],
  });

  enforce();
  setTimeout(enforce, 500);
  setTimeout(enforce, 1500);
})();
