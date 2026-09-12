(() => {
  const root = document.querySelector('.v0211-workspace');
  const actions = window.ChenPaymentWorkflowActionsV031;
  if (!root || !actions?.prepareInitiate || actions.prepareInitiate.__v123DirectMapiPrimary) return;

  const customerId = root.dataset.customerId || '';
  if (!customerId) return;

  const bridge = 'http://127.0.0.1:18763';

  const responseError = async response => {
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      const data = await response.json().catch(() => ({}));
      return data.detail || data.error || `请求失败（${response.status}）`;
    }
    return (await response.text().catch(() => '')).trim() || `请求失败（${response.status}）`;
  };

  const openWithVerifiedMapi = async () => {
    const compose = await fetch(`/customers/${customerId}/payment-mail-compose-v031`, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json'},
    });
    if (!compose.ok) throw new Error(await responseError(compose));

    const payload = await compose.json();
    if (!payload?.ok) throw new Error(payload?.error || '无法生成缴费邮件');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 18000);
    let response;
    try {
      response = await fetch(`${bridge}/compose`, {
        method: 'POST',
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        signal: controller.signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
    } catch (err) {
      if (err?.name === 'AbortError') throw new Error('Windows 邮箱助手响应超时，请重新安装最新版 Windows 助手');
      throw new Error('无法连接 Windows 邮箱助手，请重新安装最新版 Windows 助手');
    } finally {
      clearTimeout(timer);
    }

    const result = await response.json().catch(() => ({}));
    if (!response.ok || result?.ok !== true || result?.state !== 'compose-window-detected') {
      const message = String(result?.error || '');
      if (result?.code === 0 || message.includes('no compose window')) {
        throw new Error('Foxmail 没有真正打开写信窗口。请更新 Windows 助手后重试。');
      }
      throw new Error(message || `Foxmail 写信窗口启动失败（${response.status}）`);
    }

    return {
      mode: result.mode || 'foxmail-direct-mapi',
      state: 'compose-window-detected',
    };
  };

  const verifiedPrimary = async () => openWithVerifiedMapi();
  verifiedPrimary.__v123DirectMapiPrimary = true;
  actions.prepareInitiate = verifiedPrimary;
})();
