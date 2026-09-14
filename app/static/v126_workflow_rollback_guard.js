(() => {
  const root = document.querySelector('.v0211-workspace');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const customerId = root?.dataset.customerId || '';
  const csrf = workbench?.dataset.csrf || '';
  if (!root || !flow || !customerId || !csrf) return;

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
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.detail || data.error || `请求失败（${response.status}）`);
    return data;
  };

  const postAction = async action => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('action', action);
    return fetchJson(`/customers/${customerId}/payment-workflow-v031`, {method: 'POST', body: fd});
  };

  const refresh = async () => {
    await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
  };

  const blockedReason = (action, run) => {
    if (action === 'notify' && (run.initiated || run.paid)) return '请先撤回“发起缴费”，再撤回“通知客户”';
    if (action === 'initiate' && run.paid) return '请先撤回“完成缴费”，再撤回“发起缴费”';
    return '';
  };

  const isDone = (action, run) => {
    if (action === 'notify') return !!run.notified;
    if (action === 'initiate') return !!run.initiated;
    if (action === 'paid') return !!run.paid;
    return false;
  };

  // Capture at document level, before all historical flow listeners. Completed
  // stages use the server as the source of truth so a stale client-side state can
  // never turn a rollback click into a prepare/forward action.
  document.addEventListener('click', async event => {
    const btn = event.target.closest?.('[data-v031-flow-action]');
    if (!btn || !flow.contains(btn)) return;
    const action = btn.dataset.v031FlowAction || '';
    if (!['notify', 'initiate', 'paid'].includes(action)) return;
    if (btn.getAttribute('aria-pressed') !== 'true') return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (flow.dataset.v126RollbackBusy === '1') return;
    flow.dataset.v126RollbackBusy = '1';

    try {
      const snapshot = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      const run = snapshot.run || {};
      if (!isDone(action, run)) {
        await refresh();
        return;
      }
      const reason = blockedReason(action, run);
      if (reason) {
        toast(reason);
        await refresh();
        return;
      }

      await postAction(action);
      await refresh();
      const message = action === 'notify'
        ? '已撤回“通知客户”；金额核对保持有效'
        : action === 'initiate'
          ? '已撤回“发起缴费”；通知客户保持有效'
          : '已撤回“完成缴费”并恢复缴费周期';
      toast(message);
    } catch (err) {
      toast(`流程回退失败：${err.message || '未知错误'}`);
      try { await refresh(); } catch (_) {}
    } finally {
      delete flow.dataset.v126RollbackBusy;
    }
  }, true);
})();
