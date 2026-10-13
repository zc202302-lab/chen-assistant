(() => {
  const copyText = async (value) => {
    if (!value) return false;
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(value); return true; } catch (_) {}
    }
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.readOnly = true;
    Object.assign(ta.style, {position:'fixed', opacity:'0', left:'-9999px'});
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    return ok;
  };

  const notifyError = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 180); }, 1200);
  };


  const formatDateDigits = (value) => {
    const d = String(value || '').replace(/\D/g, '').slice(0, 8);
    if (d.length <= 4) return d;
    if (d.length <= 6) return d.slice(0, 4) + '/' + d.slice(4);
    return d.slice(0, 4) + '/' + d.slice(4, 6) + '/' + d.slice(6);
  };

  const bindDateInput = (input) => {
    if (!input || input.dataset.dateBound === '1') return;
    input.dataset.dateBound = '1';
    input.autocomplete = 'off';
    input.addEventListener('input', () => { input.value = formatDateDigits(input.value); input.setCustomValidity(''); });
    input.addEventListener('blur', () => {
      if (!input.value) return input.setCustomValidity('');
      input.setCustomValidity(/^\d{4}\/\d{2}\/\d{2}$/.test(input.value) ? '' : '日期格式必须为 1900/07/07');
    });
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
      if (updateUrl) {
        const u = new URL(location.href);
        if (name === 'tasks') u.searchParams.delete('home'); else u.searchParams.set('home', name);
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      }
    };
    buttons.forEach(b => b.addEventListener('click', () => show(b.dataset.homeTab)));
    show(home.dataset.activeHomeTab || 'tasks', false);
  }

  const root = document.querySelector('.v028-workspace');
  if (!root) return;


  root.querySelectorAll('.manual-date').forEach(bindDateInput);

  // 客户横向标签。
  const tabButtons = [...root.querySelectorAll('[data-customer-tab]')];
  const tabPanels = [...root.querySelectorAll('[data-customer-panel]')];
  const showTab = (name, updateUrl = true) => {
    if (!tabPanels.some(p => p.dataset.customerPanel === name)) name = 'payment';
    tabButtons.forEach(b => b.classList.toggle('active', b.dataset.customerTab === name));
    tabPanels.forEach(p => { p.hidden = p.dataset.customerPanel !== name; });
    root.dataset.activeTab = name;
    if (updateUrl) {
      const u = new URL(location.href);
      if (name === 'payment') u.searchParams.delete('tab'); else u.searchParams.set('tab', name);
      history.replaceState(null, '', u.pathname + u.search + u.hash);
    }
  };
  tabButtons.forEach(b => b.addEventListener('click', () => showTab(b.dataset.customerTab)));
  root.querySelectorAll('[data-tab-open]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tabOpen)));
  showTab(root.dataset.activeTab || 'payment', false);

  // 需要传统提交的表单，返回后恢复滚动位置。
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
  root.querySelectorAll('form[data-preserve-scroll]').forEach(form => form.addEventListener('submit', rememberScroll));

  // 业务多维筛选。
  const filterRoot = root.querySelector('[data-business-filters]');
  const filterState = {type:'', due:'', mode:'', promo:'', invoice:''};
  const applyFilters = () => {
    let visible = 0;
    root.querySelectorAll('[data-business-row]').forEach(row => {
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
  root.querySelector('[data-business-filter-reset]')?.addEventListener('click', () => {
    Object.keys(filterState).forEach(k => filterState[k] = '');
    filterRoot?.querySelectorAll('[data-business-filter]').forEach(btn => btn.classList.toggle('active', !btn.dataset.value));
    applyFilters();
  });

  const workbench = root.querySelector('[data-payment-workbench]');
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
  const revealAndSelect = input => {
    if (!input) return;
    const row = input.closest('[data-payment-row]');
    if (!row) return selectAmount(input);
    const sticky = root.querySelector('.workspace-sticky-top');
    const top = (sticky ? sticky.getBoundingClientRect().bottom : 64) + 8;
    const rect = row.getBoundingClientRect();
    if (rect.top < top) window.scrollBy({top:rect.top - top, behavior:'auto'});
    else if (rect.bottom > window.innerHeight - 18) window.scrollBy({top:rect.bottom - (window.innerHeight - 18), behavior:'auto'});
    requestAnimationFrame(() => requestAnimationFrame(() => selectAmount(input)));
  };
  const updateSummary = data => {
    const required = document.getElementById('requiredCount');
    const pending = document.getElementById('pendingCount');
    const total = document.getElementById('paymentGrandTotal');
    const readiness = document.getElementById('paymentReadiness');
    const exports = ['paymentExcelButton', 'paymentTxtButton'].map(id => document.getElementById(id)).filter(Boolean);
    if (required && data.required !== undefined) required.textContent = data.required;
    if (pending && data.pending !== undefined) pending.textContent = data.pending;
    if (total && data.total !== undefined) total.textContent = money(data.total);
    if (readiness && data.pending !== undefined) readiness.textContent = data.pending ? `还有 ${data.pending} 项金额未核对` : '本月应缴业务金额已全部核对';
    if (data.txt_ready !== undefined) {
      exports.forEach(button => {
        button.setAttribute('aria-disabled', data.txt_ready ? 'false' : 'true');
        button.classList.toggle('disabled', !data.txt_ready);
        button.classList.toggle('primary', data.txt_ready);
        button.classList.toggle('secondary', !data.txt_ready);
      });
    }
    const notify = root.querySelector('[data-payment-action="notify"]');
    if (notify && !notify.classList.contains('done')) notify.disabled = Number(data.pending || 0) !== 0;
  };
  const updatePaymentRow = (row, data) => {
    if (!row) return;
    row.dataset.confirmed = data.confirmed ? '1' : '0';
    row.dataset.mode = data.mode;
    const done = !!data.confirmed;
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
    return idx < 0 ? null : rows.slice(idx + 1).find(r => r.dataset.confirmed === '0') || null;
  };
  const savePayment = async input => {
    if (!input || input.dataset.saving === '1') return;
    const row = input.closest('[data-payment-row]');
    const raw = input.value.trim().replace(',', '.');
    if (!row || !raw) return selectAmount(input);
    input.dataset.saving = '1'; row.classList.add('is-saving');
    const fd = new FormData(); fd.append('csrf', csrf); fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) { notifyError(data.error || '保存失败'); return selectAmount(input); }
      updatePaymentRow(row, data); updateSummary(data);
      const next = nextPendingBelow(row);
      if (next) {
        const account = String(next.dataset.paymentAccount || '').trim();
        if (account) await copyText(account);
        revealAndSelect(next.querySelector('.quick-amount'));
      } else {
        activeAmount = null;
        input.blur();
      }
    } catch (_) { notifyError('网络异常，未保存'); selectAmount(input); }
    finally { delete input.dataset.saving; row.classList.remove('is-saving'); }
  };

  if (workbench) {
    document.addEventListener('keydown', e => {
      const input = e.target.closest?.('.v028-workspace .quick-amount');
      if (!input || e.key !== 'Enter') return;
      e.preventDefault(); e.stopImmediatePropagation();
      savePayment(input);
    }, true);
    workbench.querySelectorAll('.quick-amount').forEach(input => {
      input.addEventListener('focus', () => { activeAmount = input; });

    });

    // 号码/账号复制不提示，并保持正在编辑的金额框。
    workbench.addEventListener('pointerdown', e => { if (e.target.closest('.identifier-copy')) e.preventDefault(); }, true);
    workbench.addEventListener('click', async e => {
      const id = e.target.closest('.identifier-copy');
      if (!id) return;
      e.preventDefault(); e.stopPropagation();
      const keep = activeAmount && document.contains(activeAmount) ? activeAmount : null;
      await copyText(id.dataset.copy || '');
      if (keep) selectAmount(keep);
    }, true);
    window.addEventListener('focus', () => { if (activeAmount) setTimeout(() => selectAmount(activeAmount), 40); });

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
        if (!r.ok || !data.ok) return notifyError(data.error || '核对状态修改失败');
        updatePaymentRow(row, data); updateSummary(data);
      } catch (_) { notifyError('网络异常'); }
      finally { delete btn.dataset.saving; }
    }, true);

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
        if (!r.ok || !data.ok) return notifyError(data.error || '切换失败');
        updatePaymentRow(row, data); updateSummary(data);
      } catch (_) { notifyError('网络异常'); }
      finally { delete btn.dataset.saving; }
    }, true);

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
          try { await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'}); } catch (_) {}
        }
        clear();
      });
      sortable.addEventListener('dragend', () => { dragging?.classList.remove('dragging'); clear(); dragging = target = null; });
    }

    // 四列宽度按客户保存。
    const list = root.querySelector('[data-column-width-url]');
    if (list) {
      const vars = {attr:'--col-attr', number:'--col-number', account:'--col-account', amount:'--col-amount'};
      const limits = {attr:[110,520], number:[150,760], account:[160,820], amount:[120,320]};
      const current = key => parseInt(getComputedStyle(list).getPropertyValue(vars[key]), 10) || 180;
      const saveWidths = async () => {
        const fd = new FormData(); fd.append('csrf', csrf);
        Object.keys(vars).forEach(k => fd.append(k, String(current(k))));
        try { await fetch(list.dataset.columnWidthUrl, {method:'POST', body:fd, credentials:'same-origin'}); } catch (_) {}
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

    root.querySelectorAll('[data-payment-action]').forEach(btn => btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      const fd = new FormData(); fd.append('csrf', csrf); fd.append('action', btn.dataset.paymentAction);
      try {
        const r = await fetch(`/customers/${root.dataset.customerId}/payment-run`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return notifyError(data.error || '状态更新失败');
        const run = data.run || {};
        const label = document.getElementById('paymentRunLabel'); if (label) label.textContent = run.label || '';
        const notify = root.querySelector('[data-payment-action="notify"]');
        const paid = root.querySelector('[data-payment-action="paid"]');
        if (notify) { notify.classList.toggle('done', !!run.notified); notify.disabled = !!run.notified || !run.ready; }
        if (paid) { paid.classList.toggle('done', !!run.paid); paid.disabled = !!run.paid || !run.notified; }
      } catch (_) { notifyError('网络异常'); }
    }));
  }

  // 缴费表“属性”两项由当前客户统一设置，可选全局模板中的任意属性。
  const displayDialog = document.getElementById('displayAttributeDialog');
  const displayForm = displayDialog?.querySelector('[data-display-attribute-form]');
  root.querySelector('[data-display-settings]')?.addEventListener('click', () => displayDialog?.showModal());
  displayDialog?.querySelectorAll('[data-display-close]').forEach(b => b.addEventListener('click', () => displayDialog.close()));
  displayForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(displayForm);
    try {
      const r = await fetch(`/customers/${root.dataset.customerId}/display-attributes`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return notifyError(data.error || '设置失败');
      Object.entries(data.values || {}).forEach(([sid, vals]) => {
        const row = workbench?.querySelector(`[data-payment-row][data-service-id="${sid}"]`);
        if (!row) return;
        const v1 = row.querySelector('[data-display-value="1"]');
        const v2 = row.querySelector('[data-display-value="2"]');
        if (v1) v1.textContent = vals.v1;
        if (v2) v2.textContent = vals.v2;
      });
      displayDialog.close();
    } catch (_) { notifyError('网络异常'); }
  });

  // 全局统一业务属性模板编辑器。
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  const attrList = businessDialog?.querySelector('[data-global-attribute-list]');
  let editorServiceId = null;
  let editorTemplate = [];
  let editorValues = {};
  let editorInvoiceGroups = [];
  let editorScrollY = 0;
  let newCounter = 0;

  const editorControl = (item, value) => {
    let el;
    if (item.kind === 'textarea') {
      el = document.createElement('textarea'); el.rows = 2; el.value = value || '';
    } else if (item.kind === 'invoice_group') {
      el = document.createElement('select');
      const none = document.createElement('option'); none.value = ''; none.textContent = '未分组'; el.appendChild(none);
      editorInvoiceGroups.forEach(g => { const o = document.createElement('option'); o.value = String(g.id); o.textContent = g.name; if (String(value || '') === String(g.id)) o.selected = true; el.appendChild(o); });
    } else {
      el = document.createElement('input'); el.type = 'text'; el.value = value || '';
      if (item.kind === 'integer') { el.inputMode = 'numeric'; el.pattern = '\\d{1,3}'; }
      if (item.kind === 'date') { el.placeholder = '2026-10-12'; el.classList.add('attribute-date'); el.autocomplete = 'off'; }
    }
    el.classList.add('attr-value');
    return el;
  };

  const renderEditor = () => {
    if (!attrList) return;
    attrList.innerHTML = '';
    editorTemplate.forEach(item => {
      const row = document.createElement('div');
      row.className = 'global-attribute-row-v028'; row.dataset.key = item.key;
      const handle = document.createElement('button'); handle.type = 'button'; handle.className = 'global-attribute-handle'; handle.draggable = true; handle.textContent = '⠿';
      const labelWrap = document.createElement('label'); labelWrap.textContent = '属性名称';
      const labelInput = document.createElement('input'); labelInput.className = 'attr-label'; labelInput.value = item.label || ''; labelWrap.appendChild(labelInput);
      const valueWrap = document.createElement('label'); valueWrap.textContent = '当前业务的值'; valueWrap.appendChild(editorControl(item, editorValues[item.key] || ''));
      const kindWrap = document.createElement('label'); kindWrap.textContent = '类型';
      const kind = document.createElement('select'); kind.className = 'attr-kind';
      [['text','文本'],['date','日期'],['textarea','长文本']].forEach(([v,t]) => { const o = document.createElement('option'); o.value=v; o.textContent=t; if ((item.kind || 'text')===v) o.selected=true; kind.appendChild(o); });
      if (item.core || item.kind === 'invoice_group' || item.kind === 'integer') { kind.disabled = true; kind.dataset.fixedKind = item.kind; }
      kindWrap.appendChild(kind);
      const del = document.createElement('button'); del.type='button'; del.className='global-attribute-delete'; del.textContent='×'; del.title='删除属性';
      row.append(handle, labelWrap, valueWrap, kindWrap, del);
      attrList.appendChild(row);
    });
  };

  const openBusinessEditor = async (serviceId) => {
    if (!businessDialog || !businessForm) return;
    editorScrollY = window.scrollY;
    try {
      const r = await fetch(`/services/${serviceId}/attributes-v028`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return notifyError(data.error || '读取业务属性失败');
      editorServiceId = serviceId;
      editorTemplate = (data.template || []).map(x => ({...x}));
      editorValues = {...(data.values || {})};
      editorInvoiceGroups = data.invoice_groups || [];
      businessForm.elements.service_id.value = serviceId;
      renderEditor();
      businessDialog.showModal();
      root.dispatchEvent(new CustomEvent('chen:service-editor-opened', {detail:{service_id:serviceId}}));
    } catch (_) { notifyError('网络异常'); }
  };

  root.addEventListener('click', e => {
    const btn = e.target.closest('[data-open-service-editor]');
    if (!btn) return;
    e.preventDefault();
    openBusinessEditor(btn.dataset.serviceId || btn.closest('[data-service-id]')?.dataset.serviceId);
  });
  root.addEventListener('dblclick', e => {
    const btn = e.target.closest('[data-promo-service-editor]');
    if (!btn) return;
    e.preventDefault();
    openBusinessEditor(btn.dataset.serviceId);
  });
  businessDialog?.querySelectorAll('[data-business-editor-close]').forEach(btn => btn.addEventListener('click', () => {
    businessDialog.close();
    requestAnimationFrame(() => window.scrollTo({top:editorScrollY, behavior:'auto'}));
  }));
  businessDialog?.addEventListener('close', () => requestAnimationFrame(() => window.scrollTo({top:editorScrollY, behavior:'auto'})));

  businessDialog?.querySelector('[data-add-global-attribute]')?.addEventListener('click', () => {
    const key = `new_${Date.now()}_${++newCounter}`;
    editorTemplate.push({key, label:'', kind:'text', core:false});
    editorValues[key] = '';
    renderEditor();
    const last = attrList?.lastElementChild?.querySelector('.attr-label');
    last?.focus();
  });

  attrList?.addEventListener('click', e => {
    const del = e.target.closest('.global-attribute-delete');
    if (!del) return;
    const row = del.closest('.global-attribute-row-v028');
    const key = row?.dataset.key;
    editorTemplate = editorTemplate.filter(x => x.key !== key);
    delete editorValues[key];
    renderEditor();
  });

  if (attrList) {
    let draggingKey = null, targetKey = null, after = false;
    const clear = () => attrList.querySelectorAll('.drag-before,.drag-after,.dragging').forEach(x => x.classList.remove('drag-before','drag-after','dragging'));
    attrList.addEventListener('dragstart', e => {
      const handle = e.target.closest('.global-attribute-handle');
      if (!handle) { e.preventDefault(); return; }
      const row = handle.closest('.global-attribute-row-v028');
      draggingKey = row?.dataset.key || null;
      row?.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    attrList.addEventListener('dragover', e => {
      if (!draggingKey) return;
      e.preventDefault();
      const row = e.target.closest('.global-attribute-row-v028');
      if (!row || row.dataset.key === draggingKey) return;
      clear();
      targetKey = row.dataset.key;
      const rect = row.getBoundingClientRect(); after = e.clientY > rect.top + rect.height/2;
      row.classList.add(after ? 'drag-after' : 'drag-before');
    });
    attrList.addEventListener('drop', e => {
      if (!draggingKey || !targetKey) return;
      e.preventDefault();
      const from = editorTemplate.findIndex(x => x.key === draggingKey);
      let to = editorTemplate.findIndex(x => x.key === targetKey);
      if (from < 0 || to < 0) return;
      const [item] = editorTemplate.splice(from, 1);
      if (from < to) to--;
      editorTemplate.splice(to + (after ? 1 : 0), 0, item);
      renderEditor();
      draggingKey = targetKey = null;
    });
    attrList.addEventListener('dragend', () => { clear(); draggingKey = targetKey = null; });
  }

  const escapeText = value => String(value ?? '');
  const updateBusinessRows = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${sid}"]`);
      if (card) {
        const grid = card.querySelector('[data-business-attrs]');
        if (grid) {
          grid.innerHTML = '';
          (payload.attributes || []).forEach(a => {
            const box = document.createElement('div'); box.className='business-attribute';
            const small=document.createElement('small'); small.textContent=a.label;
            const strong=document.createElement('strong'); strong.textContent=a.value || '—';
            box.append(small,strong); grid.appendChild(box);
          });
        }
        if (payload.service_type !== undefined) card.dataset.filterType = payload.service_type || '未分类';
        if (payload.invoice_group_id !== undefined) card.dataset.filterInvoice = payload.invoice_group_id || 'none';
        if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
      }
      const pay = workbench?.querySelector(`[data-payment-row][data-service-id="${sid}"]`);
      if (pay) {
        const v1 = pay.querySelector('[data-display-value="1"]'); const v2 = pay.querySelector('[data-display-value="2"]');
        if (v1) v1.textContent = payload.display1 || '—'; if (v2) v2.textContent = payload.display2 || '—';
        [['number','号码'],['account','账号']].forEach(([key,kind]) => {
          const btn = pay.querySelector(`[data-display="${key}"]`)?.closest('.dense-id');
          if (!btn) return;
          const b = btn.querySelector(`[data-display="${key}"]`); if (b) b.textContent = payload[key] || '—';
          if (payload[key]) { btn.classList.add('identifier-copy'); btn.classList.remove('dense-empty'); btn.dataset.copy=payload[key]; btn.dataset.kind=kind; }
          else { btn.classList.remove('identifier-copy'); btn.classList.add('dense-empty'); delete btn.dataset.copy; }
        });
      }
    });
    applyFilters();
  };

  const syncDisplayOptions = (template, selected1, selected2) => {
    if (!displayForm) return;
    const fill = (select, selected) => {
      if (!select) return;
      select.innerHTML = '';
      template.forEach(a => { const o=document.createElement('option'); o.value=a.key; o.textContent=a.label; if (a.key===selected) o.selected=true; select.appendChild(o); });
    };
    fill(displayForm.elements.display_attr_1, selected1);
    fill(displayForm.elements.display_attr_2, selected2);
  };

  businessForm?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!editorServiceId || !attrList) return;
    const template = [];
    const values = {};
    let invalid = false;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      const key = row.dataset.key;
      const label = row.querySelector('.attr-label')?.value.trim() || '';
      if (!label) invalid = true;
      const kindSelect = row.querySelector('.attr-kind');
      const original = editorTemplate.find(x => x.key === key) || {};
      const kind = kindSelect?.disabled ? (kindSelect.dataset.fixedKind || original.kind || 'text') : (kindSelect?.value || original.kind || 'text');
      template.push({key,label,kind,core:!!original.core});
      values[key] = row.querySelector('.attr-value')?.value || '';
    });
    if (invalid || !template.length) return notifyError('属性名称不能为空，且至少保留一个属性');
    const fd = new FormData();
    fd.append('csrf', businessForm.elements.csrf.value);
    fd.append('template_json', JSON.stringify(template));
    fd.append('values_json', JSON.stringify(values));
    try {
      const r = await fetch(`/services/${editorServiceId}/attributes-v028`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return notifyError(data.error || '保存失败');
      updateBusinessRows(data.rows || {});
      syncDisplayOptions(data.template || [], data.display_attr_1, data.display_attr_2);
      businessDialog.close();
      requestAnimationFrame(() => window.scrollTo({top:editorScrollY, behavior:'auto'}));
      root.dispatchEvent(new CustomEvent('chen:service-properties-updated', {detail:{rows:data.rows || {}}}));
    } catch (_) { notifyError('网络异常，未保存'); }
  });

  // 优惠：复制不提示。
  root.addEventListener('click', async e => {
    const btn = e.target.closest('[data-copy-silent]');
    if (!btn) return;
    e.preventDefault();
    await copyText(btn.dataset.copySilent || '');
  });

  // 优惠到期时间保存。续约到后续月份后会从行动区自动移除。
  root.querySelectorAll('[data-promo-expiry-form]').forEach(form => form.addEventListener('submit', async e => {
    e.preventDefault();
    const fd = new FormData(form);
    try {
      const r = await fetch(form.action, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return notifyError(data.error || '到期时间保存失败');
      root.dispatchEvent(new CustomEvent('chen:promotions-updated'));
      const item = form.closest('[data-promo-item]');
      const group = form.closest('[data-promo-group]');
      if (!data.visible) {
        item?.remove();
        if (group && !group.querySelector('[data-promo-item]')) group.remove();
      } else {
        const input = form.querySelector('[name="expiry_date"]'); if (input) input.value = data.expiry_date;
        const currentColumn = form.closest('.promo-column-v028')?.classList.contains('state-expired') ? 'expired' : 'soon';
        if (data.bucket !== currentColumn) {
          rememberScroll();
          location.reload();
        }
      }
    } catch (_) { notifyError('网络异常'); }
  }));

  // 同一号码、同一行动列内的多个优惠拖动排序。
  root.querySelectorAll('[data-promo-sortable]').forEach(sortable => {
    let dragging = null, target = null, after = false;
    const group = sortable.closest('[data-promo-group]');
    const clear = () => sortable.querySelectorAll('.drag-before,.drag-after,.dragging').forEach(x => x.classList.remove('drag-before','drag-after','dragging'));
    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.promo-drag-handle');
      if (!handle) { e.preventDefault(); return; }
      dragging = handle.closest('[data-promo-item]');
      dragging?.classList.add('dragging'); e.dataTransfer.effectAllowed='move';
    });
    sortable.addEventListener('dragover', e => {
      if (!dragging) return; e.preventDefault();
      const row = e.target.closest('[data-promo-item]'); if (!row || row===dragging) return;
      clear(); target=row; const rect=row.getBoundingClientRect(); after=e.clientY>rect.top+rect.height/2; row.classList.add(after?'drag-after':'drag-before');
    });
    sortable.addEventListener('drop', async e => {
      if (!dragging) return; e.preventDefault();
      if (target && target!==dragging) sortable.insertBefore(dragging, after?target.nextSibling:target);
      clear();
      const ids=[...sortable.querySelectorAll('[data-promo-item]')].map(x=>x.dataset.promoId).join(',');
      const fd=new FormData(); fd.append('csrf',csrf); fd.append('group_key',group?.dataset.groupKey||''); fd.append('promotion_ids',ids);
      try { await fetch(sortable.dataset.reorderUrl,{method:'POST',body:fd,credentials:'same-origin'}); } catch (_) {}
    });
    sortable.addEventListener('dragend',()=>{clear(); dragging=target=null;});
  });
})();
