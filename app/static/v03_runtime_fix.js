(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  let paymentMembershipDirty = false;

  /*
   * v0.3 runtime compatibility now has one responsibility only: business-editor
   * payment schedule controls. The old three-stage payment-flow controller was
   * removed because v031_workflow_runtime_fix.js is the sole workflow owner.
   */

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'app-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 1600);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const postForm = async (url, fd) => fetchJson(url, {method: 'POST', body: fd});

  const periodText = () => {
    const raw = root.querySelector('.v023-payment-title-line .eyebrow')?.textContent?.trim() || '';
    return /^\d{4}-\d{2}$/.test(raw) ? raw : '';
  };

  const monthDistance = (from, to) => {
    const a = /^(\d{4})-(\d{2})$/.exec(from || '');
    const b = /^(\d{4})-(\d{2})$/.exec(to || '');
    if (!a || !b) return 0;
    return (Number(b[1]) - Number(a[1])) * 12 + Number(b[2]) - Number(a[2]);
  };

  const updateBusinessStateCells = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${CSS.escape(String(sid))}"]`);
      if (!card) return;
      const state = (payload.preview_attributes || []).find(x => x.key === '__payment_state__');
      const cell = card.querySelector('[data-attr-key="__payment_state__"] strong');
      if (state && cell) cell.textContent = state.value || '—';
      if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
    });
  };

  const ensureEditablePaymentState = () => {
    const box = businessDialog?.querySelector('.v03-payment-state-box');
    if (!box) return null;
    if (!box.querySelector('[data-v031-payment-mode]')) {
      const existing = box.querySelector('[data-v03-payment-state]')?.textContent?.trim() || '—';
      box.innerHTML = `
        <span>缴费状态</span>
        <select data-v031-payment-mode aria-label="缴费状态"></select>
        <small class="v031-payment-state-current">当前：<strong data-v03-payment-state>${existing}</strong></small>`;
    }
    return box;
  };

  const loadEditablePaymentState = async () => {
    if (!businessDialog?.open || !businessForm) return;
    const sid = String(businessForm.elements.service_id?.value || '').trim();
    if (!sid) return;
    const box = ensureEditablePaymentState();
    const select = box?.querySelector('[data-v031-payment-mode]');
    if (!select) return;
    select.disabled = true;
    try {
      const runtime = await fetchJson(`/services/${sid}/runtime-v0212`);
      if (sid !== String(businessForm.elements.service_id?.value || '').trim()) return;
      const period = periodText();
      const deferred = (runtime.deferred_until_period || '').trim();
      const activeDeferral = !!deferred && (!period || monthDistance(period, deferred) > 0);
      select.innerHTML = '';
      if (activeDeferral) {
        const keep = document.createElement('option');
        keep.value = 'deferred';
        keep.textContent = `延期至 ${deferred.replace('-', '/')}`;
        const normal = document.createElement('option');
        normal.value = 'normal';
        normal.textContent = '恢复正常缴费周期';
        select.append(keep, normal);
        select.value = 'deferred';
      } else {
        const normal = document.createElement('option');
        normal.value = 'normal';
        normal.textContent = '正常缴费周期';
        select.appendChild(normal);
        select.value = 'normal';
      }
      select.dataset.serviceId = sid;
      select.dataset.deferredUntil = deferred;
      const strong = box.querySelector('[data-v03-payment-state]');
      if (strong) strong.textContent = runtime.schedule_state || '—';
    } catch (err) {
      toast(err.message || '缴费状态读取失败');
    } finally {
      select.disabled = false;
    }
  };

  businessDialog?.addEventListener('change', async e => {
    const select = e.target.closest('[data-v031-payment-mode]');
    if (!select || select.value !== 'normal') return;
    const sid = select.dataset.serviceId || String(businessForm?.elements.service_id?.value || '').trim();
    const deferred = select.dataset.deferredUntil || '';
    if (!sid || !deferred) return;

    if (!confirm('恢复正常缴费周期？如果这条业务按正常周期本月应缴，它会重新进入缴费工作区。')) {
      select.value = 'deferred';
      return;
    }

    select.disabled = true;
    const fd = new FormData();
    fd.append('csrf', businessForm.elements.csrf.value);
    fd.append('mode', 'normal');
    try {
      const data = await postForm(`/services/${sid}/payment-status-v03`, fd);
      select.innerHTML = '<option value="normal">正常缴费周期</option>';
      select.value = 'normal';
      select.dataset.deferredUntil = '';
      const strong = businessDialog.querySelector('[data-v03-payment-state]');
      if (strong) strong.textContent = data.schedule_state || '—';
      updateBusinessStateCells(data.rows || {});
      paymentMembershipDirty = !!data.changed;
      toast(data.due ? '已恢复正常周期，本月将重新进入缴费工作区' : '已恢复正常缴费周期');
    } catch (err) {
      select.value = 'deferred';
      toast(err.message || '恢复正常缴费周期失败');
    } finally {
      select.disabled = false;
    }
  }, true);

  if (businessDialog) {
    new MutationObserver(() => {
      if (businessDialog.open) requestAnimationFrame(loadEditablePaymentState);
    }).observe(businessDialog, {attributes: true, attributeFilter: ['open']});
  }

  // If restoring a deferral changes payment membership, refresh only when the user
  // actually goes back to payment. This avoids discarding unsaved business edits.
  root.addEventListener('click', e => {
    const tab = e.target.closest('[data-customer-tab="payment"]');
    if (!tab || !paymentMembershipDirty) return;
    e.preventDefault();
    e.stopPropagation();
    e.stopImmediatePropagation();
    location.href = `/customers/${customerId}?tab=payment`;
  }, true);
})();
