(() => {
  const root = document.querySelector('.v0211-workspace[data-customer-id]');
  if (!root) return;

  const hashText = text => {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return `${text.length}:${hash >>> 0}`;
  };

  const softlyMark = element => {
    if (!element || typeof element.animate !== 'function') return;
    try { element.animate([{opacity:.62},{opacity:1}], {duration:150,easing:'ease-out'}); } catch (_) {}
  };

  const panelBusy = panel => {
    if (!panel) return false;
    const focused = document.activeElement;
    if (focused && panel.contains(focused) && focused.matches('input,textarea,select,[contenteditable="true"]')) return true;
    return !!panel.querySelector('[data-chen-dirty="1"],.is-saving,.dragging,.sort-source-v0211,.v03-business-sort-source');
  };

  const copyAttributes = (target, source) => {
    [...target.attributes].forEach(attr => target.removeAttribute(attr.name));
    [...source.attributes].forEach(attr => target.setAttribute(attr.name, attr.value));
  };

  const reconcilePaymentRows = freshDocument => {
    const panel = root.querySelector('[data-customer-panel="payment"]');
    const freshPanel = freshDocument.querySelector('[data-customer-panel="payment"]');
    if (!panel || !freshPanel || panelBusy(panel)) return;

    let list = panel.querySelector('#paymentSortable');
    const freshList = freshPanel.querySelector('#paymentSortable');
    const card = panel.querySelector('[data-payment-workbench]');
    const footer = panel.querySelector('.payment-footer');
    if (!card) return;

    // If this page was loaded while the customer had no payable rows, create the
    // list only when the server now has one. Core row actions are delegated to the
    // payment workbench, so the newly inserted rows remain immediately usable.
    if (!list && freshList) {
      list = freshList.cloneNode(true);
      const empty = [...card.children].find(el => el.matches?.('p.empty'));
      empty?.remove();
      card.insertBefore(list, footer || null);
      softlyMark(list);
      return;
    }
    if (!list) return;

    const currentRows = new Map([...list.querySelectorAll(':scope > [data-payment-row]')]
      .map(row => [String(row.dataset.serviceId || ''), row]));
    const freshRows = freshList ? [...freshList.querySelectorAll(':scope > [data-payment-row]')] : [];
    const freshIds = new Set(freshRows.map(row => String(row.dataset.serviceId || '')));
    let changed = false;

    for (const freshRow of freshRows) {
      const id = String(freshRow.dataset.serviceId || '');
      if (!id) continue;
      let currentRow = currentRows.get(id);
      if (!currentRow) {
        currentRow = freshRow.cloneNode(true);
        list.appendChild(currentRow);
        changed = true;
      } else if (hashText(currentRow.outerHTML) !== hashText(freshRow.outerHTML)) {
        copyAttributes(currentRow, freshRow);
        currentRow.innerHTML = freshRow.innerHTML;
        changed = true;
      }
      list.appendChild(currentRow);
    }

    for (const [id, row] of currentRows.entries()) {
      if (id && !freshIds.has(id)) {
        row.remove();
        changed = true;
      }
    }
    if (changed) softlyMark(list);
  };

  const syncPromotionPanel = freshDocument => {
    const panel = root.querySelector('[data-customer-panel="promotions"]');
    const freshPanel = freshDocument.querySelector('[data-customer-panel="promotions"]');
    if (!panel || !freshPanel || panelBusy(panel)) return;
    const currentHead = panel.querySelector('.section-head > span');
    const freshHead = freshPanel.querySelector('.section-head > span');
    if (currentHead && freshHead && currentHead.textContent !== freshHead.textContent) {
      currentHead.textContent = freshHead.textContent;
      softlyMark(currentHead);
    }
  };

  window.addEventListener('chen:live-refresh', event => {
    const freshDocument = event.detail?.freshDocument;
    if (!freshDocument) return;
    reconcilePaymentRows(freshDocument);
    syncPromotionPanel(freshDocument);
  });

  // 全站委托处理也覆盖实时刷新新增的输入框，避免焦点回调覆盖鼠标选区。
})();
