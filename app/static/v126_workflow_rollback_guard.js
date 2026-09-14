(() => {
  const root = document.querySelector('.v0211-workspace');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const customerId = root?.dataset.customerId || '';
  const csrf = workbench?.dataset.csrf || '';
  if (!root || !flow || !customerId || !csrf) return;

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

  const isDone = (action, run) => action === 'notify' ? !!run.notified : action === 'initiate' ? !!run.initiated : !!run.paid;
  const blocked = (action, run) => (action === 'notify' && (run.initiated || run.paid)) || (action === 'initiate' && run.paid);

  document.addEventListener('click', async event => {
    const btn = event.target.closest?.('[data-v031-flow-action]');
    if (!btn || !flow.contains(btn)) return;
    const action = btn.dataset.v031FlowAction || '';
    if (!['notify', 'initiate', 'paid'].includes(action)) return;

    let snapshot;
    try {
      snapshot = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
    } catch (_) {
      return;
    }
    const run = snapshot.run || {};
    if (!isDone(action, run)) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    if (blocked(action, run)) return;

    try {
      await postAction(action);
      await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
    } catch (_) {
      await window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
    }
  }, true);
})();
