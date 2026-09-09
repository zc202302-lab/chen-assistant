(() => {
  const root = document.querySelector('.v028-workspace');
  if (!root) return;

  const csrf = root.querySelector('[data-payment-workbench]')?.dataset.csrf || '';

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    console.info(msg);
  };

  const directRows = (list, selector) => [...list.children].filter(el => el.matches?.(selector));
  const rowIdentity = row => row.dataset.serviceId || row.dataset.promoId || row.dataset.key || row.querySelector('select')?.value || '';

  const snapshotRects = (list, selector) => {
    const result = new Map();
    directRows(list, selector).forEach(row => {
      if (!row.hidden) result.set(row, row.getBoundingClientRect());
    });
    return result;
  };

  const animateFlip = (before, list, selector) => {
    if (!Element.prototype.animate) return;
    directRows(list, selector).forEach(row => {
      const old = before.get(row);
      if (!old || row.hidden) return;
      const now = row.getBoundingClientRect();
      const dy = old.top - now.top;
      if (Math.abs(dy) < 1) return;
      row.animate(
        [{transform:`translateY(${dy}px)`}, {transform:'translateY(0)'}],
        {duration:150, easing:'cubic-bezier(.2,.75,.25,1)'}
      );
    });
  };

  const prepareHandles = (list, handleSelector) => {
    list.querySelectorAll(handleSelector).forEach(handle => {
      handle.draggable = false;
      handle.style.touchAction = 'none';
    });
  };

  const autoScroll = e => {
    const edge = 72;
    let delta = 0;
    if (e.clientY < edge) delta = -Math.max(4, Math.round((edge - e.clientY) / 5));
    else if (e.clientY > window.innerHeight - edge) delta = Math.max(4, Math.round((e.clientY - (window.innerHeight - edge)) / 5));
    if (delta) window.scrollBy({top:delta, behavior:'auto'});
  };

  // v0.3 business sorting: keep the real row in the list and move it directly.
  // This avoids cloning a full business row + FLIP animations on every pointer move,
  // which was the main source of the previous sticky/janky feeling.
  const bindFastBusinessSort = (list, handleSelector, rowSelector, onCommit) => {
    if (!list || list.dataset.fastBusinessSortBound === '1') return;
    list.dataset.fastBusinessSortBound = '1';
    prepareHandles(list, handleSelector);
    new MutationObserver(() => prepareHandles(list, handleSelector)).observe(list, {childList:true, subtree:true});

    let active = null;

    const cleanupTargets = () => list.querySelectorAll('.v03-sort-target').forEach(x => x.classList.remove('v03-sort-target'));
    const removeWindowListeners = () => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', cancel, true);
    };

    const move = e => {
      if (!active) return;
      e.preventDefault();
      autoScroll(e);
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const target = hit?.closest?.(rowSelector);
      if (!target || target === active.row || target.parentElement !== list || target.hidden) return;
      const rect = target.getBoundingClientRect();
      const beforeTarget = e.clientY < rect.top + rect.height / 2;
      const before = snapshotRects(list, rowSelector);
      if (beforeTarget) list.insertBefore(active.row, target);
      else list.insertBefore(active.row, target.nextSibling);
      cleanupTargets();
      target.classList.add('v03-sort-target');
      // One short animation per actual row crossing, not on every pointermove.
      animateFlip(before, list, rowSelector);
      active.moved = true;
    };

    const finish = async commit => {
      if (!active) return;
      const state = active;
      active = null;
      cleanupTargets();
      state.row.classList.remove('v03-business-sort-source');
      document.body.classList.remove('is-pointer-sorting');
      removeWindowListeners();

      if (!commit) {
        if (state.originalNext && state.originalNext.parentElement === list) list.insertBefore(state.row, state.originalNext);
        else list.appendChild(state.row);
        return;
      }

      const newOrder = directRows(list, rowSelector).map(rowIdentity).join('|');
      if (!state.moved || newOrder === state.originalOrder || !onCommit) return;
      list.classList.add('sort-saving-v0211');
      try {
        await onCommit(list);
        state.row.classList.add('sort-drop-pulse-v0211');
        setTimeout(() => state.row.classList.remove('sort-drop-pulse-v0211'), 260);
      } catch (_) {
        toast('排序保存失败，请刷新后重试');
      } finally {
        list.classList.remove('sort-saving-v0211');
      }
    };

    const up = e => {
      if (!active) return;
      e.preventDefault();
      finish(true);
    };
    const cancel = () => finish(false);

    list.addEventListener('pointerdown', e => {
      if (e.button !== undefined && e.button !== 0) return;
      const handle = e.target.closest(handleSelector);
      if (!handle || !list.contains(handle)) return;
      const row = handle.closest(rowSelector);
      if (!row || row.parentElement !== list || row.hidden) return;
      e.preventDefault();
      e.stopPropagation();
      active = {
        row,
        originalNext: row.nextSibling,
        originalOrder: directRows(list, rowSelector).map(rowIdentity).join('|'),
        moved: false,
      };
      row.classList.add('v03-business-sort-source');
      document.body.classList.add('is-pointer-sorting');
      window.addEventListener('pointermove', move, true);
      window.addEventListener('pointerup', up, true);
      window.addEventListener('pointercancel', cancel, true);
    }, true);
  };

  // Generic inserted-placeholder sorter remains for attribute templates and promotions.
  const bindPointerSort = (list, handleSelector, rowSelector, onCommit) => {
    if (!list || list.dataset.pointerSortBound === '1') return;
    list.dataset.pointerSortBound = '1';
    prepareHandles(list, handleSelector);
    new MutationObserver(() => prepareHandles(list, handleSelector)).observe(list, {childList:true, subtree:true});

    let active = null;

    const removeWindowListeners = () => {
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('pointercancel', cancel, true);
    };

    const moveGhost = e => {
      if (!active) return;
      active.ghost.style.left = `${Math.round(e.clientX - active.offsetX)}px`;
      active.ghost.style.top = `${Math.round(e.clientY - active.offsetY)}px`;
    };

    const placePlaceholder = (target, beforeTarget) => {
      if (!active || !target || target.parentElement !== active.list) return;
      const before = snapshotRects(active.list, active.rowSelector);
      const ref = beforeTarget ? target : target.nextSibling;
      if (ref === active.placeholder || (!beforeTarget && target.nextSibling === active.placeholder)) return;
      active.list.insertBefore(active.placeholder, ref);
      animateFlip(before, active.list, active.rowSelector);
      active.placeholder.classList.remove('insert-before','insert-after');
      active.placeholder.classList.add(beforeTarget ? 'insert-before' : 'insert-after');
    };

    const move = e => {
      if (!active) return;
      e.preventDefault();
      moveGhost(e);
      autoScroll(e);
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const target = hit?.closest?.(active.rowSelector);
      if (!target || target.parentElement !== active.list) return;
      const rect = target.getBoundingClientRect();
      placePlaceholder(target, e.clientY < rect.top + rect.height / 2);
    };

    const finish = async commit => {
      if (!active) return;
      const state = active;
      active = null;
      const before = snapshotRects(state.list, state.rowSelector);

      if (commit) state.list.insertBefore(state.row, state.placeholder);
      else if (state.originalNext && state.originalNext.parentElement === state.list) state.list.insertBefore(state.row, state.originalNext);
      else state.list.appendChild(state.row);

      state.row.classList.remove('sort-source-v0211');
      if (commit) {
        state.row.classList.add('sort-drop-pulse-v0211');
        setTimeout(() => state.row.classList.remove('sort-drop-pulse-v0211'), 300);
      }
      state.ghost.remove();
      state.placeholder.remove();
      document.body.classList.remove('is-pointer-sorting');
      removeWindowListeners();
      animateFlip(before, state.list, state.rowSelector);

      if (!commit || !state.onCommit) return;
      const newOrder = directRows(state.list, state.rowSelector).map(rowIdentity).join('|');
      if (newOrder === state.originalOrder) return;
      state.list.classList.add('sort-saving-v0211');
      try {
        await state.onCommit(state.list);
      } catch (_) {
        toast('排序保存失败，请刷新后重试');
      } finally {
        state.list.classList.remove('sort-saving-v0211');
      }
    };

    const up = e => {
      if (!active) return;
      e.preventDefault();
      finish(true);
    };
    const cancel = () => finish(false);

    list.addEventListener('pointerdown', e => {
      if (e.button !== undefined && e.button !== 0) return;
      const handle = e.target.closest(handleSelector);
      if (!handle || !list.contains(handle)) return;
      const row = handle.closest(rowSelector);
      if (!row || row.parentElement !== list || row.hidden) return;
      e.preventDefault();
      e.stopPropagation();

      const rect = row.getBoundingClientRect();
      const originalOrder = directRows(list, rowSelector).map(rowIdentity).join('|');
      const originalNext = row.nextSibling;
      const placeholder = document.createElement('div');
      placeholder.className = 'sort-insertion-placeholder-v0211';
      placeholder.style.height = `${Math.max(32, rect.height)}px`;
      placeholder.style.width = `${rect.width}px`;
      list.insertBefore(placeholder, row);

      const ghost = row.cloneNode(true);
      ghost.classList.add('sort-drag-ghost-v0211');
      ghost.removeAttribute('id');
      Object.assign(ghost.style, {
        position:'fixed',
        width:`${rect.width}px`,
        height:`${rect.height}px`,
        left:`${rect.left}px`,
        top:`${rect.top}px`,
        margin:'0',
        zIndex:'10000',
        pointerEvents:'none',
      });
      document.body.appendChild(ghost);
      row.classList.add('sort-source-v0211');
      row.remove();

      active = {
        list,
        row,
        rowSelector,
        placeholder,
        ghost,
        onCommit,
        offsetX:e.clientX - rect.left,
        offsetY:e.clientY - rect.top,
        originalOrder,
        originalNext,
      };
      moveGhost(e);
      document.body.classList.add('is-pointer-sorting');
      window.addEventListener('pointermove', move, true);
      window.addEventListener('pointerup', up, true);
      window.addEventListener('pointercancel', cancel, true);
    }, true);
  };

  const saveServiceOrder = async (list, rowSelector, source) => {
    const ids = directRows(list, rowSelector).map(row => row.dataset.serviceId).filter(Boolean);
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('service_ids', ids.join(','));
    const response = await fetch(list.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '排序保存失败');
    root.dispatchEvent(new CustomEvent('chen:service-order-updated', {detail:{source, order:data.order || ids}}));
  };

  // v0.3: only the business list is manually sortable. The payment list follows the
  // exact same services.sort_order and therefore has no independent drag behavior.
  const businessList = root.querySelector('[data-business-list][data-reorder-url]');
  bindFastBusinessSort(
    businessList,
    '.business-drag-handle',
    '[data-business-row]',
    list => saveServiceOrder(list, '[data-business-row]', 'business'),
  );

  // Global business attributes keep their dedicated editor order.
  const attrList = root.querySelector('[data-global-attribute-list]');
  bindPointerSort(attrList, '.global-attribute-handle', '.global-attribute-row-v028');

  // Legacy payment-column drag binding is intentionally not used by v0.3; the dialog
  // is now numeric-order based. Keeping this call harmlessly supports old pages only.
  const paymentColumnList = root.querySelector('[data-payment-column-list]');
  bindPointerSort(paymentColumnList, '.payment-column-handle', '[data-payment-column-row]');

  root.querySelectorAll('[data-promo-sortable]').forEach(list => {
    bindPointerSort(list, '.promo-drag-handle', '[data-promo-item]', async sortable => {
      const group = sortable.closest('[data-promo-group]');
      const ids = directRows(sortable, '[data-promo-item]').map(x => x.dataset.promoId).filter(Boolean);
      const fd = new FormData();
      fd.append('csrf', csrf);
      fd.append('group_key', group?.dataset.groupKey || '');
      fd.append('promotion_ids', ids.join(','));
      const response = await fetch(sortable.dataset.reorderUrl, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '优惠排序保存失败');
    });
  });
})();
