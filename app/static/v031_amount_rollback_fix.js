(() => {
  const root = document.querySelector('.v0211-workspace');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const customerId = root?.dataset.customerId || '';
  if (!root || !workbench || !customerId) return;

  let timer = 0;
  let checking = false;

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    const el = document.querySelector('.app-toast');
    if (!el) return;
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  const fetchJson = async url => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const refreshWorkflowOwner = async () => {
    const owner = window.ChenPaymentWorkflowRuntimeV031;
    if (owner?.refresh) return owner.refresh();
    return false;
  };

  const syncAfterSavedAmount = async (beforeFlags, attempt = 0) => {
    if (checking && attempt === 0) return;
    checking = true;
    try {
      const data = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      const run = data.run || {};
      const stillOld = !!(
        (beforeFlags.initiated && run.initiated) ||
        (beforeFlags.notified && run.notified) ||
        (beforeFlags.reviewed && run.reviewed)
      );

      // payment-current invalidates workflow state in the same DB transaction.
      // A very fast GET can still race the response path, so retry briefly. This
      // helper never paints buttons itself; the four-stage runtime is the sole renderer.
      if (stillOld && attempt < 6) {
        checking = false;
        timer = setTimeout(() => syncAfterSavedAmount(beforeFlags, attempt + 1), 80);
        return;
      }

      await refreshWorkflowOwner();
      if (!stillOld && (beforeFlags.reviewed || beforeFlags.notified || beforeFlags.initiated)) {
        toast(beforeFlags.initiated
          ? '金额已修改：请重新核对、重新通知客户并重新发起缴费'
          : beforeFlags.notified
            ? '金额已修改：原客户通知已失效，请重新核对并重新通知客户'
            : '金额已修改：请重新完成金额核对');
      }
    } catch (_) {
      // 保存失败时不主动撤销流程；服务器只有在金额保存成功时才会使旧流程失效。
    } finally {
      checking = false;
    }
  };

  const scheduleStateSync = beforeFlags => {
    clearTimeout(timer);
    timer = setTimeout(() => syncAfterSavedAmount(beforeFlags), 120);
  };

  // 只跟踪用户真实修改金额并按 Enter 保存。
  workbench.addEventListener('focusin', e => {
    const input = e.target.closest?.('.quick-amount');
    if (!input) return;
    input.dataset.v031OriginalAmount = String(input.value ?? '');
  }, true);

  workbench.addEventListener('keyup', e => {
    const input = e.target.closest?.('.quick-amount');
    if (!input || e.key !== 'Enter' || input.readOnly) return;
    const original = input.dataset.v031OriginalAmount ?? String(input.value ?? '');
    const current = String(input.value ?? '');
    input.dataset.v031OriginalAmount = current;
    const before = Number(String(original).trim().replace(',', '.'));
    const after = Number(String(current).trim().replace(',', '.'));
    if (Number.isFinite(before) && Number.isFinite(after) && Math.abs(before - after) <= 0.000001) return;
    if (!Number.isFinite(before) && !Number.isFinite(after) && original === current) return;

    const beforeFlags = {
      reviewed: root.querySelector('[data-v031-flow-action="review"]')?.getAttribute('aria-pressed') === 'true',
      notified: root.querySelector('[data-v031-flow-action="notify"]')?.getAttribute('aria-pressed') === 'true',
      initiated: root.querySelector('[data-v031-flow-action="initiate"]')?.getAttribute('aria-pressed') === 'true',
    };
    scheduleStateSync(beforeFlags);
  }, true);
})();
