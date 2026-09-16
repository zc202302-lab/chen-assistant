(() => {
  const trigger = document.querySelector('[data-quick-search-trigger]');
  const overlay = document.querySelector('[data-quick-search-v15]');
  const form = overlay?.querySelector('[data-quick-search-form]');
  const input = overlay?.querySelector('[data-quick-search-input]');
  const close = overlay?.querySelector('[data-quick-search-close]');
  const results = overlay?.querySelector('[data-quick-search-results]');
  if (!trigger || !overlay || !form || !input) return;

  const scope = overlay.dataset.searchScope === 'global' ? 'global' : 'work';
  let debounceTimer = null;
  let requestController = null;
  let requestSeq = 0;

  const clearResults = () => {
    if (!results) return;
    results.innerHTML = '';
    results.setAttribute('hidden', '');
    results.classList.remove('is-loading');
  };

  const setStatus = text => {
    if (!results) return;
    results.innerHTML = '';
    const status = document.createElement('div');
    status.className = 'quick-search-status-v151';
    status.textContent = text;
    results.appendChild(status);
    results.removeAttribute('hidden');
  };

  const renderResults = data => {
    if (!results) return;
    results.innerHTML = '';
    const groups = Array.isArray(data?.groups) ? data.groups : [];
    if (!groups.length) {
      setStatus('没有匹配结果');
      return;
    }

    groups.forEach(group => {
      const items = Array.isArray(group.items) ? group.items : [];
      if (!items.length) return;
      const section = document.createElement('section');
      section.className = 'quick-search-group-v151';

      const head = document.createElement('div');
      head.className = 'quick-search-group-head-v151';
      const label = document.createElement('strong');
      label.textContent = group.label || '结果';
      const count = document.createElement('span');
      count.textContent = String(items.length);
      head.append(label, count);
      section.appendChild(head);

      items.forEach(item => {
        const link = document.createElement('a');
        link.className = 'quick-search-result-v151';
        link.href = item.href || '#';
        link.dataset.quickSearchResult = '1';

        const title = document.createElement('strong');
        title.textContent = item.title || '';
        const meta = document.createElement('span');
        meta.textContent = item.meta || '';
        link.append(title, meta);
        section.appendChild(link);
      });
      results.appendChild(section);
    });

    if (!results.children.length) {
      setStatus('没有匹配结果');
      return;
    }
    results.removeAttribute('hidden');
  };

  const loadSuggestions = async value => {
    const q = value.trim();
    if (!q) {
      requestController?.abort();
      clearResults();
      return;
    }

    requestController?.abort();
    requestController = new AbortController();
    const seq = ++requestSeq;
    if (results) results.classList.add('is-loading');
    try {
      const url = `/quick-search-suggest?scope=${encodeURIComponent(scope)}&q=${encodeURIComponent(q)}`;
      const response = await fetch(url, {credentials:'same-origin', signal:requestController.signal});
      const data = await response.json().catch(() => ({}));
      if (seq !== requestSeq) return;
      if (!response.ok || !data.ok) {
        setStatus('搜索暂时不可用');
        return;
      }
      renderResults(data);
    } catch (error) {
      if (error?.name !== 'AbortError' && seq === requestSeq) setStatus('搜索暂时不可用');
    } finally {
      if (seq === requestSeq && results) results.classList.remove('is-loading');
    }
  };

  const scheduleSuggestions = () => {
    clearTimeout(debounceTimer);
    const q = input.value.trim();
    if (!q) {
      loadSuggestions('');
      return;
    }
    debounceTimer = setTimeout(() => loadSuggestions(q), 160);
  };

  const open = () => {
    overlay.classList.add('is-open');
    overlay.removeAttribute('hidden');
    document.body.dataset.quickSearchOpen = '1';
    requestAnimationFrame(() => {
      input.focus({preventScroll:true});
      try { input.select(); } catch (_) {}
      if (input.value.trim()) scheduleSuggestions();
    });
  };

  const hide = () => {
    overlay.classList.remove('is-open');
    overlay.setAttribute('hidden', '');
    delete document.body.dataset.quickSearchOpen;
    clearTimeout(debounceTimer);
    requestController?.abort();
    clearResults();
    trigger.focus({preventScroll:true});
  };

  trigger.addEventListener('click', event => {
    event.preventDefault();
    open();
  });

  input.addEventListener('input', scheduleSuggestions);
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
