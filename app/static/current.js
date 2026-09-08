(() => {
  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 180); }, 1050);
  };

  const copyText = async (value) => {
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

  const selectEditor = (el) => {
    if (!el || el.readOnly || el.disabled) return;
    if (el.tagName === 'SELECT' || el.type === 'checkbox' || el.type === 'radio' || el.type === 'hidden') return;
    requestAnimationFrame(() => {
      try { el.select(); } catch (_) { try { el.setSelectionRange(0, el.value.length); } catch (_) {} }
    });
  };

  const formatDateDigits = (value) => {
    const d = String(value || '').replace(/\D/g, '').slice(0, 8);
    if (d.length <= 4) return d;
    if (d.length <= 6) return d.slice(0, 4) + '/' + d.slice(4);
    return d.slice(0, 4) + '/' + d.slice(4, 6) + '/' + d.slice(6);
  };

  // 首页横向标签。
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

  const workspace = document.querySelector('.v027-workspace');
  if (!workspace) return;

  // 所有编辑输入：单击全选。日期统一手输 YYYY/MM/DD。
  workspace.addEventListener('click', (e) => {
    const el = e.target.closest('input,textarea');
    if (el) selectEditor(el);
  });
  workspace.querySelectorAll('.manual-date').forEach(input => {
    input.autocomplete = 'off';
    input.addEventListener('input', () => { input.value = formatDateDigits(input.value); input.setCustomValidity(''); });
    input.addEventListener('blur', () => {
      if (!input.value) return input.setCustomValidity('');
      input.setCustomValidity(/^\d{4}\/\d{2}\/\d{2}$/.test(input.value) ? '' : '日期格式必须为 1900/07/07');
    });
  });

  // 客户功能标签：不跳转，只切换下方区域。
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

  // 表单提交后恢复原滚动位置。
  const scrollKey = `chen-scroll:${location.pathname}`;
  const saved = sessionStorage.getItem(scrollKey);
  if (saved) {
    try {
      const state = JSON.parse(saved);
      if (Date.now() - Number(state.at || 0) < 20000) {
        requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({top:Number(state.y || 0), behavior:'auto'})));
      }
    } catch (_) {}
    sessionStorage.removeItem(scrollKey);
  }
  const rememberScroll = () => sessionStorage.setItem(scrollKey, JSON.stringify({y:window.scrollY, at:Date.now()}));
  workspace.querySelectorAll('form[data-preserve-scroll]').forEach(form => form.addEventListener('submit', rememberScroll));

  // 业务多维筛选。
  const filterRoot = workspace.querySelector('[data-business-filters]');
  const businessRows = [...workspace.querySelectorAll('[data-business-row]')];
  const filterState = {type:'', due:'', mode:'', promo:'', invoice:''};
  const applyFilters = () => {
    let visible = 0;
    businessRows.forEach(row => {
      const ok = (!filterState.type || row.dataset.filterType === filterState.type)
        && (!filterState.due || row.dataset.filterDue === filterState.due)
        && (!filterState.mode || row.dataset.filterMode === filterState.mode)
        && (!filterState.promo || row.dataset.filterPromo === filterState.promo)
        && (!filterState.invoice || row.dataset.filterInvoice === filterState.invoice);
      row.hidden = !ok;
      if (ok) visible++;
    });
    const count = document.getElementById('businessVisibleCount');
    if (count) count.textContent = visible;
  };
  filterRoot?.addEventListener('click', e => {
    const btn = e.target.closest('[data-business-filter]');
    if (!btn) return;
    const group = btn.dataset.businessFilter;
    filterState[group] = btn.dataset.value || '';
    filterRoot.querySelectorAll(`[data-business-filter="${group}"]`).forEach(x => x.classList.toggle('active', x === btn));
    applyFilters();
  });
  workspace.querySelector('[data-business-filter-reset]')?.addEventListener('click', () => {
    Object.keys(filterState).forEach(k => filterState[k] = '');
    filterRoot?.querySelectorAll('[data-business-filter]').forEach(btn => btn.classList.toggle('active', !btn.dataset.value));
    applyFilters();
  });

  const workbench = workspace.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
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
    const sticky = workspace.querySelector('.workspace-sticky-top');
    return sticky ? sticky.getBoundingClientRect().bottom + 8 : 72;
  };
  const revealAndSelect = input => {
    if (!input) return;
    const row = input.closest('[data-payment-row]');
    if (!row) return selectAmount(input);
    const rect = row.getBoundingClientRect();
    const top = stickyBottom();
    const bottom = window.innerHeight - 20;
    let delta = 0;
    if (rect.top < top) delta = rect.top - top;
    else if (rect.bottom > bottom) delta = rect.bottom - bottom;
    if (Math.abs(delta) > 1) window.scrollBy({top:delta, behavior:'auto'});
    requestAnimationFrame(() => requestAnimationFrame(() => selectAmount(input)));
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
    const notify = workspace.querySelector('[data-payment-action="notify"]');
    if (notify && !notify.classList.contains('done')) notify.disabled = Number(data.pending || 0) !== 0;
  };
  const updateRow = (row, data) => {
    if (!row) return;
    row.dataset.confirmed = data.confirmed ? '1' : '0';
    row.dataset.mode = data.mode;
    const done = data.mode === 'fixed' || !!data.confirmed;
    row.classList.toggle('is-pending', !done);
    row.classList.toggle('is-confirmed', done);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      state.textContent = done ? '✓' : '○';
      state.classList.toggle('confirmed', done);
      state.classList.toggle('pending', !done);
    }
    const input = row.querySelector('.quick-amount');
    if (input && data.display_amount !== undefined) input.value = data.display_amount;
    const rule = row.querySelector('[data-fixed-toggle]');
    if (rule) {
      const fixed = data.mode === 'fixed';
      rule.textContent = fixed ? '固' : '变';
      rule.classList.toggle('is-fixed', fixed);
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
    return idx < 0 ? null : rows.slice(idx + 1).find(r => r.dataset.mode === 'variable' && r.dataset.confirmed === '0') || null;
  };
  const savePayment = async input => {
    if (!input || input.dataset.saving === '1') return;
    const row = input.closest('[data-payment-row]');
    const raw = input.value.trim().replace(',', '.');
    if (!row || !raw) { toast('金额不能为空，本月不缴请填0'); return selectAmount(input); }
    input.dataset.saving = '1'; row.classList.add('is-saving');
    const fd = new FormData(); fd.append('csrf', csrf); fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) { toast(data.error || '保存失败'); return selectAmount(input); }
      updateRow(row, data); updateSummary(data);
      const next = nextPendingBelow(row);
      if (next) revealAndSelect(next.querySelector('.quick-amount'));
      else {
        activeAmount = null; input.blur();
        toast(Number(data.pending || 0) ? `下方已无待核对项；全表还有 ${data.pending} 项` : '本月需核对项目已全部完成');
      }
    } catch (_) { toast('网络异常，未保存'); selectAmount(input); }
    finally { delete input.dataset.saving; row.classList.remove('is-saving'); }
  };

  if (workbench) {
    document.addEventListener('keydown', e => {
      const input = e.target.closest?.('.v027-workspace .quick-amount');
      if (!input || e.key !== 'Enter') return;
      e.preventDefault(); e.stopImmediatePropagation();
      savePayment(input);
    }, true);
    workbench.querySelectorAll('.quick-amount').forEach(input => {
      input.addEventListener('focus', () => { activeAmount = input; });
      input.addEventListener('click', () => selectAmount(input));
    });

    // 复制号码/账号时保持当前金额框全选与焦点。
    workbench.addEventListener('pointerdown', e => { if (e.target.closest('.identifier-copy')) e.preventDefault(); }, true);
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

    // 核对状态可撤销/恢复。
    workbench.addEventListener('click', async e => {
      const btn = e.target.closest('[data-review-toggle]');
      if (!btn) return;
      e.preventDefault(); e.stopPropagation();
      const row = btn.closest('[data-payment-row]');
      if (!row || btn.dataset.saving === '1') return;
      btn.dataset.saving = '1';
      const fd = new FormData(); fd.append('csrf', csrf);
      try {
        const r = await fetch(`/services/${row.dataset.serviceId}/payment-review-toggle`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.error || '核对状态修改失败');
        updateRow(row, data); updateSummary(data);
        toast(data.confirmed ? '已恢复核对' : '已撤销核对');
      } catch (_) { toast('网络异常，核对状态未修改'); }
      finally { delete btn.dataset.saving; }
    }, true);

    // 固定/变动切换。
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

    // 客户级默认属性。
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

    // 单条业务属性编辑；双击号码/账号直接打开并定位对应输入框。
    const attrDialog = document.getElementById('serviceAttributeDialog');
    const attrForm = attrDialog?.querySelector('[data-attribute-form]');
    let editingRow = null;
    const fields = {service_type:'serviceType', holder_name:'holderName', number:'number', account:'account', payment_interval_months:'paymentIntervalMonths', payment_method:'paymentMethod', invoice_type:'invoiceType', invoice_group_id:'invoiceGroupId', package_type:'packageType', last_payment_date:'lastPaymentDate', notes:'notes'};
    const openAttributes = (row, focusName = '') => {
      if (!row || !attrDialog || !attrForm) return;
      editingRow = row;
      attrForm.elements.service_id.value = row.dataset.serviceId;
      Object.entries(fields).forEach(([name,key]) => { if (attrForm.elements[name]) attrForm.elements[name].value = row.dataset[key] || ''; });
      attrDialog.showModal();
      if (focusName && attrForm.elements[focusName]) setTimeout(() => { attrForm.elements[focusName].focus(); attrForm.elements[focusName].select?.(); }, 30);
    };
    workbench.addEventListener('click', e => {
      const cell = e.target.closest('[data-open-attributes]');
      if (cell) openAttributes(cell.closest('[data-payment-row]'));
    });
    workbench.addEventListener('dblclick', e => {
      const id = e.target.closest('.identifier-copy');
      if (!id) return;
      e.preventDefault(); e.stopPropagation();
      openAttributes(id.closest('[data-payment-row]'), id.dataset.kind === '账号' ? 'account' : 'number');
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
        rememberScroll();
        attrDialog.close();
        location.reload();
      } catch (_) { toast('网络异常，属性未保存'); }
    });

    // 缴费业务拖动排序。
    const sortable = document.getElementById('paymentSortable');
    if (sortable) {
      let dragging = null, target = null, after = false;
      const clear = () => sortable.querySelectorAll('.drag-before,.drag-after,.drag-target').forEach(x => x.classList.remove('drag-before','drag-after','drag-target'));
      sortable.addEventListener('dragstart', e => {
        const handle = e.target.closest('.drag-handle');
        if (!handle) { e.preventDefault(); return; }
        dragging = handle.closest('[data-payment-row]');
        dragging?.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
      });
      sortable.addEventListener('dragover', e => {
        if (!dragging) return;
        e.preventDefault();
        const row = e.target.closest('[data-payment-row]');
        if (!row || row === dragging) return;
        clear(); target = row;
        const rect = row.getBoundingClientRect();
        after = e.clientY > rect.top + rect.height / 2;
        row.classList.add('drag-target', after ? 'drag-after' : 'drag-before');
      });
      sortable.addEventListener('drop', async e => {
        if (!dragging) return;
        e.preventDefault();
        if (target && target !== dragging) {
          sortable.insertBefore(dragging, after ? target.nextSibling : target);
          const ids = [...sortable.querySelectorAll('[data-payment-row]')].map(r => r.dataset.serviceId).join(',');
          const fd = new FormData(); fd.append('csrf', csrf); fd.append('service_ids', ids);
          try {
            const r = await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
            if (!r.ok) throw new Error(); toast('顺序已保存');
          } catch (_) { toast('顺序保存失败'); }
        }
        clear();
      });
      sortable.addEventListener('dragend', () => { dragging?.classList.remove('dragging'); clear(); dragging = target = null; });
    }

    // 当前客户独立保存列宽。
    const list = workspace.querySelector('[data-column-width-url]');
    if (list) {
      const vars = {attr:'--col-attr', number:'--col-number', account:'--col-account', amount:'--col-amount'};
      const limits = {attr:[110,520], number:[150,760], account:[160,820], amount:[120,320]};
      const current = key => parseInt(getComputedStyle(list).getPropertyValue(vars[key]), 10) || 180;
      const saveWidths = async () => {
        const fd = new FormData(); fd.append('csrf', csrf);
        Object.keys(vars).forEach(k => fd.append(k, String(current(k))));
        try {
          const r = await fetch(list.dataset.columnWidthUrl, {method:'POST', body:fd, credentials:'same-origin'});
          if (!r.ok) throw new Error(); toast('列宽已保存');
        } catch (_) { toast('列宽保存失败'); }
      };
      list.querySelectorAll('[data-resize-col]').forEach(handle => {
        handle.addEventListener('pointerdown', e => {
          e.preventDefault(); e.stopPropagation();
          const key = handle.dataset.resizeCol;
          const startX = e.clientX, startW = current(key), [minW,maxW] = limits[key];
          document.body.classList.add('is-resizing-columns');
          handle.setPointerCapture?.(e.pointerId);
          const move = ev => list.style.setProperty(vars[key], `${Math.max(minW, Math.min(maxW, Math.round(startW + ev.clientX - startX)))}px`);
          const up = ev => {
            handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); handle.removeEventListener('pointercancel', up);
            document.body.classList.remove('is-resizing-columns'); handle.releasePointerCapture?.(ev.pointerId); saveWidths();
          };
          handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', up); handle.addEventListener('pointercancel', up);
        });
      });
    }

    // 单位级缴费闭环。
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
  }

  // 同一号码下多个优惠拖动排序。
  workspace.querySelectorAll('[data-promo-sortable]').forEach(sortable => {
    let dragging = null, target = null, after = false;
    const group = sortable.closest('[data-promo-group]');
    const clear = () => sortable.querySelectorAll('.promo-drag-before,.promo-drag-after').forEach(x => x.classList.remove('promo-drag-before','promo-drag-after'));
    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.promo-drag-handle');
      if (!handle) { e.preventDefault(); return; }
      dragging = handle.closest('[data-promo-item]');
      dragging?.classList.add('promo-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    sortable.addEventListener('dragover', e => {
      if (!dragging) return;
      e.preventDefault();
      const row = e.target.closest('[data-promo-item]');
      if (!row || row === dragging) return;
      clear(); target = row;
      const rect = row.getBoundingClientRect();
      after = e.clientY > rect.top + rect.height / 2;
      row.classList.add(after ? 'promo-drag-after' : 'promo-drag-before');
    });
    sortable.addEventListener('drop', async e => {
      if (!dragging) return;
      e.preventDefault();
      if (target && target !== dragging) sortable.insertBefore(dragging, after ? target.nextSibling : target);
      clear();
      const ids = [...sortable.querySelectorAll('[data-promo-item]')].map(x => x.dataset.promoId).join(',');
      const fd = new FormData();
      fd.append('csrf', csrf); fd.append('group_key', group?.dataset.groupKey || ''); fd.append('promotion_ids', ids);
      try {
        const r = await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
        if (!r.ok) throw new Error(); toast('优惠顺序已保存');
      } catch (_) { toast('优惠顺序保存失败'); }
    });
    sortable.addEventListener('dragend', () => { dragging?.classList.remove('promo-dragging'); clear(); dragging = target = null; });
  });
})();
