(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  if (!customerId) return;

  const nativeFetch = window.fetch.bind(window);
  let refreshTimer = 0;
  let refreshing = false;
  let lastHtmlSignature = '';

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
    try {
      element.animate([{opacity: 0.58}, {opacity: 1}], {duration: 150, easing: 'ease-out'});
    } catch (_) {}
  };

  const syncText = (selector, freshDocument) => {
    const current = document.querySelector(selector);
    const fresh = freshDocument.querySelector(selector);
    if (!current || !fresh) return false;
    const next = fresh.textContent;
    if (current.textContent === next) return false;
    current.textContent = next;
    softlyMark(current);
    return true;
  };

  const syncCopyValue = (selector, freshDocument) => {
    const current = document.querySelector(selector);
    const fresh = freshDocument.querySelector(selector);
    if (!current || !fresh) return;
    const value = fresh.dataset.copy || '';
    if (current.dataset.copy !== value) current.dataset.copy = value;
  };

  const syncInput = (selector, freshDocument) => {
    const current = document.querySelector(selector);
    const fresh = freshDocument.querySelector(selector);
    if (!current || !fresh || document.activeElement === current || current.dataset.chenDirty === '1') return;
    if (current.type === 'checkbox') {
      current.checked = fresh.checked;
      return;
    }
    if (current.value !== fresh.value) current.value = fresh.value;
  };

  const panelBusy = panel => {
    if (!panel) return false;
    if (document.activeElement && panel.contains(document.activeElement)) return true;
    return !!panel.querySelector('[data-chen-dirty="1"],.is-saving,.sort-source-v0211,.v03-business-sort-source');
  };

  const syncTaskPreview = freshDocument => {
    const currentCard = document.querySelector('.v023-task-card');
    const freshCard = freshDocument.querySelector('.v023-task-card');
    if (!currentCard || !freshCard) return;

    syncText('.v023-task-head .tab-text-link', freshDocument);
    const addButton = currentCard.querySelector('.v023-add-task');
    if (!addButton) return;

    const currentRows = [...currentCard.querySelectorAll('.v023-task-line,.v023-task-empty')];
    const freshRows = [...freshCard.querySelectorAll('.v023-task-line,.v023-task-empty')];
    const currentSig = currentRows.map(row => row.textContent.trim()).join('\n');
    const freshSig = freshRows.map(row => row.textContent.trim()).join('\n');
    if (currentSig === freshSig) return;

    currentRows.forEach(row => row.remove());
    freshRows.forEach(row => addButton.before(row.cloneNode(true)));
    softlyMark(currentCard);
  };

  const syncPromotionBadge = freshDocument => {
    const button = document.querySelector('[data-customer-tab="promotions"]');
    const freshButton = freshDocument.querySelector('[data-customer-tab="promotions"]');
    if (!button || !freshButton) return;
    const currentBadge = button.querySelector('.tab-count');
    const freshBadge = freshButton.querySelector('.tab-count');
    if (!freshBadge) {
      currentBadge?.remove();
      return;
    }
    if (!currentBadge) {
      button.appendChild(freshBadge.cloneNode(true));
      softlyMark(button);
      return;
    }
    if (currentBadge.textContent !== freshBadge.textContent) {
      currentBadge.textContent = freshBadge.textContent;
      softlyMark(currentBadge);
    }
  };

  const syncCustomerHeader = freshDocument => {
    syncText('.v023-name-line h1', freshDocument);
    syncText('.v023-identity-strip > div:nth-child(1) b', freshDocument);
    syncText('.v023-identity-strip > div:nth-child(2) b', freshDocument);
    syncCopyValue('.v023-name-line .copy-btn', freshDocument);
    syncCopyValue('.v023-identity-strip > div:nth-child(1) .copy-btn', freshDocument);
    syncCopyValue('.v023-identity-strip > div:nth-child(2) .copy-btn', freshDocument);

    syncInput('.v023-customer-edit input[name="name"]', freshDocument);
    syncInput('.v023-customer-edit input[name="group_code"]', freshDocument);
    syncInput('.v023-customer-edit input[name="tax_id"]', freshDocument);
    syncInput('.v023-customer-edit textarea[name="relation_summary"]', freshDocument);
    syncInput('.v023-customer-edit input[name="payment_enabled"]', freshDocument);

    const freshTitle = freshDocument.querySelector('title')?.textContent?.trim();
    if (freshTitle && document.title !== freshTitle) document.title = freshTitle;
  };

  const syncPaymentSummary = freshDocument => {
    [
      '#requiredCount', '#pendingCount', '#paymentGrandTotal', '#paymentReadiness',
      '#paymentRunLabel',
    ].forEach(selector => syncText(selector, freshDocument));

    const currentTxt = document.getElementById('paymentTxtButton');
    const freshTxt = freshDocument.getElementById('paymentTxtButton');
    if (currentTxt && freshTxt) {
      for (const name of ['class', 'aria-disabled', 'href']) {
        const value = freshTxt.getAttribute(name);
        if (value === null) currentTxt.removeAttribute(name);
        else currentTxt.setAttribute(name, value);
      }
    }

    window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
  };

  // Contacts/tasks/visits contain only simple document-level interactions. Their
  // card contents can be replaced in-place without losing the tab element,
  // scroll position or global event delegation.
  const syncSimplePanel = (name, freshDocument) => {
    const currentPanel = root.querySelector(`[data-customer-panel="${name}"]`);
    const freshPanel = freshDocument.querySelector(`[data-customer-panel="${name}"]`);
    if (!currentPanel || !freshPanel || panelBusy(currentPanel)) return;
    const currentCard = currentPanel.querySelector(':scope > .card, :scope > section.card');
    const freshCard = freshPanel.querySelector(':scope > .card, :scope > section.card');
    if (!currentCard || !freshCard) return;
    if (hashText(currentCard.innerHTML) === hashText(freshCard.innerHTML)) return;
    currentCard.innerHTML = freshCard.innerHTML;
    softlyMark(currentCard);
  };

  const copyAttributes = (target, source, keep = new Set()) => {
    const preserved = new Map();
    keep.forEach(name => {
      if (target.hasAttribute(name)) preserved.set(name, target.getAttribute(name));
    });
    [...target.attributes].forEach(attr => target.removeAttribute(attr.name));
    [...source.attributes].forEach(attr => target.setAttribute(attr.name, attr.value));
    preserved.forEach((value, name) => target.setAttribute(name, value));
  };

  // Keep the business list container itself alive because its drag/filter
  // controllers are bound to that node. Reconcile keyed service rows inside it.
  const syncBusinessRows = freshDocument => {
    const currentPanel = root.querySelector('[data-customer-panel="services"]');
    const freshPanel = freshDocument.querySelector('[data-customer-panel="services"]');
    const currentList = currentPanel?.querySelector('[data-business-list]');
    const freshList = freshPanel?.querySelector('[data-business-list]');
    if (!currentPanel || !freshPanel || !currentList || !freshList || panelBusy(currentPanel)) return;

    const currentRows = new Map([...currentList.querySelectorAll(':scope > [data-business-row]')]
      .map(row => [String(row.dataset.serviceId || ''), row]));
    const freshRows = [...freshList.querySelectorAll(':scope > [data-business-row]')];
    const freshIds = new Set(freshRows.map(row => String(row.dataset.serviceId || '')));
    let changed = false;

    for (const freshRow of freshRows) {
      const id = String(freshRow.dataset.serviceId || '');
      if (!id) continue;
      let currentRow = currentRows.get(id);
      if (!currentRow) {
        currentRow = freshRow.cloneNode(true);
        currentList.appendChild(currentRow);
        changed = true;
      } else if (hashText(currentRow.outerHTML) !== hashText(freshRow.outerHTML)) {
        const wasHidden = currentRow.hidden;
        copyAttributes(currentRow, freshRow, new Set(wasHidden ? ['hidden'] : []));
        currentRow.innerHTML = freshRow.innerHTML;
        if (wasHidden) currentRow.hidden = true;
        changed = true;
      }
      // Server order is authoritative. appendChild moves existing nodes without
      // recreating the sortable list or its listeners.
      currentList.appendChild(currentRow);
    }

    for (const [id, row] of currentRows.entries()) {
      if (id && !freshIds.has(id)) {
        row.remove();
        changed = true;
      }
    }

    if (changed) {
      const visibleCount = currentList.querySelectorAll(':scope > [data-business-row]:not([hidden])').length;
      const counter = document.getElementById('businessVisibleCount');
      if (counter) counter.textContent = String(visibleCount);
      softlyMark(currentList);
    }
  };

  const syncFromDocument = freshDocument => {
    const freshRoot = freshDocument.querySelector('.v0211-workspace');
    if (!freshRoot || freshRoot.dataset.customerId !== customerId) return;

    syncCustomerHeader(freshDocument);
    syncTaskPreview(freshDocument);
    syncPromotionBadge(freshDocument);
    syncPaymentSummary(freshDocument);
    syncBusinessRows(freshDocument);
    syncSimplePanel('contacts', freshDocument);
    syncSimplePanel('tasks', freshDocument);
    syncSimplePanel('visits', freshDocument);

    window.dispatchEvent(new CustomEvent('chen:live-refresh', {
      detail: {customerId, freshDocument},
    }));
  };

  const refreshNow = async () => {
    if (refreshing || document.hidden) return;
    if (document.querySelector('dialog[open]')) return;
    refreshing = true;
    try {
      const response = await nativeFetch(location.href, {
        method: 'GET',
        credentials: 'same-origin',
        cache: 'no-store',
        headers: {'X-Chen-Live-Refresh': '1'},
      });
      if (!response.ok) return;
      const html = await response.text();
      const signature = hashText(html);
      if (signature === lastHtmlSignature) return;
      lastHtmlSignature = signature;
      const freshDocument = new DOMParser().parseFromString(html, 'text/html');
      syncFromDocument(freshDocument);
    } catch (_) {
      // Enhancement only: existing mature page behavior remains the fallback.
    } finally {
      refreshing = false;
    }
  };

  const scheduleRefresh = (delay = 180) => {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refreshNow, delay);
  };

  window.ChenLiveRefresh = {
    refresh: () => scheduleRefresh(0),
    refreshSoon: () => scheduleRefresh(180),
  };

  root.addEventListener('input', event => {
    const field = event.target.closest?.('input,textarea,select');
    if (field) field.dataset.chenDirty = '1';
  }, true);
  root.addEventListener('change', event => {
    const field = event.target.closest?.('input,textarea,select');
    if (field) field.dataset.chenDirty = '1';
  }, true);
  root.addEventListener('submit', event => {
    event.target.querySelectorAll?.('[data-chen-dirty="1"]').forEach(field => delete field.dataset.chenDirty);
  }, true);

  // Observe all existing AJAX writes without changing their own success/error flow.
  window.fetch = async (input, init = {}) => {
    const response = await nativeFetch(input, init);
    try {
      const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
      const url = new URL(input instanceof Request ? input.url : String(input), location.href);
      if (response.ok && url.origin === location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        scheduleRefresh(220);
        setTimeout(() => scheduleRefresh(0), 800);
      }
    } catch (_) {}
    return response;
  };

  const interval = setInterval(() => {
    if (!document.hidden) refreshNow();
  }, 8000);
  window.addEventListener('focus', () => scheduleRefresh(80));
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) scheduleRefresh(80);
  });
  window.addEventListener('pagehide', () => clearInterval(interval), {once: true});

  const restoreKey = `chen-reload-position:${location.pathname}`;
  const navEntry = performance.getEntriesByType?.('navigation')?.[0];
  if (navEntry?.type === 'reload') {
    try {
      const saved = JSON.parse(sessionStorage.getItem(restoreKey) || 'null');
      if (saved && Date.now() - Number(saved.at || 0) < 30000) {
        requestAnimationFrame(() => requestAnimationFrame(() => window.scrollTo({top: Number(saved.y || 0), behavior: 'auto'})));
      }
    } catch (_) {}
  }
  window.addEventListener('beforeunload', () => {
    try { sessionStorage.setItem(restoreKey, JSON.stringify({y: window.scrollY, at: Date.now()})); } catch (_) {}
  });

  scheduleRefresh(500);
})();
