(() => {
  const root = document.querySelector('.v0211-workspace');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const customerId = root?.dataset.customerId || '';
  const csrf = workbench?.dataset.csrf || '';
  const pendingNode = document.getElementById('pendingCount');
  const totalNode = document.getElementById('paymentGrandTotal');
  if (!root || !workbench || !customerId || (!pendingNode && !totalNode)) return;

  let lastPending = pendingNode?.textContent || '';
  let lastTotal = totalNode?.textContent || '';
  let timer = 0;
  let checking = false;
  let suppressUntil = Date.now() + 800;

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    const el = document.querySelector('.app-toast');
    if (!el) return;
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const paint = run => {
    if (!run) return;
    const defs = [
      ['review', '金额核对', !!run.reviewed],
      ['notify', '已通知客户', !!run.notified],
      ['initiate', '发起缴费', !!run.initiated],
      ['paid', '完成缴费', !!run.paid],
    ];
    defs.forEach(([action, label, done], index) => {
      const btn = root.querySelector(`[data-v031-flow-action="${action}"]`);
      if (!btn) return;
      btn.textContent = done ? `✓ ${label}` : `${index + 1} ${label}`;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
      btn.classList.toggle('done', done);
      const current = !done && (
        (action === 'review' && run.ready) ||
        (action === 'notify' && run.reviewed) ||
        (action === 'initiate' && run.notified) ||
        (action === 'paid' && run.initiated)
      );
      btn.classList.toggle('current', current);
      if (action === 'review') btn.disabled = done ? !!(run.notified || run.initiated || run.paid) : !run.ready;
      else if (action === 'notify') btn.disabled = done ? !!(run.initiated || run.paid) : !run.reviewed;
      else if (action === 'initiate') btn.disabled = done ? !!run.paid : !run.notified;
      else btn.disabled = !done && !run.initiated;
    });

    const image = root.querySelector('[data-v031-payment-image]');
    if (image) image.disabled = !run.reviewed || !!run.paid;
    const foxmail = root.querySelector('[data-v03-foxmail-draft]');
    if (foxmail) foxmail.disabled = !run.notified || !!run.paid;
    const label = document.getElementById('paymentRunLabel');
    if (label) label.textContent = run.label || '';
  };

  const rollbackIfNeeded = async () => {
    if (checking) return;
    checking = true;
    try {
      const before = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      const run = before.run || {};
      if (run.paid || !(run.reviewed || run.notified || run.initiated)) {
        paint(run);
        return;
      }
      const wasInitiated = !!run.initiated;
      const wasNotified = !!run.notified;
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('action', 'invalidate');
      const after = await fetchJson(`/customers/${customerId}/payment-workflow-v031`, {method: 'POST', body: fd});
      paint(after.run || {});
      suppressUntil = Date.now() + 500;
      toast(wasInitiated
        ? '金额已修改：请重新核对、重新通知客户并重新发起缴费'
        : wasNotified
          ? '金额已修改：原客户通知已失效，请重新核对并重新通知客户'
          : '金额已修改：请重新完成金额核对');
      // After stage 3 the primary script still has an in-memory initiated flag.
      // Reload once so subsequent edits do not repeat the high-risk warning.
      if (wasInitiated) setTimeout(() => window.location.reload(), 350);
    } catch (_) {
      // Main v0.3.1 handler remains the primary path. This layer is intentionally
      // silent on transient errors to avoid duplicate error toasts.
    } finally {
      checking = false;
    }
  };

  const schedule = () => {
    clearTimeout(timer);
    const delay = Math.max(520, suppressUntil - Date.now() + 80);
    timer = setTimeout(rollbackIfNeeded, delay);
  };

  const observe = node => {
    if (!node) return;
    new MutationObserver(() => {
      const pending = pendingNode?.textContent || '';
      const total = totalNode?.textContent || '';
      const changed = pending !== lastPending || total !== lastTotal;
      lastPending = pending;
      lastTotal = total;
      if (!changed) return;
      schedule();
    }).observe(node, {childList: true, subtree: true, characterData: true});
  };

  observe(pendingNode);
  if (totalNode !== pendingNode) observe(totalNode);
})();
