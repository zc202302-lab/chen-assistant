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
  let bridgeCompose = false;

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
    setTimeout(() => el.classList.remove('show'), 3000);
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
      bridgeCompose = bridgeOnline && data.compose === true && data.verified_dispatch === true;
    } catch (_) {
      bridgeOnline = false;
      bridgeCompose = false;
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

  const downloadEmlFallback = async () => {
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
    downloadBlob(blob, filename);
  };

  const composeLocal = async () => {
    const payload = await fetchJson(`/customers/${customerId}/payment-mail-compose-v03`);
    const response = await bridgeFetch('/compose', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        recipient_b64: payload.recipient_b64 || '',
        subject_b64: payload.subject_b64 || '',
        body_b64: payload.body_b64 || '',
        attachment_filename_b64: payload.attachment_filename_b64 || '',
        attachment_content_base64: payload.attachment_content_base64 || '',
      }),
    }, 5000);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true || data.verified !== true) {
      throw new Error(data.error || 'Windows助手没有确认Foxmail写邮件窗口');
    }
    return data;
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

      if (!bridgeOnline) {
        await downloadEmlFallback();
        toast('未检测到Windows助手，已下载.eml备用草稿');
        return;
      }

      if (!bridgeCompose) {
        toast('Windows助手版本较旧，请在“邮件模板”中重新下载并安装一次助手');
        root.querySelector('[data-v03-mail-template]')?.click();
        return;
      }

      try {
        await composeLocal();
        toast('Foxmail写邮件窗口已确认打开，请核对收件人、主题、正文和TXT附件');
      } catch (err) {
        await downloadEmlFallback();
        toast(`${err.message || 'Foxmail新建邮件失败'}；已下载.eml备用草稿`);
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