(() => {
  const root = document.querySelector('.v029-workspace');
  const dialog = document.getElementById('businessAttributeDialog');
  const section = dialog?.querySelector('[data-service-promotions-editor]');
  const list = section?.querySelector('[data-editor-promotion-list]');
  const addButton = section?.querySelector('[data-add-editor-promotion]');
  if (!root || !dialog || !section || !list) return;

  const csrf = dialog.querySelector('[data-business-attribute-form] input[name="csrf"]')?.value || '';
  let currentServiceId = null;
  let requestSeq = 0;

  const toast = (msg) => {
    if (window.ChenToast) return window.ChenToast(msg);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'app-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 900);
  };

  const copyText = async value => {
    if (window.ChenCopyText) return window.ChenCopyText(value);
    if (!value) return false;
    try { await navigator.clipboard.writeText(value); return true; } catch (_) { return false; }
  };

  const formatDateDigits = value => {
    const d = String(value || '').replace(/\D/g, '').slice(0, 8);
    if (d.length <= 4) return d;
    if (d.length <= 6) return d.slice(0, 4) + '/' + d.slice(4);
    return d.slice(0, 4) + '/' + d.slice(4, 6) + '/' + d.slice(6);
  };

  const bindDate = input => {
    input.inputMode = 'numeric';
    input.placeholder = '1900/07/07';
    input.addEventListener('input', () => {
      input.value = formatDateDigits(input.value);
      input.setCustomValidity('');
    });
    input.addEventListener('blur', () => {
      if (!input.value) return input.setCustomValidity('');
      input.setCustomValidity(/^\d{4}\/\d{2}\/\d{2}$/.test(input.value) ? '' : '日期格式必须为 1900/07/07');
    });
  };

  const makeInput = (cls, value, placeholder='') => {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = cls;
    input.value = value || '';
    input.placeholder = placeholder;
    input.autocomplete = 'off';
    return input;
  };

  const renderRow = promo => {
    const row = document.createElement('div');
    row.className = 'editor-promo-row-v029 selectable-editors';
    row.dataset.promoId = promo.id || '';

    const name = makeInput('editor-promo-name-v029', promo.name, '优惠名称');
    const expiry = makeInput('editor-promo-expiry-v029 manual-date', promo.expiry_date, '1900/07/07');
    bindDate(expiry);
    const notes = makeInput('editor-promo-notes-v029', promo.notes, '备注');

    const actions = document.createElement('div');
    actions.className = 'editor-promo-row-actions-v029';
    const save = document.createElement('button');
    save.type = 'button';
    save.className = 'secondary small editor-promo-save-v029';
    save.textContent = '保存';
    save.dataset.editorPromoSave = '1';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'ghost small editor-promo-close-v029';
    close.textContent = promo.id ? '结束' : '取消';
    close.dataset.editorPromoClose = '1';
    actions.append(save, close);
    row.append(name, expiry, notes, actions);
    return row;
  };

  const render = promotions => {
    list.innerHTML = '';
    if (!promotions.length) {
      const empty = document.createElement('div');
      empty.className = 'editor-promo-empty-v029';
      empty.textContent = '暂无优惠';
      list.appendChild(empty);
      return;
    }
    promotions.forEach(p => list.appendChild(renderRow(p)));
  };

  const load = async serviceId => {
    currentServiceId = String(serviceId || '');
    const seq = ++requestSeq;
    list.innerHTML = '<div class="editor-promo-empty-v029">加载中…</div>';
    try {
      const r = await fetch(`/services/${currentServiceId}/promotions-editor-v029`, {credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (seq !== requestSeq || currentServiceId !== String(serviceId)) return;
      if (!r.ok || !data.ok) {
        list.innerHTML = '<div class="editor-promo-empty-v029">优惠读取失败</div>';
        return;
      }
      render(data.promotions || []);
    } catch (_) {
      if (seq === requestSeq) list.innerHTML = '<div class="editor-promo-empty-v029">优惠读取失败</div>';
    }
  };

  root.addEventListener('click', e => {
    const btn = e.target.closest('[data-open-service-editor]');
    if (!btn) return;
    const serviceId = btn.dataset.serviceId || btn.closest('[data-service-id]')?.dataset.serviceId;
    if (serviceId) load(serviceId);
  }, true);

  addButton?.addEventListener('click', () => {
    list.querySelector('.editor-promo-empty-v029')?.remove();
    const row = renderRow({id:'', name:'', expiry_date:'', notes:''});
    list.appendChild(row);
    row.querySelector('.editor-promo-name-v029')?.focus();
  });

  list.addEventListener('click', async e => {
    const row = e.target.closest('.editor-promo-row-v029');
    if (!row || !currentServiceId) return;

    if (e.target.closest('[data-editor-promo-save]')) {
      const name = row.querySelector('.editor-promo-name-v029');
      const expiry = row.querySelector('.editor-promo-expiry-v029');
      const notes = row.querySelector('.editor-promo-notes-v029');
      if (!name.value.trim()) return toast('优惠名称不能为空');
      if (!/^\d{4}\/\d{2}\/\d{2}$/.test(expiry.value)) return toast('日期格式应为 1900/07/07');
      row.classList.add('is-saving');
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('promotion_id', row.dataset.promoId || '');
      fd.append('name', name.value.trim());
      fd.append('expiry_date', expiry.value);
      fd.append('notes', notes.value || '');
      try {
        const r = await fetch(`/services/${currentServiceId}/promotions-editor-v029`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.detail || data.error || '优惠保存失败');
        row.dataset.promoId = String(data.id);
        name.value = data.name || '';
        expiry.value = data.expiry_date || '';
        notes.value = data.notes || '';
        const close = row.querySelector('[data-editor-promo-close]');
        if (close) close.textContent = '结束';
        root.dispatchEvent(new CustomEvent('chen:promotion-name-updated', {detail:{
          id:String(data.id), service_id:String(data.service_id || currentServiceId), name:data.name || ''
        }}));
        toast('已保存');
      } catch (_) {
        toast('优惠保存失败');
      } finally {
        row.classList.remove('is-saving');
      }
      return;
    }

    if (e.target.closest('[data-editor-promo-close]')) {
      const id = row.dataset.promoId;
      if (!id) {
        row.remove();
        if (!list.querySelector('.editor-promo-row-v029')) render([]);
        return;
      }
      row.classList.add('is-saving');
      const fd = new FormData(); fd.append('csrf', csrf);
      try {
        const r = await fetch(`/promotions/${id}/close-editor-v029`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.detail || data.error || '优惠结束失败');
        row.remove();
        root.querySelectorAll(`[data-promo-item][data-promo-id="${CSS.escape(String(id))}"]`).forEach(item => {
          const group = item.closest('[data-promo-group]');
          item.remove();
          if (group && !group.querySelector('[data-promo-item]')) group.remove();
        });
        if (!list.querySelector('.editor-promo-row-v029')) render([]);
        toast('已结束');
      } catch (_) {
        toast('优惠结束失败');
      } finally {
        row.classList.remove('is-saving');
      }
    }
  });

  // 优惠工作区：单击立即复制，双击进入就地编辑。双击时前两次点击可能已经完成复制，
  // 但不会阻止进入编辑，也保持了单击复制的即时响应。
  root.querySelectorAll('.promo-name-copy-v028').forEach(btn => { btn.dataset.promoNameEdit = '1'; });

  const makePromoButton = (name) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'promo-name-copy-v028';
    btn.dataset.copySilent = name;
    btn.dataset.promoNameEdit = '1';
    const strong = document.createElement('strong');
    strong.textContent = name || '未命名优惠';
    btn.appendChild(strong);
    return btn;
  };

  const updatePromotionNameEverywhere = (id, name) => {
    root.querySelectorAll(`[data-promo-item][data-promo-id="${CSS.escape(String(id))}"] .promo-name-copy-v028`).forEach(btn => {
      btn.dataset.copySilent = name;
      btn.dataset.promoNameEdit = '1';
      const strong = btn.querySelector('strong');
      if (strong) strong.textContent = name || '未命名优惠';
    });
    const editorRow = list.querySelector(`.editor-promo-row-v029[data-promo-id="${CSS.escape(String(id))}"]`);
    const editorName = editorRow?.querySelector('.editor-promo-name-v029');
    if (editorName) editorName.value = name || '';
  };

  root.addEventListener('chen:promotion-name-updated', e => {
    const d = e.detail || {};
    if (d.id) updatePromotionNameEverywhere(d.id, d.name || '');
  });

  const beginInlineRename = button => {
    const item = button.closest('[data-promo-item]');
    const id = item?.dataset.promoId;
    if (!id) return;
    const original = button.dataset.copySilent || button.textContent.trim();
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'promo-name-inline-edit-v030';
    input.value = original;
    input.autocomplete = 'off';
    input.dataset.promoId = id;
    input.dataset.original = original;
    button.replaceWith(input);
    window.ChenSelectAllInput ? window.ChenSelectAllInput(input) : (input.focus(), input.select());

    let finished = false;
    const restore = name => {
      if (finished) return;
      finished = true;
      input.replaceWith(makePromoButton(name));
    };
    const save = async () => {
      if (finished || input.dataset.saving === '1') return;
      const name = input.value.trim();
      if (!name) return restore(original);
      if (name === original) return restore(original);
      input.dataset.saving = '1';
      const fd = new FormData(); fd.append('csrf', csrf); fd.append('name', name);
      try {
        const r = await fetch(`/promotions/${id}/name-v030`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) {
          toast(data.detail || data.error || '优惠名称保存失败');
          delete input.dataset.saving;
          return window.ChenSelectAllInput?.(input);
        }
        const saved = data.name || name;
        restore(saved);
        root.dispatchEvent(new CustomEvent('chen:promotion-name-updated', {detail:{
          id:String(data.id || id), service_id:String(data.service_id || ''), name:saved
        }}));
        toast('已保存');
      } catch (_) {
        delete input.dataset.saving;
        toast('优惠名称保存失败');
        window.ChenSelectAllInput?.(input);
      }
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); save(); }
      else if (e.key === 'Escape') { e.preventDefault(); restore(original); }
    });
    input.addEventListener('blur', () => save());
  };

  document.addEventListener('click', async e => {
    const btn = e.target.closest?.('.v029-workspace .promo-name-copy-v028');
    if (!btn) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const ok = await copyText(btn.dataset.copySilent || btn.textContent.trim());
    toast(ok ? '已复制' : '复制失败');
  }, true);

  document.addEventListener('dblclick', e => {
    const btn = e.target.closest?.('.v029-workspace .promo-name-copy-v028');
    if (!btn) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    beginInlineRename(btn);
  }, true);
})();
