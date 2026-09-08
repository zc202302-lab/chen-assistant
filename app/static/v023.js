(() => {
  const workspace = document.querySelector('.v023-workspace');
  if (!workspace) return;
  const workbench = workspace.querySelector('[data-payment-workbench]');
  if (!workbench) return;
  const csrf = workbench.dataset.csrf || '';
  let activeAmount = null;

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
    ta.value = value; ta.readOnly = true;
    Object.assign(ta.style, { position:'fixed', opacity:'0', left:'-9999px' });
    document.body.appendChild(ta); ta.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove(); return ok;
  };

  const selectAmount = input => {
    if (!input) return;
    activeAmount = input;
    input.focus({preventScroll:true});
    requestAnimationFrame(() => {
      try { input.setSelectionRange(0, input.value.length); } catch (_) { input.select?.(); }
    });
  };

  const money = n => {
    const v = Math.round((Number(n)||0)*100)/100;
    return '¥' + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/,'').replace(/\.$/,''));
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
      readiness.textContent = data.pending ? `需核对 ${data.required} 项，其中还有 ${data.pending} 项未核对` : `需核对 ${data.required} 项，已全部核对`;
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
        em.className = 'delta-badge ' + (Number(data.delta)>0 ? 'up' : 'down');
        em.textContent = (Number(data.delta)>0?'+':'') + String(Math.round(Number(data.delta)*100)/100);
        fb.appendChild(em);
      }
    }
  };

  const nextPendingAfter = row => {
    const rows = [...workbench.querySelectorAll('[data-payment-row]')];
    const idx = rows.indexOf(row);
    const ordered = rows.slice(idx+1).concat(rows.slice(0, idx+1));
    return ordered.find(r => r.dataset.mode === 'variable' && r.dataset.confirmed === '0') || null;
  };

  const savePayment = async input => {
    if (!input || input.dataset.saving === '1') return;
    const raw = input.value.trim().replace(',', '.');
    if (!raw) { toast('金额不能为空，本月不缴请填0'); return selectAmount(input); }
    const row = input.closest('[data-payment-row]');
    input.dataset.saving = '1'; row?.classList.add('is-saving');
    const fd = new FormData(); fd.append('csrf', csrf); fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, {method:'POST',body:fd,credentials:'same-origin'});
      const data = await r.json().catch(()=>({}));
      if (!r.ok || !data.ok) { toast(data.error || '保存失败'); return selectAmount(input); }
      updateRow(row, data); updateSummary(data);
      const next = nextPendingAfter(row);
      if (next) {
        const nextInput = next.querySelector('.quick-amount');
        next.scrollIntoView({behavior:'smooth',block:'center'});
        setTimeout(() => selectAmount(nextInput), 140);
      } else { activeAmount = null; input.blur(); toast('本月需核对项目已全部完成'); }
    } catch (_) { toast('网络异常，未保存'); selectAmount(input); }
    finally { delete input.dataset.saving; row?.classList.remove('is-saving'); }
  };

  // After Enter selects the next amount, copying must not steal its focus/selection.
  workbench.addEventListener('pointerdown', e => {
    if (e.target.closest('.identifier-copy')) e.preventDefault();
  }, true);

  workbench.addEventListener('click', async e => {
    const id = e.target.closest('.identifier-copy');
    if (!id) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const keep = activeAmount && document.contains(activeAmount) ? activeAmount : null;
    const ok = await copyText(id.dataset.copy || '');
    id.classList.add('copied'); setTimeout(()=>id.classList.remove('copied'),450);
    toast(ok ? `已复制${id.dataset.kind || ''}` : '复制失败');
    if (keep) selectAmount(keep);
  }, true);

  document.addEventListener('keydown', e => {
    const input = e.target.closest?.('.v023-workspace .quick-amount');
    if (!input || e.key !== 'Enter') return;
    e.preventDefault(); e.stopImmediatePropagation();
    savePayment(input);
  }, true);

  workbench.querySelectorAll('.quick-amount').forEach(input => {
    input.addEventListener('focus', () => { activeAmount = input; });
    input.addEventListener('click', () => selectAmount(input));
  });

  window.addEventListener('focus', () => {
    if (activeAmount && document.contains(activeAmount)) setTimeout(() => selectAmount(activeAmount), 60);
  });

  workbench.addEventListener('click', async e => {
    const btn = e.target.closest('[data-fixed-toggle]');
    if (!btn) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const row = btn.closest('[data-payment-row]');
    if (!row || btn.dataset.saving === '1') return;
    btn.dataset.saving = '1';
    const fd = new FormData(); fd.append('csrf', csrf);
    try {
      const r = await fetch(`/services/${row.dataset.serviceId}/toggle-fixed`, {method:'POST',body:fd,credentials:'same-origin'});
      const data = await r.json().catch(()=>({}));
      if (!r.ok || !data.ok) return toast(data.error || '切换失败');
      updateRow(row, data); updateSummary(data);
      toast(data.mode === 'fixed' ? '已设为固定缴费' : '已取消固定缴费');
    } catch (_) { toast('网络异常'); }
    finally { delete btn.dataset.saving; }
  }, true);

  // Persistent drag ordering.
  const sortable = document.getElementById('paymentSortable');
  if (sortable) {
    let dragging = null;
    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.drag-handle');
      if (!handle) { e.preventDefault(); return; }
      dragging = handle.closest('[data-payment-row]');
      dragging?.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', dragging?.dataset.serviceId || '');
    });
    sortable.addEventListener('dragover', e => {
      if (!dragging) return;
      e.preventDefault();
      const row = e.target.closest('[data-payment-row]');
      sortable.querySelectorAll('.drag-over').forEach(x=>x.classList.remove('drag-over'));
      if (!row || row === dragging) return;
      row.classList.add('drag-over');
      const rect = row.getBoundingClientRect();
      if (e.clientY < rect.top + rect.height/2) sortable.insertBefore(dragging, row);
      else sortable.insertBefore(dragging, row.nextSibling);
    });
    sortable.addEventListener('dragend', async () => {
      if (!dragging) return;
      dragging.classList.remove('dragging');
      sortable.querySelectorAll('.drag-over').forEach(x=>x.classList.remove('drag-over'));
      dragging = null;
      const ids = [...sortable.querySelectorAll('[data-payment-row]')].map(r=>r.dataset.serviceId).join(',');
      const fd = new FormData(); fd.append('csrf', csrf); fd.append('service_ids', ids);
      try {
        const r = await fetch(sortable.dataset.reorderUrl, {method:'POST',body:fd,credentials:'same-origin'});
        if (!r.ok) throw new Error();
        toast('顺序已保存');
      } catch (_) { toast('顺序保存失败，刷新后可能恢复'); }
    });
  }

  // Attribute dialog: all current service attributes + two chosen defaults for the first column.
  const dialog = document.getElementById('serviceAttributeDialog');
  const attrForm = dialog?.querySelector('[data-attribute-form]');
  let editingRow = null;
  const fieldMap = {
    service_type:'serviceType', holder_name:'holderName', number:'number', account:'account',
    payment_cycle:'paymentCycle', payment_method:'paymentMethod', invoice_type:'invoiceType',
    invoice_group_id:'invoiceGroupId', package_type:'packageType', last_payment_date:'lastPaymentDate', notes:'notes',
    display_attr_1:'displayAttr1', display_attr_2:'displayAttr2'
  };
  const openAttributes = row => {
    if (!dialog || !attrForm || !row) return;
    editingRow = row;
    attrForm.elements.service_id.value = row.dataset.serviceId;
    Object.entries(fieldMap).forEach(([name,key]) => {
      const el = attrForm.elements[name]; if (el) el.value = row.dataset[key] || '';
    });
    dialog.showModal();
  };
  workbench.addEventListener('click', e => {
    const cell = e.target.closest('[data-open-attributes]');
    if (!cell) return;
    e.preventDefault();
    openAttributes(cell.closest('[data-payment-row]'));
  });
  dialog?.querySelectorAll('[data-attribute-close]').forEach(b => b.addEventListener('click',()=>dialog.close()));
  dialog?.addEventListener('click', e => { if (e.target === dialog) dialog.close(); });
  attrForm?.addEventListener('submit', async e => {
    e.preventDefault();
    if (!editingRow) return;
    const fd = new FormData(attrForm);
    const sid = fd.get('service_id'); fd.delete('service_id');
    try {
      const r = await fetch(`/services/${sid}/attributes`, {method:'POST',body:fd,credentials:'same-origin'});
      const data = await r.json().catch(()=>({}));
      if (!r.ok || !data.ok) return toast(data.error || '属性保存失败');
      Object.entries(fieldMap).forEach(([name,key]) => {
        if (name.startsWith('display_attr_')) return;
        if (data[name] !== undefined) editingRow.dataset[key] = data[name] ?? '';
      });
      editingRow.dataset.displayAttr1 = data.display_attr_1;
      editingRow.dataset.displayAttr2 = data.display_attr_2;
      const l1=editingRow.querySelector('[data-display-label="1"]'),v1=editingRow.querySelector('[data-display-value="1"]');
      const l2=editingRow.querySelector('[data-display-label="2"]'),v2=editingRow.querySelector('[data-display-value="2"]');
      if(l1)l1.textContent=data.display_label_1;if(v1)v1.textContent=data.display_value_1;
      if(l2)l2.textContent=data.display_label_2;if(v2)v2.textContent=data.display_value_2;
      const n=editingRow.querySelector('[data-display="number"]'),a=editingRow.querySelector('[data-display="account"]');
      if(n)n.textContent=data.number||'—';if(a)a.textContent=data.account||'—';
      const nb=n?.closest('.dense-id');if(nb){nb.dataset.copy=data.number||'';nb.classList.toggle('identifier-copy',!!data.number);nb.classList.toggle('dense-empty',!data.number)}
      const ab=a?.closest('.dense-id');if(ab){ab.dataset.copy=data.account||'';ab.classList.toggle('identifier-copy',!!data.account);ab.classList.toggle('dense-empty',!data.account)}
      dialog.close(); toast('属性已保存');
    } catch (_) { toast('网络异常，属性未保存'); }
  });
})();
