(() => {
  const workspace = document.querySelector('.v025-workspace');
  if (!workspace) return;
  const workbench = workspace.querySelector('[data-payment-workbench]');
  const dialog = document.getElementById('serviceAttributeDialog');
  const form = dialog?.querySelector('[data-attribute-form]');
  if (!workbench || !dialog || !form) return;
  const fields = {
    service_type:'serviceType', holder_name:'holderName', number:'number', account:'account', payment_cycle:'paymentCycle',
    payment_interval_months:'paymentIntervalMonths', next_payment_period:'nextPaymentPeriod', payment_method:'paymentMethod',
    invoice_type:'invoiceType', invoice_group_id:'invoiceGroupId', package_type:'packageType', last_payment_date:'lastPaymentDate', notes:'notes'
  };
  workbench.addEventListener('dblclick', e => {
    const id = e.target.closest('.identifier-copy');
    if (!id) return;
    e.preventDefault(); e.stopPropagation();
    const row = id.closest('[data-payment-row]');
    if (!row) return;
    form.elements.service_id.value = row.dataset.serviceId;
    Object.entries(fields).forEach(([name,key]) => { if (form.elements[name]) form.elements[name].value = row.dataset[key] || ''; });
    dialog.showModal();
    const target = id.dataset.kind === '账号' ? form.elements.account : form.elements.number;
    setTimeout(() => { target?.focus(); target?.select?.(); }, 30);
  });
})();
