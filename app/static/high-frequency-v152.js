(() => {
  const root = document.querySelector('.v028-workspace');
  if (!root) return;

  const workbench = root.querySelector('[data-payment-workbench]');
  if (!workbench) return;

  // Move the monthly total out of the header and align it with the amount column
  // at the bottom of the current payment table.
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
    return rows.slice(index + 1).find(item => item.dataset.mode === 'variable' && item.dataset.confirmed === '0') || null;
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

  let advanceSource = null;
  let advanceToken = 0;

  const armAdvance = row => {
    if (!row || row.dataset.confirmed !== '0' || row.dataset.mode !== 'variable') return;
    advanceSource = row;
    advanceToken += 1;
  };

  // Enter already saves and advances in v0.2.8; remember the source so the
  // destination row's account can be copied at the same time.
  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    const input = event.target.closest?.('.v028-workspace .quick-amount');
    if (!input) return;
    armAdvance(input.closest('[data-payment-row]'));
  }, true);

  // Manual review confirmation gets the same advance behavior as Enter.
  workbench.addEventListener('pointerdown', event => {
    const button = event.target.closest('[data-review-toggle]');
    if (!button) return;
    armAdvance(button.closest('[data-payment-row]'));
  }, true);

  const observer = new MutationObserver(() => {
    const source = advanceSource;
    if (!source || source.dataset.confirmed !== '1') return;
    const token = advanceToken;
    advanceSource = null;
    const next = nextPendingBelow(source);
    if (!next) return;
    setTimeout(() => {
      if (token !== advanceToken) return;
      focusAmountAndCopyAccount(next);
    }, 0);
  });
  observer.observe(workbench, {subtree:true, attributes:true, attributeFilter:['data-confirmed']});
})();
