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
        {duration:170, easing:'cubic-bezier(.2,.75,.25,1)'}
      );
    });
  };

  const prepareHandles = (list, handleSelector) => {
    list.querySelectorAll(handleSelector).forEach(handle => {
      handle.draggable = false;
      handle.style.touchAction = 'none';
    });
  };

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

    const autoScroll = e => {
      const edge = 76;
      let delta = 0;
      if (e.clientY < edge) delta = -Math.max(5, Math.round((edge - e.clientY) / 4));
      else if (e.clientY > window.innerHeight - edge) delta = Math.max(5, Math.round((e.clientY - (window.innerHeight - edge)) / 4));
      if (delta) window.scrollBy({top:delta, behavior:'auto'});
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
      active.distance = Math.max(active.distance, Math.hypot(e.clientX - active.startX, e.clientY - active.startY));
      moveGhost(e);
      autoScroll(e);
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      const target = hit?.closest?.(active.rowSelector);
      if (!target || target.parentElement !== active.list) return;
      const rect = target.getBoundingClientRect();
      placePlaceholder(target, e.clientY < rect.top + rect.height / 2);
    };

    const cleanupVisuals = () => {
      if (!active) return;
      active.ghost.remove();
      active.placeholder.remove();
      document.body.classList.remove('is-pointer-sorting');
      removeWindowListeners();
    };

    const finish = async (commit) => {
      if (!active) return;
      const state = active;
      active = null;
      const before = snapshotRects(state.list, state.rowSelector);
      state.list.insertBefore(state.row, state.placeholder);
      state.row.classList.remove('sort-source-v0211');
      state.row.classList.add('sort-drop-pulse-v0211');
      setTimeout(() => state.row.classList.remove('sort-drop-pulse-v0211'), 380);
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
      const paymentCols = getComputedStyle(list).getPropertyValue('--payment-cols');
      if (paymentCols) ghost.style.setProperty('--payment-cols', paymentCols);
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
        startX:e.clientX,
        startY:e.clientY,
        offsetX:e.clientX - rect.left,
        offsetY:e.clientY - rect.top,
        distance:0,
        originalOrder:directRows(list, rowSelector).map(rowIdentity).concat(rowIdentity(row)).join('|'),
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

  // 业务主列表与缴费工作列表：操作的是同一份 services.sort_order。
  const businessList = root.querySelector('[data-business-list][data-reorder-url]');
  bindPointerSort(businessList, '.business-drag-handle', '[data-business-row]', list => saveServiceOrder(list, '[data-business-row]', 'business'));

  const paymentList = document.getElementById('paymentSortable');
  bindPointerSort(paymentList, '.drag-handle', '[data-payment-row]', list => saveServiceOrder(list, '[data-payment-row]', 'payment'));

  // 全局业务属性：DOM 顺序就是保存顺序。
  const attrList = root.querySelector('[data-global-attribute-list]');
  bindPointerSort(attrList, '.global-attribute-handle', '.global-attribute-row-v028');

  // 缴费显示属性：同样用插入式排序，最终由“应用”统一保存。
  const paymentColumnList = root.querySelector('[data-payment-column-list]');
  bindPointerSort(paymentColumnList, '.payment-column-handle', '[data-payment-column-row]');

  // 优惠：同一号码、同一行动列内拖动后立即保存顺序。
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
