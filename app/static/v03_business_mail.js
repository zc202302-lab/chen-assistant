(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const FOXMAIL_BRIDGE = 'http://127.0.0.1:18763';

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
    setTimeout(() => el.classList.remove('show'), 1900);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const applyBusinessRows = rows => {
    Object.entries(rows || {}).forEach(([sid, payload]) => {
      const card = root.querySelector(`[data-business-row][data-service-id="${CSS.escape(String(sid))}"]`);
      if (!card) return;
      const grid = card.querySelector('[data-business-attrs]');
      if (grid) {
        grid.innerHTML = '';
        const attrs = payload.preview_attributes || [];
        grid.style.setProperty('--business-visible-count', String(Math.max(1, attrs.length)));
        attrs.forEach(attr => {
          const box = document.createElement('div');
          box.className = 'business-attribute';
          box.dataset.attrKey = attr.key || '';
          const shown = attr.value || '—';
          box.title = `${attr.label || '属性'}：${shown} · 双击编辑`;
          // Keep the label in the DOM because business-sync.js uses it to build the
          // table header, but hide the repeated row label visually for readability.
          const small = document.createElement('small');
          small.className = 'business-attribute-label-v03';
          small.textContent = attr.label || '属性';
          const strong = document.createElement('strong');
          strong.textContent = shown;
          box.append(small, strong);
          grid.appendChild(box);
        });
      }
      if (payload.due !== undefined) card.dataset.filterDue = payload.due ? '1' : '0';
    });
  };

  /* ---------------- 客户级业务显示配置 ---------------- */
  const syncCustomerBusinessDisplay = async () => {
    if (!customerId) return;
    try {
      const data = await fetchJson(`/customers/${customerId}/business-columns-v0212`);
      applyBusinessRows(data.rows || {});
    } catch (_) {}
  };
  syncCustomerBusinessDisplay();

  /* ---------------- 业务总览：一条常用筛选 + 更多筛选 ---------------- */
  const filterRoot = root.querySelector('[data-business-filters]');
  if (filterRoot && !filterRoot.dataset.v03ReadableFilters) {
    filterRoot.dataset.v03ReadableFilters = '1';
    filterRoot.classList.add('v03-readable-filters');

    const lines = [...filterRoot.querySelectorAll(':scope > .filter-line')];
    const reset = filterRoot.querySelector(':scope > [data-business-filter-reset]');
    const primary = document.createElement('div');
    primary.className = 'v03-filter-primary';
    const primaryLabel = document.createElement('span');
    primaryLabel.className = 'v03-filter-primary-label';
    primaryLabel.textContent = '快速筛选';
    primary.appendChild(primaryLabel);

    // 缴费状态是业务总览里最高频的筛选，因此只把这一组常驻显示。
    const dueLine = lines.find(line => line.querySelector('[data-business-filter="due"]')) || lines[0];
    if (dueLine) primary.appendChild(dueLine);

    const more = document.createElement('details');
    more.className = 'v03-filter-more';
    more.innerHTML = '<summary><span>更多筛选</span><em data-v03-more-filter-count hidden>0</em></summary><div class="v03-filter-more-body"></div>';
    const moreBody = more.querySelector('.v03-filter-more-body');
    lines.forEach(line => {
      if (line !== dueLine) moreBody.appendChild(line);
    });

    const selectedSummary = document.createElement('span');
    selectedSummary.className = 'v03-filter-selection-summary';
    selectedSummary.textContent = '全部业务';
    primary.appendChild(selectedSummary);

    filterRoot.prepend(primary);
    if (moreBody.children.length) primary.insertAdjacentElement('afterend', more);
    else more.remove();
    if (reset) filterRoot.appendChild(reset);

    const activeButtons = () => [...filterRoot.querySelectorAll('[data-business-filter].active')]
      .filter(btn => !!btn.dataset.value);

    const updateFilterSummary = () => {
      const active = activeButtons();
      const extraActive = active.filter(btn => moreBody.contains(btn));
      const badge = more.querySelector('[data-v03-more-filter-count]');
      if (badge) {
        badge.textContent = String(extraActive.length);
        badge.hidden = extraActive.length === 0;
        more.classList.toggle('has-active', extraActive.length > 0);
      }
      if (active.length === 0) {
        selectedSummary.textContent = '全部业务';
      } else {
        selectedSummary.textContent = active.map(btn => btn.textContent.trim()).join(' · ');
      }
      if (reset) reset.hidden = active.length === 0;
    };

    filterRoot.addEventListener('click', () => requestAnimationFrame(updateFilterSummary));
    updateFilterSummary();
  }

  /* ---------------- 客户级邮件模板 + Windows Foxmail ---------------- */
  const footer = root.querySelector('.payment-footer');
  if (!footer || !customerId) return;

  // SMTP is retired from the visible v0.3 workflow. Keep its old node hidden so
  // legacy automation/compatibility checks do not break while the UI moves to Foxmail.
  const oldSmtpButton = footer.querySelector('[data-v03-send-email]');
  oldSmtpButton?.classList.add('v03-retired-smtp');

  const mailActions = document.createElement('div');
  mailActions.className = 'v03-local-mail-actions';
  mailActions.innerHTML = `
    <button type="button" class="secondary" data-v03-mail-template>邮件模板</button>
    <button type="button" class="primary" data-v03-foxmail-draft disabled>Foxmail草稿</button>`;
  footer.appendChild(mailActions);

  const templateButton = mailActions.querySelector('[data-v03-mail-template]');
  const draftButton = mailActions.querySelector('[data-v03-foxmail-draft]');

  const dialog = document.createElement('dialog');
  dialog.className = 'v03-mail-template-dialog';
  dialog.innerHTML = `
    <form method="dialog" class="v03-mail-template-card" data-v03-mail-template-form>
      <div class="v03-mail-template-head">
        <div><small>当前客户长期使用</small><h3>Foxmail 邮件模板</h3></div>
        <button type="button" class="dialog-x" data-v03-mail-close aria-label="关闭">×</button>
      </div>
      <div class="v03-mail-template-note">
        <b>发送方式</b>
        <span>保存后长期绑定当前客户。完成缴费后优先调用 Windows Foxmail；未检测到本地助手时自动下载 .eml 草稿。</span>
        <i data-v03-foxmail-bridge-state>正在检测 Windows 助手…</i>
      </div>
      <label class="v03-mail-field">
        <span>收件人 <small>全局固定</small></span>
        <input type="text" data-v03-mail-recipient readonly placeholder="尚未配置，可在Foxmail中填写">
      </label>
      <label class="v03-mail-field">
        <span>邮件主题 <small>按客户长期保存</small></span>
        <input type="text" maxlength="300" data-v03-mail-subject placeholder="例如：中泰物流9月份缴费明细">
      </label>
      <label class="v03-mail-field">
        <span>邮件正文 <small>按客户长期保存，可为空</small></span>
        <textarea rows="6" maxlength="10000" data-v03-mail-body placeholder="正文可留空"></textarea>
      </label>
      <div class="v03-mail-template-actions">
        <button type="button" class="secondary" data-v03-mail-cancel>取消</button>
        <button type="submit" class="primary">保存模板</button>
      </div>
    </form>`;
  document.body.appendChild(dialog);

  const form = dialog.querySelector('[data-v03-mail-template-form]');
  const recipientInput = dialog.querySelector('[data-v03-mail-recipient]');
  const subjectInput = dialog.querySelector('[data-v03-mail-subject]');
  const bodyInput = dialog.querySelector('[data-v03-mail-body]');
  const bridgeState = dialog.querySelector('[data-v03-foxmail-bridge-state]');
  let mailTemplate = {subject: '', body: ''};
  let workflowPaid = false;
  let bridgeOnline = false;

  const bridgeFetch = async (path, options = {}, timeoutMs = 900) => {
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

  const updateBridgeState = () => {
    if (bridgeState) {
      bridgeState.textContent = bridgeOnline
        ? 'Windows 助手已连接：可直接调用 Foxmail'
        : '未检测到 Windows 助手：将使用 .eml 草稿下载';
      bridgeState.classList.toggle('online', bridgeOnline);
    }
    if (!draftButton.disabled) draftButton.textContent = bridgeOnline ? '调用Foxmail' : 'Foxmail草稿';
  };

  const probeBridge = async () => {
    try {
      const response = await bridgeFetch('/health', {}, 650);
      const data = await response.json().catch(() => ({}));
      bridgeOnline = response.ok && data.ok === true;
    } catch (_) {
      bridgeOnline = false;
    }
    updateBridgeState();
    return bridgeOnline;
  };

  const refreshDraftButton = () => {
    const hasSubject = !!(mailTemplate.subject || '').trim();
    draftButton.disabled = !workflowPaid || !hasSubject;
    draftButton.textContent = bridgeOnline ? '调用Foxmail' : 'Foxmail草稿';
    draftButton.title = !workflowPaid
      ? '完成本月缴费后可生成Foxmail草稿'
      : (!hasSubject ? '请先为当前客户保存邮件主题' : (bridgeOnline ? '直接在Windows中打开Foxmail邮件草稿' : '生成包含缴费TXT附件的Foxmail邮件草稿'));
  };

  const loadTemplate = async () => {
    const data = await fetchJson(`/customers/${customerId}/mail-template-v03`);
    mailTemplate = data.template || {subject: '', body: ''};
    recipientInput.value = data.recipient || '';
    recipientInput.placeholder = data.recipient_configured ? '' : '尚未配置，可在Foxmail中填写';
    subjectInput.value = mailTemplate.subject || '';
    bodyInput.value = mailTemplate.body || '';
    refreshDraftButton();
    return data;
  };

  const loadPaidState = async () => {
    try {
      let data;
      try {
        data = await fetchJson(`/customers/${customerId}/workflow-state-v03`);
      } catch (_) {
        data = await fetchJson(`/customers/${customerId}/payment-run-v03`);
      }
      workflowPaid = !!data.run?.paid;
    } catch (_) {
      workflowPaid = false;
    }
    refreshDraftButton();
  };

  templateButton.addEventListener('click', async () => {
    templateButton.disabled = true;
    try {
      await Promise.all([loadTemplate(), probeBridge()]);
      dialog.showModal();
      subjectInput.focus();
      subjectInput.select();
    } catch (err) {
      toast(err.message || '邮件模板读取失败');
    } finally {
      templateButton.disabled = false;
    }
  });

  const closeDialog = () => dialog.open && dialog.close();
  dialog.querySelector('[data-v03-mail-close]').addEventListener('click', closeDialog);
  dialog.querySelector('[data-v03-mail-cancel]').addEventListener('click', closeDialog);
  dialog.addEventListener('click', e => {
    if (e.target === dialog) closeDialog();
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('subject', subjectInput.value.trim());
    fd.append('body', bodyInput.value || '');
    try {
      const data = await fetchJson(`/customers/${customerId}/mail-template-v03`, {method: 'POST', body: fd});
      mailTemplate = data.template || mailTemplate;
      recipientInput.value = data.recipient || '';
      closeDialog();
      refreshDraftButton();
      toast(mailTemplate.subject ? '当前客户邮件模板已保存' : '模板已保存；主题为空时不能生成邮件');
    } catch (err) {
      toast(err.message || '邮件模板保存失败');
    } finally {
      submit.disabled = false;
    }
  });

  const filenameFromDisposition = (headerValue, fallback = 'payment.eml') => {
    const value = headerValue || '';
    const utf8 = value.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8) {
      try { return decodeURIComponent(utf8[1].trim()); } catch (_) {}
    }
    const plain = value.match(/filename="?([^";]+)"?/i);
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
    const bytes = new TextEncoder().encode(text || '');
    return bytesToBase64(bytes);
  };

  const openWithLocalFoxmail = async (blob, filename) => {
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
      }, 3500);
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok !== true) throw new Error(data.error || '本地助手打开失败');
      return true;
    } catch (_) {
      bridgeOnline = false;
      updateBridgeState();
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
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1200);
  };

  draftButton.addEventListener('click', async () => {
    draftButton.disabled = true;
    try {
      await loadPaidState();
      if (!workflowPaid) return toast('请先完成本月缴费');
      if (!(mailTemplate.subject || '').trim()) {
        try { await loadTemplate(); } catch (_) {}
        if (!(mailTemplate.subject || '').trim()) {
          dialog.showModal();
          subjectInput.focus();
          return toast('请先为这个客户保存邮件主题');
        }
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
      const opened = await openWithLocalFoxmail(blob, filename);
      if (opened) {
        toast('已调用 Windows Foxmail，请检查邮件主题、正文和附件后发送');
      } else {
        downloadBlob(blob, filename);
        toast('未检测到 Windows 助手，已下载 Foxmail .eml 草稿');
      }
    } catch (err) {
      toast(err.message || 'Foxmail草稿生成失败');
    } finally {
      refreshDraftButton();
    }
  });

  loadTemplate().catch(() => {});
  loadPaidState();
  probeBridge();
})();
