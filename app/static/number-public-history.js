(() => {
  'use strict';
  const status = document.querySelector('.history-copy-status');
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-history-copy]');
    if (!button) return;
    const number = button.dataset.historyCopy;
    let copied = false;
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(number); copied = true; } catch (_) {}
    }
    if (!copied) {
      const input = document.createElement('textarea');
      input.value = number;
      input.readOnly = true;
      Object.assign(input.style, {position: 'fixed', left: '-9999px', opacity: '0'});
      document.body.appendChild(input);
      input.select();
      try { copied = document.execCommand('copy'); } catch (_) {}
      input.remove();
      button.focus({preventScroll: true});
    }
    if (status) status.textContent = copied ? '号码已复制' : '复制失败，请长按号码复制';
    if (!copied) {
      const range = document.createRange();
      range.selectNodeContents(button);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
})();
