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

  const HISTORY_KEY = 'chen:app-history:v142';
  const MAX_ENTRIES = 60;
  let pageLeaving = false;

  const currentLocation = () => `${window.location.pathname}${window.location.search}${window.location.hash}`;

  const emptyHistory = () => ({entries: [], index: -1});

  const readHistory = () => {
    try {
      const parsed = JSON.parse(window.sessionStorage.getItem(HISTORY_KEY) || 'null');
      if (!parsed || !Array.isArray(parsed.entries) || !Number.isInteger(parsed.index)) {
        return emptyHistory();
      }
      const entries = parsed.entries.filter(entry => typeof entry === 'string' && entry.startsWith('/'));
      if (!entries.length) return emptyHistory();
      const index = Math.max(0, Math.min(parsed.index, entries.length - 1));
      return {entries, index};
    } catch (_error) {
      return emptyHistory();
    }
  };

  const writeHistory = state => {
    try {
      window.sessionStorage.setItem(HISTORY_KEY, JSON.stringify(state));
      return true;
    } catch (_error) {
      return false;
    }
  };

  const reconcileHistory = () => {
    const current = currentLocation();
    const state = readHistory();

    if (!state.entries.length) {
      const initial = {entries: [current], index: 0};
      writeHistory(initial);
      return initial;
    }

    if (state.entries[state.index] === current) return state;

    if (state.index > 0 && state.entries[state.index - 1] === current) {
      state.index -= 1;
      writeHistory(state);
      return state;
    }

    if (state.index + 1 < state.entries.length && state.entries[state.index + 1] === current) {
      state.index += 1;
      writeHistory(state);
      return state;
    }

    // This is a new in-app navigation rather than an adjacent history traversal.
    // Drop the logical forward branch, just like a normal browser navigation does.
    state.entries = state.entries.slice(0, state.index + 1);
    state.entries.push(current);
    state.index = state.entries.length - 1;

    if (state.entries.length > MAX_ENTRIES) {
      const trim = state.entries.length - MAX_ENTRIES;
      state.entries = state.entries.slice(trim);
      state.index = Math.max(0, state.index - trim);
    }

    writeHistory(state);
    return state;
  };

  const paintAvailability = () => {
    const state = reconcileHistory();
    const hasBack = state.index > 0;
    const hasForward = state.index >= 0 && state.index < state.entries.length - 1;

    backButton.disabled = !hasBack;
    forwardButton.disabled = !hasForward;
    backButton.setAttribute('aria-disabled', hasBack ? 'false' : 'true');
    forwardButton.setAttribute('aria-disabled', hasForward ? 'false' : 'true');
    backButton.title = hasBack ? '返回上一页' : '没有可返回的页面';
    forwardButton.title = hasForward ? '前进到下一页' : '没有可前进的页面';
  };

  const traverse = offset => {
    const state = reconcileHistory();
    const targetIndex = state.index + offset;
    if (targetIndex < 0 || targetIndex >= state.entries.length) return;

    const source = currentLocation();
    const target = state.entries[targetIndex];
    state.index = targetIndex;
    writeHistory(state);
    pageLeaving = false;

    // Prefer the native browser traversal so the real history stack, scroll position,
    // and BFCache behavior remain intact. Some browser/PWA combinations can report a
    // forward/back entry yet ignore the actual traversal; in that case, fall back to
    // the exact URL that our same-tab app history recorded.
    if (offset < 0) window.history.back();
    else window.history.forward();

    window.setTimeout(() => {
      if (!pageLeaving && currentLocation() === source) {
        window.location.assign(target);
      }
    }, 350);
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

  window.addEventListener('pagehide', () => {
    pageLeaving = true;
  });
  window.addEventListener('pageshow', () => {
    pageLeaving = false;
    paintAvailability();
  });
  window.addEventListener('popstate', paintAvailability);

  paintAvailability();
})();
