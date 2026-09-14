(() => {
  const root = document.querySelector('.v0211-workspace');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const customerId = root?.dataset.customerId || '';
  const csrf = workbench?.dataset.csrf || '';
  if (!root || !flow || !customerId || !csrf) return;

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    console.info(msg);
  };

  const fetchJson = async (url, options = {}) => {
    const r = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.detail || data.error || `请求失败（${r.status}）`);
    return data;
  };

  const postAction = async action => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('action', action);
    return fetchJson(`/customers/${customerId}/payment-workflow-v031`, {method: 'POST', body: fd});
  };

  const isDone = (action, run) => {
    if (action === 'notify') return !!run.notified;
    if (action === 'initiate') return !!run.initiated;
    if (action === 'paid') return !!run.paid;
    return false;
  };

  const blockedReason = (action, run) => {
    if (action === 'notify' && (run.initiated || run.paid)) return '请先撤回“发起缴费”，再撤回“通知客户”';
    if (action === 'initiate' && run.paid) return '请先撤回“完成缴费”，再撤回“发起缴费”';
    return '';
  };

  // Every click is intercepted BEFORE historical listeners run. We then read the
  // authoritative server state. If the stage is done, this click means rollback.
  // If it is not done, refresh the legacy runtime and replay the click once.
  document.addEventListener('click', async event => {
    const btn = event.target.closest?.('[data-v031-flow-action]');
    if (!btn || !flow.contains(btn)) return;
    const action = btn.dataset.v031FlowAction || '';
    if (!['notify', 'initiate', 'paid'].includes(action)) return;

    if (btn.dataset.v127Replay === '1') return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (flow.dataset.v127Busy === '1') return;
    flow.dataset.v127Busy = '1';

    try {
      const snapshot = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      const run = snapshot.run || {};

      if (isDone(action, run)) {
        const reason = blockedReason(action, run);
        if (reason) {
          toast(reason);
          await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
          return;
        }
        await postAction(action);
        await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
        toast(action === 'notify'
          ? '已撤回“通知客户”'
          : action === 'initiate'
            ? '已撤回“发起缴费”'
            : '已撤回“完成缴费”并恢复缴费周期');
        return;
      }

      // Forward path: first synchronize the old runtime closure with server truth,
      // then replay exactly one click so the mature two-step external action flow
      // (prepare -> confirm) remains unchanged.
      await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
      btn.dataset.v127Replay = '1';
      btn.click();
      delete btn.dataset.v127Replay;
    } catch (err) {
      toast(`缴费流程状态同步失败：${err.message || '未知错误'}`);
      try { await window.ChenPaymentWorkflowRuntimeV031?.refresh?.(); } catch (_) {}
    } finally {
      delete flow.dataset.v127Busy;
      delete btn.dataset.v127Replay;
    }
  }, true);
})();
