(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const templateButton = root.querySelector('[data-v03-mail-template]');
  const dialog = document.querySelector('.v03-mail-template-dialog');
  const form = dialog?.querySelector('[data-v03-mail-template-form]');
  if (!customerId || !templateButton || !dialog || !form) return;

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
    setTimeout(() => el.classList.remove('show'), 2200);
  };

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  /* ---------------- 缴费工作区标题：两行 ---------------- */
  const paymentHead = root.querySelector('.v025-payment-head');
  const titleLine = root.querySelector('.v023-payment-title-line');
  if (paymentHead && titleLine) {
    paymentHead.classList.add('v03-payment-head-two-row');

    let tools = paymentHead.querySelector('[data-v03-payment-head-tools]');
    if (!tools) {
      tools = document.createElement('div');
      tools.className = 'v03-payment-head-tools';
      tools.dataset.v03PaymentHeadTools = '1';
      tools.innerHTML = '<div class="v03-payment-head-tools-left"></div><div class="v03-payment-head-tools-right"></div>';
      paymentHead.appendChild(tools);
    }

    const left = tools.querySelector('.v03-payment-head-tools-left');
    const right = tools.querySelector('.v03-payment-head-tools-right');
    const attributeButton = titleLine.querySelector('[data-payment-columns-settings]');
    const workflow = titleLine.querySelector('[data-v03-payment-flow]');

    if (attributeButton) left.appendChild(attributeButton);
    templateButton.textContent = '缴费模板';
    templateButton.classList.add('v03-payment-template-button');
    left.appendChild(templateButton);
    if (workflow) right.appendChild(workflow);
  } else {
    templateButton.textContent = '缴费模板';
  }

  /* ---------------- “邮件模板”升级为客户级“缴费模板” ---------------- */
  const headTitle = dialog.querySelector('.v03-mail-template-head h3');
  if (headTitle) headTitle.textContent = '缴费模板';
  const headKicker = dialog.querySelector('.v03-mail-template-head small');
  if (headKicker) headKicker.textContent = '当前客户长期使用';

  const note = dialog.querySelector('.v03-mail-template-note span');
  if (note) {
    note.textContent = '邮件主题、正文和TXT附件文件名长期绑定当前客户；收件人全局共用。调用Foxmail时自动带入当前客户的缴费TXT附件。';
  }

  const subjectInput = dialog.querySelector('[data-v03-mail-subject]');
  const bodyInput = dialog.querySelector('[data-v03-mail-body]');
  const recipientInput = dialog.querySelector('[data-v03-mail-recipient]');
  const subjectField = subjectInput?.closest('.v03-mail-field');

  let attachmentInput = dialog.querySelector('[data-v03-mail-attachment-filename]');
  if (!attachmentInput && subjectField) {
    const field = document.createElement('label');
    field.className = 'v03-mail-field v03-payment-attachment-field';
    field.innerHTML = `
      <span>TXT附件文件名 <small>按客户长期保存；不写 .txt 会自动补全</small></span>
      <input type="text" maxlength="160" data-v03-mail-attachment-filename
             placeholder="例如：淄博润泰物流缴费明细.txt；留空使用自动文件名">`;
    subjectField.insertAdjacentElement('afterend', field);
    attachmentInput = field.querySelector('[data-v03-mail-attachment-filename]');
  }

  const loadPaymentTemplate = async () => {
    const data = await fetchJson(`/customers/${customerId}/mail-template-v03`);
    const template = data.template || {};
    if (attachmentInput) attachmentInput.value = template.attachment_filename || '';
    return data;
  };

  templateButton.addEventListener('click', () => {
    loadPaymentTemplate().catch(err => toast(err.message || '缴费模板读取失败'));
  }, true);

  /*
   * 接管保存动作，把附件文件名与邮件主题/正文一起保存。
   * capture=true 保证在旧邮件模板提交处理器之前执行，避免一次点击发出两次保存请求。
   */
  form.addEventListener('submit', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;

    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('recipient', recipientInput?.value.trim() || '');
    fd.append('subject', subjectInput?.value.trim() || '');
    fd.append('body', bodyInput?.value || '');
    fd.append('attachment_filename', attachmentInput?.value.trim() || '');

    try {
      const data = await fetchJson(`/customers/${customerId}/mail-template-v03`, {method: 'POST', body: fd});
      const template = data.template || {};
      if (recipientInput) recipientInput.value = data.recipient || '';
      if (subjectInput) subjectInput.value = template.subject || '';
      if (bodyInput) bodyInput.value = template.body || '';
      if (attachmentInput) attachmentInput.value = template.attachment_filename || '';
      if (dialog.open) dialog.close();
      toast('当前客户缴费模板已保存');
    } catch (err) {
      toast(err.message || '缴费模板保存失败');
    } finally {
      if (submit) submit.disabled = false;
    }
  }, true);

  loadPaymentTemplate().catch(() => {});
})();
