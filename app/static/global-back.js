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
  const supportsNavigationApi = Boolean(
    navigationApi
      && typeof navigationApi.back === 'function'
      && typeof navigationApi.forward === 'function'
  );

  const updateAvailability = () => {
    // Chromium and newer WebKit expose exact back/forward availability through
    // the Navigation API. Older browsers still receive working History API
    // controls; they simply stay visually enabled because the History API does
    // not expose the current position inside the browser history stack.
    if (supportsNavigationApi && typeof navigationApi.canGoBack === 'boolean') {
      backButton.disabled = !navigationApi.canGoBack;
    } else {
      backButton.disabled = false;
    }
    if (supportsNavigationApi && typeof navigationApi.canGoForward === 'boolean') {
      forwardButton.disabled = !navigationApi.canGoForward;
    } else {
      forwardButton.disabled = false;
    }
  };

  backButton.addEventListener('click', event => {
    event.preventDefault();
    if (supportsNavigationApi) {
      if (typeof navigationApi.canGoBack === 'boolean' && !navigationApi.canGoBack) return;
      navigationApi.back();
      return;
    }
    window.history.back();
  });

  forwardButton.addEventListener('click', event => {
    event.preventDefault();
    if (supportsNavigationApi) {
      if (typeof navigationApi.canGoForward === 'boolean' && !navigationApi.canGoForward) return;
      navigationApi.forward();
      return;
    }
    window.history.forward();
  });

  if (supportsNavigationApi && typeof navigationApi.addEventListener === 'function') {
    navigationApi.addEventListener('currententrychange', updateAvailability);
  }
  window.addEventListener('pageshow', updateAvailability);
  updateAvailability();
})();
