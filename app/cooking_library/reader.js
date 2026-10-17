'use strict';
(() => {
  const book = document.querySelector('main[data-book]');
  if (!book) return;
  const id = book.dataset.book, total = Number(book.dataset.total);
  const key = 'chen-cooking-reader-v1-' + id;
  const page = Number(book.dataset.page);
  const target = n => '/cooking/books/' + id + '/pages/' + n;
  if (page) {
    try { localStorage.setItem(key, String(page)); }
    catch (_) { document.querySelector('#reading-status').textContent = '浏览器未允许保存阅读位置。'; }
  } else {
    let saved;
    try { saved = Number(localStorage.getItem(key)); } catch (_) { return; }
    if (Number.isInteger(saved) && saved >= 1 && saved <= total) {
      const link = document.querySelector('#continue-reading');
      link.href = target(saved); link.hidden = false;
      document.querySelector('#saved-position').textContent = '本浏览器上次读到 PDF 第' + saved + '页';
    }
    return;
  }
  const jump = document.querySelector('#page-jump');
  jump.addEventListener('submit', e => {
    e.preventDefault();
    const input = jump.querySelector('input'), n = Number(input.value);
    if (input.reportValidity() && Number.isInteger(n) && n >= 1 && n <= total) location.assign(target(n));
  });
  const image = document.querySelector('#page-image');
  let zoom = 100;
  const resize = n => {
    zoom = Math.min(250, Math.max(50, n));
    image.style.width = zoom + '%';
    document.querySelector('#zoom-label').textContent = zoom + '%';
  };
  document.querySelector('#zoom-in').addEventListener('click', () => resize(zoom + 25));
  document.querySelector('#zoom-out').addEventListener('click', () => resize(zoom - 25));
  document.querySelector('#zoom-reset').addEventListener('click', () => resize(100));
})();
