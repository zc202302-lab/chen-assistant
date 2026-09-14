(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const paymentList = document.getElementById('paymentSortable');
  const businessList = root.querySelector('[data-business-list]');
  const flow = root.querySelector('[data-v031-payment-flow]');

  const rowText = row => {
    const formValues = [...row.querySelectorAll('input,textarea,select')].map(el => el.value || '').join(' ');
    return `${row.textContent || ''} ${formValues}`.toLowerCase();
  };

  const normalized = value => String(value ?? '').trim().toLowerCase();

  /* v1.2.5: stage 1 is derived state, never a manual workflow action. */
  const reviewButton = flow?.querySelector('[data-v031-flow-action="review"]');
  const paintReviewFromRows = () => {
    if (!reviewButton || !paymentList) return;
    const rows = [...paymentList.querySelectorAll('[data-payment-row]')];
    const allConfirmed = rows.length > 0 && rows.every(row => row.dataset.confirmed === '1');
    reviewButton.disabled = true;
    reviewButton.setAttribute('aria-disabled', 'true');
    reviewButton.setAttribute('aria-pressed', allConfirmed ? 'true' : 'false');
    reviewButton.classList.toggle('done', allConfirmed);
    reviewButton.classList.toggle('current', !allConfirmed);
    reviewButton.textContent = allConfirmed ? '✓ 1 金额核对' : '1 金额核对';
    reviewButton.title = allConfirmed ? '所有缴费金额均已确认，自动完成金额核对' : '存在未核对金额，金额核对自动失效';
  };

  document.addEventListener('click', event => {
    const btn = event.target.closest?.('[data-v031-flow-action="review"]');
    if (!btn) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    paintReviewFromRows();
  }, true);

  let reviewSyncTimer = 0;
  const syncWorkflow = () => {
    paintReviewFromRows();
    clearTimeout(reviewSyncTimer);
    reviewSyncTimer = setTimeout(() => {
      window.ChenPaymentWorkflowRuntimeV031?.refresh?.();
    }, 80);
  };

  if (paymentList) {
    new MutationObserver(mutations => {
      if (mutations.some(m => m.type === 'attributes' && m.attributeName === 'data-confirmed')) syncWorkflow();
    }).observe(paymentList, {subtree: true, attributes: true, attributeFilter: ['data-confirmed']});
    paintReviewFromRows();
    setTimeout(syncWorkflow, 350);
  }

  /* Remove all v1.2.4 standalone search/filter bars. */
  root.querySelectorAll('[data-v124-payment-tools], .v124-business-search-wrap').forEach(el => el.remove());
  root.querySelectorAll('[data-business-filters], .business-filters').forEach(el => el.remove());
  const legacyServiceFilter = root.querySelector('#serviceFilter');
  legacyServiceFilter?.remove();

  const applyPaymentFilters = () => {
    if (!paymentList) return;
    const inputs = [...paymentList.querySelectorAll('[data-v125-payment-filter]')];
    const state = paymentList.querySelector('[data-v125-payment-state]')?.value || '';
    paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
      let show = true;
      inputs.forEach(input => {
        if (!show) return;
        const q = normalized(input.value);
        if (!q) return;
        const key = input.dataset.v125PaymentFilter || '';
        let cellText = '';
        if (key === 'payment_amount') cellText = row.querySelector('.quick-amount')?.value || '';
        else if (key === 'number') cellText = row.querySelector('[data-payment-attr-key="number"], [data-display="number"]')?.textContent || row.querySelector('.dense-id:nth-of-type(1)')?.textContent || '';
        else if (key === 'account') cellText = row.querySelector('[data-payment-attr-key="account"], [data-display="account"]')?.textContent || '';
        else if (key) cellText = row.querySelector(`[data-payment-attr-key="${CSS.escape(key)}"]`)?.textContent || '';
        if (!cellText) cellText = rowText(row);
        show = normalized(cellText).includes(q);
      });
      if (show && state) {
        if (state === 'pending') show = row.dataset.confirmed === '0';
        else if (state === 'confirmed') show = row.dataset.confirmed === '1';
        else if (state === 'fixed') show = row.dataset.mode === 'fixed';
        else if (state === 'variable') show = row.dataset.mode === 'variable';
      }
      row.hidden = !show;
      row.style.display = show ? '' : 'none';
    });
  };

  const installPaymentHeaderFilters = () => {
    if (!paymentList || paymentList.dataset.v125HeaderFilters === '1') return;
    const header = paymentList.querySelector('.v028-payment-header, .dense-payment-header');
    if (!header) return;
    paymentList.dataset.v125HeaderFilters = '1';
    const dynamicHeads = [...header.querySelectorAll('[data-payment-column-head]')];
    const fallbackHeads = [...header.querySelectorAll('.resizable-head')];
    const heads = dynamicHeads.length ? dynamicHeads : fallbackHeads;
    const fallbackKeys = ['attr', 'number', 'account', 'payment_amount'];
    heads.forEach((head, index) => {
      const key = head.dataset.paymentAttrKey || fallbackKeys[index] || `col_${index}`;
      head.classList.add('v125-filter-head');
      if (head.querySelector('[data-v125-payment-filter]')) return;
      const input = document.createElement('input');
      input.type = 'search';
      input.autocomplete = 'off';
      input.className = 'v125-head-search';
      input.placeholder = '搜索';
      input.dataset.v125PaymentFilter = key;
      input.setAttribute('aria-label', `${head.textContent.trim() || key}筛选`);
      input.addEventListener('pointerdown', e => e.stopPropagation());
      input.addEventListener('click', e => e.stopPropagation());
      input.addEventListener('input', applyPaymentFilters);
      head.appendChild(input);
    });
    const trailing = header.lastElementChild;
    if (trailing && !trailing.querySelector?.('[data-v125-payment-state]')) {
      trailing.classList.add('v125-state-head');
      const select = document.createElement('select');
      select.className = 'v125-head-select';
      select.dataset.v125PaymentState = '1';
      select.innerHTML = '<option value="">全部</option><option value="pending">待核对</option><option value="confirmed">已核对</option><option value="fixed">固定</option><option value="variable">变动</option>';
      select.addEventListener('change', applyPaymentFilters);
      trailing.appendChild(select);
    }
  };

  const businessAttrValues = row => [...row.querySelectorAll('.business-attribute')].map(cell => normalized(cell.querySelector('strong')?.textContent || cell.textContent));
  const businessFilters = {attrs: [], type: '', due: '', mode: '', promo: '', invoice: ''};
  const applyBusinessFilters = () => {
    if (!businessList) return;
    let visible = 0;
    businessList.querySelectorAll('[data-business-row]').forEach(row => {
      const values = businessAttrValues(row);
      let show = businessFilters.attrs.every((q, i) => !q || (values[i] || '').includes(q));
      if (show && businessFilters.type) show = row.dataset.filterType === businessFilters.type;
      if (show && businessFilters.due) show = row.dataset.filterDue === businessFilters.due;
      if (show && businessFilters.mode) show = row.dataset.filterMode === businessFilters.mode;
      if (show && businessFilters.promo) show = row.dataset.filterPromo === businessFilters.promo;
      if (show && businessFilters.invoice) show = row.dataset.filterInvoice === businessFilters.invoice;
      row.hidden = !show;
      row.style.display = show ? '' : 'none';
      if (show) visible += 1;
    });
    const count = document.getElementById('businessVisibleCount');
    if (count) count.textContent = String(visible);
  };

  const unique = key => [...new Set([...businessList.querySelectorAll('[data-business-row]')].map(row => row.dataset[key] || '').filter(Boolean))];
  const optionHtml = (allLabel, values) => `<option value="">${allLabel}</option>${values.map(v => `<option value="${String(v).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;')}">${v}</option>`).join('')}`;

  const installBusinessHeaderFilters = () => {
    if (!businessList || businessList.dataset.v125HeaderFilters === '1') return;
    const first = businessList.querySelector('[data-business-row]');
    if (!first) return;
    const attrs = [...first.querySelectorAll('.business-attribute')];
    if (!attrs.length) return;
    businessList.dataset.v125HeaderFilters = '1';
    businessFilters.attrs = attrs.map(() => '');

    const header = document.createElement('div');
    header.className = 'v125-business-header';
    header.style.setProperty('--v125-business-cols', String(attrs.length));
    attrs.forEach((attr, index) => {
      const cell = document.createElement('div');
      cell.className = 'v125-business-head-cell';
      const label = attr.querySelector('small')?.textContent?.trim() || `字段${index + 1}`;
      cell.innerHTML = `<span>${label}</span><input type="search" autocomplete="off" class="v125-head-search" placeholder="搜索" data-v125-business-attr="${index}">`;
      cell.querySelector('input').addEventListener('input', event => {
        businessFilters.attrs[index] = normalized(event.target.value);
        applyBusinessFilters();
      });
      header.appendChild(cell);
    });

    const filterCell = document.createElement('div');
    filterCell.className = 'v125-business-head-cell v125-business-conditions';
    filterCell.innerHTML = '<span>筛选</span><button type="button" class="v125-filter-button" data-v125-business-filter-button>▾</button><div class="v125-filter-popover" data-v125-business-filter-popover hidden></div>';
    const popover = filterCell.querySelector('[data-v125-business-filter-popover]');
    const invoiceValues = unique('filterInvoice');
    popover.innerHTML = `
      <label>类型<select data-key="type">${optionHtml('全部', unique('filterType'))}</select></label>
      <label>缴费<select data-key="due"><option value="">全部</option><option value="1">本月应缴</option><option value="0">本月不缴</option></select></label>
      <label>金额<select data-key="mode"><option value="">全部</option><option value="fixed">固定</option><option value="variable">变动</option></select></label>
      <label>优惠<select data-key="promo">${optionHtml('全部', unique('filterPromo'))}</select></label>
      <label>发票组<select data-key="invoice">${optionHtml('全部', invoiceValues)}</select></label>
      <button type="button" class="ghost small" data-v125-clear-business>清除</button>`;
    filterCell.querySelector('[data-v125-business-filter-button]').addEventListener('click', event => {
      event.stopPropagation();
      popover.hidden = !popover.hidden;
    });
    popover.addEventListener('change', event => {
      const select = event.target.closest('select[data-key]');
      if (!select) return;
      businessFilters[select.dataset.key] = select.value;
      applyBusinessFilters();
    });
    popover.querySelector('[data-v125-clear-business]').addEventListener('click', () => {
      Object.assign(businessFilters, {type:'', due:'', mode:'', promo:'', invoice:''});
      businessFilters.attrs.fill('');
      header.querySelectorAll('input').forEach(input => { input.value = ''; });
      popover.querySelectorAll('select').forEach(select => { select.value = ''; });
      applyBusinessFilters();
    });
    header.appendChild(filterCell);
    businessList.parentNode.insertBefore(header, businessList);
    document.addEventListener('click', event => {
      if (!filterCell.contains(event.target)) popover.hidden = true;
    });
  };

  installPaymentHeaderFilters();
  installBusinessHeaderFilters();
})();
