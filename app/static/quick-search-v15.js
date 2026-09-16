(() => {
  const trigger = document.querySelector('[data-quick-search-trigger]');
  const overlay = document.querySelector('[data-quick-search-v15]');
  const form = overlay?.querySelector('[data-quick-search-form]');
  const input = overlay?.querySelector('[data-quick-search-input]');
  const close = overlay?.querySelector('[data-quick-search-close]');
  if (!trigger || !overlay || !form || !input) return;

  const open = () => {
    overlay.classList.add('is-open');
    overlay.removeAttribute('hidden');
    document.body.dataset.quickSearchOpen = '1';
    requestAnimationFrame(() => {
      input.focus({preventScroll:true});
      try { input.select(); } catch (_) {}
    });
  };

  const hide = () => {
    overlay.classList.remove('is-open');
    overlay.setAttribute('hidden', '');
    delete document.body.dataset.quickSearchOpen;
    trigger.focus({preventScroll:true});
  };

  trigger.addEventListener('click', event => {
    event.preventDefault();
    open();
  });

  close?.addEventListener('click', hide);
  overlay.addEventListener('click', event => {
    if (event.target === overlay) hide();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && overlay.classList.contains('is-open')) {
      event.preventDefault();
      hide();
    }
  });

  form.addEventListener('submit', event => {
    const q = input.value.trim();
    if (!q) {
      event.preventDefault();
      input.focus();
      return;
    }
    input.value = q;
    let field = form.querySelector('input[type="hidden"][name="q"]');
    if (!field) {
      field = document.createElement('input');
      field.type = 'hidden';
      field.name = 'q';
      form.appendChild(field);
    }
    field.value = q;
  });
})();
