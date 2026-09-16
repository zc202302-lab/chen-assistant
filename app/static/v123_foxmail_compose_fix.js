(() => {
  const root = document.querySelector('.v0211-workspace');
  const actions = window.ChenPaymentWorkflowActionsV031;
  if (!root || !actions?.prepareInitiate || actions.prepareInitiate.__v146FoxmailDialogPrimary) return;

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

  const bridgeFetch = async (path, options = {}, timeoutMs = 30000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(`${bridge}${path}`, {
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        signal: controller.signal,
        ...options,
      });
    } catch (err) {
      if (err?.name === 'AbortError') {
        throw new Error('Windows 邮箱助手响应超时，请重新安装最新版 Windows 助手');
      }
      throw new Error('无法连接 Windows 邮箱助手，请重新安装最新版 Windows 助手');
    } finally {
      clearTimeout(timer);
    }
  };

  const requireV08Bridge = async () => {
    const response = await bridgeFetch('/health', {headers: {'Accept': 'application/json'}}, 4000);
    const health = await response.json().catch(() => ({}));
    if (!response.ok || health?.ok !== true) {
      throw new Error('Windows 邮箱助手状态异常，请重新安装最新版 Windows 助手');
    }
    if (
      health?.version !== '0.8' ||
      health?.launch_mode !== 'foxmail-exe-mailto-dialog' ||
      health?.attachment_mode !== 'file-dialog-uiautomation' ||
      health?.mapi_required !== false
    ) {
      throw new Error('检测到旧版 Windows 邮箱助手。请重新安装最新版助手后再发起缴费。');
    }
  };

  const openWithFoxmailExe = async () => {
    await requireV08Bridge();

    const compose = await fetch(`/customers/${customerId}/payment-mail-compose-v031`, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json'},
    });
    if (!compose.ok) throw new Error(await responseError(compose));

    const payload = await compose.json();
    if (!payload?.ok) throw new Error(payload?.error || '无法生成缴费邮件');

    const response = await bridgeFetch('/compose', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const result = await response.json().catch(() => ({}));

    if (
      !response.ok ||
      result?.ok !== true ||
      result?.verified !== true ||
      result?.launch_verified !== true ||
      result?.attachment_dialog_verified !== true ||
      result?.state !== 'attachment-dialog-completed' ||
      result?.mode !== 'foxmail-exe-mailto-dialog'
    ) {
      const message = String(result?.error || '');
      if (message.includes('compose window did not appear')) {
        throw new Error('Foxmail 没有真正打开写信窗口。请确认 Foxmail 已正常登录，然后重试。');
      }
      if (message.includes('attachment dialog')) {
        throw new Error('Foxmail 已打开写信窗口，但 TXT 附件没有成功通过附件窗口加入。请重试。');
      }
      throw new Error(message || `Foxmail 写信窗口启动或附件添加失败（${response.status}）`);
    }

    return {
      mode: result.mode,
      state: result.state,
      verified: true,
      attachmentVerified: true,
    };
  };

  const verifiedPrimary = async () => openWithFoxmailExe();
  verifiedPrimary.__v146FoxmailDialogPrimary = true;
  actions.prepareInitiate = verifiedPrimary;
})();
