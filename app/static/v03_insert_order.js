(() => {
  const SELECTORS = '[data-v03-payment-order],[data-business-column-order-v0212]';
  const timerByInput = new WeakMap();

  const groupFor = input => {
    if (input.matches('[data-v03-payment-order]')) {
      return input.closest('[data-payment-column-list]') || input.closest('.v03-display-order-list');
    }
    return input.closest('[data-business-columns-list-v0212]') || input.closest('.business-columns-list-v0212');
  };

  const inputsFor = input => {
    const group = groupFor(input);
    if (!group) return [];
    const selector = input.matches('[data-v03-payment-order]')
      ? '[data-v03-payment-order]'
      : '[data-business-column-order-v0212]';
    return [...group.querySelectorAll(selector)];
  };

  const currentNumber = el => {
    const raw = String(el.value || '').trim();
    if (!/^\d{1,3}$/.test(raw)) return null;
    const n = Number(raw);
    return n >= 1 ? n : null;
  };

  const normalizeInsert = input => {
    const target = currentNumber(input);
    if (target === null) return;
    const all = inputsFor(input);
    if (!all.length) return;

    // Treat the typed number as an insertion position. Existing displayed fields
    // keep their relative order; the edited field is inserted at target and every
    // field at/after that position shifts right automatically.
    const others = all
      .filter(el => el !== input)
      .map((el, index) => ({el, order: currentNumber(el), index}))
      .filter(item => item.order !== null)
      .sort((a, b) => a.order - b.order || a.index - b.index);

    const maxPosition = others.length + 1;
    const position = Math.max(1, Math.min(target, maxPosition));
    others.splice(position - 1, 0, {el: input, order: position, index: -1});
    others.forEach((item, index) => {
      item.el.value = String(index + 1);
      item.el.dataset.v03NormalizedOrder = String(index + 1);
    });
  };

  document.addEventListener('input', e => {
    const input = e.target.closest?.(SELECTORS);
    if (!input) return;
    const old = timerByInput.get(input);
    if (old) clearTimeout(old);
    const timer = setTimeout(() => normalizeInsert(input), 220);
    timerByInput.set(input, timer);
  }, true);

  document.addEventListener('change', e => {
    const input = e.target.closest?.(SELECTORS);
    if (!input) return;
    const old = timerByInput.get(input);
    if (old) clearTimeout(old);
    normalizeInsert(input);
  }, true);

  document.addEventListener('keydown', e => {
    const input = e.target.closest?.(SELECTORS);
    if (!input || e.key !== 'Enter') return;
    normalizeInsert(input);
  }, true);

  // Existing save handlers intentionally reject duplicate numbers. Normalize in
  // capture phase first, so a duplicate typed immediately before clicking Save is
  // converted into a valid insertion order before those handlers read the form.
  document.addEventListener('submit', e => {
    const form = e.target;
    if (!(form instanceof HTMLFormElement)) return;
    const changed = form.querySelector(SELECTORS + ':focus') || form.querySelector(SELECTORS);
    if (!changed) return;
    const focused = form.querySelector(SELECTORS + ':focus');
    if (focused && currentNumber(focused) !== null) normalizeInsert(focused);
    else {
      // Repair any accidental duplicates/gaps deterministically even when the last
      // edited input has already lost focus.
      const all = [...form.querySelectorAll(SELECTORS)];
      const visible = all
        .map((el, index) => ({el, order: currentNumber(el), index}))
        .filter(item => item.order !== null)
        .sort((a, b) => a.order - b.order || a.index - b.index);
      visible.forEach((item, index) => { item.el.value = String(index + 1); });
    }
  }, true);
})();
