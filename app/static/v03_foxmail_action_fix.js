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
  let bridgeVersion = '';

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
    setTimeout(() => el.classList.remove('show'), 5000);
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
      bridgeVersion = data.version || '';
    } catch (_) {
      bridgeOnline = false;
      bridgeCompose = false;
      bridgeVersion = '';
    }
    if (!busy) button.textContent = '调用Foxmail';
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
    }, 7000);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok !== true || data.verified !== true) {
      throw new Error(data.error || 'Windows助手没有确认Foxmail写邮件窗口');
    }
    return data;
  };

  const setBusy = value => {
    busy = value;
    button.disabled = value;
    button.textContent = value ? '正在准备邮件…' : '调用Foxmail';
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
        toast('未检测到Windows助手。请确认助手正在运行；本次不会自动下载.eml，以便保留故障信息。');
        return;
      }

      if (!bridgeCompose) {
        const versionText = bridgeVersion ? `（当前版本 ${bridgeVersion}）` : '';
        toast(`Windows助手版本不支持可靠调用${versionText}，请重新下载并安装最新版助手。`);
        return;
      }

      try {
        await composeLocal();
        toast('Foxmail写邮件窗口已确认打开，请核对收件人、主题、正文和TXT附件');
      } catch (err) {
        toast(`Foxmail调用失败：${err.message || '未知错误'}。本次未自动下载.eml。`);
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