(() => {
  const root = document.querySelector('.v0211-workspace');
  const dialog = document.getElementById('businessAttributeDialog');
  const form = dialog?.querySelector('[data-business-attribute-form]');
  const attrList = dialog?.querySelector('[data-global-attribute-list]');
  if (!root || !dialog || !form || !attrList) return;

  const SYSTEM_STATE = '__payment_state__';

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

  const serviceId = () => String(form.elements.service_id?.value || '').trim();
  const csrf = () => String(form.elements.csrf?.value || '').trim();

  const postForm = async (url, fd) => {
    const r = await fetch(url, {method:'POST', body:fd, credentials:'same-origin'});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || !data.ok) throw new Error(data.detail || data.error || '保存失败');
    return data;
  };

  const ensureRuntimePanel = () => {
    let panel = dialog.querySelector('[data-business-runtime-v0212]');
    if (!panel) {
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
        </div>
        <button type="button" class="danger ghost" data-delete-service-v0212>删除此条数据</button>`;
      const firstSection = form.querySelector('.business-editor-section-v029');
      form.insertBefore(panel, firstSection || form.querySelector('.attribute-dialog-actions'));
    } else {
      panel.querySelector('[data-business-schedule-state-v0212]')?.closest('div')?.remove();
    }
    return panel;
  };

  const makeOrderControl = row => {
    row.querySelector('.business-visible-toggle-v0212')?.remove();
    row.querySelectorAll('[data-business-visible-v0212]').forEach(x => x.closest('label')?.remove());
    let wrap = row.querySelector('[data-business-display-order-wrap]');
    if (wrap) return wrap.querySelector('[data-business-display-order]');
    wrap = document.createElement('label');
    wrap.className = 'business-display-order-wrap-v0212';
    wrap.dataset.businessDisplayOrderWrap = '1';
    wrap.textContent = '业务显示序号';
    const input = document.createElement('input');
    input.type = 'text';
    input.inputMode = 'numeric';
    input.autocomplete = 'off';
    input.placeholder = '留空不显示';
    input.className = 'business-display-order-input-v0212';
    input.dataset.businessDisplayOrder = '1';
    input.style.width = '96px';
    wrap.appendChild(input);
    row.insertBefore(wrap, row.querySelector('.global-attribute-delete') || null);
    return input;
  };

  const ensureSystemStateRow = () => {
    let row = attrList.querySelector(`.global-attribute-row-v028[data-key="${SYSTEM_STATE}"]`);
    if (row) return row;
    row = document.createElement('div');
    row.className = 'global-attribute-row-v028 system-derived-attribute-v0212';
    row.dataset.key = SYSTEM_STATE;
    row.dataset.systemDerived = '1';

    const handle = document.createElement('span');
    handle.className = 'global-attribute-handle';
    handle.textContent = '•';
    handle.title = '系统关联属性';

    const labelWrap = document.createElement('label');
    labelWrap.textContent = '属性名称';
    const labelInput = document.createElement('input');
    labelInput.className = 'attr-label';
    labelInput.value = '缴费状态';
    labelInput.readOnly = true;
    labelWrap.appendChild(labelInput);

    const valueWrap = document.createElement('label');
    valueWrap.textContent = '当前业务的值';
    const value = document.createElement('input');
    value.className = 'attr-value';
    value.readOnly = true;
    value.dataset.paymentStateValue = '1';
    value.value = '—';
    valueWrap.appendChild(value);

    const kindWrap = document.createElement('label');
    kindWrap.textContent = '类型';
    const kind = document.createElement('select');
    kind.className = 'attr-kind';
    kind.disabled = true;
    kind.dataset.fixedKind = 'derived_state';
    const opt = document.createElement('option');
    opt.value = 'derived_state';
    opt.textContent = '系统关联';
    opt.selected = true;
    kind.appendChild(opt);
    kindWrap.appendChild(kind);

    row.append(handle, labelWrap, valueWrap, kindWrap);
    attrList.insertBefore(row, attrList.firstChild);
    makeOrderControl(row);
    return row;
  };

  const decorateRows = () => {
    ensureSystemStateRow();
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => makeOrderControl(row));
  };

  const applyOrderValues = orderedKeys => {
    const order = new Map((orderedKeys || []).map((key, index) => [String(key), index + 1]));
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      const input = makeOrderControl(row);
      input.value = order.has(row.dataset.key || '') ? String(order.get(row.dataset.key || '')) : '';
    });
  };

  const loadRuntime = async () => {
    const sid = serviceId();
    if (!sid) return;
    const panel = ensureRuntimePanel();
    decorateRows();
    try {
      const r = await fetch(`/services/${sid}/runtime-v0212`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok || sid !== serviceId()) throw new Error(data.detail || data.error || '读取失败');
      const status = panel.querySelector('[data-business-status-v0212]');
      if (status) status.value = data.status || 'active';
      const stateValue = attrList.querySelector('[data-payment-state-value]');
      if (stateValue) stateValue.value = data.schedule_state || '—';
      applyOrderValues(data.business_visible_keys || []);
    } catch (err) {
      toast(err.message || '业务显示设置读取失败');
    }
  };

  ensureRuntimePanel();
  new MutationObserver(() => requestAnimationFrame(decorateRows))
    .observe(attrList, {childList:true, subtree:false});
  new MutationObserver(() => {
    if (dialog.open) requestAnimationFrame(loadRuntime);
  }).observe(dialog, {attributes:true, attributeFilter:['open']});

  const readDisplayOrder = () => {
    const entries = [];
    const used = new Set();
    let error = '';
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      if (error) return;
      const raw = row.querySelector('[data-business-display-order]')?.value.trim() || '';
      if (!raw) return;
      if (!/^\d{1,3}$/.test(raw) || Number(raw) < 1) {
        error = '业务显示序号请输入1到999的正整数，留空代表不显示';
        return;
      }
      const n = Number(raw);
      if (used.has(n)) {
        error = `业务显示序号 ${n} 重复，请为每个显示属性填写不同序号`;
        return;
      }
      used.add(n);
      entries.push({key: row.dataset.key || '', order:n});
    });
    entries.sort((a, b) => a.order - b.order);
    return {entries, error};
  };

  const updateBusinessRows = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${CSS.escape(String(sid))}"]`);
      if (!card) return;
      const grid = card.querySelector('[data-business-attrs]');
      if (grid) {
        grid.innerHTML = '';
        (payload.preview_attributes || []).forEach(attr => {
          const box = document.createElement('div');
          box.className = 'business-attribute';
          box.dataset.attrKey = attr.key || '';
          box.title = `${attr.label || '属性'}：${attr.value || '—'}`;
          const small = document.createElement('small');
          small.textContent = attr.label || '属性';
          const strong = document.createElement('strong');
          strong.textContent = attr.value || '—';
          box.append(small, strong);
          grid.appendChild(box);
        });
      }
      if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
    });
  };

  const save = async button => {
    const sid = serviceId();
    if (!sid) return toast('未识别到当前业务，请关闭编辑窗口后重新打开');
    decorateRows();

    const {entries, error} = readDisplayOrder();
    if (error) return toast(error);

    const template = [];
    const values = {};
    let invalid = false;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      if (row.dataset.systemDerived === '1') return;
      const key = row.dataset.key || '';
      const label = row.querySelector('.attr-label')?.value.trim() || '';
      const kindSelect = row.querySelector('.attr-kind');
      const kind = kindSelect?.disabled
        ? (kindSelect.dataset.fixedKind || kindSelect.value || 'text')
        : (kindSelect?.value || 'text');
      if (!key || !label) invalid = true;
      template.push({key, label, kind, core: !!kindSelect?.disabled});
      values[key] = row.querySelector('.attr-value')?.value || '';
    });
    if (invalid || !template.length) return toast('属性名称不能为空，且至少保留一个属性');

    button.disabled = true;
    button.dataset.savingV0212 = '1';
    try {
      const attrFd = new FormData();
      attrFd.append('csrf', csrf());
      attrFd.append('template_json', JSON.stringify(template));
      attrFd.append('values_json', JSON.stringify(values));
      const attrData = await postForm(`/services/${sid}/attributes-v028`, attrFd);

      const orderedKeys = entries.map(item => {
        if (item.key === SYSTEM_STATE) return SYSTEM_STATE;
        return attrData.key_map?.[item.key] || item.key;
      }).filter((key, index, arr) => key && arr.indexOf(key) === index);

      const runtimeFd = new FormData();
      runtimeFd.append('csrf', csrf());
      runtimeFd.append('status', dialog.querySelector('[data-business-status-v0212]')?.value || 'active');
      runtimeFd.append('business_visible_json', JSON.stringify(orderedKeys));
      const runtimeData = await postForm(`/services/${sid}/runtime-v0212`, runtimeFd);

      updateBusinessRows(runtimeData.rows || {});
      dialog.close();
      toast('业务已保存');
    } catch (err) {
      button.disabled = false;
      delete button.dataset.savingV0212;
      toast(err.message || '业务保存失败');
    }
  };

  dialog.addEventListener('click', e => {
    const saveButton = e.target.closest('[data-business-attribute-form] button[type="submit"]');
    if (!saveButton) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (saveButton.dataset.savingV0212 === '1') return;
    save(saveButton);
  }, true);

  dialog.addEventListener('click', async e => {
    const del = e.target.closest('[data-delete-service-v0212]');
    if (!del) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const sid = serviceId();
    if (!sid) return toast('未识别到当前业务，请关闭编辑窗口后重新打开');
    if (!confirm('确定永久删除这条业务数据吗？关联的缴费记录和优惠记录也会一并删除，此操作不可恢复。')) return;
    del.disabled = true;
    const fd = new FormData();
    fd.append('csrf', csrf());
    try {
      await postForm(`/services/${sid}/delete-v0212`, fd);
      toast('数据已删除');
      location.reload();
    } catch (err) {
      del.disabled = false;
      toast(err.message || '删除失败');
    }
  }, true);
})();