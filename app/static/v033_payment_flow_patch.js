(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const toast = message => {
    if (window.ChenToast) return window.ChenToast(message);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'app-toast';
      document.body.appendChild(el);
    }
    el.textContent = message;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  // v0.3.3 keeps all four payment stages non-blocking. Older modules still call
  // confirm()/alert(); suppress only payment-workflow messages while leaving
  // confirmations elsewhere in the application untouched.
  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);

  const silentConfirm = text => {
    return (
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
  };

  window.confirm = message => {
    const text = String(message ?? '');
    if (silentConfirm(text)) return true;
    return nativeConfirm(message);
  };

  window.alert = message => {
    const text = String(message ?? '');
    if (
      text.includes('缴费图片已生成并复制到剪贴板') ||
      text.includes('缴费图片已生成，但自动复制到剪贴板失败') ||
      text.includes('Foxmail写邮件窗口已打开，并已带入收件人、主题、正文和TXT附件')
    ) {
      if (text.includes('Foxmail写邮件窗口')) {
        if (window.ChenFoxmailMapiAcceptedWindowUnverified) {
          window.ChenFoxmailMapiAcceptedWindowUnverified = false;
          toast('Foxmail已接收写信请求；请检查写信窗口和TXT附件');
        } else {
          toast('Foxmail已打开；发送后再次点击“发起缴费”即可确认');
        }
      } else {
        toast('缴费图片已准备；发送后再次点击“通知客户”即可确认');
      }
      return;
    }
    return nativeAlert(message);
  };

  // Foxmail Simple MAPI returning code 0 means Foxmail accepted the compose
  // request, including the MapiFileDesc attachment. Helper v0.5 additionally
  // compared the number of visible Foxmail windows before/after dispatch. Foxmail
  // can reuse an existing top-level window or create UI asynchronously, so that
  // secondary heuristic can produce a false failure even after MAPI succeeded.
  // Treat only this exact code-0 false-negative as accepted; every real MAPI error
  // still propagates normally. The workflow remains in "待确认" until the operator
  // actually sends the message and clicks stage 3 again.
  const actions = window.ChenPaymentWorkflowActionsV031;
  if (actions?.prepareInitiate && !actions.prepareInitiate.__v033MapiCompat) {
    const originalPrepareInitiate = actions.prepareInitiate.bind(actions);
    const wrappedPrepareInitiate = async (...args) => {
      try {
        return await originalPrepareInitiate(...args);
      } catch (err) {
        const message = String(err?.message || '');
        if (message.includes('Foxmail MAPI returned success but no compose window was detected')) {
          window.ChenFoxmailMapiAcceptedWindowUnverified = true;
          return {
            mode: 'foxmail-direct-mapi',
            state: 'mapi-accepted-window-unverified',
          };
        }
        throw err;
      }
    };
    wrappedPrepareInitiate.__v033MapiCompat = true;
    actions.prepareInitiate = wrappedPrepareInitiate;
  }

  // Force a real browser download for the payment TXT. A plain navigation to
  // /payment.txt can be rendered as text by some browser/proxy combinations;
  // fetching the response and clicking a Blob URL with the download attribute
  // makes the operator action deterministic while preserving server validation.
  const txtButton = document.getElementById('paymentTxtButton');
  if (txtButton) {
    const filenameFromDisposition = disposition => {
      const value = String(disposition || '');
      const utf8 = value.match(/filename\*=UTF-8''([^;]+)/i);
      if (utf8?.[1]) {
        try {
          return decodeURIComponent(utf8[1].replace(/^"|"$/g, ''));
        } catch (_) {
          // Fall through to the ASCII filename/fallback.
        }
      }
      const plain = value.match(/filename="?([^";]+)"?/i);
      return plain?.[1] || '缴费.txt';
    };

    txtButton.addEventListener('click', async event => {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (txtButton.dataset.downloading === '1') return;
      if (txtButton.classList.contains('disabled') || txtButton.getAttribute('aria-disabled') === 'true') {
        toast('请先完成本月全部金额核对，再生成缴费TXT');
        return;
      }

      const href = txtButton.getAttribute('href');
      if (!href) {
        toast('缴费TXT下载地址不存在');
        return;
      }

      txtButton.dataset.downloading = '1';
      txtButton.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(href, {
          credentials: 'same-origin',
          cache: 'no-store',
          headers: {'Accept': 'text/plain'},
        });
        if (!response.ok) {
          let detail = '';
          const type = response.headers.get('content-type') || '';
          if (type.includes('application/json')) {
            const data = await response.json().catch(() => ({}));
            detail = data.detail || data.error || '';
          } else {
            detail = (await response.text().catch(() => '')).trim();
          }
          throw new Error(detail || `生成失败（${response.status}）`);
        }

        const blob = await response.blob();
        if (!blob.size) throw new Error('服务器返回了空TXT文件');
        const filename = filenameFromDisposition(response.headers.get('Content-Disposition'));
        const url = URL.createObjectURL(blob);
        const download = document.createElement('a');
        download.href = url;
        download.download = filename.toLowerCase().endsWith('.txt') ? filename : `${filename}.txt`;
        download.style.display = 'none';
        document.body.appendChild(download);
        download.click();
        download.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1500);
        toast('缴费TXT已下载');
      } catch (err) {
        toast(`缴费TXT生成失败：${err.message || '未知错误'}`);
      } finally {
        delete txtButton.dataset.downloading;
        txtButton.removeAttribute('aria-busy');
      }
    }, true);
  }

  const dialog = document.querySelector('.v03-mail-template-dialog');
  if (!dialog) return;

  const note = dialog.querySelector('.v03-mail-template-note span');
  if (note) {
    note.textContent = '收件人、邮件主题、正文和TXT附件文件名都只属于当前客户；未填写时只提示，不会从其他客户或默认值自动补充。';
  }

  const recipient = dialog.querySelector('[data-v03-mail-recipient]');
  const recipientCaption = recipient?.closest('.v03-mail-field')?.querySelector('span');
  if (recipientCaption) {
    recipientCaption.innerHTML = '收件人 <small>按当前客户长期保存，不与其他客户共用</small>';
  }

  const attachment = dialog.querySelector('[data-v03-mail-attachment-filename]');
  const attachmentCaption = attachment?.closest('.v03-mail-field')?.querySelector('span');
  if (attachmentCaption) {
    attachmentCaption.innerHTML = 'TXT附件文件名 <small>按当前客户长期保存；必填，不自动生成</small>';
  }
  if (attachment) {
    attachment.placeholder = '例如：淄博润泰物流缴费明细.txt';
  }
})();