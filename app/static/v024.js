(() => {
  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 160); }, 950);
  };

  const copyText = async value => {
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

  // Homepage v0.2.4: horizontal tabs, one panel visible at a time.
  const home = document.querySelector('[data-home-tabs]');
  if (home) {
    const buttons = [...home.querySelectorAll('[data-home-tab]')];
    const panels = [...home.querySelectorAll('[data-home-panel]')];
    const showHome = (name, updateUrl = true) => {
      if (!panels.some(p => p.dataset.homePanel === name)) name = 'tasks';
      buttons.forEach(b => b.classList.toggle('active', b.dataset.homeTab === name));
      panels.forEach(p => { p.hidden = p.dataset.homePanel !== name; });
      home.dataset.activeHomeTab = name;
      if (updateUrl) {
        const u = new URL(location.href);
        if (name === 'tasks') u.searchParams.delete('home');
        else u.searchParams.set('home', name);
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      }
    };
    buttons.forEach(b => b.addEventListener('click', () => showHome(b.dataset.homeTab)));
    showHome(home.dataset.activeHomeTab || 'tasks', false);
  }

  const workspace = document.querySelector('.v023-workspace');
  if (!workspace) return;
  const workbench = workspace.querySelector('[data-payment-workbench]');
  if (!workbench) return;
  const csrf = workbench.dataset.csrf || '';
  let activeAmount = null;

  const money = n => {
    const v = Math.round((Number(n) || 0) * 100) / 100;
    return '¥' + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''));
  };

  const selectAmount = input => {
    if (!input) return;
    activeAmount = input;
    input.focus({preventScroll:true});
    requestAnimationFrame(() => {
      try { input.setSelectionRange(0, input.value.length); }
      catch (_) { input.select?.(); }
    });
  };

  const keepRowVisible = row => {
    if (!row) return;
    const sticky = document.querySelector('.workspace-sticky-top');
    const topLimit = sticky ? sticky.getBoundingClientRect().bottom + 8 : 72;
    const bottomLimit = window.innerHeight - 18;
    const rect = row.getBoundingClientRect();
    let delta = 0;
    if (rect.top < topLimit) delta = rect.top - topLimit;
    else if (rect.bottom > bottomLimit) delta = rect.bottom - bottomLimit;
    if (Math.abs(delta) > 1) window.scrollBy({top: delta, left: 0, behavior: 'auto'});
  };

  const focusAmountStable = input => {
    if (!input) return;
    const row = input.closest('[data-payment-row]');
    // Focus must never invoke browser auto-scroll. We place the row ourselves relative to the sticky header.
    selectAmount(input);
    requestAnimationFrame(() => {
      keepRowVisible(row);
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
    if (readiness && data.required !== undefined && data.pending !== undefined) {
      readiness.textContent = data.pending
        ? `需核对 ${data.required} 项，其中还有 ${data.pending} 项未核对`
        : `需核对 ${data.required} 项，已全部核对`;
    }
    if (txt && data.txt_ready !== undefined) {
      txt.setAttribute('aria-disabled', data.txt_ready ? 'false' : 'true');
      txt.classList.toggle('disabled', !data.txt_ready);
      txt.classList.toggle('primary', data.txt_ready);
      txt.classList.toggle('secondary', !data.txt_ready);
    }
  };

  const updateRow = (row, data) => {
    if (!row) return;
    row.dataset.confirmed = data.confirmed ? '1' : '0';
    row.dataset.mode = data.mode;
    row.dataset.changed = data.delta === null || data.delta === undefined ? '0' : '1';
    row.dataset.zero = data.confirmed && Number(data.amount) === 0 ? '1' : '0';
    row.classList.toggle('is-pending', data.mode === 'variable' && !data.confirmed);
    row.classList.toggle('is-confirmed', data.mode === 'fixed' || !!data.confirmed);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      const done = data.mode === 'fixed' || !!data.confirmed;
      state.textContent = done ? '✓' : '○';
      state.classList.toggle('confirmed', done);
      state.classList.toggle('pending', !done);
      state.title = done ? '本月已确认' : '本月待核对';
    }
    const input = row.querySelector('.quick-amount');
    if (input && data.display_amount !== undefined) {
      input.value = data.display_amount;
      input.dataset.lastSaved = input.value;
    }
    const rule = row.querySelector('[data-fixed-toggle]');
    if (rule) {
      const fixed = data.mode === 'fixed';
      rule.textContent = fixed ? '固' : '变';
      rule.classList.toggle('is-fixed', fixed);
      rule.title = fixed ? '固定金额，点击取消固定' : '变动金额，点击设为固定';
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

  // Important: only search downward. Never wrap to an earlier row, which previously looked like a random jump.
  const nextPendingBelow = row => {
    const rows = [...workbench.querySelectorAll('[data-payment-row]')];
    const idx = rows.indexOf(row);
    if (idx < 0) return null;
    return rows.slice(idx + 1).find(r => r.dataset.mode === 'variable' && r.dataset.confirmed === '0') || null;
  };

  const savePayment = async input => {
    if (!input || input.dataset.saving === '1') return;
    const raw = input.value.trim().replace(',', '.');
    if (!raw) {
      toast('金额不能为空，本月不缴请填0');
      return selectAmount(input);
    }
    const row = input.closest('[data-payment-row]');
    input.dataset.saving = '1';
    row?.classList.add('is-saving');
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, {
        method:'POST', body:fd, credentials:'same-origin'
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        toast(data.error || '保存失败');
        return selectAmount(input);
      }
      updateRow(row, data);
      updateSummary(data);

      const next = nextPendingBelow(row);
      if (next) {
        const nextInput = next.querySelector('.quick-amount');
        focusAmountStable(nextInput);
      } else {
        if (Number(data.pending || 0) === 0) {
          activeAmount = null;
          input.blur();
          toast('本月需核对项目已全部完成');
        } else {
          activeAmount = null;
          input.blur();
          toast(`已到列表末尾，上方还有 ${data.pending} 项未核对`);
        }
      }
    } catch (_) {
      toast('网络异常，未保存');
      selectAmount(input);
    } finally {
      delete input.dataset.saving;
      row?.classList.remove('is-saving');
    }
  };

  // Enter is captured before older handlers so there is exactly one save-and-next action.
  document.addEventListener('keydown', e => {
    const input = e.target.closest?.('.v023-workspace .quick-amount');
    if (!input || e.key !== 'Enter') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    savePayment(input);
  }, true);

  workbench.querySelectorAll('.quick-amount').forEach(input => {
    input.dataset.lastSaved = input.value;
    input.addEventListener('focus', () => { activeAmount = input; });
    input.addEventListener('click', () => selectAmount(input));
  });

  // Copying a number/account must not steal the selected amount field after Enter.
  workbench.addEventListener('pointerdown', e => {
    if (e.target.closest('.identifier-copy')) e.preventDefault();
  }, true);

  workbench.addEventListener('click', async e => {
    const id = e.target.closest('.identifier-copy');
    if (!id) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const row = id.closest('[data-payment-row]');
    const keep = activeAmount && document.contains(activeAmount)
      ? activeAmount
      : row?.querySelector('.quick-amount');
    const ok = await copyText(id.dataset.copy || '');
    id.classList.add('copied');
    setTimeout(() => id.classList.remove('copied'), 450);
    toast(ok ? `已复制${id.dataset.kind || ''}` : '复制失败');
    if (keep) selectAmount(keep);
  }, true);

  window.addEventListener('focus', () => {
    if (activeAmount && document.contains(activeAmount)) setTimeout(() => selectAmount(activeAmount), 50);
  });

  workbench.addEventListener('click', async e => {
    const btn = e.target.closest('[data-fixed-toggle]');
    if (!btn) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const row = btn.closest('[data-payment-row]');
    if (!row || btn.dataset.saving === '1') return;
    btn.dataset.saving = '1';
    const fd = new FormData();
    fd.append('csrf', csrf);
    try {
      const r = await fetch(`/services/${row.dataset.serviceId}/toggle-fixed`, {
        method:'POST', body:fd, credentials:'same-origin'
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '切换失败');
      updateRow(row, data);
      updateSummary(data);
      toast(data.mode === 'fixed' ? '已设为固定缴费' : '已取消固定缴费');
    } catch (_) {
      toast('网络异常');
    } finally {
      delete btn.dataset.saving;
    }
  }, true);

  // v0.2.4 drag: show a stable insertion line while dragging; move the row only once on drop.
  const sortable = document.getElementById('paymentSortable');
  if (sortable) {
    let dragging = null;
    let target = null;
    let placeAfter = false;
    const clearTarget = () => {
      sortable.querySelectorAll('.drag-before,.drag-after,.drag-target').forEach(x => {
        x.classList.remove('drag-before','drag-after','drag-target');
      });
      target = null;
    };
    const saveOrder = async () => {
      const ids = [...sortable.querySelectorAll('[data-payment-row]')].map(r => r.dataset.serviceId).join(',');
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('service_ids', ids);
      try {
        const r = await fetch(sortable.dataset.reorderUrl, {method:'POST',body:fd,credentials:'same-origin'});
        if (!r.ok) throw new Error();
        toast('顺序已保存');
      } catch (_) {
        toast('顺序保存失败，刷新后可能恢复');
      }
    };

    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.drag-handle');
      if (!handle) {
        e.preventDefault();
        return;
      }
      dragging = handle.closest('[data-payment-row]');
      if (!dragging) return;
      dragging.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', dragging.dataset.serviceId || '');
      try { e.dataTransfer.setDragImage(dragging, 24, 20); } catch (_) {}
    });

    sortable.addEventListener('dragover', e => {
      if (!dragging) return;
      e.preventDefault();
      const row = e.target.closest('[data-payment-row]');
      if (!row || row === dragging) return;
      const rect = row.getBoundingClientRect();
      const after = e.clientY >= rect.top + rect.height / 2;
      if (target === row && placeAfter === after) return;
      clearTarget();
      target = row;
      placeAfter = after;
      row.classList.add('drag-target', after ? 'drag-after' : 'drag-before');
    });

    sortable.addEventListener('drop', e => {
      if (!dragging) return;
      e.preventDefault();
      if (target && target !== dragging) {
        if (placeAfter) sortable.insertBefore(dragging, target.nextSibling);
        else sortable.insertBefore(dragging, target);
        saveOrder();
      }
      clearTarget();
    });

    sortable.addEventListener('dragend', () => {
      dragging?.classList.remove('dragging');
      clearTarget();
      dragging = null;
    });
  }

  // Per-row property dialog edits the row's complete attributes only.
  // Default displayed properties are intentionally hidden here and configured once from the header.
  const dialog = document.getElementById('serviceAttributeDialog');
  const attrForm = dialog?.querySelector('[data-attribute-form]');
  let editingRow = null;
  const fieldMap = {
    service_type:'serviceType', holder_name:'holderName', number:'number', account:'account',
    payment_cycle:'paymentCycle', payment_method:'paymentMethod', invoice_type:'invoiceType',
    invoice_group_id:'invoiceGroupId', package_type:'packageType', last_payment_date:'lastPaymentDate', notes:'notes'
  };

  const openAttributes = row => {
    if (!dialog || !attrForm || !row) return;
    editingRow = row;
    attrForm.elements.service_id.value = row.dataset.serviceId;
    Object.entries(fieldMap).forEach(([name,key]) => {
      const el = attrForm.elements[name];
      if (el) el.value = row.dataset[key] || '';
    });
    // Keep the obsolete per-row display fields aligned with the customer-wide choice, but do not show them.
    if (attrForm.elements.display_attr_1) attrForm.elements.display_attr_1.value = row.dataset.displayAttr1 || 'service_type';
    if (attrForm.elements.display_attr_2) attrForm.elements.display_attr_2.value = row.dataset.displayAttr2 || 'holder_name';
    dialog.showModal();
  };

  workbench.addEventListener('click', e => {
    const cell = e.target.closest('[data-open-attributes]');
    if (!cell) return;
    e.preventDefault();
    openAttributes(cell.closest('[data-payment-row]'));
  });
  dialog?.querySelectorAll('[data-attribute-close]').forEach(b => b.addEventListener('click', () => dialog.close()));
  dialog?.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });

  attrForm?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!editingRow) return;
    const fd = new FormData(attrForm);
    const sid = fd.get('service_id');
    fd.delete('service_id');
    try {
      const r = await fetch(`/services/${sid}/attributes`, {method:'POST',body:fd,credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '属性保存失败');
      Object.entries(fieldMap).forEach(([name,key]) => {
        if (data[name] !== undefined) editingRow.dataset[key] = data[name] ?? '';
      });
      const n = editingRow.querySelector('[data-display="number"]');
      const a = editingRow.querySelector('[data-display="account"]');
      if (n) n.textContent = data.number || '—';
      if (a) a.textContent = data.account || '—';
      const nb = n?.closest('.dense-id');
      if (nb) {
        nb.dataset.copy = data.number || '';
        nb.classList.toggle('identifier-copy', !!data.number);
        nb.classList.toggle('dense-empty', !data.number);
      }
      const ab = a?.closest('.dense-id');
      if (ab) {
        ab.dataset.copy = data.account || '';
        ab.classList.toggle('identifier-copy', !!data.account);
        ab.classList.toggle('dense-empty', !data.account);
      }
      dialog.close();
      // The first-column values may depend on any edited property; reload keeps them exact.
      location.reload();
    } catch (_) {
      toast('网络异常，属性未保存');
    }
  });

  // Customer-wide first-column display settings, opened from the single header label "属性".
  const header = workbench.querySelector('.v023-payment-header');
  const rows = [...workbench.querySelectorAll('[data-payment-row]')];
  const firstRow = rows[0] || null;
  const attrOptions = [
    ['service_type','类型'], ['holder_name','姓名/属性'], ['invoice_group','发票组'],
    ['payment_cycle','缴费周期'], ['payment_method','付款方式'], ['invoice_type','发票类型'],
    ['package_type','套餐类型'], ['last_payment_date','上次缴费'], ['notes','备注']
  ];
  const optionHtml = attrOptions.map(([v,l]) => `<option value="${v}">${l}</option>`).join('');
  let globalDialog = null;

  if (header && header.children.length >= 2) {
    const attrHeaderCell = header.children[1];
    attrHeaderCell.innerHTML = '<button type="button" class="v024-attr-header" data-global-attr-open>属性</button>';
    globalDialog = document.createElement('dialog');
    globalDialog.className = 'v024-global-attr-dialog';
    globalDialog.innerHTML = `
      <form class="v024-global-attr-shell" data-global-attr-form>
        <h3>统一设置属性列</h3>
        <p>这里设置一次，当前客户的所有缴费数据行都会使用同样的两个默认属性。</p>
        <div class="v024-global-attr-grid">
          <label>第一属性<select name="display_attr_1">${optionHtml}</select></label>
          <label>第二属性<select name="display_attr_2">${optionHtml}</select></label>
        </div>
        <div class="v024-global-attr-actions">
          <button type="button" class="ghost" data-global-attr-close>取消</button>
          <button type="submit" class="primary">应用到全部数据行</button>
        </div>
      </form>`;
    document.body.appendChild(globalDialog);
    const form = globalDialog.querySelector('[data-global-attr-form]');
    const initial1 = firstRow?.dataset.displayAttr1 || 'service_type';
    const initial2 = firstRow?.dataset.displayAttr2 || 'holder_name';
    form.elements.display_attr_1.value = initial1;
    form.elements.display_attr_2.value = initial2;

    attrHeaderCell.querySelector('[data-global-attr-open]').addEventListener('click', () => {
      const current = workbench.querySelector('[data-payment-row]');
      form.elements.display_attr_1.value = current?.dataset.displayAttr1 || initial1;
      form.elements.display_attr_2.value = current?.dataset.displayAttr2 || initial2;
      globalDialog.showModal();
    });
    globalDialog.querySelector('[data-global-attr-close]').addEventListener('click', () => globalDialog.close());
    globalDialog.addEventListener('click', e => { if (e.target === globalDialog) globalDialog.close(); });
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const a1 = form.elements.display_attr_1.value;
      const a2 = form.elements.display_attr_2.value;
      if (a1 === a2) return toast('两个默认属性不能相同');
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('display_attr_1', a1);
      fd.append('display_attr_2', a2);
      try {
        const customerId = workspace.dataset.customerId;
        const r = await fetch(`/customers/${customerId}/display-attributes`, {method:'POST',body:fd,credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.error || '设置失败');
        globalDialog.close();
        location.reload();
      } catch (_) {
        toast('网络异常，设置未保存');
      }
    });
  }
})();
