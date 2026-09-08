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
        if (!list.querySelector('.editor-promo-row-v029')) render([]);
        toast('已结束');
      } catch (_) {
        toast('优惠结束失败');
      } finally {
        row.classList.remove('is-saving');
      }
    }
  });
})();
