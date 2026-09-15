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
  const supportsNavigationAvailability = Boolean(
    navigationApi
      && typeof navigationApi.canGoBack === 'boolean'
      && typeof navigationApi.canGoForward === 'boolean'
  );

  const updateAvailability = () => {
    // The Navigation API is useful for knowing whether adjacent history entries
    // exist. Actual traversal deliberately uses the long-established History API
    // below: it is more reliable for ordinary cross-document back/forward history
    // and matches the browser controls this UI mirrors.
    if (supportsNavigationAvailability) {
      backButton.disabled = !navigationApi.canGoBack;
      forwardButton.disabled = !navigationApi.canGoForward;
    } else {
      // History API does not expose the current stack position. Keep the controls
      // usable on older browsers; a no-op at either end is native browser behavior.
      backButton.disabled = false;
      forwardButton.disabled = false;
    }
  };

  backButton.addEventListener('click', event => {
    event.preventDefault();
    if (supportsNavigationAvailability && !navigationApi.canGoBack) return;
    window.history.back();
  });

  forwardButton.addEventListener('click', event => {
    event.preventDefault();
    if (supportsNavigationAvailability && !navigationApi.canGoForward) return;
    window.history.forward();
  });

  if (navigationApi && typeof navigationApi.addEventListener === 'function') {
    navigationApi.addEventListener('currententrychange', updateAvailability);
  }
  window.addEventListener('pageshow', updateAvailability);
  window.addEventListener('popstate', updateAvailability);
  updateAvailability();
})();
