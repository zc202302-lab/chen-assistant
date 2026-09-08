(() => {
  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 160); }, 1050);
  };

  const copyText = async value => {
    if (!value) return false;
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(value); return true; } catch (_) {}
    }
    const ta = document.createElement('textarea');
    ta.value = value; ta.readOnly = true;
    Object.assign(ta.style, {position:'fixed', opacity:'0', left:'-9999px'});
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove(); return ok;
  };

  // 首页：横向标签，只显示一个内容面板。
  const home = document.querySelector('[data-home-tabs]');
  if (home) {
    const buttons = [...home.querySelectorAll('[data-home-tab]')];
    const panels = [...home.querySelectorAll('[data-home-panel]')];
    const show = (name, updateUrl = true) => {
      if (!panels.some(p => p.dataset.homePanel === name)) name = 'tasks';
      buttons.forEach(b => b.classList.toggle('active', b.dataset.homeTab === name));
      panels.forEach(p => { p.hidden = p.dataset.homePanel !== name; });
      home.dataset.activeHomeTab = name;
      if (updateUrl) {
        const u = new URL(location.href);
        if (name === 'tasks') u.searchParams.delete('home'); else u.searchParams.set('home', name);
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      }
    };
    buttons.forEach(b => b.addEventListener('click', () => show(b.dataset.homeTab)));
    show(home.dataset.activeHomeTab || 'tasks', false);
  }

  const workspace = document.querySelector('.v025-workspace');
  if (!workspace) return;

  // 客户页横向标签，不跳转页面。
  const tabButtons = [...workspace.querySelectorAll('[data-customer-tab]')];
  const tabPanels = [...workspace.querySelectorAll('[data-customer-panel]')];
  const showTab = (name, updateUrl = true) => {
    if (!tabPanels.some(p => p.dataset.customerPanel === name)) name = 'payment';
    tabButtons.forEach(b => b.classList.toggle('active', b.dataset.customerTab === name));
    tabPanels.forEach(p => { p.hidden = p.dataset.customerPanel !== name; });
    workspace.dataset.activeTab = name;
    if (updateUrl) {
      const u = new URL(location.href);
      if (name === 'payment') u.searchParams.delete('tab'); else u.searchParams.set('tab', name);
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    }
  };
  tabButtons.forEach(b => b.addEventListener('click', () => showTab(b.dataset.customerTab)));
  workspace.querySelectorAll('[data-tab-open]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tabOpen)));
  showTab(workspace.dataset.activeTab || 'payment', false);

  const workbench = workspace.querySelector('[data-payment-workbench]');
  if (!workbench) return;
  const csrf = workbench.dataset.csrf || '';
  let activeAmount = null;

  const money = n => {
    const v = Math.round((Number(n) || 0) * 100) / 100;
    return '¥' + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''));
  };

  const selectAmount = input => {
    if (!input || !document.contains(input)) return;
    activeAmount = input;
    input.focus({preventScroll:true});
    try { input.setSelectionRange(0, input.value.length); } catch (_) { input.select?.(); }
  };

  const stickyBottom = () => {
    const sticky = document.querySelector('.workspace-sticky-top');
    return sticky ? sticky.getBoundingClientRect().bottom + 8 : 72;
  };

  const revealAndSelect = input => {
    if (!input) return;
    const row = input.closest('[data-payment-row]');
    if (!row) return selectAmount(input);
    const rect = row.getBoundingClientRect();
    const top = stickyBottom();
    const bottom = window.innerHeight - 18;
    let delta = 0;
    if (rect.top < top) delta = rect.top - top;
    else if (rect.bottom > bottom) delta = rect.bottom - bottom;
    if (Math.abs(delta) > 1) window.scrollBy({top: delta, behavior:'auto'});
    requestAnimationFrame(() => {
      selectAmount(input);
      requestAnimationFrame(() => selectAmount(input));
    });
  };

  const updateSummary = data => {
    const required = document.getElementById('requiredCount');
    const pending = document.getElementById('pendingCount');
    const total = document.getElementById('paymentGrandTotal');
    const readiness = document.getElementById('paymentReadiness');
    const txt = document.getElementById('paymentTxtButton');
    if (required && data.required !== undefined) required.textContent = data.required;
    if (pending && data.pending !== undefined) pending.textContent = data.pending;
    if (total && data.total !== undefined) total.textContent = money(data.total);
    if (readiness && data.pending !== undefined) readiness.textContent = data.pending ? `还有 ${data.pending} 项金额未核对` : '本月应缴业务金额已全部核对';
    if (txt && data.txt_ready !== undefined) {
      txt.setAttribute('aria-disabled', data.txt_ready ? 'false' : 'true');
      txt.classList.toggle('disabled', !data.txt_ready);
      txt.classList.toggle('primary', data.txt_ready);
      txt.classList.toggle('secondary', !data.txt_ready);
    }
    const run = workspace.querySelector('[data-payment-run]');
    const notify = run?.querySelector('[data-payment-action="notify"]');
    if (notify && !notify.classList.contains('done')) notify.disabled = Number(data.pending || 0) !== 0;
  };

  const updateRow = (row, data) => {
    if (!row) return;
    row.dataset.confirmed = data.confirmed ? '1' : '0';
    row.dataset.mode = data.mode;
    row.classList.toggle('is-pending', data.mode === 'variable' && !data.confirmed);
    row.classList.toggle('is-confirmed', data.mode === 'fixed' || !!data.confirmed);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      const done = data.mode === 'fixed' || !!data.confirmed;
      state.textContent = done ? '✓' : '○';
      state.classList.toggle('confirmed', done); state.classList.toggle('pending', !done);
    }
    const input = row.querySelector('.quick-amount');
    if (input && data.display_amount !== undefined) input.value = data.display_amount;
    const rule = row.querySelector('[data-fixed-toggle]');
    if (rule) {
      const fixed = data.mode === 'fixed';
      rule.textContent = fixed ? '固' : '变'; rule.classList.toggle('is-fixed', fixed);
    }
    const fb = row.querySelector('.amount-feedback');
    if (fb) {
      fb.innerHTML = '';
      if (data.delta !== null && data.delta !== undefined) {
        const em = document.createElement('em');
        em.className = 'delta-badge ' + (Number(data.delta) > 0 ? 'up' : 'down');
        em.textContent = (Number(data.delta) > 0 ? '+' : '') + String(Math.round(Number(data.delta) * 100) / 100);
        fb.appendChild(em);
      }
    }
  };

  const nextPendingBelow = row => {
    const rows = [...workbench.querySelectorAll('[data-payment-row]')];
    const idx = rows.indexOf(row);
    if (idx < 0) return null;
    return rows.slice(idx + 1).find(r => r.dataset.mode === 'variable' && r.dataset.confirmed === '0') || null;
  };

  const savePayment = async input => {
    if (!input || input.dataset.saving === '1') return;
    const raw = input.value.trim().replace(',', '.');
    if (!raw) { toast('金额不能为空，本月不缴请填0'); return selectAmount(input); }
    const row = input.closest('[data-payment-row]');
    if (!row) return;
    input.dataset.saving = '1'; row.classList.add('is-saving');
    const fd = new FormData(); fd.append('csrf', csrf); fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) { toast(data.error || '保存失败'); return selectAmount(input); }
      updateRow(row, data); updateSummary(data);
      const next = nextPendingBelow(row);
      if (next) {
        const nextInput = next.querySelector('.quick-amount');
        // This is intentionally immediate and deterministic: no smooth scrolling, no wrapping.
        revealAndSelect(nextInput);
      } else {
        activeAmount = null; input.blur();
        toast(Number(data.pending || 0) ? `下方已没有待核对项；全表还有 ${data.pending} 项未核对` : '本月需核对项目已全部完成');
      }
    } catch (_) { toast('网络异常，未保存'); selectAmount(input); }
    finally { delete input.dataset.saving; row.classList.remove('is-saving'); }
  };

  // v0.2.5 only loads this handler; older v0.2.3/v0.2.4 handlers are no longer loaded.
  document.addEventListener('keydown', e => {
    const input = e.target.closest?.('.v025-workspace .quick-amount');
    if (!input || e.key !== 'Enter') return;
    e.preventDefault(); e.stopImmediatePropagation();
    savePayment(input);
  }, true);

  workbench.querySelectorAll('.quick-amount').forEach(input => {
    input.addEventListener('focus', () => { activeAmount = input; });
    input.addEventListener('click', () => selectAmount(input));
  });

  // 复制号码/账号时保留当前金额编辑状态。
  workbench.addEventListener('pointerdown', e => {
    if (e.target.closest('.identifier-copy')) e.preventDefault();
  }, true);
  workbench.addEventListener('click', async e => {
    const id = e.target.closest('.identifier-copy');
    if (!id) return;
    e.preventDefault(); e.stopPropagation();
    const keep = activeAmount && document.contains(activeAmount) ? activeAmount : null;
    const ok = await copyText(id.dataset.copy || '');
    toast(ok ? `已复制${id.dataset.kind || ''}` : '复制失败');
    if (keep) selectAmount(keep);
  }, true);
  window.addEventListener('focus', () => { if (activeAmount) setTimeout(() => selectAmount(activeAmount), 40); });

  // 固定/变动快捷切换。
  workbench.addEventListener('click', async e => {
    const btn = e.target.closest('[data-fixed-toggle]');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    const row = btn.closest('[data-payment-row]');
    if (!row || btn.dataset.saving === '1') return;
    btn.dataset.saving = '1';
    const fd = new FormData(); fd.append('csrf', csrf);
    try {
      const r = await fetch(`/services/${row.dataset.serviceId}/toggle-fixed`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '切换失败');
      updateRow(row, data); updateSummary(data);
      toast(data.mode === 'fixed' ? '已设为固定缴费' : '已取消固定缴费');
    } catch (_) { toast('网络异常'); }
    finally { delete btn.dataset.saving; }
  }, true);

  // 客户级默认属性设置。
  const displayDialog = document.getElementById('displayAttributeDialog');
  const displayForm = displayDialog?.querySelector('[data-display-attribute-form]');
  workspace.querySelector('[data-display-settings]')?.addEventListener('click', () => displayDialog?.showModal());
  displayDialog?.querySelectorAll('[data-display-close]').forEach(b => b.addEventListener('click', () => displayDialog.close()));
  displayForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(displayForm);
    try {
      const r = await fetch(`/customers/${workspace.dataset.customerId}/display-attributes`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '设置失败');
      Object.entries(data.values || {}).forEach(([sid, vals]) => {
        const row = workbench.querySelector(`[data-payment-row][data-service-id="${sid}"]`);
        if (!row) return;
        const v1 = row.querySelector('[data-display-value="1"]'); const v2 = row.querySelector('[data-display-value="2"]');
        if (v1) v1.textContent = vals.v1; if (v2) v2.textContent = vals.v2;
      });
      displayDialog.close(); toast('已应用到该客户全部号码');
    } catch (_) { toast('网络异常，设置未保存'); }
  });

  // 单条业务完整属性编辑。
  const attrDialog = document.getElementById('serviceAttributeDialog');
  const attrForm = attrDialog?.querySelector('[data-attribute-form]');
  let editingRow = null;
  const fields = {
    service_type:'serviceType', holder_name:'holderName', number:'number', account:'account', payment_cycle:'paymentCycle',
    payment_interval_months:'paymentIntervalMonths', next_payment_period:'nextPaymentPeriod', payment_method:'paymentMethod',
    invoice_type:'invoiceType', invoice_group_id:'invoiceGroupId', package_type:'packageType', last_payment_date:'lastPaymentDate', notes:'notes'
  };
  workbench.addEventListener('click', e => {
    const cell = e.target.closest('[data-open-attributes]');
    if (!cell || !attrDialog || !attrForm) return;
    editingRow = cell.closest('[data-payment-row]');
    attrForm.elements.service_id.value = editingRow.dataset.serviceId;
    Object.entries(fields).forEach(([name,key]) => { if (attrForm.elements[name]) attrForm.elements[name].value = editingRow.dataset[key] || ''; });
    attrDialog.showModal();
  });
  attrDialog?.querySelectorAll('[data-attribute-close]').forEach(b => b.addEventListener('click', () => attrDialog.close()));
  attrForm?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!editingRow) return;
    const fd = new FormData(attrForm); const sid = fd.get('service_id'); fd.delete('service_id');
    try {
      const r = await fetch(`/services/${sid}/attributes`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '属性保存失败');
      attrDialog.close(); toast('属性已保存');
      // Attributes can affect due-cycle inclusion, so reload safely rather than leaving a stale workbench.
      location.reload();
    } catch (_) { toast('网络异常，属性未保存'); }
  });

  // 拖动排序：只显示落点，松手后再移动。
  const sortable = document.getElementById('paymentSortable');
  if (sortable) {
    let dragging = null, target = null, after = false;
    const clear = () => sortable.querySelectorAll('.drag-before,.drag-after,.drag-target').forEach(x => x.classList.remove('drag-before','drag-after','drag-target'));
    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.drag-handle');
      if (!handle) { e.preventDefault(); return; }
      dragging = handle.closest('[data-payment-row]');
      dragging?.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move';
    });
    sortable.addEventListener('dragover', e => {
      if (!dragging) return; e.preventDefault();
      const row = e.target.closest('[data-payment-row]'); if (!row || row === dragging) return;
      clear(); target = row; const rect = row.getBoundingClientRect(); after = e.clientY > rect.top + rect.height / 2;
      row.classList.add('drag-target', after ? 'drag-after' : 'drag-before');
    });
    sortable.addEventListener('drop', async e => {
      if (!dragging) return; e.preventDefault();
      if (target && target !== dragging) {
        sortable.insertBefore(dragging, after ? target.nextSibling : target);
        const ids = [...sortable.querySelectorAll('[data-payment-row]')].map(r => r.dataset.serviceId).join(',');
        const fd = new FormData(); fd.append('csrf', csrf); fd.append('service_ids', ids);
        try { const r = await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'}); if (!r.ok) throw new Error(); toast('顺序已保存'); }
        catch (_) { toast('顺序保存失败'); }
      }
      clear();
    });
    sortable.addEventListener('dragend', () => { dragging?.classList.remove('dragging'); clear(); dragging = target = null; });
  }

  // 单位级缴费闭环：金额核对 -> 已通知客户 -> 已完成缴费。
  workspace.querySelectorAll('[data-payment-action]').forEach(btn => btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    const action = btn.dataset.paymentAction;
    const fd = new FormData(); fd.append('csrf', csrf); fd.append('action', action);
    try {
      const r = await fetch(`/customers/${workspace.dataset.customerId}/payment-run`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '状态更新失败');
      const run = data.run || {};
      const label = document.getElementById('paymentRunLabel'); if (label) label.textContent = run.label || '';
      const notify = workspace.querySelector('[data-payment-action="notify"]'); const paid = workspace.querySelector('[data-payment-action="paid"]');
      if (notify) { notify.classList.toggle('done', !!run.notified); notify.disabled = !!run.notified || !run.ready; }
      if (paid) { paid.classList.toggle('done', !!run.paid); paid.disabled = !!run.paid || !run.notified; }
      toast(action === 'notify' ? '已标记通知客户' : '已完成本月缴费');
    } catch (_) { toast('网络异常，状态未更新'); }
  }));

  const filter = document.getElementById('serviceFilter');
  filter?.addEventListener('input', () => {
    const q = filter.value.trim().toLowerCase();
    workspace.querySelectorAll('[data-service-text]').forEach(card => { card.hidden = q && !card.dataset.serviceText.toLowerCase().includes(q); });
  });
})();
