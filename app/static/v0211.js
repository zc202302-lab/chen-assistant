(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const paymentList = document.getElementById('paymentSortable');
  const businessList = root.querySelector('[data-business-list]');
  const paymentDialog = document.getElementById('paymentColumnsDialog');
  const paymentForm = paymentDialog?.querySelector('[data-payment-columns-form]');
  const paymentColumnList = paymentDialog?.querySelector('[data-payment-column-list]');
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  const AMOUNT_KEY = 'payment_amount';

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    console.info(msg);
  };

  let availableColumns = [];
  try {
    availableColumns = JSON.parse(paymentDialog?.dataset.paymentColumnOptions || '[]');
  } catch (_) {
    availableColumns = [];
  }

  const selectedKeys = () => paymentColumnList
    ? [...paymentColumnList.querySelectorAll('[data-payment-column-row]')].map(row => row.querySelector('select')?.value || '').filter(Boolean)
    : [];

  const optionLabel = key => availableColumns.find(x => x.key === key)?.label || (key === AMOUNT_KEY ? '缴费金额' : key);

  const refreshColumnRowControls = () => {
    if (!paymentColumnList) return;
    paymentColumnList.querySelectorAll('[data-payment-column-row]').forEach(row => {
      const select = row.querySelector('select');
      const del = row.querySelector('[data-payment-column-delete]');
      if (!select) return;
      const current = select.value || row.dataset.key || '';
      select.innerHTML = '';
      availableColumns.forEach(column => {
        const option = document.createElement('option');
        option.value = column.key;
        option.textContent = column.label;
        option.selected = column.key === current;
        select.appendChild(option);
      });
      if (![...select.options].some(o => o.value === current) && availableColumns.length) {
        select.value = availableColumns[0].key;
      }
      row.dataset.key = select.value;
      const required = select.value === AMOUNT_KEY;
      select.dataset.requiredPaymentAmount = required ? '1' : '';
      if (del) {
        del.disabled = required;
        del.title = required ? '缴费金额不能删除' : '删除这个显示属性';
      }
    });
  };

  const makeColumnRow = key => {
    const row = document.createElement('div');
    row.className = 'payment-column-editor-row-v0211';
    row.dataset.paymentColumnRow = '1';
    row.dataset.key = key;

    const handle = document.createElement('button');
    handle.type = 'button';
    handle.className = 'payment-column-handle drag-handle';
    handle.draggable = false;
    handle.title = '按住拖动改变属性位置';
    handle.textContent = '⠿';

    const select = document.createElement('select');
    select.className = 'payment-column-select-v0211';
    availableColumns.forEach(column => {
      const option = document.createElement('option');
      option.value = column.key;
      option.textContent = column.label;
      option.selected = column.key === key;
      select.appendChild(option);
    });

    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'ghost small payment-column-delete-v0211';
    del.dataset.paymentColumnDelete = '1';
    del.textContent = '删除';

    row.append(handle, select, del);
    paymentColumnList.appendChild(row);
    refreshColumnRowControls();
    return row;
  };

  root.querySelector('[data-payment-columns-settings]')?.addEventListener('click', () => paymentDialog?.showModal());
  paymentDialog?.querySelectorAll('[data-payment-columns-close]').forEach(btn => btn.addEventListener('click', () => paymentDialog.close()));

  paymentColumnList?.addEventListener('change', e => {
    const select = e.target.closest('.payment-column-select-v0211');
    if (!select) return;
    const row = select.closest('[data-payment-column-row]');
    if (row) row.dataset.key = select.value;
    refreshColumnRowControls();
  });

  paymentColumnList?.addEventListener('click', e => {
    const del = e.target.closest('[data-payment-column-delete]');
    if (!del || del.disabled) return;
    del.closest('[data-payment-column-row]')?.remove();
  });

  paymentDialog?.querySelector('[data-payment-column-add]')?.addEventListener('click', () => {
    const used = new Set(selectedKeys());
    const next = availableColumns.find(column => !used.has(column.key) && column.key !== AMOUNT_KEY)
      || availableColumns.find(column => !used.has(column.key));
    if (!next) return toast('已经显示全部可用属性');
    const row = makeColumnRow(next.key);
    row.querySelector('select')?.focus();
  });

  const savePaymentColumns = async keys => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('columns_json', JSON.stringify(keys));
    const r = await fetch(`/customers/${root.dataset.customerId}/payment-columns-v0211`, {
      method: 'POST', body: fd, credentials: 'same-origin'
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '缴费属性保存失败');
    return data;
  };

  paymentForm?.addEventListener('submit', async e => {
    e.preventDefault();
    const keys = selectedKeys();
    if (!keys.includes(AMOUNT_KEY)) keys.push(AMOUNT_KEY);
    if (new Set(keys).size !== keys.length) return toast('同一个缴费属性不能重复');
    if (!keys.length) return toast('至少保留缴费金额');
    try {
      await savePaymentColumns(keys);
      const u = new URL(location.href);
      u.searchParams.delete('tab');
      location.href = u.pathname + u.search + u.hash;
    } catch (err) {
      toast(err.message || '缴费属性保存失败');
    }
  });

  // 动态缴费列宽：每个已选属性都可独立拖宽，并按客户保存。
  const paymentKeys = () => (paymentList?.dataset.paymentColumnKeys || '').split(',').map(x => x.trim()).filter(Boolean);
  const parseWidths = () => {
    const keys = paymentKeys();
    const raw = paymentList ? getComputedStyle(paymentList).getPropertyValue('--payment-cols').trim() : '';
    const parts = raw.split(/\s+/).map(x => parseInt(x, 10));
    const result = {};
    keys.forEach((key, index) => { result[key] = Number.isFinite(parts[index]) ? parts[index] : 180; });
    return result;
  };
  const applyWidths = widths => {
    if (!paymentList) return;
    paymentList.style.setProperty('--payment-cols', paymentKeys().map(key => `${Math.max(110, Math.min(900, Number(widths[key]) || 180))}px`).join(' '));
  };
  const persistWidths = async widths => {
    if (!paymentList) return;
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('widths_json', JSON.stringify(widths));
    try {
      await fetch(paymentList.dataset.columnWidthUrl, {method:'POST', body:fd, credentials:'same-origin', keepalive:true});
    } catch (_) {}
  };

  paymentList?.querySelectorAll('[data-resize-payment-col]').forEach(handle => {
    handle.addEventListener('pointerdown', e => {
      e.preventDefault();
      e.stopPropagation();
      const key = handle.dataset.resizePaymentCol;
      const widths = parseWidths();
      const startX = e.clientX;
      const startW = widths[key] || 180;
      document.body.classList.add('is-resizing-columns');
      handle.setPointerCapture?.(e.pointerId);
      const move = ev => {
        widths[key] = Math.max(110, Math.min(900, Math.round(startW + ev.clientX - startX)));
        applyWidths(widths);
      };
      const up = ev => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        document.body.classList.remove('is-resizing-columns');
        handle.releasePointerCapture?.(ev.pointerId);
        persistWidths(widths);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
  });

  // 缴费页的业务属性：单击复制，双击仍在缴费页直接打开同一条业务主数据编辑器。
  root.addEventListener('pointerdown', e => {
    if (e.target.closest('[data-payment-business-cell]')) e.preventDefault();
  }, true);
  root.addEventListener('dblclick', e => {
    const cell = e.target.closest('[data-payment-business-cell]');
    if (!cell) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const row = cell.closest('[data-payment-row]');
    row?.querySelector('[data-open-service-editor]')?.click();
  }, true);

  let activeEditorServiceId = '';
  root.addEventListener('click', e => {
    const btn = e.target.closest('[data-open-service-editor]');
    if (!btn) return;
    activeEditorServiceId = btn.dataset.serviceId || btn.closest('[data-service-id]')?.dataset.serviceId || '';
  }, true);

  const displayValue = (key, raw, data) => {
    if (!raw) return '—';
    const meta = (data.template || []).find(x => x.key === key);
    if (meta?.kind === 'invoice_group') {
      const group = (data.invoice_groups || []).find(x => String(x.id) === String(raw));
      return group?.name || '未分组';
    }
    return String(raw);
  };

  const syncPaymentHeaderLabels = template => {
    const labels = new Map((template || []).map(x => [x.key, x.label]));
    labels.set(AMOUNT_KEY, '缴费金额');
    paymentList?.querySelectorAll('[data-payment-column-head]').forEach(head => {
      const label = head.querySelector('span');
      if (label) label.textContent = labels.get(head.dataset.paymentAttrKey) || head.dataset.paymentAttrKey;
    });
  };

  const syncAvailableColumns = template => {
    availableColumns = (template || []).map(x => ({key:x.key, label:x.label, kind:x.kind || 'text'}));
    availableColumns.push({key:AMOUNT_KEY, label:'缴费金额', kind:'payment_amount'});
    if (paymentDialog) paymentDialog.dataset.paymentColumnOptions = JSON.stringify(availableColumns);
    refreshColumnRowControls();
  };

  const refreshServiceIntoPayment = async serviceId => {
    if (!serviceId) return;
    try {
      const r = await fetch(`/services/${serviceId}/attributes-v028`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return;
      const validKeys = new Set((data.template || []).map(x => x.key));
      validKeys.add(AMOUNT_KEY);
      const currentKeys = paymentKeys();
      if (currentKeys.some(key => !validKeys.has(key))) {
        const filtered = currentKeys.filter(key => validKeys.has(key));
        if (!filtered.includes(AMOUNT_KEY)) filtered.push(AMOUNT_KEY);
        await savePaymentColumns(filtered);
        location.reload();
        return;
      }
      syncAvailableColumns(data.template || []);
      syncPaymentHeaderLabels(data.template || []);
      const row = workbench?.querySelector(`[data-payment-row][data-service-id="${CSS.escape(String(serviceId))}"]`);
      if (!row) return;
      row.querySelectorAll('[data-payment-business-cell]').forEach(cell => {
        const key = cell.dataset.paymentAttrKey;
        const raw = data.values?.[key] ?? '';
        const shown = displayValue(key, raw, data);
        const strong = cell.querySelector('[data-payment-cell-value]');
        if (strong) strong.textContent = shown;
        if (raw) cell.dataset.copySilent = shown;
        else delete cell.dataset.copySilent;
        if (key === 'number' || key === 'account') {
          if (raw) {
            cell.classList.add('identifier-copy');
            cell.classList.remove('dense-empty');
            cell.dataset.copy = String(raw);
          } else {
            cell.classList.remove('identifier-copy');
            cell.classList.add('dense-empty');
            delete cell.dataset.copy;
          }
        }
      });
    } catch (_) {}
  };

  businessDialog?.addEventListener('close', () => {
    const sid = activeEditorServiceId;
    if (sid) setTimeout(() => refreshServiceIntoPayment(sid), 80);
  });

  // 排序也是同一份 service.sort_order：无论从业务还是缴费拖动，两个工作区马上按后端完整顺序重排。
  const applyServiceOrder = order => {
    const rank = new Map((order || []).map((id, index) => [String(id), index]));
    const reorder = (container, selector) => {
      if (!container) return;
      const rows = [...container.querySelectorAll(selector)].filter(row => rank.has(String(row.dataset.serviceId)));
      rows.sort((a, b) => rank.get(String(a.dataset.serviceId)) - rank.get(String(b.dataset.serviceId)));
      rows.forEach(row => container.appendChild(row));
    };
    reorder(businessList, ':scope > [data-business-row]');
    reorder(paymentList, ':scope > [data-payment-row]');
  };
  root.addEventListener('chen:service-order-updated', e => applyServiceOrder(e.detail?.order || []));
})();
