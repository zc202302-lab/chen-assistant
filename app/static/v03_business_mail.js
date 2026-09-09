(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';

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
    setTimeout(() => el.classList.remove('show'), 1700);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  /* ---------------- 业务总览：常用筛选 + 更多筛选 ---------------- */
  const filterRoot = root.querySelector('[data-business-filters]');
  if (filterRoot && !filterRoot.dataset.v03ReadableFilters) {
    filterRoot.dataset.v03ReadableFilters = '1';
    filterRoot.classList.add('v03-readable-filters');

    const lines = [...filterRoot.querySelectorAll(':scope > .filter-line')];
    const reset = filterRoot.querySelector(':scope > [data-business-filter-reset]');
    const primary = document.createElement('div');
    primary.className = 'v03-filter-primary';
    const more = document.createElement('details');
    more.className = 'v03-filter-more';
    more.innerHTML = '<summary><span>更多筛选</span><em data-v03-more-filter-count hidden>0</em></summary><div class="v03-filter-more-body"></div>';
    const moreBody = more.querySelector('.v03-filter-more-body');

    lines.forEach((line, index) => {
      if (index < 2) primary.appendChild(line);
      else moreBody.appendChild(line);
    });
    filterRoot.prepend(primary);
    if (moreBody.children.length) primary.insertAdjacentElement('afterend', more);
    else more.remove();
    if (reset) filterRoot.appendChild(reset);

    const updateMoreCount = () => {
      const active = [...moreBody.querySelectorAll('[data-business-filter].active')]
        .filter(btn => !!btn.dataset.value).length;
      const badge = more.querySelector('[data-v03-more-filter-count]');
      if (!badge) return;
      badge.textContent = String(active);
      badge.hidden = active === 0;
      more.classList.toggle('has-active', active > 0);
    };
    filterRoot.addEventListener('click', () => requestAnimationFrame(updateMoreCount));
    updateMoreCount();
  }

  /* ---------------- 客户级邮件模板 + Foxmail 草稿 ---------------- */
  const footer = root.querySelector('.payment-footer');
  if (!footer || !customerId) return;

  // Retire the old SMTP button from the visible v0.3 workflow. v03.js may still
  // hold a reference to the detached element, but can no longer affect this UI.
  footer.querySelector('[data-v03-send-email]')?.remove();

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
        <span>系统保存主题和正文，并把本月缴费 TXT 打包进 .eml 草稿；Windows 上用 Foxmail 打开后发送。</span>
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
        <span>邮件正文 <small>可为空</small></span>
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
  let mailTemplate = {subject: '', body: ''};
  let workflowPaid = false;

  const refreshDraftButton = () => {
    const hasSubject = !!(mailTemplate.subject || '').trim();
    draftButton.disabled = !workflowPaid || !hasSubject;
    draftButton.title = !workflowPaid
      ? '完成本月缴费后可生成Foxmail草稿'
      : (!hasSubject ? '请先为当前客户保存邮件主题' : '生成包含缴费TXT附件的Foxmail邮件草稿');
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
      await loadTemplate();
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
      toast(mailTemplate.subject ? '客户邮件模板已保存' : '邮件模板已保存，主题为空时不能生成草稿');
    } catch (err) {
      toast(err.message || '邮件模板保存失败');
    } finally {
      submit.disabled = false;
    }
  });

  draftButton.addEventListener('click', async () => {
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
    // Browser downloads the RFC 5322 .eml draft. On Windows, associate .eml with
    // Foxmail; opening the downloaded draft retains subject/body/TXT attachment.
    const a = document.createElement('a');
    a.href = `/customers/${customerId}/payment-mail-draft-v03`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast('Foxmail草稿已生成，请在Windows中用Foxmail打开');
  });

  loadTemplate().catch(() => {});
  loadPaidState();
})();
