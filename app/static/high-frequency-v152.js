(() => {
  const workbench = document.querySelector('[data-payment-workbench]');
  if (!workbench) return;
  const root = workbench.closest('.v0211-workspace,.v027-workspace') || document;

  const ensurePaymentTotalRow = () => {
    const paymentList = document.getElementById('paymentSortable');
    const grandTotal = document.getElementById('paymentGrandTotal');
    const total = grandTotal?.closest('.v023-total') || grandTotal?.parentElement || document.querySelector('.v023-total');
    if (!paymentList || !total) return;
    let row = paymentList.querySelector('[data-payment-total-row-v152]');
    if (!row) {
      row = document.createElement('div');
      row.className = 'payment-total-row-v152';
      row.dataset.paymentTotalRowV152 = '1';
      paymentList.appendChild(row);
    }
    total.classList.remove('v124-total-moved');
    total.classList.add('payment-total-v152');
    if (total.parentElement !== row) row.appendChild(total);

    // v1.2.4 used its own total helper row. v1.5.2 supersedes that row; once the
    // real total has moved into the v1.5.2 row, remove the now-empty legacy row so
    // live reconciliation cannot strand it directly below the table header.
    paymentList.querySelectorAll('.v124-payment-total-row').forEach(legacy => legacy.remove());

    // Reconciliation may append payment rows after this helper row. Keep the total
    // physically at the bottom of the current payment table after every refresh.
    if (row !== paymentList.lastElementChild) paymentList.appendChild(row);
  };

  ensurePaymentTotalRow();
  window.addEventListener('chen:live-refresh', () => ensurePaymentTotalRow());

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

  const accountValue = row => String(
    row?.dataset.paymentAccount ||
    row?.querySelector('.identifier-copy[data-kind="账号"][data-copy]')?.dataset.copy ||
    ''
  ).trim();

  const focusAmountAndCopyAccount = async row => {
    if (!row) return;
    const serviceId = String(row.dataset.serviceId || '');
    const account = accountValue(row);
    if (account) await copyText(account);

    const liveRow = currentRowByServiceId(serviceId) || row;
    const input = liveRow.querySelector('.quick-amount');
    if (!input) return;
    const sticky = root.querySelector?.('.workspace-sticky-top');
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

  window.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const input = event.target.closest?.('[data-payment-workbench] .quick-amount');
    if (!input) return;
    arm('amount', input.closest('[data-payment-row]'));
  }, true);

  workbench.addEventListener('focusin', event => {
    const input = event.target.closest?.('.quick-amount');
    if (!input || armed?.kind !== 'amount') return;
    const row = input.closest('[data-payment-row]');
    if (!row) return;
    const targetId = String(row.dataset.serviceId || '');
    if (!targetId || targetId === armed.serviceId) return;
    const pending = armed;
    armed = null;
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

  window.addEventListener('pointerdown', event => {
    const button = event.target.closest?.('[data-payment-workbench] [data-review-toggle]');
    if (!button) return;
    const row = button.closest('[data-payment-row]');
    if (row?.dataset.confirmed !== '0') return;
    const pending = arm('review', row);
    setTimeout(() => waitForReviewedRow(pending), 0);
  }, true);
})();
