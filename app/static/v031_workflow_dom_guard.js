(() => {
  const root = document.querySelector('.v0211-workspace');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  if (!root || !workbench || !flow) return;

  let scheduled = false;

  // The older v0.3.1 script asks for confirmation before editing an amount after
  // stage 3. v0.3.2 deliberately makes amount rollback silent: the server saves
  // the changed row, restores stage 4 when necessary, clears later workflow
  // stages and leaves every untouched row alone. Stop propagation only; do not
  // cancel the browser's edit itself.
  document.addEventListener('beforeinput', event => {
    const input = event.target.closest?.('.quick-amount');
    if (!input || !root.contains(input)) return;
    event.stopPropagation();
  }, true);

  const enforce = () => {
    scheduled = false;
    const paid = flow.querySelector('[data-v031-flow-action="paid"]')?.getAttribute('aria-pressed') === 'true';

    // Amounts stay editable in every stage. Editing after stage 4 is safe because
    // the server restores the saved pre-payment schedule before rolling back.
    root.querySelectorAll('.quick-amount').forEach(input => {
      if (input.readOnly) input.readOnly = false;
    });

    root.querySelectorAll('[data-payment-row]').forEach(row => {
      const fixed = row.dataset.mode === 'fixed';
      const confirmed = row.dataset.confirmed === '1';
      const review = row.querySelector('[data-review-toggle]');
      const fixedToggle = row.querySelector('[data-fixed-toggle]');
      const defer = row.querySelector('[data-defer-payment-v0212]');

      if (fixed) {
        // Fixed amounts are normally automatic. A fixed amount that has just
        // been manually edited is returned by the server as data-confirmed=0;
        // that single row must remain pending until the user confirms it once.
        row.classList.toggle('is-confirmed', confirmed);
        row.classList.toggle('is-pending', !confirmed);
        row.classList.toggle('v031-fixed-auto-confirmed', confirmed);
        if (review) {
          const shouldDisable = paid || confirmed;
          if (review.disabled !== shouldDisable) review.disabled = shouldDisable;
          if (review.textContent !== (confirmed ? '✓' : '○')) review.textContent = confirmed ? '✓' : '○';
          const title = confirmed
            ? '固定缴费金额自动确认，无需人工核对'
            : '金额刚刚修改，请重新确认这一条';
          if (review.title !== title) review.title = title;
          review.classList.toggle('confirmed', confirmed);
          review.classList.toggle('pending', !confirmed);
          review.classList.toggle('v031-auto-confirmed', confirmed);
        }
      } else if (review && review.disabled !== paid) {
        review.disabled = paid;
      }

      if (fixedToggle && fixedToggle.disabled !== paid) fixedToggle.disabled = paid;
      if (defer && defer.disabled !== paid) defer.disabled = paid;
    });

    // Other controls may remain protected after completion, but the amount field
    // itself is no longer visually or functionally locked.
    root.classList.remove('v03-payment-locked');
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(enforce);
  };

  // The four-stage flow is the authority. Any late legacy mutation of readonly /
  // disabled flags is corrected to match the final stage and row-level state.
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
