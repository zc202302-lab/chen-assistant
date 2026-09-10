(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  // v0.3.3 keeps the fast operator workflow non-blocking. Older modules still
  // call confirm()/alert(); suppress only the payment messages that are now
  // represented by workflow button state + toast feedback.
  const nativeConfirm = window.confirm.bind(window);
  const nativeAlert = window.alert.bind(window);

  const silentConfirm = text => {
    return (
      text.includes('确认已经把本次缴费图片通过微信发送给客户') ||
      text.includes('确认已经在Foxmail中将缴费邮件发送给同事') ||
      text.includes('确认缴费图片已经通过微信发送给客户') ||
      text.includes('确认缴费邮件已经在Foxmail中发送给同事') ||
      text.includes('确认撤回“通知客户”状态') ||
      text.includes('确认撤回“发起缴费”状态') ||
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
      if (window.ChenToast) {
        if (text.includes('Foxmail写邮件窗口')) {
          window.ChenToast('Foxmail已打开；发送后再次点击“发起缴费”即可确认');
        } else {
          window.ChenToast('缴费图片已准备；发送后再次点击“通知客户”即可确认');
        }
      }
      return;
    }
    return nativeAlert(message);
  };

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
