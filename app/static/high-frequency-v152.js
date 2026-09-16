(() => {
  const root = document.querySelector('.v028-workspace');
  if (!root) return;

  const workbench = root.querySelector('[data-payment-workbench]');
  if (!workbench) return;

  // Move the monthly total out of the header and align it with the amount column
  // at the bottom of the current payment table. When there are no rows the total
  // remains in the header, so an empty payment month never loses its summary.
  const paymentList = document.getElementById('paymentSortable');
  const total = document.querySelector('.v023-total');
  if (paymentList && total && !paymentList.querySelector('[data-payment-total-row-v152]')) {
    const row = document.createElement('div');
    row.className = 'payment-total-row-v152';
    row.dataset.paymentTotalRowV152 = '1';
    total.classList.add('payment-total-v152');
    row.appendChild(total);
    paymentList.appendChild(row);
  }

  const copyText = async value => {
    if (!value) return false;
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(value); return true; } catch (_) {}
    }
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.readOnly = true;
    Object.assign(ta.style, {position:'fixed', opacity:'0', left:'-9999px'});
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    return ok;
  };

  const rowsNow = () => [...workbench.querySelectorAll('[data-payment-row]')];
  const currentRowByServiceId = serviceId => rowsNow()
    .find(item => String(item.dataset.serviceId || '') === String(serviceId || '')) || null;

  const nextPendingBelow = serviceId => {
    const rows = rowsNow();
    const source = rows.find(item => String(item.dataset.serviceId || '') === String(serviceId || ''));
    const index = rows.indexOf(source);
    if (index < 0) return null;
    return rows.slice(index + 1).find(item => item.dataset.confirmed === '0') || null;
  };

  const accountValue = row => row?.querySelector('.identifier-copy[data-kind="账号"][data-copy]')?.dataset.copy || '';

  const focusAmountAndCopyAccount = async row => {
    if (!row) return;
    const serviceId = String(row.dataset.serviceId || '');
    const account = accountValue(row);
    if (account) await copyText(account);

    // Clipboard access can yield long enough for same-document live refresh to
    // reconcile the rows. Re-resolve the destination before scrolling/focusing.
    const liveRow = currentRowByServiceId(serviceId) || row;
    const input = liveRow.querySelector('.quick-amount');
    if (!input) return;
    const sticky = root.querySelector('.workspace-sticky-top');
    const top = (sticky ? sticky.getBoundingClientRect().bottom : 64) + 8;
    const rect = liveRow.getBoundingClientRect();
    if (rect.top < top) window.scrollBy({top: rect.top - top, behavior:'auto'});
    else if (rect.bottom > window.innerHeight - 18) window.scrollBy({top: rect.bottom - (window.innerHeight - 18), behavior:'auto'});
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const latestRow = currentRowByServiceId(serviceId) || liveRow;
      const latestInput = latestRow.querySelector('.quick-amount') || input;
      latestInput.focus({preventScroll:true});
      try { latestInput.setSelectionRange(0, latestInput.value.length); } catch (_) { latestInput.select?.(); }
    }));
  };

  let armed = null;
  let serial = 0;
  const arm = (kind, row) => {
    if (!row) return null;
    armed = {kind, serial: ++serial, serviceId: String(row.dataset.serviceId || '')};
    return armed;
  };

  // v0.2.8 already owns the mature Enter-save behavior and moves focus after a
  // successful save. Remember the source before its document-capture handler runs;
  // a later focusin on another payment amount is therefore the successful advance.
  window.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const input = event.target.closest?.('.v028-workspace .quick-amount');
    if (!input) return;
    arm('amount', input.closest('[data-payment-row]'));
  }, true);

  root.addEventListener('focusin', event => {
    const input = event.target.closest?.('.quick-amount');
    if (!input || armed?.kind !== 'amount') return;
    const row = input.closest('[data-payment-row]');
    if (!row) return;
    const targetId = String(row.dataset.serviceId || '');
    if (!targetId || targetId === armed.serviceId) return;
    const pending = armed;
    armed = null;
    // Focus has already landed on the mature handler's chosen next row. Copying
    // does not disturb that focus, so no second competing navigation is introduced.
    void copyText(accountValue(row));
    if (pending.serial !== serial) return;
  });

  const waitForReviewedRow = (pending, attemptsLeft = 160) => {
    if (!pending || pending.kind !== 'review') return;
    if (armed?.serial !== pending.serial) return;
    const source = currentRowByServiceId(pending.serviceId);
    if (source?.dataset.confirmed === '1') {
      const next = nextPendingBelow(pending.serviceId);
      armed = null;
      if (next) void focusAmountAndCopyAccount(next);
      return;
    }
    if (attemptsLeft <= 0) {
      if (armed?.serial === pending.serial) armed = null;
      return;
    }
    setTimeout(() => waitForReviewedRow(pending, attemptsLeft - 1), 25);
  };

  // A manual 未核对 -> 已核对 is the one review action that advances. Instead of
  // monkey-patching window.fetch, observe the authoritative DOM state that the
  // mature v0.2.8 handler updates after a successful server response. This remains
  // correct even when live refresh replaces payment-row elements during the request.
  window.addEventListener('pointerdown', event => {
    const button = event.target.closest?.('.v028-workspace [data-review-toggle]');
    if (!button) return;
    const row = button.closest('[data-payment-row]');
    if (row?.dataset.confirmed !== '0') return;
    const pending = arm('review', row);
    setTimeout(() => waitForReviewedRow(pending), 0);
  }, true);
})();
