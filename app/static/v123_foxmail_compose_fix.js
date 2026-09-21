(() => {
  const root = document.querySelector('.v0211-workspace');
  const actions = window.ChenPaymentWorkflowActionsV031;
  if (!root || !actions?.prepareInitiate || actions.prepareInitiate.__v159FoxmailClipboardAttachment) return;

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

  const bridgeFetch = async (path, options = {}, timeoutMs = 22000) => {
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

  const requireV09Bridge = async () => {
    const response = await bridgeFetch('/health', {headers: {'Accept': 'application/json'}}, 4000);
    const health = await response.json().catch(() => ({}));
    if (!response.ok || health?.ok !== true) {
      throw new Error('Windows 邮箱助手状态异常，请重新安装最新版 Windows 助手');
    }
    if (
      health?.version !== '0.9' ||
      health?.launch_mode !== 'foxmail-exe-mailto-clipboard-ready' ||
      health?.attachment_mode !== 'clipboard-file-drop' ||
      health?.auto_send !== false ||
      health?.mapi_required !== false
    ) {
      throw new Error('检测到旧版 Windows 邮箱助手。请重新安装最新版助手后再准备缴费邮件。');
    }
  };

  const prepareFoxmailDraft = async () => {
    await requireV09Bridge();

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
      result?.attachment_file_verified !== true ||
      result?.attachment_clipboard_verified !== true ||
      result?.attachment_integrity_verified !== true ||
      result?.explorer_dispatched !== false ||
      result?.state !== 'draft-open-clipboard-ready' ||
      result?.mode !== 'foxmail-exe-mailto-clipboard-ready'
    ) {
      const message = String(result?.error || '');
      if (message.includes('compose window did not appear')) {
        throw new Error('Foxmail 没有真正打开写信窗口。请确认 Foxmail 已正常登录，然后重试。');
      }
      if (message.includes('clipboard')) {
        throw new Error('缴费 TXT 没有成功放入文件剪贴板，请重试。');
      }
      if (message.includes('SHA256')) {
        throw new Error('缴费 TXT 完整性校验失败，已停止发起缴费。');
      }
      if (message.includes('TXT attachment')) {
        throw new Error('缴费 TXT 没有成功准备，请重试。');
      }
      throw new Error(message || `Foxmail 草稿或 TXT 准备失败（${response.status}）`);
    }

    return {
      mode: result.mode,
      state: result.state,
      verified: true,
      attachmentReady: true,
      clipboardAttachment: true,
    };
  };

  const verifiedPrimary = async () => prepareFoxmailDraft();
  verifiedPrimary.__v159FoxmailClipboardAttachment = true;
  actions.prepareInitiate = verifiedPrimary;

  const previousAlert = window.alert.bind(window);
  window.alert = message => {
    const text = String(message ?? '');
    if (
      text.includes('Foxmail写邮件窗口已打开，并已带入收件人、主题、正文和TXT附件') ||
      text.includes('Foxmail写邮件窗口已打开，缴费TXT已放入文件剪贴板')
    ) {
      if (window.ChenToast) {
        window.ChenToast('Foxmail草稿已打开，TXT已复制到文件剪贴板；在邮件窗口按 Ctrl+V 添加附件');
      }
      return;
    }
    return previousAlert(message);
  };

  const syncManualHint = () => {
    const button = root.querySelector('[data-v031-flow-action="initiate"]');
    if (!button) return;
    const awaiting = button.classList.contains('awaiting-confirm');
    const done = button.getAttribute('aria-pressed') === 'true';
    const nextTitle = done
      ? '已确认缴费邮件发送完成；点击可撤回此状态'
      : awaiting
        ? 'Foxmail草稿和TXT已准备；在邮件窗口按 Ctrl+V 加入TXT，检查并发送后再次点击确认'
        : '准备Foxmail草稿并把TXT放入文件剪贴板；系统不会自动发送邮件';
    if (button.title !== nextTitle) button.title = nextTitle;
  };

  syncManualHint();
  const flow = root.querySelector('[data-v031-payment-flow]');
  if (flow) {
    new MutationObserver(syncManualHint).observe(flow, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ['class', 'aria-pressed', 'title'],
    });
  }
})();
