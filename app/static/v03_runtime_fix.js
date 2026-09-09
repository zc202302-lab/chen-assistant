(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const flow = root.querySelector('[data-v03-payment-flow]');
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  let paymentMembershipDirty = false;
  let flowState = null;

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

  /* ---- workflow recovery: labels are never blank, and this layer owns clicks ---- */
  const flowDefs = [
    ['review', '金额核对'],
    ['notify', '通知客户'],
    ['paid', '完成缴费'],
  ];

  const editControls = () => root.querySelectorAll('.quick-amount,[data-review-toggle],[data-fixed-toggle],[data-defer-payment-v0212]');

  const renderFlow = () => {
    if (!flow) return;
    flowDefs.forEach(([action, label], index) => {
      const btn = flow.querySelector(`[data-v03-flow-action="${action}"]`);
      if (!btn) return;
      const done = !!flowState?.[action === 'review' ? 'reviewed' : action === 'notify' ? 'notified' : 'paid'];
      btn.textContent = done ? `✓ ${label}` : `${index + 1} ${label}`;
      btn.classList.toggle('done', done);
      btn.classList.toggle('current', !!flowState && !done && (
        (action === 'review' && flowState.ready) ||
        (action === 'notify' && flowState.reviewed) ||
        (action === 'paid' && flowState.notified)
      ));

      let disabled = !flowState;
      let title = flowState ? '' : '正在读取缴费流程状态';
      if (flowState) {
        if (action === 'review') {
          disabled = done ? !!(flowState.notified || flowState.paid) : !flowState.ready;
          title = done
            ? (disabled ? '请先撤回后续步骤' : '点击撤回金额核对')
            : (flowState.ready ? '确认本月金额已全部核对' : `还有 ${flowState.pending || 0} 项金额未核对`);
        } else if (action === 'notify') {
          disabled = done ? !!flowState.paid : !flowState.reviewed;
          title = done ? (disabled ? '请先撤回完成缴费' : '点击撤回通知客户') : '先完成金额核对后才能通知客户';
        } else {
          disabled = !done && !flowState.notified;
          title = done ? '点击撤回完成缴费并恢复缴费前周期' : '先完成通知客户后才能完成缴费';
        }
      }
      btn.disabled = disabled;
      btn.title = title;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
    });

    const locked = !!(flowState?.notified || flowState?.paid);
    editControls().forEach(control => {
      if (control.matches('.quick-amount')) control.readOnly = locked;
      else control.disabled = locked;
    });
    root.classList.toggle('v03-payment-locked', locked);
  };

  const loadFlow = async () => {
    if (!flow || !customerId) return;
    renderFlow();
    try {
      let data;
      try {
        data = await fetchJson(`/customers/${customerId}/workflow-state-v03`);
      } catch (_) {
        data = await fetchJson(`/customers/${customerId}/payment-run-v03`);
      }
      flowState = data.run || {};
      if (data.stats && flowState.pending === undefined) flowState.pending = Number(data.stats.pending || 0);
      renderFlow();
    } catch (err) {
      toast(`缴费流程读取失败：${err.message}`);
      renderFlow();
    }
  };

  if (flow) {
    // Fix the visible production regression immediately, before any network request returns.
    flowDefs.forEach(([action, label], index) => {
      const btn = flow.querySelector(`[data-v03-flow-action="${action}"]`);
      if (btn && !btn.textContent.trim()) btn.textContent = `${index + 1} ${label}`;
    });

    flow.addEventListener('click', async e => {
      const btn = e.target.closest('[data-v03-flow-action]');
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      e.stopImmediatePropagation();
      if (!flowState) {
        await loadFlow();
        if (!flowState) return;
      }
      if (btn.disabled) return;

      const action = btn.dataset.v03FlowAction || '';
      if (action === 'paid' && flowState.paid) {
        if (!confirm('撤回“完成缴费”并恢复本次缴费前的周期状态？')) return;
      }
      btn.disabled = true;
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('action', action);
      try {
        const data = await postForm(`/customers/${customerId}/payment-run`, fd);
        flowState = data.run || flowState;
        if (data.stats) flowState.pending = Number(data.stats.pending || 0);
        renderFlow();
        const message = action === 'review'
          ? (flowState.reviewed ? '金额核对已确认' : '已撤回金额核对')
          : action === 'notify'
            ? (flowState.notified ? '已标记通知客户' : '已撤回通知状态')
            : (flowState.paid ? '本月缴费已完成' : '已撤回完成缴费并恢复周期');
        toast(message);
      } catch (err) {
        toast(err.message || '缴费流程操作失败');
        await loadFlow();
      }
    }, true);

    loadFlow();
  }

  /* ---- business editor: payment status becomes an editable runtime control ---- */
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
        <small class="v031-payment-state-current">当前：<strong data-v03-payment-state>${existing}</strong></small>
        <small data-v031-payment-help>正常周期由缴费周期自动计算；如当前已延期，可在这里恢复正常。</small>`;
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
