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

  const numberValue = value => {
    const parsed = Number(String(value ?? '').trim().replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : null;
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

      // payment-current is authoritative and invalidates in the same DB transaction.
      // If this GET arrived just before that transaction committed, retry briefly.
      if (stillOld && attempt < 6) {
        checking = false;
        timer = setTimeout(() => syncAfterSavedAmount(beforeFlags, attempt + 1), 80);
        return;
      }

      paint(run);
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
    const before = numberValue(original);
    const after = numberValue(current);
    if (before !== null && after !== null && Math.abs(before - after) <= 0.000001) return;
    if (before === null && after === null && original === current) return;

    const beforeFlags = {
      reviewed: root.querySelector('[data-v031-flow-action="review"]')?.getAttribute('aria-pressed') === 'true',
      notified: root.querySelector('[data-v031-flow-action="notify"]')?.getAttribute('aria-pressed') === 'true',
      initiated: root.querySelector('[data-v031-flow-action="initiate"]')?.getAttribute('aria-pressed') === 'true',
    };
    scheduleStateSync(beforeFlags);
  }, true);
})();
