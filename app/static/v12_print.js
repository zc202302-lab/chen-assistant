(() => {
  const sheet = document.getElementById('v12PrintSheet');
  if (!sheet) return;
  const fit = () => {
    sheet.style.zoom = '1';
    requestAnimationFrame(() => {
      const target = 1040;
      const h = sheet.scrollHeight;
      const scale = Math.max(.58, Math.min(1, target / Math.max(h, 1)));
      sheet.style.zoom = String(scale);
    });
  };
  window.addEventListener('load', fit);
  window.addEventListener('beforeprint', fit);
})();
