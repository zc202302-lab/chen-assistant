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

  const nextPendingBelow = row => {
    const rows = [...workbench.querySelectorAll('[data-payment-row]')];
    const index = rows.indexOf(row);
    if (index < 0) return null;
    // "未核对" is authoritative; a deliberately unchecked fixed row is also a
    // valid destination and must not be skipped.
    return rows.slice(index + 1).find(item => item.dataset.confirmed === '0') || null;
  };

  const focusAmountAndCopyAccount = async row => {
    if (!row) return;
    const account = row.querySelector('.identifier-copy[data-kind="账号"][data-copy]');
    if (account?.dataset.copy) await copyText(account.dataset.copy);
    const input = row.querySelector('.quick-amount');
    if (!input) return;
    const sticky = root.querySelector('.workspace-sticky-top');
    const top = (sticky ? sticky.getBoundingClientRect().bottom : 64) + 8;
    const rect = row.getBoundingClientRect();
    if (rect.top < top) window.scrollBy({top: rect.top - top, behavior:'auto'});
    else if (rect.bottom > window.innerHeight - 18) window.scrollBy({top: rect.bottom - (window.innerHeight - 18), behavior:'auto'});
    requestAnimationFrame(() => requestAnimationFrame(() => {
      input.focus({preventScroll:true});
      try { input.setSelectionRange(0, input.value.length); } catch (_) { input.select?.(); }
    }));
  };

  let armed = null;
  let serial = 0;
  const arm = (kind, row) => {
    if (!row) return;
    armed = {kind, row, serial: ++serial, serviceId: String(row.dataset.serviceId || '')};
  };

  // v0.2.8 handles Enter at document capture phase and stops propagation. Window
  // capture runs earlier, so it is the stable place to remember the user's intent
  // without changing the mature save handler itself.
  window.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const input = event.target.closest?.('.v028-workspace .quick-amount');
    if (!input) return;
    arm('amount', input.closest('[data-payment-row]'));
  }, true);

  // Only a manual transition from 未核对 -> 已核对 should advance. Remember the
  // row before the existing handler sends its request.
  window.addEventListener('pointerdown', event => {
    const button = event.target.closest?.('.v028-workspace [data-review-toggle]');
    if (!button) return;
    const row = button.closest('[data-payment-row]');
    if (row?.dataset.confirmed === '0') arm('review', row);
  }, true);

  // Observe the two established payment endpoints at the network boundary. This
  // keeps all server/state semantics in the mature handlers; v1.5.2 only adds the
  // post-success focus + clipboard behavior requested for high-frequency entry.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const requestUrl = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
    const pending = armed;
    const isAmount = /\/services\/(\d+)\/payment-current(?:\?|$)/.exec(requestUrl);
    const isReview = /\/services\/(\d+)\/payment-review-toggle(?:\?|$)/.exec(requestUrl);
    const response = await nativeFetch(...args);

    if (!pending || (!isAmount && !isReview)) return response;
    const serviceId = String((isAmount || isReview)[1] || '');
    if (serviceId !== pending.serviceId) return response;

    const clone = response.clone();
    setTimeout(async () => {
      if (armed?.serial !== pending.serial) return;
      let data = {};
      try { data = await clone.json(); } catch (_) {}
      if (!response.ok || !data?.ok) {
        if (armed?.serial === pending.serial) armed = null;
        return;
      }
      if (pending.kind === 'review' && !data.confirmed) {
        if (armed?.serial === pending.serial) armed = null;
        return;
      }
      const source = pending.row;
      const next = nextPendingBelow(source);
      if (armed?.serial === pending.serial) armed = null;
      if (next) await focusAmountAndCopyAccount(next);
    }, 0);
    return response;
  };
})();
