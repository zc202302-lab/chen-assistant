(() => {
  const brand = document.querySelector('.brand');
  if (brand) {
    const path = window.location.pathname;
    const isWork = path === '/work' || path === '/search' || path.startsWith('/customers') || path.startsWith('/products') || path.startsWith('/accounts');
    const isLife = path.startsWith('/life');
    // Preserve the visible workspace href for compatibility, but the actual click
    // always returns to the outermost Chen Assistant home as requested.
    brand.href = isWork ? '/work' : (isLife ? '/life' : '/');
    brand.title = '返回晨的助手主页面';
    brand.addEventListener('click', event => {
      event.preventDefault();
      window.location.assign('/');
    });
  }

  const button = document.querySelector('[data-global-back]');
  if (!button) return;

  const hasSameOriginReferrer = () => {
    if (!document.referrer) return false;
    try {
      return new URL(document.referrer).origin === window.location.origin;
    } catch (_) {
      return false;
    }
  };

  button.addEventListener('click', () => {
    const fallback = button.dataset.backFallback || '/';
    if (window.history.length > 1 && hasSameOriginReferrer()) {
      window.history.back();
      return;
    }
    window.location.assign(fallback);
  });
})();
