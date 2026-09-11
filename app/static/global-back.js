(() => {
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
