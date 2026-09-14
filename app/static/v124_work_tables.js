(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const textOf = row => {
    const values = [...row.querySelectorAll('input,textarea,select')].map(el => el.value || '').join(' ');
    return `${row.textContent || ''} ${values}`.toLowerCase();
  };

  const paymentList = root.querySelector('.v0211-payment-list');
  if (paymentList && !root.querySelector('[data-v124-payment-tools]')) {
    const tools = document.createElement('div');
    tools.className = 'v124-table-tools';
    tools.dataset.v124PaymentTools = '1';
    tools.innerHTML = `
      <div class="v124-table-tools-title"><b>缴费明细</b><span>搜索与筛选</span></div>
      <input class="v124-table-search" type="search" placeholder="搜索号码 / 账号 / 姓名 / 表格内容" data-v124-payment-search>
      <div class="v124-filter-group" role="group" aria-label="缴费筛选">
        <button type="button" class="active" data-v124-payment-filter="all">全部</button>
        <button type="button" data-v124-payment-filter="pending">待核对</button>
        <button type="button" data-v124-payment-filter="confirmed">已核对</button>
        <button type="button" data-v124-payment-filter="variable">变动</button>
        <button type="button" data-v124-payment-filter="fixed">固定</button>
      </div>`;
    paymentList.parentNode.insertBefore(tools, paymentList);

    const search = tools.querySelector('[data-v124-payment-search]');
    let filter = 'all';
    const apply = () => {
      const q = (search.value || '').trim().toLowerCase();
      paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
        const textMatch = !q || textOf(row).includes(q);
        let stateMatch = true;
        if (filter === 'pending') stateMatch = row.dataset.confirmed === '0';
        else if (filter === 'confirmed') stateMatch = row.dataset.confirmed === '1';
        else if (filter === 'variable') stateMatch = row.dataset.mode === 'variable';
        else if (filter === 'fixed') stateMatch = row.dataset.mode === 'fixed';
        row.hidden = !(textMatch && stateMatch);
      });
    };
    search.addEventListener('input', apply);
    tools.addEventListener('click', e => {
      const btn = e.target.closest('[data-v124-payment-filter]');
      if (!btn) return;
      filter = btn.dataset.v124PaymentFilter || 'all';
      tools.querySelectorAll('[data-v124-payment-filter]').forEach(x => x.classList.toggle('active', x === btn));
      apply();
    });

    const total = document.querySelector('.v023-total');
    if (total && !paymentList.querySelector('.v124-payment-total-row')) {
      const keys = String(paymentList.dataset.paymentColumnKeys || '').split(',').filter(Boolean);
      const row = document.createElement('div');
      row.className = 'v124-payment-total-row';
      const gutter = document.createElement('span');
      gutter.className = 'v124-total-gutter';
      row.appendChild(gutter);
      keys.forEach(key => {
        const cell = document.createElement('div');
        cell.className = 'v124-total-cell';
        cell.dataset.paymentAttrKey = key;
        if (key === 'payment_amount') {
          cell.classList.add('is-amount-total');
          total.classList.add('v124-total-moved');
          cell.appendChild(total);
        }
        row.appendChild(cell);
      });
      const action = document.createElement('span');
      action.className = 'v124-total-action';
      row.appendChild(action);
      paymentList.appendChild(row);
    }
  }

  const businessCard = root.querySelector('.business-v028');
  if (businessCard && !businessCard.querySelector('[data-v124-business-search]')) {
    const head = businessCard.querySelector('.section-head');
    const wrap = document.createElement('div');
    wrap.className = 'v124-business-search-wrap';
    wrap.innerHTML = '<input class="v124-table-search" type="search" placeholder="搜索业务表格内容" data-v124-business-search>';
    head?.appendChild(wrap);
    const search = wrap.querySelector('[data-v124-business-search]');
    const apply = () => {
      const q = (search.value || '').trim().toLowerCase();
      businessCard.querySelectorAll('[data-business-row]').forEach(row => {
        row.style.display = !q || textOf(row).includes(q) ? '' : 'none';
      });
    };
    search.addEventListener('input', apply);
  }

  const focusService = new URLSearchParams(location.search).get('focus_service');
  if (focusService) {
    const target = root.querySelector(`[data-business-row][data-service-id="${focusService}"]`);
    if (target) {
      const businessTab = root.querySelector('[data-customer-tab="services"]');
      if (businessTab && !businessTab.classList.contains('active')) businessTab.click();
      target.classList.add('v124-focus-hit');
      requestAnimationFrame(() => requestAnimationFrame(() => {
        target.scrollIntoView({behavior: 'smooth', block: 'center'});
      }));
      setTimeout(() => target.classList.remove('v124-focus-hit'), 5000);
    }
  }
})();
