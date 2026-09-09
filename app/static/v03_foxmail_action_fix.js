(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const original = root.querySelector('[data-v03-foxmail-draft]');
  if (!customerId || !original) return;

  const FOXMAIL_BRIDGE = 'http://127.0.0.1:18763';
  const button = original.cloneNode(true);
  button.disabled = false;
  button.removeAttribute('disabled');
  original.replaceWith(button);

  let busy = false;
  let bridgeOnline = false;

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'app-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 2600);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.detail || data.error || '操作失败');
    }
    return data;
  };

  const bridgeFetch = async (path, options = {}, timeoutMs = 4000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(`${FOXMAIL_BRIDGE}${path}`, {
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        signal: controller.signal,
        ...options,
      });
    } finally {
      clearTimeout(timer);
    }
  };

  const probeBridge = async () => {
    try {
      const response = await bridgeFetch('/health', {}, 1200);
      const data = await response.json().catch(() => ({}));
      bridgeOnline = response.ok && data.ok === true;
    } catch (_) {
      bridgeOnline = false;
    }
    if (!busy) button.textContent = bridgeOnline ? '调用Foxmail' : 'Foxmail草稿';
    return bridgeOnline;
  };

  const loadPaid = async () => {
    try {
      const data = await fetchJson(`/customers/${customerId}/workflow-state-v03`);
      return !!data.run?.paid;
    } catch (_) {
      const data = await fetchJson(`/customers/${customerId}/payment-run-v03`);
      return !!data.run?.paid;
    }
  };

  const loadTemplate = async () => {
    const data = await fetchJson(`/customers/${customerId}/mail-template-v03`);
    return data.template || {subject: '', body: ''};
  };

  const filenameFromDisposition = (value, fallback = 'payment.eml') => {
    const header = value || '';
    const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8) {
      try { return decodeURIComponent(utf8[1].trim()); } catch (_) {}
    }
    const plain = header.match(/filename="?([^";]+)"?/i);
    return plain?.[1]?.trim() || fallback;
  };

  const bytesToBase64 = bytes => {
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  };

  const textToBase64 = text => {
    return bytesToBase64(new TextEncoder().encode(text || ''));
  };

  const openLocal = async (blob, filename) => {
    if (!bridgeOnline && !(await probeBridge())) return false;
    try {
      const bytes = new Uint8Array(await blob.arrayBuffer());
      const response = await bridgeFetch('/open', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          filename_b64: textToBase64(filename),
          content_base64: bytesToBase64(bytes),
        }),
      }, 5000);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok !== true) {
        throw new Error(data.error || 'Windows 助手打开失败');
      }
      return true;
    } catch (_) {
      bridgeOnline = false;
      return false;
    }
  };

  const downloadBlob = (blob, filename) => {
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = filename || 'payment.eml';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
  };

  const setBusy = value => {
    busy = value;
    button.disabled = value;
    button.textContent = value ? '正在准备邮件…' : (bridgeOnline ? '调用Foxmail' : 'Foxmail草稿');
  };

  button.addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    try {
      const [paid, template] = await Promise.all([loadPaid(), loadTemplate(), probeBridge()]);

      if (!paid) {
        toast('当前客户本月缴费流程尚未完成，完成缴费后才能调用Foxmail');
        return;
      }

      if (!(template.subject || '').trim()) {
        toast('请先点击“邮件模板”，为当前客户保存邮件主题');
        root.querySelector('[data-v03-mail-template]')?.click();
        return;
      }

      const response = await fetch(`/customers/${customerId}/payment-mail-draft-v03`, {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.error || '邮件草稿生成失败');
      }

      const blob = await response.blob();
      const filename = filenameFromDisposition(response.headers.get('Content-Disposition'));
      const opened = await openLocal(blob, filename);

      if (opened) {
        toast('Foxmail已打开，请核对收件人、主题、正文和TXT附件');
      } else {
        downloadBlob(blob, filename);
        toast('Windows助手未能打开邮件，已自动下载.eml草稿');
      }
    } catch (err) {
      toast(err.message || '调用Foxmail失败');
    } finally {
      setBusy(false);
      probeBridge();
    }
  });

  probeBridge();
})();
