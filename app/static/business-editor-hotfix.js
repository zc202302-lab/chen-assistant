(() => {
  const root = document.querySelector('.v0211-workspace');
  const dialog = document.getElementById('businessAttributeDialog');
  const form = dialog?.querySelector('[data-business-attribute-form]');
  const attrList = dialog?.querySelector('[data-global-attribute-list]');
  if (!root || !dialog || !form || !attrList) return;

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
          <div><small>当前缴费状态</small><strong data-business-schedule-state-v0212>—</strong></div>
        </div>
        <button type="button" class="danger ghost" data-delete-service-v0212>删除此条数据</button>`;
      const firstSection = form.querySelector('.business-editor-section-v029');
      form.insertBefore(panel, firstSection || form.querySelector('.attribute-dialog-actions'));
    }
    return panel;
  };

  const ensureVisibilityChecks = () => {
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      if (row.querySelector('[data-business-visible-v0212]')) return;
      const label = document.createElement('label');
      label.className = 'business-visible-toggle-v0212';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.dataset.businessVisibleV0212 = '1';
      check.checked = true;
      label.append(check, document.createTextNode('业务模块显示'));
      row.insertBefore(label, row.querySelector('.global-attribute-delete') || null);
    });
  };

  const loadRuntime = async () => {
    const sid = serviceId();
    if (!sid) return;
    const panel = ensureRuntimePanel();
    ensureVisibilityChecks();
    try {
      const r = await fetch(`/services/${sid}/runtime-v0212`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok || sid !== serviceId()) throw new Error(data.detail || data.error || '读取失败');
      const status = panel.querySelector('[data-business-status-v0212]');
      const schedule = panel.querySelector('[data-business-schedule-state-v0212]');
      if (status) status.value = data.status || 'active';
      if (schedule) schedule.textContent = data.schedule_state || '—';
      const visible = new Set(data.business_visible_keys || []);
      attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
        const check = row.querySelector('[data-business-visible-v0212]');
        if (check) check.checked = visible.has(row.dataset.key || '');
      });
    } catch (err) {
      toast(err.message || '业务状态读取失败');
    }
  };

  ensureRuntimePanel();
  new MutationObserver(() => requestAnimationFrame(ensureVisibilityChecks))
    .observe(attrList, {childList:true, subtree:false});
  new MutationObserver(() => {
    if (dialog.open) requestAnimationFrame(loadRuntime);
  }).observe(dialog, {attributes:true, attributeFilter:['open']});

  const save = async button => {
    const sid = serviceId();
    if (!sid) return toast('未识别到当前业务，请关闭编辑窗口后重新打开');
    ensureVisibilityChecks();

    const template = [];
    const values = {};
    const visibleKeys = [];
    let invalid = false;
    attrList.querySelectorAll('.global-attribute-row-v028').forEach(row => {
      const key = row.dataset.key || '';
      const label = row.querySelector('.attr-label')?.value.trim() || '';
      const kindSelect = row.querySelector('.attr-kind');
      const kind = kindSelect?.disabled
        ? (kindSelect.dataset.fixedKind || kindSelect.value || 'text')
        : (kindSelect?.value || 'text');
      if (!key || !label) invalid = true;
      template.push({key, label, kind, core: !!kindSelect?.disabled});
      values[key] = row.querySelector('.attr-value')?.value || '';
      if (row.querySelector('[data-business-visible-v0212]')?.checked) visibleKeys.push(key);
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

      const mappedVisible = visibleKeys
        .map(key => attrData.key_map?.[key] || key)
        .filter((key, index, arr) => arr.indexOf(key) === index);
      const runtimeFd = new FormData();
      runtimeFd.append('csrf', csrf());
      runtimeFd.append('status', dialog.querySelector('[data-business-status-v0212]')?.value || 'active');
      runtimeFd.append('business_visible_json', JSON.stringify(mappedVisible));
      await postForm(`/services/${sid}/runtime-v0212`, runtimeFd);

      toast('业务已保存');
      location.reload();
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
