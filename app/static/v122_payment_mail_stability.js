(() => {
  const root = document.querySelector('.v0211-workspace');
  const actions = window.ChenPaymentWorkflowActionsV031;
  const customerId = root?.dataset.customerId || '';
  if (!root || !customerId || !actions?.prepareInitiate) return;

  const FOXMAIL_BRIDGE = 'http://127.0.0.1:18763';
  const legacyMapiInitiate = actions.prepareInitiate.bind(actions);

  const responseError = async response => {
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      const data = await response.json().catch(() => ({}));
      return data.detail || data.error || `请求失败（${response.status}）`;
    }
    return (await response.text().catch(() => '')).trim() || `请求失败（${response.status}）`;
  };

  const filenameFromDisposition = disposition => {
    const value = String(disposition || '');
    const utf8 = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8?.[1]) {
      try { return decodeURIComponent(utf8[1].replace(/^"|"$/g, '')); } catch (_) {}
    }
    const plain = value.match(/filename="?([^";]+)"?/i);
    return plain?.[1] || 'payment.eml';
  };

  const bytesToBase64 = bytes => {
    const step = 0x8000;
    let binary = '';
    for (let i = 0; i < bytes.length; i += step) {
      binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + step, bytes.length)));
    }
    return btoa(binary);
  };

  const openEmlViaLocalHelper = async () => {
    const draftResponse = await fetch(`/customers/${customerId}/payment-mail-draft-v03`, {
      credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'message/rfc822'},
    });
    if (!draftResponse.ok) throw new Error(await responseError(draftResponse));

    const bytes = new Uint8Array(await draftResponse.arrayBuffer());
    if (!bytes.length) throw new Error('服务器生成的邮件草稿为空');
    const filename = filenameFromDisposition(draftResponse.headers.get('Content-Disposition'));

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    let response;
    try {
      response = await fetch(`${FOXMAIL_BRIDGE}/open`, {
        method: 'POST', mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          filename_b64: btoa(unescape(encodeURIComponent(filename))),
          content_base64: bytesToBase64(bytes),
        }),
      });
    } catch (err) {
      if (err?.name === 'AbortError') throw new Error('Windows 邮箱助手响应超时');
      throw new Error('无法连接 Windows 邮箱助手');
    } finally {
      clearTimeout(timer);
    }

    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true) {
      throw new Error(result.error || 'Windows 邮箱助手未能打开邮件草稿');
    }
    return {mode: result.mode || 'eml-shell', state: 'draft-open-dispatched'};
  };

  const stablePrepareInitiate = async () => {
    // Primary path: a fully formed RFC822 draft is opened through Windows Shell.
    // This avoids Foxmail Simple-MAPI window detection, which was the long-term
    // source of false failures and intermittent compose-window launches.
    try {
      return await openEmlViaLocalHelper();
    } catch (emlError) {
      // Keep direct MAPI only as a compatibility fallback for PCs whose .eml
      // association is broken. It is no longer the primary path.
      try {
        const result = await legacyMapiInitiate();
        return {...(result || {}), fallback: 'direct-mapi'};
      } catch (mapiError) {
        throw new Error(`邮箱启动失败：${emlError.message}；备用MAPI也失败：${mapiError.message}`);
      }
    }
  };
  stablePrepareInitiate.__v122StableMailLaunch = true;
  actions.prepareInitiate = stablePrepareInitiate;
})();
