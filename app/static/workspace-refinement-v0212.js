(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const csrf = root.querySelector('[data-payment-workbench]')?.dataset.csrf || '';
  const paymentList = document.getElementById('paymentSortable');
  const businessCard = root.querySelector('.business-v028');
  const SYSTEM_PAYMENT_STATE = '__payment_state__';

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
    setTimeout(() => el.classList.remove('show'), 1300);
  };

  const postForm = async (url, fd) => {
    const r = await fetch(url, {method:'POST', body:fd, credentials:'same-origin'});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '保存失败');
    return data;
  };

  // 缴费表始终按当前可用宽度平均分配显示列，不再由历史像素宽度撑出页面。
  const fitPaymentColumns = () => {
    if (!paymentList) return;
    const count = paymentList.querySelectorAll('.v0211-payment-header [data-payment-column-head]').length || 1;
    paymentList.classList.add('payment-auto-fit-v0212');
    paymentList.style.setProperty('--payment-column-count', String(count));
    paymentList.querySelectorAll('[data-payment-business-cell]').forEach(cell => {
      const value = cell.querySelector('[data-payment-cell-value]')?.textContent?.trim() || '';
      cell.title = value ? `${value} · 双击编辑` : '双击编辑';
    });
    paymentList.querySelectorAll('.payment-amount-cell-v0211').forEach(cell => {
      const input = cell.querySelector('.quick-amount');
      if (input) input.title = `${input.value || '0'} · 双击编辑业务`;
    });
  };
  fitPaymentColumns();
  if (paymentList) {
    new ResizeObserver(() => fitPaymentColumns()).observe(paymentList);
    new MutationObserver(() => requestAnimationFrame(fitPaymentColumns))
      .observe(paymentList, {childList:true, subtree:true});
  }

  // 统一交互：双击缴费或业务表格中的字段，打开同一条业务的统一编辑器。
  document.addEventListener('dblclick', e => {
    let row = null;
    const paymentField = e.target.closest('[data-payment-row] [data-payment-attr-key]');
    if (paymentField) row = paymentField.closest('[data-payment-row]');

    if (!row) {
      const businessField = e.target.closest('[data-business-row] .business-attribute');
      if (businessField) row = businessField.closest('[data-business-row]');
    }
    if (!row) return;

    const trigger = row.querySelector('[data-open-service-editor]');
    if (!trigger) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    trigger.click();
  }, true);

  const updateBusinessRows = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${CSS.escape(String(sid))}"]`);
      if (!card) return;
      const grid = card.querySelector('[data-business-attrs]');
      if (grid) {
        const attrs = payload.preview_attributes || [];
        grid.innerHTML = '';
        grid.style.setProperty('--business-visible-count', String(Math.max(1, attrs.length)));
        attrs.forEach(attr => {
          const box = document.createElement('div');
          box.className = 'business-attribute';
          box.dataset.attrKey = attr.key || '';
          const shown = attr.value || '—';
          box.title = `${attr.label || '属性'}：${shown} · 双击编辑`;
          const small = document.createElement('small');
          small.textContent = attr.label || '属性';
          const strong = document.createElement('strong');
          strong.textContent = shown;
          box.append(small, strong);
          grid.appendChild(box);
        });
      }
      if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
    });
  };

  root.querySelectorAll('[data-business-attrs]').forEach(grid => {
    grid.style.setProperty('--business-visible-count', String(Math.max(1, grid.querySelectorAll('.business-attribute').length)));
    grid.querySelectorAll('.business-attribute').forEach(box => {
      const label = box.querySelector('small')?.textContent?.trim() || '属性';
      const value = box.querySelector('strong')?.textContent?.trim() || '—';
      box.title = `${label}：${value} · 双击编辑`;
    });
  });

  if (!businessCard || !customerId) return;

  // 业务模块独立“显示属性”入口：模块级设置，不必先打开某条业务。
  const head = businessCard.querySelector('.section-head');
  if (!head) return;
  let trigger = head.querySelector('[data-business-columns-settings-v0212]');
  if (!trigger) {
    trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'ghost small business-columns-settings-v0212';
    trigger.dataset.businessColumnsSettingsV0212 = '1';
    trigger.textContent = '显示属性';
    const counter = head.querySelector('span');
    head.insertBefore(trigger, counter || null);
  }

  const dialog = document.createElement('dialog');
  dialog.className = 'service-attribute-dialog business-columns-dialog-v0212';
  dialog.innerHTML = `
    <form class="attribute-dialog-shell" data-business-columns-form-v0212>
      <div class="attribute-dialog-head">
        <div><small>业务模块</small><h3>显示属性</h3></div>
        <button type="button" class="dialog-close" data-business-columns-close-v0212>×</button>
      </div>
      <p class="business-columns-help-v0212">填写显示序号的属性才会显示；按序号从小到大排列。留空代表不显示。</p>
      <div class="business-columns-list-v0212" data-business-columns-list-v0212></div>
      <div class="attribute-dialog-actions">
        <button type="button" class="secondary" data-business-columns-close-v0212>取消</button>
        <button type="submit" class="primary">保存显示设置</button>
      </div>
    </form>`;
  document.body.appendChild(dialog);

  const form = dialog.querySelector('[data-business-columns-form-v0212]');
  const list = dialog.querySelector('[data-business-columns-list-v0212]');
  let options = [];
  let current = [];

  const renderColumns = () => {
    const order = new Map(current.map((key, index) => [String(key), index + 1]));
    const orderedOptions = [...options].sort((a, b) => {
      const ao = order.get(String(a.key)) || 9999;
      const bo = order.get(String(b.key)) || 9999;
      return ao - bo;
    });
    list.innerHTML = '';
    orderedOptions.forEach(option => {
      const row = document.createElement('label');
      row.className = 'business-column-setting-row-v0212';
      row.dataset.businessColumnKey = option.key;
      const name = document.createElement('span');
      name.textContent = option.label || option.key;
      if (option.key === SYSTEM_PAYMENT_STATE) {
        const tag = document.createElement('small');
        tag.textContent = '延期联动';
        name.appendChild(tag);
      }
      const input = document.createElement('input');
      input.type = 'text';
      input.inputMode = 'numeric';
      input.autocomplete = 'off';
      input.placeholder = '留空隐藏';
      input.value = order.has(String(option.key)) ? String(order.get(String(option.key))) : '';
      input.dataset.businessColumnOrderV0212 = '1';
      row.append(name, input);
      list.appendChild(row);
    });
  };

  const loadColumns = async () => {
    trigger.disabled = true;
    try {
      const r = await fetch(`/customers/${customerId}/business-columns-v0212`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '读取显示属性失败');
      options = data.options || [];
      current = data.columns || [];
      renderColumns();
      dialog.showModal();
      const first = list.querySelector('input');
      first?.focus();
    } catch (err) {
      toast(err.message || '读取显示属性失败');
    } finally {
      trigger.disabled = false;
    }
  };

  trigger.addEventListener('click', loadColumns);
  dialog.querySelectorAll('[data-business-columns-close-v0212]').forEach(btn => {
    btn.addEventListener('click', () => dialog.close());
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const entries = [];
    const used = new Set();
    for (const row of list.querySelectorAll('[data-business-column-key]')) {
      const raw = row.querySelector('[data-business-column-order-v0212]')?.value.trim() || '';
      if (!raw) continue;
      if (!/^\d{1,3}$/.test(raw) || Number(raw) < 1) return toast('显示序号请输入1到999的正整数');
      const n = Number(raw);
      if (used.has(n)) return toast(`显示序号 ${n} 重复，请使用不同序号`);
      used.add(n);
      entries.push({key: row.dataset.businessColumnKey, order:n});
    }
    entries.sort((a, b) => a.order - b.order);
    const columns = entries.map(item => item.key);
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('columns_json', JSON.stringify(columns));
    try {
      const data = await postForm(`/customers/${customerId}/business-columns-v0212`, fd);
      current = data.columns || columns;
      updateBusinessRows(data.rows || {});
      dialog.close();
      toast('业务显示属性已保存');
    } catch (err) {
      toast(err.message || '显示属性保存失败');
    } finally {
      submit.disabled = false;
    }
  });
})();
