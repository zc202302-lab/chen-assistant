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

  const STORAGE_KEY = 'chen-assistant:history-nav:v1432';
  const MAX_ENTRIES = 80;
  const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;

  const sanitize = raw => {
    if (!raw || !Array.isArray(raw.entries) || !raw.entries.length) return null;
    const entries = raw.entries
      .filter(value => typeof value === 'string' && value.startsWith('/'))
      .slice(-MAX_ENTRIES);
    if (!entries.length) return null;
    let index = Number.isInteger(raw.index) ? raw.index : entries.length - 1;
    index = Math.max(0, Math.min(index, entries.length - 1));
    const pending = raw.pending && typeof raw.pending === 'object'
      && typeof raw.pending.target === 'string'
      && Number.isInteger(raw.pending.index)
      ? { target: raw.pending.target, index: raw.pending.index }
      : null;
    return { entries, index, pending };
  };

  const loadState = () => {
    try {
      return sanitize(JSON.parse(window.sessionStorage.getItem(STORAGE_KEY) || 'null'));
    } catch (_) {
      return null;
    }
  };

  const saveState = state => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {
      // If sessionStorage is unavailable, page navigation itself still works.
    }
  };

  let state = loadState();
  if (!state) {
    state = { entries: [currentUrl], index: 0, pending: null };
  } else if (
    state.pending
    && state.pending.target === currentUrl
    && state.pending.index >= 0
    && state.pending.index < state.entries.length
    && state.entries[state.pending.index] === currentUrl
  ) {
    state.index = state.pending.index;
    state.pending = null;
  } else if (state.entries[state.index] === currentUrl) {
    state.pending = null;
  } else if (state.index > 0 && state.entries[state.index - 1] === currentUrl) {
    state.index -= 1;
    state.pending = null;
  } else if (state.index < state.entries.length - 1 && state.entries[state.index + 1] === currentUrl) {
    state.index += 1;
    state.pending = null;
  } else {
    state.entries = state.entries.slice(0, state.index + 1);
    state.entries.push(currentUrl);
    if (state.entries.length > MAX_ENTRIES) state.entries = state.entries.slice(-MAX_ENTRIES);
    state.index = state.entries.length - 1;
    state.pending = null;
  }
  saveState(state);

  const updateAvailability = () => {
    const canBack = state.index > 0;
    const canForward = state.index < state.entries.length - 1;
    backButton.disabled = !canBack;
    forwardButton.disabled = !canForward;
    backButton.setAttribute('aria-disabled', canBack ? 'false' : 'true');
    forwardButton.setAttribute('aria-disabled', canForward ? 'false' : 'true');
    backButton.title = canBack ? '返回上一页' : '没有可返回的页面';
    forwardButton.title = canForward ? '前进到下一页' : '没有可前进的页面';
  };

  const navigateTo = targetIndex => {
    if (targetIndex < 0 || targetIndex >= state.entries.length) return;
    const target = state.entries[targetIndex];
    if (!target) return;
    state.pending = { target, index: targetIndex };
    saveState(state);
    window.location.assign(target);
  };

  backButton.addEventListener('click', event => {
    event.preventDefault();
    if (state.index <= 0) return;
    navigateTo(state.index - 1);
  });

  forwardButton.addEventListener('click', event => {
    event.preventDefault();
    if (state.index >= state.entries.length - 1) return;
    navigateTo(state.index + 1);
  });

  updateAvailability();
})();