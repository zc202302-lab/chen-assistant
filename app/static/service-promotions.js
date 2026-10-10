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
  let promotionsChanged = false;
  dialog.addEventListener('close', () => {
    if (!promotionsChanged) return;
    promotionsChanged = false;
    if (root.querySelector('[data-full-promotions]')?.open) sessionStorage.setItem(`chen:full-promotions:${root.dataset.customerId}`, '1');
    location.reload();
  });

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

    const slot = makeInput('editor-promo-slot', String(promo.slot_number || ''), '1～5');
    slot.type = 'number'; slot.min = '1'; slot.max = '5'; slot.step = '1';
    slot.setAttribute('aria-label', '优惠编号');
    const name = makeInput('editor-promo-name-v029', promo.name, '优惠名称');
    const expiry = makeInput('editor-promo-expiry-v029', promo.expiry_date, '1900/07/07');
    expiry.setAttribute('aria-label', '到期时间');
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
    row.append(slot, name, expiry, notes, actions);
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

  root.addEventListener('chen:service-editor-opened', e => load(e.detail.service_id));

  addButton?.addEventListener('click', () => {
    list.querySelector('.editor-promo-empty-v029')?.remove();
    const used = new Set([...list.querySelectorAll('.editor-promo-slot')].map(el => Number(el.value)));
    const next = [1,2,3,4,5].find(n => !used.has(n));
    if (!next) return toast('优惠1～5已全部占用');
    const row = renderRow({id:'', slot_number:next, name:'', expiry_date:'', notes:''});
    list.appendChild(row);
    row.querySelector('.editor-promo-name-v029')?.focus();
  });

  // 捕获阶段统一处理业务编辑器中的优惠操作。这样即使其他工作区脚本在冒泡阶段
  // 处理点击，也不会吞掉“保存/结束”动作，保证业务模块 -> 优惠模块的反向同步可靠。
  const popover = document.createElement('div');
  popover.className = 'promotion-content-popover';
  popover.id = 'promotionContentPopover';
  popover.setAttribute('role', 'region');
  popover.setAttribute('aria-label', '完整优惠内容');
  popover.hidden = true;
  document.body.appendChild(popover);
  let popoverButton = null;
  const closePopover = () => {
    popover.hidden = true;
    popoverButton?.setAttribute('aria-expanded', 'false');
    popoverButton = null;
  };
  const togglePopover = btn => {
    if (popoverButton === btn) return closePopover();
    closePopover();
    popoverButton = btn;
    btn.setAttribute('aria-controls', popover.id);
    btn.setAttribute('aria-expanded', 'true');
    popover.textContent = btn.dataset.copySilent || btn.textContent.trim();
    popover.hidden = false;
    const anchor = btn.getBoundingClientRect();
    const box = popover.getBoundingClientRect();
    popover.style.left = `${Math.max(12, Math.min(anchor.left, innerWidth-box.width-12))}px`;
    const below = anchor.bottom + 6;
    popover.style.top = `${Math.max(12, below+box.height <= innerHeight-12 ? below : anchor.top-box.height-6)}px`;
  };
  document.addEventListener('click', e => {
    if (!e.target.closest?.('.promo-name-copy-v028') && !popover.contains(e.target)) closePopover();
  }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePopover(); });
  window.addEventListener('resize', closePopover);
  document.addEventListener('scroll', e => { if (!popover.contains(e.target)) closePopover(); }, true);

  document.addEventListener('click', async e => {
    const saveButton = e.target.closest?.('[data-editor-promo-save]');
    const closeButton = e.target.closest?.('[data-editor-promo-close]');
    if (!saveButton && !closeButton) return;
    const row = e.target.closest?.('.editor-promo-row-v029');
    if (!row || !list.contains(row) || !currentServiceId) return;
    e.preventDefault();
    e.stopPropagation();

    if (saveButton) {
      const name = row.querySelector('.editor-promo-name-v029');
      const expiry = row.querySelector('.editor-promo-expiry-v029');
      const notes = row.querySelector('.editor-promo-notes-v029');
      if (!name.value.trim()) return toast('优惠名称不能为空');
      const slot = row.querySelector('.editor-promo-slot');
      if (!slot.checkValidity() || !slot.value) return toast('优惠编号须为1～5');
      row.classList.add('is-saving');
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('promotion_id', row.dataset.promoId || '');
      fd.append('name', name.value.trim());
      fd.append('expiry_date', expiry.value);
      fd.append('slot_number', slot.value);
      fd.append('notes', notes.value || '');
      try {
        const r = await fetch(`/services/${currentServiceId}/promotions-editor-v029`, {method:'POST', body:fd, credentials:'same-origin'});
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.detail || data.error || '优惠保存失败');
        row.dataset.promoId = String(data.id);
        promotionsChanged = true;
        name.value = data.name || '';
        expiry.value = data.expiry_date || '';
        notes.value = data.notes || '';
        slot.value = String(data.slot_number);
        [...list.querySelectorAll('.editor-promo-row-v029')]
          .sort((a,b) => Number(a.querySelector('.editor-promo-slot').value) - Number(b.querySelector('.editor-promo-slot').value))
          .forEach(item => list.appendChild(item));
        root.dispatchEvent(new CustomEvent('chen:promotions-updated'));
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

    if (closeButton) {
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
        promotionsChanged = true;
        row.remove();
        root.querySelectorAll(`[data-promo-item][data-promo-id="${CSS.escape(String(id))}"]`).forEach(item => {
          const group = item.closest('[data-promo-group]');
          item.remove();
          if (group && !group.querySelector('[data-promo-item]')) group.remove();
        });
        if (!list.querySelector('.editor-promo-row-v029')) render([]);
        root.dispatchEvent(new CustomEvent('chen:promotions-updated'));
        toast('已结束');
      } catch (_) {
        toast('优惠结束失败');
      } finally {
        row.classList.remove('is-saving');
      }
    }
  }, true);

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
    togglePopover(btn);
    const ok = await copyText(btn.dataset.copySilent || btn.textContent.trim());
    toast(ok ? '已复制' : '复制失败');
  }, true);

  document.addEventListener('dblclick', e => {
    const btn = e.target.closest?.('.v029-workspace .promo-name-copy-v028');
    if (!btn) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    closePopover();
    beginInlineRename(btn);
  }, true);
  const full = root.querySelector('[data-full-promotions]');
  let tableRequest = 0;
  const refreshTable = async () => {
    if (!full) return;
    const seq = ++tableRequest;
    const error = full.querySelector('[data-full-promotions-error]');
    try {
      const response = await fetch(full.dataset.tableUrl, {credentials:'same-origin', cache:'no-store'});
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error('load failed');
      if (seq !== tableRequest) return;
      const body = full.querySelector('tbody');
      const fragment = document.createDocumentFragment();
      data.rows.forEach((cells, index) => {
        const tr = document.createElement('tr');
        cells.forEach((value, col) => {
          const td=document.createElement('td');
          const content=document.createElement(col === 0 ? 'button' : 'span');
          content.className = col === 0 ? 'full-promotion-number' : 'full-promotion-cell';
          content.textContent = value;
          if (col === 0) {
            content.type='button'; content.dataset.promoServiceEditor='1';
            content.dataset.serviceId=String(data.service_ids[index]); content.title='双击编辑属性';
          }
          td.appendChild(content); tr.appendChild(td);
        });
        fragment.appendChild(tr);
      });
      body.replaceChildren(fragment);
      full.querySelector('summary span').textContent = `${data.rows.length} 行`;
      error.textContent = '';
    } catch (_) {
      if (seq === tableRequest) error.textContent = '全量优惠刷新失败，请重试';
    }
  };
  full?.addEventListener('toggle', () => { if (full.open) refreshTable(); });
  const fullKey = `chen:full-promotions:${root.dataset.customerId}`;
  if (full && sessionStorage.getItem(fullKey) === '1') {
    sessionStorage.removeItem(fullKey);
    full.open = true;
  }
  root.addEventListener('chen:promotions-updated', refreshTable);
  root.addEventListener('chen:promotion-name-updated', refreshTable);
  root.addEventListener('chen:service-properties-updated', e => {
    closePopover();
    Object.entries(e.detail.rows || {}).forEach(([sid, payload]) => {
      root.querySelectorAll(`.promo-number-copy-v028[data-service-id="${CSS.escape(sid)}"]`).forEach(btn => {
        const number = payload.number || payload.account || '';
        btn.dataset.copySilent = number;
        btn.querySelector('strong').textContent = number;
        const values = Object.fromEntries((payload.attributes || []).map(a => [a.key, a.value === '—' ? '' : a.value]));
        btn.querySelector('small').textContent = [values.service_type, values.holder_name].filter(Boolean).join(' · ');
        const group = btn.closest('[data-promo-group]');
        if (group) group.dataset.groupKey = `${group.dataset.groupKey.split(':')[0]}:${number || `service-${sid}`}`;
      });
    });
    refreshTable();
  });
  root.querySelector('[data-customer-tab="promotions"]')?.addEventListener('click', refreshTable);
})();
