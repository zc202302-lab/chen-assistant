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
  let notifyPrepared = false;
  let initiatePrepared = false;

  // v0.3.1 integrates these actions into stage 2 / stage 3.
  root.querySelectorAll('[data-v031-payment-image],[data-v03-foxmail-draft]').forEach(el => {
    el.hidden = true;
    el.setAttribute('aria-hidden', 'true');
  });

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
      const row = control.closest('[data-payment-row]');
      const fixedReview = control.matches('[data-review-toggle]') && row?.dataset.mode === 'fixed';
      const confirmed = row?.dataset.confirmed === '1';
      if (control.matches('.quick-amount')) {
        control.readOnly = locked;
      } else if (fixedReview) {
        // Fixed rows are normally automatic confirmations. If the amount itself
        // was edited, the server marks exactly that row unconfirmed until the
        // user clicks it once; do not overwrite that pending state here.
        control.disabled = locked || confirmed;
        control.title = confirmed
          ? '固定缴费金额自动确认，无需人工核对'
          : '金额刚刚修改，请重新确认这一条';
        control.textContent = confirmed ? '✓' : '○';
        control.classList.toggle('confirmed', confirmed);
        control.classList.toggle('pending', !confirmed);
        control.classList.toggle('v031-auto-confirmed', confirmed);
      } else {
        control.disabled = locked;
      }
    });
    root.querySelectorAll('[data-payment-row][data-mode="fixed"]').forEach(row => {
      const confirmed = row.dataset.confirmed === '1';
      row.classList.toggle('is-confirmed', confirmed);
      row.classList.toggle('is-pending', !confirmed);
      row.classList.toggle('v031-fixed-auto-confirmed', confirmed);
    });
    root.classList.toggle('v03-payment-locked', locked);
  };

  const normalizePrepared = () => {
    if (!state) return;
    // Preserve a prepared external action while its prerequisite remains valid.
    // Amount changes or a server-side rollback clear the prerequisite and therefore
    // also clear the transient "待确认" state.
    if (!state.reviewed || state.notified) notifyPrepared = false;
    if (!state.notified || state.initiated) initiatePrepared = false;
  };

  const render = () => {
    if (!state) return;
    normalizePrepared();
    const defs = [
      ['review', '金额核对', !!state.reviewed],
      ['notify', '通知客户', !!state.notified],
      ['initiate', '发起缴费', !!state.initiated],
      ['paid', '完成缴费', !!state.paid],
    ];

    defs.forEach(([action, label, done], index) => {
      const btn = flow.querySelector(`[data-v031-flow-action="${action}"]`);
      if (!btn) return;
      const awaiting = !done && ((action === 'notify' && notifyPrepared) || (action === 'initiate' && initiatePrepared));
      let disabled = busy;
      if (action === 'review') disabled ||= done ? !!(state.notified || state.initiated || state.paid) : !state.ready;
      else if (action === 'notify') disabled ||= done ? !!(state.initiated || state.paid) : !state.reviewed;
      else if (action === 'initiate') disabled ||= done ? !!state.paid : !state.notified;
      else disabled ||= !done && !state.initiated;

      btn.disabled = !!disabled;
      btn.textContent = done
        ? `✓ ${index + 1} ${label}`
        : awaiting
          ? `待确认 · ${index + 1} ${label}`
          : `${index + 1} ${label}`;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
      btn.classList.toggle('done', done);
      btn.classList.toggle('awaiting-confirm', awaiting);
      btn.classList.toggle('current', !done && !awaiting && (
        (action === 'review' && state.ready) ||
        (action === 'notify' && state.reviewed) ||
        (action === 'initiate' && state.notified) ||
        (action === 'paid' && state.initiated)
      ));

      if (action === 'review') {
        btn.title = done ? '当前所有应缴金额均已核对' : `还有 ${state.pending || 0} 项金额待确认`;
      } else if (action === 'notify') {
        btn.title = done
          ? '点击撤回客户通知状态'
          : awaiting
            ? '缴费图片已准备；发送微信后点击这里确认已发送'
            : '点击后自动生成并复制缴费图片';
      } else if (action === 'initiate') {
        btn.title = done
          ? '点击撤回发起缴费状态'
          : awaiting
            ? 'Foxmail写邮件窗口已打开；邮件发送后点击这里确认已发送'
            : '点击后直接打开Foxmail写邮件窗口';
      } else {
        btn.title = done ? '点击撤回完成缴费并恢复缴费前周期' : '确认已经完成实际支付';
      }
    });

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

  // Single public renderer/refresh owner. Auxiliary scripts may request a refresh,
  // but must not rewrite the four-stage button DOM themselves.
  window.ChenPaymentWorkflowRuntimeV031 = {
    refresh: () => loadState({quiet: true}),
    render: () => render(),
  };

  const saveAction = async action => {
    busy = true;
    render();
    try {
      const data = await postAction(action);
      state = data.run || state;
      if (action === 'notify') notifyPrepared = false;
      if (action === 'initiate') initiatePrepared = false;
      render();
      const messages = {
        review: state.reviewed ? '金额核对已确认' : '已撤回金额核对；固定金额仍保持自动已确认',
        notify: state.notified ? '已确认客户通知完成' : '已撤回客户通知',
        initiate: state.initiated ? '已确认缴费邮件已发送' : '已撤回发起缴费',
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
  };

  const prepareNotify = async () => {
    const actions = window.ChenPaymentWorkflowActionsV031;
    if (!actions?.prepareNotice) throw new Error('通知客户功能尚未加载完成，请刷新页面重试');
    busy = true;
    render();
    try {
      const result = await actions.prepareNotice();
      notifyPrepared = true;
      render();
      if (result?.mode === 'clipboard') {
        alert('缴费图片已生成并复制到剪贴板。\n\n请进入微信直接粘贴并发送给客户；发送完成后回到本页面，再点击“待确认 · 2 通知客户”确认已发送。\n\n在你确认前，本环节不会标记为完成。');
        toast('缴费图片已复制；发送后回来确认“通知客户”');
      } else {
        alert(`缴费图片已生成，但自动复制到剪贴板失败（${result?.warning || '浏览器限制'}）。\n\n系统已下载图片作为备用，请发送给客户；发送完成后回到本页面，再点击“待确认 · 2 通知客户”确认已发送。`);
        toast('缴费图片已下载备用；发送后回来确认“通知客户”');
      }
    } finally {
      busy = false;
      render();
    }
  };

  const prepareInitiate = async () => {
    const actions = window.ChenPaymentWorkflowActionsV031;
    if (!actions?.prepareInitiate) throw new Error('Foxmail功能尚未加载完成，请刷新页面重试');
    busy = true;
    render();
    try {
      await actions.prepareInitiate();
      initiatePrepared = true;
      render();
      alert('Foxmail写邮件窗口已打开，并已带入收件人、主题、正文和TXT附件。\n\n请在Foxmail中检查并发送；发送完成后回到本页面，再点击“待确认 · 3 发起缴费”确认已发送。\n\n在你确认前，本环节不会标记为完成。');
      toast('Foxmail已打开；发送邮件后回来确认“发起缴费”');
    } finally {
      busy = false;
      render();
    }
  };

  // Capture phase owns the four-stage workflow before older listeners can act.
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

    try {
      if (action === 'notify' && !state.notified) {
        if (!notifyPrepared) {
          await prepareNotify();
          return;
        }
        if (!confirm('确认缴费图片已经通过微信发送给客户？\n\n点击“确定”后，第2步才会标记为完成。')) return;
        await saveAction('notify');
        return;
      }

      if (action === 'initiate' && !state.initiated) {
        if (!initiatePrepared) {
          await prepareInitiate();
          return;
        }
        if (!confirm('确认缴费邮件已经在Foxmail中发送给同事？\n\n点击“确定”后，第3步才会标记为完成。')) return;
        await saveAction('initiate');
        return;
      }

      if (action === 'paid' && !state.paid) {
        if (!confirm('确认同事已收到邮件，并且你已经完成本次实际支付？')) return;
      }
      if (action === 'paid' && state.paid) {
        if (!confirm('撤回“完成缴费”并恢复本次缴费前的周期状态？')) return;
      }
      if (action === 'notify' && state.notified) {
        if (!confirm('确认撤回“通知客户”状态？')) return;
      }
      if (action === 'initiate' && state.initiated) {
        if (!confirm('确认撤回“发起缴费”状态？')) return;
      }

      await saveAction(action);
    } catch (err) {
      toast(`操作失败：${err.message || '未知错误'}`);
      busy = false;
      render();
    }
  }, true);

  // Amount saving is authoritative on the server. Re-read state after Enter.
  workbench.addEventListener('keyup', event => {
    const input = event.target.closest?.('.quick-amount');
    if (!input || event.key !== 'Enter') return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => loadState({quiet: true}), 260);
  }, true);

  // Row confirmation can now auto-complete stage 1. Refresh the workflow after
  // the row-level POST finishes so the top workflow reflects that immediately.
  workbench.addEventListener('click', event => {
    if (!event.target.closest?.('[data-review-toggle]')) return;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(() => loadState({quiet: true}), 260);
  }, true);

  loadState();
  setTimeout(() => loadState({quiet: true}), 350);
  setTimeout(() => loadState({quiet: true}), 1000);
})();
