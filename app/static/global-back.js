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
    if (supportsNavigationAvailability) {
      const hasBack = navigationApi.canGoBack;
      const hasForward = navigationApi.canGoForward;
      backButton.disabled = !hasBack;
      forwardButton.disabled = !hasForward;
      backButton.setAttribute('aria-disabled', hasBack ? 'false' : 'true');
      forwardButton.setAttribute('aria-disabled', hasForward ? 'false' : 'true');
      backButton.title = hasBack ? '返回上一页' : '没有可返回的页面';
      forwardButton.title = hasForward ? '前进到下一页' : '没有可前进的页面';
      return;
    }

    // Older browsers do not expose reliable history availability. Keep the
    // controls enabled and let the native History API decide whether traversal
    // is possible instead of inventing a parallel history stack.
    backButton.disabled = false;
    forwardButton.disabled = false;
    backButton.setAttribute('aria-disabled', 'false');
    forwardButton.setAttribute('aria-disabled', 'false');
    backButton.title = '返回上一页';
    forwardButton.title = '前进到下一页';
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