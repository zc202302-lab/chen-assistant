(() => {
  const root = document.querySelector('.v0211-workspace');
  const dialog = document.getElementById('businessAttributeDialog');
  if (!root || !dialog) return;
  let paymentMembershipDirty = false;
  root.addEventListener('chen:service-properties-updated', () => { paymentMembershipDirty = true; });
  root.addEventListener('click', event => {
    if (!paymentMembershipDirty || !event.target.closest('[data-customer-tab="payment"]')) return;
    event.preventDefault(); event.stopImmediatePropagation();
    location.href = `/customers/${root.dataset.customerId}?tab=payment`;
  }, true);
  // Mode changes are saved atomically with the business attributes.
  root.addEventListener('chen:service-editor-opened', event => {
    const box = dialog.querySelector('.v03-payment-state-box');
    if (!box) return;
    box.innerHTML = '<span>缴费模式</span><select data-v031-payment-mode aria-label="缴费模式"><option value="periodic">周期缴费</option><option value="specified">指定缴费</option></select><small data-payment-mode-help></small><strong data-v03-payment-state hidden></strong>';
    const select = box.querySelector('select');
    select.value = event.detail.schedule_mode || 'periodic';
    const explain = () => {
      const help = select.value === 'periodic'
        ? '按上次缴费时间和缴费周期计算' : '按下次缴费时间安排';
      select.title = help;
      box.querySelector('small').textContent = help;
    };
    select.addEventListener('change', explain);
    explain();
  });
})();
