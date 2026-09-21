(() => {
  const brand = document.querySelector('.brand');
  if (brand) {
    brand.href = '/';
    brand.title = '返回晨的助手主页面';
  }

  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const toast = message => {
    if (window.ChenToast) return window.ChenToast(message);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div'); el.className = 'app-toast'; document.body.appendChild(el);
    }
    el.textContent = message;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);
  const silentConfirm = text => (
    text.includes('确认已经把本次缴费图片通过微信发送给客户') ||
    text.includes('确认已经在Foxmail中将缴费邮件发送给同事') ||
    text.includes('确认缴费图片已经通过微信发送给客户') ||
    text.includes('确认缴费邮件已经在Foxmail中发送给同事') ||
    text.includes('确认同事已收到邮件，并且你已经完成本次实际支付') ||
    text.includes('撤回“完成缴费”并恢复本次缴费前的周期状态') ||
    text.includes('确认撤回“通知客户”状态') ||
    text.includes('确认撤回“发起缴费”状态') ||
    text.includes('确认撤回“金额核对”状态') ||
    text.includes('该客户已经发起缴费。修改金额后')
  );
  window.confirm = message => silentConfirm(String(message ?? '')) ? true : nativeConfirm(message);
  window.alert = message => {
    const text = String(message ?? '');
    if (
      text.includes('缴费图片已生成并复制到剪贴板') ||
      text.includes('缴费图片已生成，但自动复制到剪贴板失败') ||
      text.includes('Foxmail写邮件窗口已打开，并已带入收件人、主题、正文和TXT附件') ||
      text.includes('Foxmail写邮件窗口已打开，缴费TXT已放入文件剪贴板')
    ) {
      if (text.includes('Foxmail写邮件窗口')) toast('邮箱草稿已打开；发送后再次点击“发起缴费”即可确认');
      else toast('缴费图片已准备；发送后再次点击“通知客户”即可确认');
      return;
    }
    return nativeAlert(message);
  };

  const actions = window.ChenPaymentWorkflowActionsV031;
  if (actions?.prepareInitiate && !actions.prepareInitiate.__v033MapiCompat) {
    const originalPrepareInitiate = actions.prepareInitiate.bind(actions);
    const wrappedPrepareInitiate = async (...args) => {
      try { return await originalPrepareInitiate(...args); }
      catch (err) {
        const message = String(err?.message || '');
        if (message.includes('Foxmail MAPI returned success but no compose window was detected')) {
          return {mode: 'foxmail-direct-mapi', state: 'mapi-accepted-window-unverified'};
        }
        throw err;
      }
    };
    wrappedPrepareInitiate.__v033MapiCompat = true;
    actions.prepareInitiate = wrappedPrepareInitiate;
  }

  // v1.2.2: primary launch path is a complete .eml draft opened by Windows Shell.
  // Direct MAPI remains only as a fallback. This removes Foxmail window-count
  // detection from the normal path, which was the source of long-term instability.
  if (actions?.prepareInitiate && !actions.prepareInitiate.__v122StableMailLaunch) {
    const fallbackMapi = actions.prepareInitiate.bind(actions);
    const customerId = root.dataset.customerId || '';
    const bridge = 'http://127.0.0.1:18763';

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
      if (utf8?.[1]) { try { return decodeURIComponent(utf8[1].replace(/^"|"$/g, '')); } catch (_) {} }
      const plain = value.match(/filename="?([^";]+)"?/i);
      return plain?.[1] || 'payment.eml';
    };
    const utf8Base64 = text => {
      const bytes = new TextEncoder().encode(text);
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return btoa(binary);
    };
    const bytesToBase64 = bytes => {
      let binary = '';
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return btoa(binary);
    };
    const openEml = async () => {
      const draft = await fetch(`/customers/${customerId}/payment-mail-draft-v03`, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'message/rfc822'}});
      if (!draft.ok) throw new Error(await responseError(draft));
      const bytes = new Uint8Array(await draft.arrayBuffer());
      if (!bytes.length) throw new Error('服务器生成的邮件草稿为空');
      const filename = filenameFromDisposition(draft.headers.get('Content-Disposition'));
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      let response;
      try {
        response = await fetch(`${bridge}/open`, {
          method: 'POST', mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal,
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({filename_b64: utf8Base64(filename), content_base64: bytesToBase64(bytes)}),
        });
      } catch (err) {
        if (err?.name === 'AbortError') throw new Error('Windows 邮箱助手响应超时');
        throw new Error('无法连接 Windows 邮箱助手');
      } finally { clearTimeout(timer); }
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) throw new Error(result.error || 'Windows 邮箱助手未能打开邮件草稿');
      return {mode: result.mode || 'eml-shell', state: 'draft-open-dispatched'};
    };
    const stablePrepareInitiate = async () => {
      try { return await openEml(); }
      catch (emlError) {
        try { return {...(await fallbackMapi()), fallback: 'direct-mapi'}; }
        catch (mapiError) { throw new Error(`邮箱启动失败：${emlError.message}；备用MAPI也失败：${mapiError.message}`); }
      }
    };
    stablePrepareInitiate.__v122StableMailLaunch = true;
    actions.prepareInitiate = stablePrepareInitiate;
  }

  const filenameFromDisposition = (disposition, fallback) => {
    const value = String(disposition || '');
    const utf8 = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8?.[1]) { try { return decodeURIComponent(utf8[1].replace(/^"|"$/g, '')); } catch (_) {} }
    const plain = value.match(/filename="?([^";]+)"?/i);
    return plain?.[1] || fallback;
  };
  const responseErrorForExport = async response => {
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) {
      const data = await response.json().catch(() => ({}));
      return data.detail || data.error || `生成失败（${response.status}）`;
    }
    return (await response.text().catch(() => '')).trim() || `生成失败（${response.status}）`;
  };
  const bindPaymentExport = ({id, label, fallback, accept}) => {
    const button = document.getElementById(id);
    if (!button) return;
    button.addEventListener('click', async event => {
      event.preventDefault(); event.stopImmediatePropagation();
      if (button.dataset.downloading === '1') return;
      if (button.classList.contains('disabled') || button.getAttribute('aria-disabled') === 'true') {
        toast(`请先完成本月全部金额核对，再生成缴费${label}`);
        return;
      }
      const href = button.getAttribute('href');
      if (!href) { toast(`缴费${label}下载地址不存在`); return; }
      button.dataset.downloading = '1'; button.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(href, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': accept}});
        if (!response.ok) throw new Error(await responseErrorForExport(response));
        const blob = await response.blob();
        if (!blob.size) throw new Error(`服务器返回了空${label}文件`);
        const filename = filenameFromDisposition(response.headers.get('Content-Disposition'), fallback);
        const url = URL.createObjectURL(blob);
        const download = document.createElement('a');
        download.href = url; download.download = filename; download.style.display = 'none';
        document.body.appendChild(download); download.click(); download.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1500);
        toast(`缴费${label}已下载`);
      } catch (err) { toast(`缴费${label}生成失败：${err.message || '未知错误'}`); }
      finally { delete button.dataset.downloading; button.removeAttribute('aria-busy'); }
    }, true);
  };
  bindPaymentExport({id: 'paymentExcelButton', label: 'EXCEL', fallback: '缴费.xlsx', accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  bindPaymentExport({id: 'paymentTxtButton', label: 'TXT', fallback: '缴费.txt', accept: 'text/plain'});

  const dialog = document.querySelector('.v03-mail-template-dialog');
  if (!dialog) return;
  const note = dialog.querySelector('.v03-mail-template-note span');
  if (note) note.textContent = '收件人、邮件主题、正文、TXT附件文件名和EXCEL附件文件名都只属于当前客户；TXT与EXCEL完全分离，任一未填写都不会互相推导。';
  const recipient = dialog.querySelector('[data-v03-mail-recipient]');
  const recipientCaption = recipient?.closest('.v03-mail-field')?.querySelector('span');
  if (recipientCaption) recipientCaption.innerHTML = '收件人 <small>按当前客户长期保存，不与其他客户共用</small>';
  const attachment = dialog.querySelector('[data-v03-mail-attachment-filename]');
  const attachmentCaption = attachment?.closest('.v03-mail-field')?.querySelector('span');
  if (attachmentCaption) attachmentCaption.innerHTML = 'TXT附件文件名 <small>生成TXT和邮件附件都只使用此名称；必填</small>';
  if (attachment) attachment.placeholder = '例如：淄博润泰物流缴费明细.txt';
})();
