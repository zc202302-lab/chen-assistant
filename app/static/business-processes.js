(() => {
  const form = document.querySelector('[data-process-editor]');
  if (!form) return;
  let dirty = false, submitting = false, urls = [];
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; });
  const clearPreview = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; };
  const upload = form.querySelector('[data-process-images]');
  upload?.addEventListener('change', () => {
    clearPreview();
    const preview = form.querySelector('[data-image-preview]');
    const error = form.querySelector('[data-image-error]');
    preview.replaceChildren();
    const files = [...upload.files];
    const message = files.length > 12 ? '每次最多添加12张图片。' :
      files.some(file => file.size > 8 * 1024 * 1024) ? '每张图片最多8MB。' :
      files.reduce((sum, file) => sum + file.size, 0) > 31 * 1024 * 1024 ? '请分次添加图片，一次保存最多32MB。' : '';
    upload.setCustomValidity(message);
    error.textContent = message; error.hidden = !message;
    if (message) return;
    files.forEach(file => {
      const figure = document.createElement('figure');
      const img = document.createElement('img');
      img.src = URL.createObjectURL(file); urls.push(img.src); img.alt = '待保存配图';
      const caption = document.createElement('figcaption'); caption.textContent = file.name;
      figure.append(img, caption); preview.appendChild(figure);
    });
  });
  form.addEventListener('submit', () => {
    submitting = true;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true; button.textContent = '正在保存…';
  });
  window.addEventListener('beforeunload', event => {
    if (dirty && !submitting) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pagehide', clearPreview);
  window.addEventListener('pageshow', () => {
    submitting = false;
    const button = form.querySelector('button[type=submit]');
    button.disabled = false; button.textContent = upload ? '保存步骤' : '保存流程';
  });
})();
