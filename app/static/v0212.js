(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const csrf = root.querySelector('[data-payment-workbench]')?.dataset.csrf || '';
  const paymentList = document.getElementById('paymentSortable');
  const paymentDialog = document.getElementById('paymentColumnsDialog');
  const paymentForm = paymentDialog?.querySelector('[data-payment-columns-form]');
  const paymentColumnList = paymentDialog?.querySelector('[data-payment-column-list]');
  const businessDialog = document.getElementById('businessAttributeDialog');
  const businessForm = businessDialog?.querySelector('[data-business-attribute-form]');
  const attrList = businessDialog?.querySelector('[data-global-attribute-list]');
  const AMOUNT = 'payment_amount';

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
    setTimeout(() => el.classList.remove('show'), 1100);
  };

  const postForm = async (url, fd) => {
    const r = await fetch(url, {method:'POST', body:fd, credentials:'same-origin'});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '保存失败');
    return data;
  };

  const scrubAmountFromAttributeDialog = () => {
    if (!paymentDialog) return;
    paymentColumnList?.querySelectorAll('[data-payment-column-row]').forEach(row => {
      const select = row.querySelector('select');
      const key = row.dataset.key || select?.value || '';
      if (key === AMOUNT || select?.value === AMOUNT) row.remove();
    });
    paymentDialog.querySelectorAll('option[value="payment_amount"]').forEach(option => option.remove());
    const help = paymentDialog.querySelector('.payment-columns-help-v0211');
    if (help) help.textContent = '拖动“本月缴费”表头可调整位置。';
    const trigger = root.querySelector('[data-payment-columns-settings]');
    if (trigger) trigger.textContent = '显示属性';
  };

  if (paymentColumnList) {
    new MutationObserver(() => requestAnimationFrame(scrubAmountFromAttributeDialog))
      .observe(paymentColumnList, {childList:true, subtree:true});
  }
  scrubAmountFromAttributeDialog();

  const currentLayoutKeys = () => (paymentList?.dataset.paymentColumnKeys || '')
    .split(',').map(x => x.trim()).filter(Boolean);

  const widthMapFor = keys => {
    const raw = paymentList ? getComputedStyle(paymentList).getPropertyValue('--payment-cols').trim() : '';
    const widths = raw.split(/\s+/).filter(Boolean);
    const map = new Map();
    keys.forEach((key, index) => map.set(key, widths[index] || '180px'));
    return map;
  };

  const applyPaymentLayoutDom = (order, oldKeys) => {
    if (!paymentList) return;
    const widths = widthMapFor(oldKeys);
    const header = paymentList.querySelector('.v0211-payment-header');
    const actionHead = header?.querySelector('.payment-action-head-v0211');
    order.forEach(key => {
      const head = header?.querySelector(`[data-payment-column-head][data-payment-attr-key="${CSS.escape(key)}"]`);
      if (head && actionHead) header.insertBefore(head, actionHead);
    });
    paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
      const actions = row.querySelector('.payment-row-actions-v0211');
      order.forEach(key => {
        const cell = row.querySelector(`[data-payment-attr-key="${CSS.escape(key)}"]`);
        if (cell && actions) row.insertBefore(cell, actions);
      });
    });
    paymentList.dataset.paymentColumnKeys = order.join(',');
    paymentList.style.setProperty('--payment-cols', order.map(key => widths.get(key) || '180px').join(' '));
  };

  const persistPaymentLayout = async order => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('columns_json', JSON.stringify(order));
    await postForm(`/customers/${root.dataset.customerId}/payment-columns-v0211`, fd);
  };

  if (paymentList) {
    const header = paymentList.querySelector('.v0211-payment-header');
    let dragging = null;
    header?.querySelectorAll('[data-payment-column-head]').forEach(head => {
      head.draggable = true;
      head.classList.add('payment-head-draggable-v0212');
      head.title = `${head.textContent.trim()}：拖动改变显示位置`;
    });
    header?.addEventListener('dragstart', e => {
      const head = e.target.closest('[data-payment-column-head]');
      if (!head || e.target.closest('[data-resize-payment-col]')) return;
      dragging = head;
      head.classList.add('is-dragging-v0212');
      e.dataTransfer.effectAllowed = 'move';
    });
    header?.addEventListener('dragover', e => {
      if (!dragging) return;
      const target = e.target.closest('[data-payment-column-head]');
      if (!target || target === dragging) return;
      e.preventDefault();
      const rect = target.getBoundingClientRect();
      const after = e.clientX > rect.left + rect.width / 2;
      target.classList.toggle('drag-after-v0212', after);
      target.classList.toggle('drag-before-v0212', !after);
    });
    header?.addEventListener('dragleave', e => {
      const target = e.target.closest('[data-payment-column-head]');
      target?.classList.remove('drag-before-v0212', 'drag-after-v0212');
    });
    header?.addEventListener('drop', async e => {
      if (!dragging) return;
      const target = e.target.closest('[data-payment-column-head]');
      if (!target || target === dragging) return;
      e.preventDefault();
      const oldKeys = currentLayoutKeys();
      const rect = target.getBoundingClientRect();
      const after = e.clientX > rect.left + rect.width / 2;
      const actionHead = header.querySelector('.payment-action-head-v0211');
      header.insertBefore(dragging, after ? target.nextSibling : target);
      if (actionHead && dragging.nextSibling === null) header.insertBefore(dragging, actionHead);
      const order = [...header.querySelectorAll('[data-payment-column-head]')].map(x => x.dataset.paymentAttrKey);
      applyPaymentLayoutDom(order, oldKeys);
      header.querySelectorAll('.drag-before-v0212,.drag-after-v0212').forEach(x => x.classList.remove('drag-before-v0212','drag-after-v0212'));
      try {
        await persistPaymentLayout(order);
        toast('显示顺序已保存');
      } catch (err) {
        toast(err.message || '顺序保存失败');
        location.reload();
      }
    });
    header?.addEventListener('dragend', () => {
      dragging?.classList.remove('is-dragging-v0212');
      header.querySelectorAll('.drag-before-v0212,.drag-after-v0212').forEach(x => x.classList.remove('drag-before-v0212','drag-after-v0212'));
      dragging = null;
    });
  }

  document.addEventListener('submit', async e => {
    if (!paymentForm || e.target !== paymentForm) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const businessKeys = [...paymentColumnList.querySelectorAll('[data-payment-column-row] select')]
      .map(x => x.value).filter(x => x && x !== AMOUNT);
    if (new Set(businessKeys).size !== businessKeys.length) return toast('同一个显示属性不能重复');
    const current = currentLayoutKeys();
    const amountIndex = Math.max(0, current.indexOf(AMOUNT));
    const order = [...businessKeys];
    order.splice(Math.min(amountIndex, order.length), 0, AMOUNT);
    try {
      await persistPaymentLayout(order);
      location.reload();
    } catch (err) {
      toast(err.message || '显示属性保存失败');
    }
  }, true);

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
    btn.title = '输入延期月数：1=本月不缴，2=本月和下月不缴';
    const input = document.createElement('input');
    input.type = 'text';
    input.inputMode = 'numeric';
    input.pattern = '\\d{1,3}';
    input.placeholder = '月';
    input.className = 'payment-defer-input-v0212';
    input.hidden = true;
    wrap.append(btn, input);
    actions.insertBefore(wrap, actions.firstChild);

    btn.addEventListener('click', () => {
      input.hidden = !input.hidden;
      if (!input.hidden) {
        input.value = '1';
        input.focus();
        input.select();
      }
    });
    input.addEventListener('keydown', async e => {
      if (e.key === 'Escape') {
        e.preventDefault();
        input.hidden = true;
        return;
      }
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
        location.reload();
      } catch (err) {
        input.disabled = false;
        input.focus();
        input.select();
        toast(err.message || '延期失败');
      }
    });
  });

  let activeServiceId = '';
  let visibleDraft = new Set();

  root.addEventListener('click', e => {
    const btn = e.target.closest('[data-open-service-editor]');
    if (!btn) return;
    activeServiceId = btn.dataset.serviceId || btn.closest('[data-service-id]')?.dataset.serviceId || '';
  }, true);

  const ensureRuntimePanel = () => {
    if (!businessDialog || !businessForm) return null;
    let panel = businessDialog.querySelector('[data-business-runtime-v0212]');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.className = 'business-runtime-v0212';
    panel.dataset.businessRuntimeV0212 = '1';
    panel.innerHTML = `
      <div class="business-runtime-state-v0212">
        <label>业务状态
          <select data-business-status-v0212>
            <option value="active">启用</option>
            <option value="inactive">停用</option>
          </select>
        </label>
        <div><small>当前缴费状态</small><strong data-business-schedule-state-v0212>—</strong></div>
      </div>
      <button type="button" class="danger ghost" data-delete-service-v0212>删除此条数据</button>`;
    const firstSection = businessForm.querySelector('.business-editor-section-v029');
    businessForm.insertBefore(panel, firstSection || businessForm.lastElementChild);
    return panel;
  };

  const decorateAttributeRows = () => {
    if (!attrList) return;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      if (row.querySelector('[data-business-visible-v0212]')) return;
      const key = row.dataset.key || '';
      const label = document.createElement('label');
      label.className = 'business-visible-toggle-v0212';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.dataset.businessVisibleV0212 = '1';
      check.checked = key.startsWith('new_') ? true : visibleDraft.has(key);
      check.addEventListener('change', () => {
        if (check.checked) visibleDraft.add(key);
        else visibleDraft.delete(key);
      });
      label.append(check, document.createTextNode('业务模块显示'));
      const del = row.querySelector('.global-attribute-delete');
      row.insertBefore(label, del || null);
    });
  };

  if (attrList) {
    new MutationObserver(() => requestAnimationFrame(decorateAttributeRows))
      .observe(attrList, {childList:true, subtree:false});
  }

  const loadRuntime = async serviceId => {
    if (!serviceId) return;
    try {
      const r = await fetch(`/services/${serviceId}/runtime-v0212`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok || serviceId !== activeServiceId) return;
      visibleDraft = new Set(data.business_visible_keys || []);
      const panel = ensureRuntimePanel();
      const status = panel?.querySelector('[data-business-status-v0212]');
      const schedule = panel?.querySelector('[data-business-schedule-state-v0212]');
      if (status) status.value = data.status || 'active';
      if (schedule) schedule.textContent = data.schedule_state || '—';
      decorateAttributeRows();
      attrList?.querySelectorAll('.global-attribute-row-v028').forEach(row => {
        const check = row.querySelector('[data-business-visible-v0212]');
        if (check) check.checked = visibleDraft.has(row.dataset.key);
      });
    } catch (_) {
      toast('业务状态读取失败');
    }
  };

  if (businessDialog) {
    new MutationObserver(() => {
      if (businessDialog.open && activeServiceId) loadRuntime(activeServiceId);
    }).observe(businessDialog, {attributes:true, attributeFilter:['open']});
  }

  businessDialog?.addEventListener('click', async e => {
    const del = e.target.closest('[data-delete-service-v0212]');
    if (!del || !activeServiceId) return;
    if (!confirm('确定永久删除这条业务数据吗？关联的缴费记录和优惠记录也会一并删除，此操作不可恢复。')) return;
    del.disabled = true;
    const fd = new FormData();
    fd.append('csrf', businessForm.elements.csrf.value);
    try {
      await postForm(`/services/${activeServiceId}/delete-v0212`, fd);
      businessDialog.close();
      toast('数据已删除');
      location.reload();
    } catch (err) {
      del.disabled = false;
      toast(err.message || '删除失败');
    }
  });

  document.addEventListener('submit', async e => {
    if (!businessForm || e.target !== businessForm || !activeServiceId || !attrList) return;
    e.preventDefault();
    e.stopImmediatePropagation();

    const template = [];
    const values = {};
    const checkedKeys = [];
    let invalid = false;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      const key = row.dataset.key || '';
      const label = row.querySelector('.attr-label')?.value.trim() || '';
      if (!label) invalid = true;
      const kindSelect = row.querySelector('.attr-kind');
      const kind = kindSelect?.disabled
        ? (kindSelect.dataset.fixedKind || kindSelect.value || 'text')
        : (kindSelect?.value || 'text');
      template.push({key, label, kind, core: !!kindSelect?.disabled});
      values[key] = row.querySelector('.attr-value')?.value || '';
      if (row.querySelector('[data-business-visible-v0212]')?.checked) checkedKeys.push(key);
    });
    if (invalid || !template.length) return toast('属性名称不能为空，且至少保留一个属性');

    const saveButton = businessForm.querySelector('button[type="submit"]');
    if (saveButton) saveButton.disabled = true;
    try {
      const attrFd = new FormData();
      attrFd.append('csrf', businessForm.elements.csrf.value);
      attrFd.append('template_json', JSON.stringify(template));
      attrFd.append('values_json', JSON.stringify(values));
      const attrData = await postForm(`/services/${activeServiceId}/attributes-v028`, attrFd);

      const mappedVisible = checkedKeys
        .map(key => attrData.key_map?.[key] || key)
        .filter((key, index, arr) => arr.indexOf(key) === index);
      const runtimeFd = new FormData();
      runtimeFd.append('csrf', businessForm.elements.csrf.value);
      runtimeFd.append('status', businessDialog.querySelector('[data-business-status-v0212]')?.value || 'active');
      runtimeFd.append('business_visible_json', JSON.stringify(mappedVisible));
      await postForm(`/services/${activeServiceId}/runtime-v0212`, runtimeFd);

      businessDialog.close();
      toast('业务已保存');
      location.reload();
    } catch (err) {
      if (saveButton) saveButton.disabled = false;
      toast(err.message || '业务保存失败');
    }
  }, true);
})();
