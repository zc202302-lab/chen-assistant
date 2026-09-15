(() => {
  const brand = document.querySelector('.brand');
  if (brand) {
    const path = window.location.pathname;
    const isWork = path === '/work' || path.startsWith('/work/') || path === '/search' || path.startsWith('/customers') || path.startsWith('/products') || path.startsWith('/accounts');
    const isLife = path.startsWith('/life');
    brand.href = isWork ? '/work' : (isLife ? '/life' : '/');
    brand.title = '返回晨的助手主页面';
    brand.addEventListener('click', event => {
      event.preventDefault();
      window.location.assign('/');
    });
  }

  const backButton = document.querySelector('[data-history-back]');
  const forwardButton = document.querySelector('[data-history-forward]');
  if (!backButton || !forwardButton) return;

  const navigationApi = window.navigation;
  const supportsNavigationEntries = Boolean(
    navigationApi
      && typeof navigationApi.entries === 'function'
      && typeof navigationApi.traverseTo === 'function'
      && navigationApi.currentEntry
  );

  const sameOrigin = entry => {
    if (!entry?.url) return false;
    try {
      return new URL(entry.url).origin === window.location.origin;
    } catch (_error) {
      return false;
    }
  };

  const adjacentEntry = offset => {
    if (!supportsNavigationEntries) return null;
    const entries = navigationApi.entries();
    const current = navigationApi.currentEntry;
    const entry = entries[current.index + offset];
    return sameOrigin(entry) ? entry : null;
  };

  const updateAvailability = () => {
    if (supportsNavigationEntries) {
      const backEntry = adjacentEntry(-1);
      const forwardEntry = adjacentEntry(1);
      backButton.disabled = !backEntry;
      forwardButton.disabled = !forwardEntry;
      backButton.setAttribute('aria-disabled', backEntry ? 'false' : 'true');
      forwardButton.setAttribute('aria-disabled', forwardEntry ? 'false' : 'true');
      backButton.title = backEntry ? '返回上一页' : '没有可返回的页面';
      forwardButton.title = forwardEntry ? '前进到下一页' : '没有可前进的页面';
      return;
    }

    // Older browsers do not expose the current history-stack position. Keep the
    // controls usable and let the History API use native no-op behavior at an end.
    backButton.disabled = false;
    forwardButton.disabled = false;
    backButton.setAttribute('aria-disabled', 'false');
    forwardButton.setAttribute('aria-disabled', 'false');
  };

  const traverse = offset => {
    if (supportsNavigationEntries) {
      const entry = adjacentEntry(offset);
      if (!entry) return;
      // Target the exact adjacent history entry instead of issuing a generic
      // forward/back request. This avoids a rapid back-then-forward click being
      // lost while a cross-document traversal has just restored the page.
      const result = navigationApi.traverseTo(entry.key);
      if (result?.finished && typeof result.finished.catch === 'function') {
        result.finished.catch(() => {});
      }
      return;
    }
    if (offset < 0) window.history.back();
    else window.history.forward();
  };

  backButton.addEventListener('click', event => {
    event.preventDefault();
    if (backButton.disabled) return;
    traverse(-1);
  });

  forwardButton.addEventListener('click', event => {
    event.preventDefault();
    if (forwardButton.disabled) return;
    traverse(1);
  });

  if (navigationApi && typeof navigationApi.addEventListener === 'function') {
    navigationApi.addEventListener('currententrychange', updateAvailability);
  }
  window.addEventListener('pageshow', updateAvailability);
  window.addEventListener('popstate', updateAvailability);
  updateAvailability();
})();
