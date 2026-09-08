(() => {
  const root = document.querySelector('.v027-workspace');
  if (!root) return;

  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 160); }, 1000);
  };

  // 业务/优惠表单提交后回到原来的滚动位置，而不是跳回页面顶部。
  const scrollKey = `chen-scroll:${location.pathname}`;
  const saved = sessionStorage.getItem(scrollKey);
  if (saved) {
    try {
      const state = JSON.parse(saved);
      if (Date.now() - Number(state.at || 0) < 15000) {
        requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({top:Number(state.y || 0), behavior:'auto'})));
      }
    } catch (_) {}
    sessionStorage.removeItem(scrollKey);
  }
  root.querySelectorAll('form[data-preserve-scroll]').forEach(form => {
    form.addEventListener('submit', () => {
      sessionStorage.setItem(scrollKey, JSON.stringify({y:window.scrollY, at:Date.now()}));
    });
  });

  // 缴费工作台：列宽由当前客户独立保存。
  const list = root.querySelector('[data-column-width-url]');
  if (list) {
    const csrf = root.querySelector('[data-payment-workbench]')?.dataset.csrf || '';
    const varNames = {attr:'--col-attr', number:'--col-number', account:'--col-account', amount:'--col-amount'};
    const limits = {attr:[110,520], number:[150,760], account:[160,820], amount:[120,320]};
    const current = key => parseInt(getComputedStyle(list).getPropertyValue(varNames[key]), 10) || 180;
    const saveWidths = async () => {
      const fd = new FormData();
      fd.append('csrf', csrf);
      Object.keys(varNames).forEach(k => fd.append(k, String(current(k))));
      try {
        const r = await fetch(list.dataset.columnWidthUrl, {method:'POST', body:fd, credentials:'same-origin'});
        if (!r.ok) throw new Error();
        toast('列宽已保存');
      } catch (_) { toast('列宽保存失败'); }
    };
    list.querySelectorAll('[data-resize-col]').forEach(handle => {
      handle.addEventListener('pointerdown', e => {
        e.preventDefault(); e.stopPropagation();
        const key = handle.dataset.resizeCol;
        const startX = e.clientX;
        const startW = current(key);
        const [minW, maxW] = limits[key];
        document.body.classList.add('is-resizing-columns');
        handle.setPointerCapture?.(e.pointerId);
        const move = ev => {
          const width = Math.max(minW, Math.min(maxW, Math.round(startW + ev.clientX - startX)));
          list.style.setProperty(varNames[key], `${width}px`);
        };
        const up = ev => {
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', up);
          handle.removeEventListener('pointercancel', up);
          document.body.classList.remove('is-resizing-columns');
          handle.releasePointerCapture?.(ev.pointerId);
          saveWidths();
        };
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
        handle.addEventListener('pointercancel', up);
      });
    });
  }

  // 同一号码下多个优惠可拖动排序；只在当前号码组内改变顺序。
  root.querySelectorAll('[data-promo-sortable]').forEach(sortable => {
    let dragging = null;
    let target = null;
    let after = false;
    const group = sortable.closest('[data-promo-group]');
    const clear = () => sortable.querySelectorAll('.promo-drag-before,.promo-drag-after').forEach(x => x.classList.remove('promo-drag-before','promo-drag-after'));

    sortable.addEventListener('dragstart', e => {
      const handle = e.target.closest('.promo-drag-handle');
      if (!handle) { e.preventDefault(); return; }
      dragging = handle.closest('[data-promo-item]');
      dragging?.classList.add('promo-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    sortable.addEventListener('dragover', e => {
      if (!dragging) return;
      e.preventDefault();
      const row = e.target.closest('[data-promo-item]');
      if (!row || row === dragging) return;
      clear(); target = row;
      const rect = row.getBoundingClientRect();
      after = e.clientY > rect.top + rect.height / 2;
      row.classList.add(after ? 'promo-drag-after' : 'promo-drag-before');
    });
    sortable.addEventListener('drop', async e => {
      if (!dragging) return;
      e.preventDefault();
      if (target && target !== dragging) sortable.insertBefore(dragging, after ? target.nextSibling : target);
      clear();
      const ids = [...sortable.querySelectorAll('[data-promo-item]')].map(x => x.dataset.promoId).join(',');
      const fd = new FormData();
      fd.append('csrf', root.querySelector('[data-payment-workbench]')?.dataset.csrf || '');
      fd.append('group_key', group?.dataset.groupKey || '');
      fd.append('promotion_ids', ids);
      try {
        const r = await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
        if (!r.ok) throw new Error();
        toast('优惠顺序已保存');
      } catch (_) { toast('优惠顺序保存失败'); }
    });
    sortable.addEventListener('dragend', () => {
      dragging?.classList.remove('promo-dragging');
      clear(); dragging = target = null;
    });
  });
})();
