(() => {
  const root = document.querySelector('.v0211-workspace');
  const actions = window.ChenPaymentWorkflowActionsV031;
  if (!root || !actions?.prepareInitiate || actions.prepareInitiate.__v123DirectMapiPrimary) return;

  const customerId = root.dataset.customerId || '';
  if (!customerId) return;

  const fallback = actions.prepareInitiate.bind(actions);
  const bridge = 'http://127.0.0.1:18763';

  const responseError = async response => {
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      const data = await response.json().catch(() => ({}));
      return data.detail || data.error || `请求失败（${response.status}）`;
    }
    return (await response.text().catch(() => '')).trim() || `请求失败（${response.status}）`;
  };

  const openWithDirectMapi = async () => {
    const compose = await fetch(`/customers/${customerId}/payment-mail-compose-v031`, {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json'},
    });
    if (!compose.ok) throw new Error(await responseError(compose));

    const payload = await compose.json();
    if (!payload?.ok) throw new Error(payload?.error || '无法生成缴费邮件');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
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
      if (err?.name === 'AbortError') throw new Error('Windows 邮箱助手响应超时');
      throw new Error('无法连接 Windows 邮箱助手');
    } finally {
      clearTimeout(timer);
    }

    const result = await response.json().catch(() => ({}));
    const message = String(result?.error || '');

    // Foxmail has historically reused an existing top-level window.  The helper's
    // old window-count probe could therefore report a false negative even when
    // MAPISendMail returned code 0 and the compose request was accepted.
    if (result?.ok === true || (result?.code === 0 && message.includes('MAPI returned success but no compose window was detected'))) {
      return {
        mode: 'foxmail-direct-mapi',
        state: result?.ok === true ? (result.state || 'mapi-accepted') : 'mapi-accepted-window-unverified',
      };
    }

    throw new Error(message || `Foxmail MAPI 调用失败（${response.status}）`);
  };

  const directMapiPrimary = async () => {
    try {
      return await openWithDirectMapi();
    } catch (mapiError) {
      // Keep the complete EML route only as a last-resort fallback. Foxmail may
      // display EML as a message viewer, so it must never be the normal path.
      try {
        return {...(await fallback()), fallback: 'eml'};
      } catch (fallbackError) {
        throw new Error(`邮箱启动失败：${mapiError.message}；备用方式也失败：${fallbackError.message}`);
      }
    }
  };

  directMapiPrimary.__v123DirectMapiPrimary = true;
  actions.prepareInitiate = directMapiPrimary;
})();
