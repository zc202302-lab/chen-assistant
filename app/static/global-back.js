(() => {
  const brand = document.querySelector('.brand');
  if (brand) {
    const path = window.location.pathname;
    const isWork = path === '/work' || path.startsWith('/work/') || path === '/search' || path.startsWith('/customers') || path.startsWith('/products') || path.startsWith('/accounts');
    const isLife = path.startsWith('/life');
    // Preserve the visible workspace href for compatibility, while clicking the
    // brand itself continues to return to the outermost Chen Assistant home.
    brand.href = isWork ? '/work' : (isLife ? '/life' : '/');
    brand.title = '返回晨的助手主页面';
    brand.addEventListener('click', event => {
      event.preventDefault();
      window.location.assign('/');
    });
  }

  const button = document.querySelector('[data-global-back]');
  if (!button) return;

  // “返回上一级”必须是稳定的层级导航，而不是浏览器 history.back()。
  // history 在重定向、表单提交、PWA 或同页 replaceState 场景下可能回到
  // 一个会再次跳转到当前页的历史项，用户看到的结果就是“按钮没反应”。
  // 由服务端给出的 data-back-fallback 才是当前页面确定的上一级。
  button.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    const fallback = button.dataset.backFallback || '/';
    if (window.location.pathname + window.location.search + window.location.hash === fallback) return;
    window.location.assign(fallback);
  }, true);
})();
