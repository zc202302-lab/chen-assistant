(() => {
  const sheet = document.querySelector('.recipe-print-sheet');
  const fit = () => {
    if (!sheet) return;
    sheet.style.zoom = '1';
    requestAnimationFrame(() => {
      const targetHeight = 1040;
      const height = Math.max(sheet.scrollHeight, 1);
      const scale = Math.max(.55, Math.min(1, targetHeight / height));
      sheet.style.zoom = String(scale);
    });
  };
  window.addEventListener('load', fit);
  window.addEventListener('beforeprint', fit);
  document.querySelector('[data-recipe-print]')?.addEventListener('click', () => {
    fit();
    // Keep printing in the click gesture: Safari may ignore deferred print calls.
    window.print();
  });
})();
