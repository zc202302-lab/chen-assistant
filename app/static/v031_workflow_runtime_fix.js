(() => {
  const root = document.querySelector('.v0211-workspace');
  const workbench = root?.querySelector('[data-payment-workbench]');
  const flow = root?.querySelector('[data-v031-payment-flow]');
  const customerId = root?.dataset.customerId || '';
  const csrf = workbench?.dataset.csrf || '';
  if (!root || !workbench || !flow || !customerId || !csrf) return;

  let state = null;
  let busy = false;
  let syncTimer = 0;

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
    if (!response.ok || data.ok === false) {
      throw new Error(data.detail || data.error || `请求失败（${response.status}）`);
    }
    return data;
  };

  const postAction = async action => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('action', action);
    return fetchJson(`/customers/${customerId}/payment-workflow-v031`, {method: 'POST', body: fd});
  };

  const setPaidLock = () => {
    const locked = !!state?.paid;
    root.querySelectorAll('.quick-amount,[data-review-toggle],[data-fixed-toggle],[data-defer-payment-v0212]').forEach(control => {
      if (control.matches('.quick-amount')) control.readOnly = locked;
      else control.disabled = locked;
    });
    root.classList.toggle('v03-payment-locked', locked);
  };

  const render = () => {
    if (!state) return;
    const defs = [
      ['review', '金额核对', !!state.reviewed],
      ['notify', '已通知客户', !!state.notified],
      ['initiate', '发起缴费', !!state.initiated],
      ['paid', '完成缴费', !!state.paid],
    ];

    defs.forEach(([action, label, done], index) => {
      const btn = flow.querySelector(`[data-v031-flow-action="${action}"]`);
      if (!btn) return;
      let disabled = busy;
      if (action === 'review') disabled ||= done ? !!(state.notified || state.initiated || state.paid) : !state.ready;
      else if (action === 'notify') disabled ||= done ? !!(state.initiated || state.paid) : !state.reviewed;
      else if (action === 'initiate') disabled ||= done ? !!state.paid : !state.notified;
      else disabled ||= !done && !state.initiated;

      btn.disabled = !!disabled;
      btn.textContent = done ? `✓ ${label}` : `${index + 1} ${label}`;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
      btn.classList.toggle('done', done);
      btn.classList.toggle('current', !done && (
        (action === 'review' && state.ready) ||
        (action === 'notify' && state.reviewed) ||
        (action === 'initiate' && state.notified) ||
        (action === 'paid' && state.initiated)
      ));
    });

    const image = root.querySelector('[data-v031-payment-image]');
    if (image) image.disabled = busy || !state.reviewed || !!state.paid;
    const foxmail = root.querySelector('[data-v03-foxmail-draft]');
    if (foxmail) foxmail.disabled = busy || !state.notified || !!state.paid;
    const label = document.getElementById('paymentRunLabel');
    if (label) label.textContent = state.label || '';
    setPaidLock();
  };

  const loadState = async ({quiet = false} = {}) => {
    try {
      const data = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      state = data.run || {};
      render();
      root.dataset.v031WorkflowReady = '1';
      return true;
    } catch (err) {
      root.dataset.v031WorkflowReady = '0';
      if (!quiet) toast(`缴费流程初始化失败：${err.message}`);
      return false;
    }
  };

  const confirmAction = action => {
    if (action === 'notify' && !state?.notified) return confirm('确认已经把本次缴费图片通过微信发送给客户？');
    if (action === 'initiate' && !state?.initiated) return confirm('确认已经在Foxmail中将缴费邮件发送给同事？');
    if (action === 'paid' && !state?.paid) return confirm('确认同事已收到邮件，并且你已经完成本次实际支付？');
    if (action === 'paid' && state?.paid) return confirm('撤回“完成缴费”并恢复本次缴费前的周期状态？');
    return true;
  };

  // Capture phase deliberately takes ownership before the older v0.3/v0.3.1 bubble listeners.
  flow.addEventListener('click', async event => {
    const btn = event.target.closest('[data-v031-flow-action]');
    if (!btn) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (btn.disabled || busy) return;

    if (!state) {
      const ok = await loadState();
      if (!ok) return;
    }
    const action = btn.dataset.v031FlowAction || '';
    if (!confirmAction(action)) return;

    busy = true;
    render();
    try {
      const data = await postAction(action);
      state = data.run || state;
      render();
      const messages = {
        review: state.reviewed ? '金额核对已确认' : '已撤回金额核对',
        notify: state.notified ? '已确认客户通知' : '已撤回客户通知',
        initiate: state.initiated ? '已确认发起缴费' : '已撤回发起缴费',
        paid: state.paid ? '本月缴费已完成' : '已撤回完成缴费并恢复缴费周期',
      };
      toast(messages[action] || '状态已更新');
    } catch (err) {
      toast(`缴费流程操作失败：${err.message}`);
      await loadState({quiet: true});
    } finally {
      busy = false;
      render();
    }
  }, true);

  // Amount saving is authoritative on the server. Re-read the four-stage state after Enter.
  workbench.addEventListener('keyup', event => {
    const input = event.target.closest?.('.quick-amount');
    if (!input || event.key !== 'Enter') return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => loadState({quiet: true}), 260);
  }, true);

  // The legacy v0.3 request may finish after this script and re-lock controls. Reassert
  // v0.3.1 state a few times during initial page settling, then normal actions own it.
  loadState();
  setTimeout(() => loadState({quiet: true}), 350);
  setTimeout(() => loadState({quiet: true}), 1000);
})();
