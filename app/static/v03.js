(() => {
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
    setTimeout(() => el.classList.remove('show'), 1500);
  };

  const fetchJson = async (url, options = {}) => {
    const r = await fetch(url, {credentials: 'same-origin', ...options});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const postForm = async (url, fd) => fetchJson(url, {method: 'POST', body: fd});

  /* ---------------- 首页：高频客户搜索 ---------------- */
  const initHomeSearch = () => {
    const home = document.querySelector('.home-v024');
    if (!home || home.querySelector('[data-v03-home-search]')) return;
    const head = home.querySelector('.home-v024-head');
    if (!head) return;

    const wrap = document.createElement('section');
    wrap.className = 'v03-home-search';
    wrap.dataset.v03HomeSearch = '1';
    wrap.innerHTML = `
      <div class="v03-home-search-box">
        <span class="v03-search-icon">⌕</span>
        <input type="search" inputmode="search" autocomplete="off" autocapitalize="off"
               placeholder="搜索客户、集团编码、号码、账号、联系人…" aria-label="搜索客户" data-v03-search-input>
        <button type="button" class="v03-search-clear" data-v03-search-clear hidden>×</button>
      </div>
      <div class="v03-search-results" data-v03-search-results hidden></div>`;
    head.insertAdjacentElement('afterend', wrap);

    const input = wrap.querySelector('[data-v03-search-input]');
    const results = wrap.querySelector('[data-v03-search-results]');
    const clear = wrap.querySelector('[data-v03-search-clear]');
    let timer = 0;
    let seq = 0;
    let activeIndex = -1;

    const items = () => [...results.querySelectorAll('[data-v03-search-result]')];
    const highlight = index => {
      const list = items();
      if (!list.length) return;
      activeIndex = Math.max(0, Math.min(index, list.length - 1));
      list.forEach((el, i) => el.classList.toggle('active', i === activeIndex));
      list[activeIndex]?.scrollIntoView({block: 'nearest'});
    };

    const render = data => {
      results.innerHTML = '';
      activeIndex = -1;
      const list = data.results || [];
      if (!list.length) {
        const empty = document.createElement('div');
        empty.className = 'v03-search-empty';
        empty.textContent = data.q ? '没有找到匹配客户' : '暂无最近客户';
        results.appendChild(empty);
      } else {
        list.forEach(item => {
          const a = document.createElement('a');
          a.href = `/customers/${item.id}`;
          a.className = 'v03-search-result';
          a.dataset.v03SearchResult = '1';
          const name = document.createElement('strong');
          name.textContent = item.name || '未命名客户';
          const hint = document.createElement('small');
          hint.textContent = item.hint || item.group_code || item.tax_id || '打开客户';
          const arrow = document.createElement('span');
          arrow.textContent = '›';
          a.append(name, hint, arrow);
          results.appendChild(a);
        });
      }
      results.hidden = false;
    };

    const search = async () => {
      const mine = ++seq;
      const q = input.value.trim();
      clear.hidden = !q;
      try {
        const data = await fetchJson(`/api/v03/customers/search?q=${encodeURIComponent(q)}`);
        if (mine !== seq) return;
        render(data);
      } catch (_) {
        if (mine === seq) {
          results.innerHTML = '<div class="v03-search-empty">搜索暂不可用</div>';
          results.hidden = false;
        }
      }
    };

    const schedule = (delay = 120) => {
      clearTimeout(timer);
      timer = setTimeout(search, delay);
    };

    input.addEventListener('focus', () => schedule(0));
    input.addEventListener('input', () => schedule());
    input.addEventListener('keydown', e => {
      const list = items();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        highlight(activeIndex < 0 ? 0 : activeIndex + 1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        highlight(activeIndex < 0 ? list.length - 1 : activeIndex - 1);
      } else if (e.key === 'Enter' && list.length) {
        e.preventDefault();
        (list[activeIndex >= 0 ? activeIndex : 0])?.click();
      } else if (e.key === 'Escape') {
        results.hidden = true;
        input.blur();
      }
    });
    clear.addEventListener('click', () => {
      input.value = '';
      clear.hidden = true;
      input.focus();
      schedule(0);
    });
    document.addEventListener('pointerdown', e => {
      if (!wrap.contains(e.target)) results.hidden = true;
    });

    const headerSearch = document.querySelector('.search-link');
    headerSearch?.addEventListener('click', e => {
      e.preventDefault();
      input.focus();
      input.select();
      schedule(0);
    });
  };

  initHomeSearch();

  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const paymentList = document.getElementById('paymentSortable');
  const businessList = root.querySelector('[data-business-list]');

  /* ---------------- 表格：实时自动适配 ---------------- */
  const tableFont = count => count <= 4 ? 14 : count <= 6 ? 13 : count <= 8 ? 12 : count <= 10 ? 11 : 10;

  const fitPayment = () => {
    if (!paymentList) return;
    const count = paymentList.querySelectorAll('[data-payment-column-head]').length || 1;
    paymentList.classList.add('payment-auto-fit-v03');
    paymentList.style.setProperty('--v03-payment-count', String(count));
    paymentList.style.setProperty('--v03-payment-font', `${tableFont(count)}px`);
    paymentList.querySelectorAll('[data-payment-business-cell]').forEach(cell => {
      const value = cell.querySelector('[data-payment-cell-value]')?.textContent?.trim() || '—';
      cell.title = `${value} · 双击编辑`;
    });
  };

  const fitBusiness = () => {
    if (!businessList) return;
    const first = businessList.querySelector('[data-business-row] [data-business-attrs]');
    const count = first?.querySelectorAll('.business-attribute').length || 1;
    root.style.setProperty('--v03-business-count', String(count));
    root.style.setProperty('--v03-business-font', `${tableFont(count)}px`);
    businessList.querySelectorAll('[data-business-attrs]').forEach(grid => {
      grid.style.setProperty('--business-visible-count', String(count));
    });
  };

  const fitAll = () => { fitPayment(); fitBusiness(); };
  fitAll();
  if (paymentList) {
    new ResizeObserver(fitPayment).observe(paymentList);
    new MutationObserver(() => requestAnimationFrame(fitPayment)).observe(paymentList, {childList: true, subtree: true});
  }
  if (businessList) {
    new ResizeObserver(fitBusiness).observe(businessList);
    new MutationObserver(() => requestAnimationFrame(fitBusiness)).observe(businessList, {childList: true, subtree: true, characterData: true});
  }

  /* ---------------- 缴费显示属性：和业务一致的“数字序号” ---------------- */
  const paymentDialog = document.getElementById('paymentColumnsDialog');
  const paymentForm = paymentDialog?.querySelector('[data-payment-columns-form]');
  const paymentColumnList = paymentDialog?.querySelector('[data-payment-column-list]');
  const paymentSettingsTrigger = root.querySelector('[data-payment-columns-settings]');
  const AMOUNT = 'payment_amount';

  const paymentOptions = () => {
    try {
      return JSON.parse(paymentDialog?.dataset.paymentColumnOptions || '[]');
    } catch (_) {
      return [];
    }
  };
  const paymentKeys = () => (paymentList?.dataset.paymentColumnKeys || '').split(',').map(x => x.trim()).filter(Boolean);

  const renderPaymentColumnOrder = () => {
    if (!paymentDialog || !paymentColumnList) return;
    const current = paymentKeys();
    const order = new Map(current.map((key, index) => [key, index + 1]));
    const options = paymentOptions();
    const amount = options.find(x => x.key === AMOUNT) || {key: AMOUNT, label: '缴费金额'};
    const business = options.filter(x => x.key !== AMOUNT);
    const rows = [amount, ...business].sort((a, b) => {
      const ao = order.get(a.key) || 9999;
      const bo = order.get(b.key) || 9999;
      return ao - bo;
    });
    paymentColumnList.innerHTML = '';
    paymentColumnList.classList.add('v03-display-order-list');
    rows.forEach(option => {
      const row = document.createElement('label');
      row.className = 'v03-display-order-row';
      row.dataset.v03PaymentColumnKey = option.key;
      const name = document.createElement('span');
      name.textContent = option.label || option.key;
      if (option.key === AMOUNT) {
        const tag = document.createElement('small');
        tag.textContent = '必显';
        name.appendChild(tag);
      }
      const input = document.createElement('input');
      input.type = 'text';
      input.inputMode = 'numeric';
      input.autocomplete = 'off';
      input.placeholder = option.key === AMOUNT ? '必填序号' : '留空隐藏';
      input.value = order.has(option.key) ? String(order.get(option.key)) : '';
      input.dataset.v03PaymentOrder = '1';
      row.append(name, input);
      paymentColumnList.appendChild(row);
    });
    const help = paymentDialog.querySelector('.payment-columns-help-v0211');
    if (help) help.textContent = '填写显示序号的属性才会显示，并按数字从小到大排列；留空代表隐藏。缴费金额为缴费核心功能，必须填写序号。';
    paymentDialog.querySelector('[data-payment-column-add]')?.closest('div')?.setAttribute('hidden', '');
  };

  document.addEventListener('click', e => {
    const trigger = e.target.closest('[data-payment-columns-settings]');
    if (!trigger || !paymentDialog) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    renderPaymentColumnOrder();
    paymentDialog.showModal();
    paymentColumnList?.querySelector('input')?.focus();
  }, true);

  paymentForm?.addEventListener('submit', async e => {
    e.preventDefault();
    e.stopImmediatePropagation();
    const entries = [];
    const used = new Set();
    let hasAmount = false;
    for (const row of paymentColumnList.querySelectorAll('[data-v03-payment-column-key]')) {
      const key = row.dataset.v03PaymentColumnKey || '';
      const raw = row.querySelector('[data-v03-payment-order]')?.value.trim() || '';
      if (!raw) {
        if (key === AMOUNT) return toast('缴费金额必须填写显示序号');
        continue;
      }
      if (!/^\d{1,3}$/.test(raw) || Number(raw) < 1) return toast('显示序号请输入1到999的正整数');
      const n = Number(raw);
      if (used.has(n)) return toast(`显示序号 ${n} 重复`);
      used.add(n);
      entries.push({key, order: n});
      if (key === AMOUNT) hasAmount = true;
    }
    if (!hasAmount) return toast('缴费金额必须显示');
    entries.sort((a, b) => a.order - b.order);
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('columns_json', JSON.stringify(entries.map(x => x.key)));
    const submit = paymentForm.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await postForm(`/customers/${customerId}/payment-columns-v0211`, fd);
      paymentDialog.close();
      toast('缴费显示属性已保存');
      setTimeout(() => location.reload(), 120);
    } catch (err) {
      toast(err.message || '显示属性保存失败');
    } finally {
      submit.disabled = false;
    }
  }, true);

  /* ---------------- 缴费流程：上移 + 三步都支持有序撤回 ---------------- */
  let workflowState = null;
  let workflowMail = null;
  let invalidateTimer = 0;

  const titleLine = root.querySelector('.v023-payment-title-line');
  const oldRunCard = root.querySelector('.payment-run-card');
  const flow = document.createElement('div');
  flow.className = 'v03-payment-flow';
  flow.dataset.v03PaymentFlow = '1';
  ['review', 'notify', 'paid'].forEach((action, index) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'v03-flow-step';
    btn.dataset.v03FlowAction = action;
    btn.dataset.step = String(index + 1);
    flow.appendChild(btn);
  });
  if (titleLine) titleLine.appendChild(flow);
  oldRunCard?.remove();

  const footer = root.querySelector('.payment-footer');
  let emailButton = footer?.querySelector('[data-v03-send-email]');
  if (footer && !emailButton) {
    emailButton = document.createElement('button');
    emailButton.type = 'button';
    emailButton.className = 'secondary v03-email-button';
    emailButton.dataset.v03SendEmail = '1';
    footer.appendChild(emailButton);
  }

  const editControls = () => root.querySelectorAll('.quick-amount,[data-review-toggle],[data-fixed-toggle],[data-defer-payment-v0212]');
  const updateEditingLock = () => {
    const locked = !!(workflowState?.notified || workflowState?.paid);
    editControls().forEach(el => {
      if (el.matches('.quick-amount')) el.readOnly = locked;
      else el.disabled = locked;
    });
    root.classList.toggle('v03-payment-locked', locked);
  };

  const renderWorkflow = () => {
    if (!workflowState) return;
    const defs = [
      ['review', '金额核对', !!workflowState.reviewed],
      ['notify', '通知客户', !!workflowState.notified],
      ['paid', '完成缴费', !!workflowState.paid],
    ];
    defs.forEach(([action, label, done], index) => {
      const btn = flow.querySelector(`[data-v03-flow-action="${action}"]`);
      if (!btn) return;
      btn.classList.toggle('done', done);
      btn.classList.toggle('current', !done && ((action === 'review' && workflowState.ready) || (action === 'notify' && workflowState.reviewed) || (action === 'paid' && workflowState.notified)));
      btn.textContent = done ? `✓ ${label}` : `${index + 1} ${label}`;
      let disabled = false;
      let title = '';
      if (action === 'review') {
        disabled = done ? !!(workflowState.notified || workflowState.paid) : !workflowState.ready;
        title = done ? (disabled ? '请先撤回后续步骤' : '点击撤回金额核对') : (workflowState.ready ? '确认本月金额已核对' : '还有金额未核对');
      } else if (action === 'notify') {
        disabled = done ? !!workflowState.paid : !workflowState.reviewed;
        title = done ? (disabled ? '请先撤回完成缴费' : '点击撤回通知状态') : '标记已通知客户';
      } else {
        disabled = !done && !workflowState.notified;
        title = done ? '点击撤回完成缴费，并恢复缴费前周期状态' : '标记本月缴费完成';
      }
      btn.disabled = disabled;
      btn.title = title;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
    });

    if (emailButton) {
      const configured = !!workflowMail?.configured;
      const sent = !!workflowMail?.sent;
      emailButton.disabled = !configured || !workflowState.paid;
      emailButton.classList.toggle('sent', sent);
      emailButton.textContent = !configured ? '邮件未配置' : (sent ? '重新发送邮件' : '发送缴费邮件');
      if (configured) emailButton.title = `${workflowMail.recipient || ''}\n${workflowMail.subject_preview || ''}`;
      else emailButton.title = '在服务器 .env 中配置 SMTP 和收件人后即可使用';
    }
    updateEditingLock();
  };

  const loadWorkflow = async () => {
    if (!customerId || !flow.isConnected) return;
    try {
      const data = await fetchJson(`/customers/${customerId}/payment-run-v03`);
      workflowState = data.run || {};
      workflowMail = data.mail || {};
      renderWorkflow();
    } catch (err) {
      toast(err.message || '缴费流程状态读取失败');
    }
  };

  flow.addEventListener('click', async e => {
    const btn = e.target.closest('[data-v03-flow-action]');
    if (!btn || btn.disabled || !workflowState) return;
    const action = btn.dataset.v03FlowAction;
    if (action === 'paid' && workflowState.paid) {
      if (!confirm('撤回“完成缴费”并恢复本次缴费前的周期状态？')) return;
    }
    btn.disabled = true;
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('action', action);
    try {
      const data = await postForm(`/customers/${customerId}/payment-run`, fd);
      workflowState = data.run || workflowState;
      if (action === 'paid' && !workflowState.paid && workflowMail) {
        workflowMail.sent = false;
        workflowMail.sent_at = '';
      }
      renderWorkflow();
      toast(action === 'review'
        ? (workflowState.reviewed ? '金额核对已确认' : '已撤回金额核对')
        : action === 'notify'
          ? (workflowState.notified ? '已标记通知客户' : '已撤回通知状态')
          : (workflowState.paid ? '本月缴费已完成' : '已撤回完成缴费并恢复周期'));
    } catch (err) {
      toast(err.message || '状态更新失败');
      renderWorkflow();
    }
  });

  emailButton?.addEventListener('click', async () => {
    if (emailButton.disabled || !workflowMail?.configured) return;
    const message = `发送缴费TXT到：${workflowMail.recipient}\n主题：${workflowMail.subject_preview}\n\n确认发送？`;
    if (!confirm(message)) return;
    emailButton.disabled = true;
    emailButton.textContent = '发送中…';
    const fd = new FormData();
    fd.append('csrf', csrf);
    try {
      const data = await postForm(`/customers/${customerId}/payment-email-v03`, fd);
      workflowMail.sent = true;
      workflowMail.sent_at = new Date().toISOString();
      workflowMail.recipient = data.recipient || workflowMail.recipient;
      workflowMail.subject_preview = data.subject || workflowMail.subject_preview;
      renderWorkflow();
      toast('缴费TXT邮件已发送');
    } catch (err) {
      toast(err.message || '邮件发送失败');
      renderWorkflow();
    }
  });

  // 已做“金额核对”后再次修改金额，自动撤回核对状态，避免流程状态失真。
  workbench?.addEventListener('input', e => {
    if (!e.target.closest('.quick-amount') || !workflowState?.reviewed || workflowState.notified || workflowState.paid) return;
    clearTimeout(invalidateTimer);
    invalidateTimer = setTimeout(async () => {
      if (!workflowState?.reviewed || workflowState.notified || workflowState.paid) return;
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('action', 'review');
      try {
        const data = await postForm(`/customers/${customerId}/payment-run`, fd);
        workflowState = data.run || workflowState;
        renderWorkflow();
        toast('金额已修改，金额核对状态已自动撤回');
      } catch (_) {}
    }, 180);
  });

  /* ---------------- 延期：保留功能，但不依赖旧 v0212.js ---------------- */
  const installDeferral = () => {
    root.querySelectorAll('[data-payment-row]').forEach(row => {
      const actions = row.querySelector('.payment-row-actions-v0211');
      if (!actions || actions.querySelector('[data-defer-payment-v0212]')) return;
      const wrap = document.createElement('span');
      wrap.className = 'payment-defer-wrap-v0212';
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ghost tiny payment-defer-v0212';
      btn.dataset.deferPaymentV0212 = '1';
      btn.textContent = '延期';
      const input = document.createElement('input');
      input.type = 'text';
      input.inputMode = 'numeric';
      input.placeholder = '月';
      input.className = 'payment-defer-input-v0212';
      input.hidden = true;
      wrap.append(btn, input);
      actions.prepend(wrap);
      btn.addEventListener('click', () => {
        if (workflowState?.notified || workflowState?.paid) return toast('请先撤回后续缴费步骤再延期');
        input.hidden = !input.hidden;
        if (!input.hidden) {
          input.value = '1';
          input.focus();
          input.select();
        }
      });
      input.addEventListener('keydown', async e => {
        if (e.key === 'Escape') return void (input.hidden = true);
        if (e.key !== 'Enter') return;
        e.preventDefault();
        const months = Number.parseInt(input.value, 10);
        if (!Number.isInteger(months) || months < 1 || months > 120) return toast('延期月数请输入1到120之间的整数');
        input.disabled = true;
        const fd = new FormData();
        fd.append('csrf', csrf);
        fd.append('months', String(months));
        try {
          const data = await postForm(`/services/${row.dataset.serviceId}/defer-v0212`, fd);
          toast(data.label || '已延期');
          setTimeout(() => location.reload(), 120);
        } catch (err) {
          input.disabled = false;
          toast(err.message || '延期失败');
        }
      });
    });
    updateEditingLock();
  };
  installDeferral();
  if (paymentList) new MutationObserver(installDeferral).observe(paymentList, {childList: true, subtree: true});

  /* ---------------- 业务编辑：上方业务状态，下方业务属性保持原样 ---------------- */
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  const attrList = businessDialog?.querySelector('[data-global-attribute-list]');
  let editorMeta = new Map();

  const ensureBusinessStatusPanel = () => {
    if (!businessDialog || !businessForm) return null;
    let panel = businessDialog.querySelector('[data-v03-business-status-panel]');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.className = 'v03-business-status-panel';
    panel.dataset.v03BusinessStatusPanel = '1';
    panel.innerHTML = `
      <div class="v03-business-status-head">
        <b>业务状态</b>
        <button type="button" class="danger ghost small" data-v03-delete-service>删除此条数据</button>
      </div>
      <div class="v03-business-status-grid">
        <label><span>开停状态</span>
          <select data-v03-business-enabled>
            <option value="active">启用</option>
            <option value="inactive">停用</option>
          </select>
        </label>
        <div class="v03-payment-state-box"><span>缴费状态</span><strong data-v03-payment-state>—</strong></div>
      </div>`;
    const firstSection = businessForm.querySelector('.business-editor-section-v029');
    businessForm.insertBefore(panel, firstSection || businessForm.querySelector('.attribute-dialog-actions'));
    return panel;
  };

  const loadBusinessStatus = async () => {
    const sid = String(businessForm?.elements.service_id?.value || '').trim();
    if (!sid || !businessDialog?.open) return;
    const panel = ensureBusinessStatusPanel();
    try {
      const [runtime, attrs] = await Promise.all([
        fetchJson(`/services/${sid}/runtime-v0212`),
        fetchJson(`/services/${sid}/attributes-v028`),
      ]);
      if (sid !== String(businessForm.elements.service_id?.value || '').trim()) return;
      panel.querySelector('[data-v03-business-enabled]').value = runtime.status || 'active';
      panel.querySelector('[data-v03-payment-state]').textContent = runtime.schedule_state || '—';
      editorMeta = new Map((attrs.template || []).map(x => [String(x.key), x]));
    } catch (err) {
      toast(err.message || '业务状态读取失败');
    }
  };

  ensureBusinessStatusPanel();
  if (businessDialog) {
    new MutationObserver(() => {
      if (businessDialog.open) requestAnimationFrame(loadBusinessStatus);
    }).observe(businessDialog, {attributes: true, attributeFilter: ['open']});
  }

  const updateBusinessRows = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${CSS.escape(String(sid))}"]`);
      if (!card) return;
      const grid = card.querySelector('[data-business-attrs]');
      if (grid) {
        // Keep the modal opener and other unchanged cells connected. Replacing
        // them during save discards native focus restoration and pending gestures.
        const existing = new Map([...grid.querySelectorAll('.business-attribute')]
          .map(box => [box.dataset.attrKey, box]));
        const kept = new Set();
        (payload.preview_attributes || []).forEach((attr, index) => {
          const box = existing.get(attr.key) || document.createElement('div');
          box.classList.add('business-attribute');
          box.dataset.attrKey = attr.key || '';
          box.title = `${attr.label || '属性'}：${attr.value || '—'} · 双击编辑`;
          let small = box.querySelector('small');
          let strong = box.querySelector('strong');
          if (!small || !strong) {
            small = document.createElement('small');
            strong = document.createElement('strong');
            box.replaceChildren(small, strong);
          }
          if (small.textContent !== (attr.label || '属性')) small.textContent = attr.label || '属性';
          if (strong.textContent !== (attr.value || '—')) strong.textContent = attr.value || '—';
          if (grid.children[index] !== box) grid.insertBefore(box, grid.children[index] || null);
          kept.add(box);
        });
        [...grid.children].forEach(box => { if (!kept.has(box)) box.remove(); });
      }
      if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
    });
    fitBusiness();
  };

  let businessSaving = false;
  businessForm?.addEventListener('submit', async e => {
    e.preventDefault();
    e.stopImmediatePropagation();
    if (businessSaving) return;
    const sid = String(businessForm.elements.service_id?.value || '').trim();
    if (!sid || !attrList) return toast('未识别到当前业务');
    const template = [];
    const values = {};
    let invalid = false;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      const key = row.dataset.key || '';
      const label = row.querySelector('.attr-label')?.value.trim() || '';
      const kindSelect = row.querySelector('.attr-kind');
      const meta = editorMeta.get(key) || {};
      const kind = kindSelect?.disabled
        ? (kindSelect.dataset.fixedKind || meta.kind || 'text')
        : (kindSelect?.value || meta.kind || 'text');
      if (!key || !label) invalid = true;
      template.push({key, label, kind, core: !!meta.core});
      values[key] = row.querySelector('.attr-value')?.value || '';
    });
    if (invalid || !template.length) return toast('属性名称不能为空，且至少保留一个属性');

    const submit = businessForm.querySelector('button[type="submit"]');
    businessSaving = true;
    if (document.activeElement === submit) submit.blur();
    submit.disabled = true;
    try {
      const attrFd = new FormData();
      attrFd.append('csrf', businessForm.elements.csrf.value);
      attrFd.append('template_json', JSON.stringify(template));
      attrFd.append('values_json', JSON.stringify(values));
      const attrData = await postForm(`/services/${sid}/attributes-v028`, attrFd);
      editorMeta = new Map((attrData.template || []).map(x => [String(x.key), x]));

      const statusFd = new FormData();
      statusFd.append('csrf', businessForm.elements.csrf.value);
      statusFd.append('status', businessDialog.querySelector('[data-v03-business-enabled]')?.value || 'active');
      const statusData = await postForm(`/services/${sid}/status-v03`, statusFd);
      // Finish the native modal/focus lifecycle before refreshing any opener
      // in the business, payment or promotion panels.
      submit.disabled = false;
      businessDialog.close();
      updateBusinessRows(statusData.rows || {});
      root.dispatchEvent(new CustomEvent('chen:service-properties-updated', {detail:{rows:attrData.rows || {}}}));
      toast('业务已保存');
    } catch (err) {
      toast(err.message || '业务保存失败');
    } finally {
      businessSaving = false;
      submit.disabled = false;
    }
  }, true);

  businessDialog?.addEventListener('click', async e => {
    const del = e.target.closest('[data-v03-delete-service]');
    if (!del) return;
    e.preventDefault();
    const sid = String(businessForm?.elements.service_id?.value || '').trim();
    if (!sid) return toast('未识别到当前业务');
    if (!confirm('确定永久删除这条业务数据吗？关联的缴费记录和优惠记录也会一并删除，此操作不可恢复。')) return;
    del.disabled = true;
    const fd = new FormData();
    fd.append('csrf', businessForm.elements.csrf.value);
    try {
      await postForm(`/services/${sid}/delete-v0212`, fd);
      toast('业务已删除');
      setTimeout(() => location.reload(), 120);
    } catch (err) {
      del.disabled = false;
      toast(err.message || '删除失败');
    }
  }, true);

  loadWorkflow();
})();
