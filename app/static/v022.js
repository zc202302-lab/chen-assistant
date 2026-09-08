(() => {
  const tabs = document.querySelector('[data-customer-tabs]');
  if (tabs) {
    const buttons = [...tabs.querySelectorAll('[data-customer-tab]')];
    const panels = [...tabs.querySelectorAll('[data-customer-panel]')];
    const showTab = (name, updateUrl = true) => {
      if (!panels.some(p => p.dataset.customerPanel === name)) name = 'payment';
      buttons.forEach(b => b.classList.toggle('active', b.dataset.customerTab === name));
      panels.forEach(p => { p.hidden = p.dataset.customerPanel !== name; });
      tabs.dataset.activeTab = name;
      if (updateUrl) {
        const u = new URL(location.href);
        if (name === 'payment') u.searchParams.delete('tab');
        else u.searchParams.set('tab', name);
        history.replaceState(null, '', u.pathname + u.search + u.hash);
      }
    };
    buttons.forEach(b => b.addEventListener('click', () => showTab(b.dataset.customerTab)));
    tabs.querySelectorAll('[data-tab-open]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tabOpen)));
    showTab(tabs.dataset.activeTab || 'payment', false);

    tabs.querySelectorAll('form[data-workspace-form]').forEach(form => {
      form.addEventListener('submit', async e => {
        e.preventDefault();
        e.stopPropagation();
        if (form.dataset.confirm && !confirm(form.dataset.confirm)) return;
        const submit = form.querySelector('button[type="submit"],button:not([type])');
        if (submit) submit.disabled = true;
        try {
          const r = await fetch(form.action, {
            method: (form.method || 'POST').toUpperCase(),
            body: new FormData(form),
            credentials: 'same-origin'
          });
          if (!r.ok) {
            const text = await r.text().catch(() => '');
            alert(text && text.length < 160 ? text : '保存失败');
            return;
          }
          const tab = form.dataset.returnTab || tabs.dataset.activeTab || 'payment';
          const id = tabs.dataset.customerId;
          location.href = `/customers/${id}${tab === 'payment' ? '' : `?tab=${encodeURIComponent(tab)}`}`;
        } catch (_) {
          alert('网络异常，操作未保存');
        } finally {
          if (submit) submit.disabled = false;
        }
      });
    });
  }

  const syncPaymentRow = row => {
    const done = row.dataset.mode === 'fixed' || row.dataset.confirmed === '1';
    row.classList.toggle('is-confirmed', done);
    row.classList.toggle('is-pending', !done);
    const state = row.querySelector('[data-row-state]');
    if (state) {
      state.textContent = done ? '✓' : '○';
      state.classList.toggle('confirmed', done);
      state.classList.toggle('pending', !done);
      state.title = done ? '本月已确认' : '本月待核对';
    }
    const rule = row.querySelector('[data-fixed-toggle]');
    if (rule) {
      const fixed = row.dataset.mode === 'fixed';
      rule.textContent = fixed ? '固' : '变';
      rule.title = fixed ? '固定金额，点击取消固定' : '变动金额，点击设为固定';
      rule.classList.toggle('is-fixed', fixed);
    }
  };

  const rows = [...document.querySelectorAll('[data-payment-row]')];
  rows.forEach(syncPaymentRow);
  if (rows.length) {
    const observer = new MutationObserver(records => {
      const touched = new Set();
      records.forEach(r => {
        const row = r.target.closest?.('[data-payment-row]') || (r.target.matches?.('[data-payment-row]') ? r.target : null);
        if (row) touched.add(row);
      });
      touched.forEach(syncPaymentRow);
    });
    rows.forEach(row => observer.observe(row, { attributes: true, attributeFilter: ['data-confirmed', 'data-mode'] }));
  }
})();
