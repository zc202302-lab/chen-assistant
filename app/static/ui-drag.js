(() => {
  const workspace = document.querySelector('.v028-workspace');
  if (!workspace) return;

  const csrf = workspace.querySelector('[data-payment-workbench]')?.dataset.csrf || '';

  const bindPointerSort = (list, handleSelector, rowSelector, onCommit) => {
    if (!list || list.dataset.pointerSortBound === '1') return;
    list.dataset.pointerSortBound = '1';
    list.querySelectorAll(handleSelector).forEach(h => {
      h.draggable = false;
      h.style.touchAction = 'none';
    });

    let active = null;
    const cleanup = () => {
      if (!active) return;
      active.row.classList.remove('dragging');
      document.body.classList.remove('is-pointer-sorting');
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', cancel, true);
    };
    const move = e => {
      if (!active) return;
      e.preventDefault();
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const target = hit?.closest?.(rowSelector);
      if (!target || target === active.row || target.parentElement !== list) return;
      const rect = target.getBoundingClientRect();
      const before = e.clientY < rect.top + rect.height / 2;
      if (before) list.insertBefore(active.row, target);
      else list.insertBefore(active.row, target.nextSibling);
    };
    const finish = async () => {
      if (!active) return;
      const state = active;
      cleanup();
      active = null;
      if (onCommit) await onCommit(state.list);
    };
    const up = e => { e.preventDefault(); finish(); };
    const cancel = () => { cleanup(); active = null; };

    list.addEventListener('pointerdown', e => {
      const handle = e.target.closest(handleSelector);
      if (!handle || !list.contains(handle)) return;
      const row = handle.closest(rowSelector);
      if (!row || row.parentElement !== list) return;
      e.preventDefault();
      active = {list, row};
      row.classList.add('dragging');
      document.body.classList.add('is-pointer-sorting');
      window.addEventListener('pointermove', move, true);
      window.addEventListener('pointerup', up, true);
      window.addEventListener('pointercancel', cancel, true);
    }, true);
  };

  // 业务属性：DOM 顺序即保存顺序，点击“保存”时由 v028.js 写入全局模板。
  const attrList = document.querySelector('[data-global-attribute-list]');
  if (attrList) {
    const observer = new MutationObserver(() => {
      attrList.querySelectorAll('.global-attribute-handle').forEach(h => {
        h.draggable = false;
        h.style.touchAction = 'none';
      });
    });
    observer.observe(attrList, {childList:true});
    bindPointerSort(attrList, '.global-attribute-handle', '.global-attribute-row-v028');
  }

  // 优惠：同号码组内松手即保存顺序。
  workspace.querySelectorAll('[data-promo-sortable]').forEach(list => {
    bindPointerSort(list, '.promo-drag-handle', '[data-promo-item]', async sortable => {
      const group = sortable.closest('[data-promo-group]');
      const ids = [...sortable.querySelectorAll('[data-promo-item]')].map(x => x.dataset.promoId).join(',');
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('group_key', group?.dataset.groupKey || '');
      fd.append('promotion_ids', ids);
      try {
        await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
      } catch (_) {}
    });
  });
})();
