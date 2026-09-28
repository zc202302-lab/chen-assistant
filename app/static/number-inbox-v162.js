document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-copy-value]');
  if (!target) return;
  const value = target.getAttribute('data-copy-value') || '';
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    const original = target.textContent;
    target.textContent = original + '  ✓';
    window.setTimeout(() => { target.textContent = original; }, 900);
  } catch (_) {
    const range = document.createRange();
    range.selectNodeContents(target);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
});