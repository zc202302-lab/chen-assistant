(() => {
  const workspace = document.querySelector('.customer-workspace[data-customer-id]');
  if (!workspace) return;

  const customerId = workspace.dataset.customerId;
  if (!customerId) return;

  const servicesPanel = workspace.querySelector('[data-customer-panel="services"]');
  const sectionHead = servicesPanel?.querySelector('.section-head');
  if (!sectionHead) return;

  const csrf = workspace.querySelector('input[name="csrf"]')?.value
    || workspace.querySelector('[data-payment-workbench]')?.dataset.csrf
    || '';

  const control = document.createElement('div');
  control.className = 'customer-runtime-v143';
  control.setAttribute('data-customer-runtime-v143', '');
  control.innerHTML = `
    <span class="customer-runtime-label-v143" data-customer-runtime-label>客户状态</span>
    <span class="customer-runtime-badge-v143" data-customer-runtime-badge>读取中</span>
    <button type="button" class="customer-runtime-action-v143" data-customer-runtime-action disabled>停用客户</button>
  `;
  sectionHead.appendChild(control);

  const badge = control.querySelector('[data-customer-runtime-badge]');
  const action = control.querySelector('[data-customer-runtime-action]');
  let currentStatus = 'active';

  const paymentPanel = workspace.querySelector('[data-customer-panel="payment"]');
  let inactiveNote = null;

  const applyPaymentGate = inactive => {
    workspace.dataset.customerInactive = inactive ? '1' : '0';
    if (!paymentPanel) return;

    if (inactive) {
      if (!inactiveNote) {
        inactiveNote = document.createElement('div');
        inactiveNote.className = 'customer-inactive-note-v143';
        inactiveNote.textContent = '客户已停用：当前不参与任何缴费提醒。业务、金额、周期和既有核对状态均保留，重新启用后继续使用。';
        const card = paymentPanel.querySelector('[data-payment-workbench]');
        card?.prepend(inactiveNote);
      }
      paymentPanel.querySelectorAll('[data-payment-action], [data-v031-flow-action]').forEach(el => {
        el.disabled = true;
        el.setAttribute('aria-disabled', 'true');
      });
      const txt = paymentPanel.querySelector('#paymentTxtButton');
      if (txt) {
        txt.classList.add('disabled');
        txt.setAttribute('aria-disabled', 'true');
      }
      const readiness = paymentPanel.querySelector('#paymentReadiness');
      if (readiness) readiness.textContent = '客户已停用，不参与本月缴费提醒';
    } else if (inactiveNote) {
      inactiveNote.remove();
      inactiveNote = null;
    }
  };

  const paint = status => {
    currentStatus = status === 'inactive' ? 'inactive' : 'active';
    const active = currentStatus === 'active';
    badge.textContent = active ? '已启用' : '已停用';
    badge.classList.toggle('is-active', active);
    badge.classList.toggle('is-inactive', !active);
    action.textContent = active ? '停用客户' : '重新启用';
    action.classList.toggle('is-danger', active);
    action.classList.toggle('is-restore', !active);
    action.disabled = false;
    applyPaymentGate(!active);
  };

  const requestStatus = async () => {
    const response = await fetch(`/customers/${customerId}/runtime-v143`, {
      headers: {'Accept': 'application/json'},
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`status ${response.status}`);
    return response.json();
  };

  action.addEventListener('click', async () => {
    if (action.disabled) return;
    action.disabled = true;
    const nextStatus = currentStatus === 'active' ? 'inactive' : 'active';
    try {
      const body = new URLSearchParams({csrf, status: nextStatus});
      const response = await fetch(`/customers/${customerId}/runtime-v143`, {
        method: 'POST',
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        },
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.detail || data.error || `status ${response.status}`);
      paint(data.status);
      window.location.reload();
    } catch (error) {
      console.error('customer status update failed', error);
      action.disabled = false;
      badge.textContent = '操作失败';
      badge.classList.remove('is-active', 'is-inactive');
    }
  });

  requestStatus().then(data => paint(data.status)).catch(error => {
    console.error('customer status load failed', error);
    badge.textContent = '读取失败';
    action.disabled = true;
  });
})();
