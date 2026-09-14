(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const paymentList = document.getElementById('paymentSortable');
  const businessList = root.querySelector('[data-business-list]');
  const normalize = value => String(value ?? '').trim().toLowerCase();
  const rowText = row => {
    const values = [...row.querySelectorAll('input,textarea,select')].map(el => el.value || '').join(' ');
    return normalize(`${row.textContent || ''} ${values}`);
  };

  // v1.2.8 removes all search boxes/selects embedded in table headers. Keep table headers
  // purely as labels; find/filter controls live in a compact on-demand panel instead.
  root.querySelectorAll('[data-v125-payment-filter],[data-v125-payment-state]').forEach(el => el.remove());
  root.querySelectorAll('.v125-business-header').forEach(el => el.remove());
  root.querySelectorAll('[data-v124-payment-tools],.v124-business-search-wrap,[data-business-filters],.business-filters').forEach(el => el.remove());
  root.querySelector('#serviceFilter')?.remove();
  const paymentActionHead = paymentList?.querySelector('.payment-action-head-v0211');
  if (paymentActionHead) paymentActionHead.textContent = '操作';
  paymentList?.querySelectorAll('.v125-filter-head,.v125-state-head').forEach(el => el.classList.remove('v125-filter-head','v125-state-head'));

  const escapeHtml = value => String(value)
    .replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

  const makeFinder = ({kind, anchor, title, placeholder, filters, apply, clear}) => {
    if (!anchor || root.querySelector(`[data-v128-finder="${kind}"]`)) return null;
    const shell = document.createElement('div');
    shell.className = 'v128-finder-shell';
    shell.dataset.v128Finder = kind;
    shell.innerHTML = `
      <button type="button" class="v128-finder-trigger" data-v128-finder-trigger aria-expanded="false">
        <span class="v128-finder-icon">⌕</span><span>查找筛选</span><b data-v128-active-count hidden>0</b>
      </button>
      <div class="v128-finder-panel" data-v128-finder-panel hidden>
        <div class="v128-finder-panel-head"><strong>${escapeHtml(title)}</strong><button type="button" class="v128-finder-close" data-v128-finder-close aria-label="关闭">×</button></div>
        <label class="v128-finder-search"><span>查找</span><input type="search" autocomplete="off" placeholder="${escapeHtml(placeholder)}" data-v128-query></label>
        <div class="v128-finder-filters">${filters}</div>
        <div class="v128-finder-actions"><button type="button" class="v128-finder-clear" data-v128-clear>清除条件</button><span data-v128-result-count></span></div>
      </div>`;
    anchor.appendChild(shell);

    const trigger = shell.querySelector('[data-v128-finder-trigger]');
    const panel = shell.querySelector('[data-v128-finder-panel]');
    const query = shell.querySelector('[data-v128-query]');
    const active = shell.querySelector('[data-v128-active-count]');
    const result = shell.querySelector('[data-v128-result-count]');
    const controls = () => [query, ...shell.querySelectorAll('select[data-v128-filter]')];
    const activeCount = () => controls().filter(el => normalize(el.value)).length;
    const refreshBadge = () => {
      const n = activeCount();
      active.textContent = String(n);
      active.hidden = n === 0;
      trigger.classList.toggle('has-filter', n > 0);
    };
    const run = () => {
      const visible = apply(shell);
      result.textContent = `显示 ${visible} 项`;
      refreshBadge();
    };
    trigger.addEventListener('click', e => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
      trigger.setAttribute('aria-expanded', panel.hidden ? 'false' : 'true');
      if (!panel.hidden) setTimeout(() => query.focus(), 0);
    });
    shell.querySelector('[data-v128-finder-close]').addEventListener('click', () => {
      panel.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
    });
    shell.addEventListener('input', e => {
      if (e.target.matches('[data-v128-query]')) run();
    });
    shell.addEventListener('change', e => {
      if (e.target.matches('select[data-v128-filter]')) run();
    });
    shell.querySelector('[data-v128-clear]').addEventListener('click', () => {
      clear(shell);
      run();
      query.focus();
    });
    document.addEventListener('click', e => {
      if (!shell.contains(e.target)) {
        panel.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
      }
    });
    panel.addEventListener('click', e => e.stopPropagation());
    run();
    return shell;
  };

  if (paymentList) {
    const paymentHead = root.querySelector('.v025-payment-head');
    const anchor = paymentHead?.querySelector('.v023-payment-title-line') || paymentHead;
    makeFinder({
      kind: 'payment',
      anchor,
      title: '缴费明细',
      placeholder: '号码、账号、姓名、金额…',
      filters: `
        <label><span>核对状态</span><select data-v128-filter="state"><option value="">全部</option><option value="pending">待核对</option><option value="confirmed">已核对</option></select></label>
        <label><span>金额规则</span><select data-v128-filter="mode"><option value="">全部</option><option value="variable">变动</option><option value="fixed">固定</option></select></label>`,
      apply: shell => {
        const q = normalize(shell.querySelector('[data-v128-query]').value);
        const state = shell.querySelector('[data-v128-filter="state"]').value;
        const mode = shell.querySelector('[data-v128-filter="mode"]').value;
        let visible = 0;
        paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
          let show = !q || rowText(row).includes(q);
          if (show && state === 'pending') show = row.dataset.confirmed === '0';
          if (show && state === 'confirmed') show = row.dataset.confirmed === '1';
          if (show && mode) show = row.dataset.mode === mode;
          row.hidden = !show;
          row.style.display = show ? '' : 'none';
          if (show) visible += 1;
        });
        return visible;
      },
      clear: shell => shell.querySelectorAll('input,select').forEach(el => { el.value = ''; }),
    });
  }

  if (businessList) {
    const businessCard = root.querySelector('.business-v028');
    const anchor = businessCard?.querySelector('.section-head');
    const unique = key => [...new Set([...businessList.querySelectorAll('[data-business-row]')]
      .map(row => row.dataset[key] || '').filter(Boolean))];
    const options = (label, values) => `<option value="">${label}</option>${values.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')}`;
    makeFinder({
      kind: 'business',
      anchor,
      title: '业务数据',
      placeholder: '号码、账号、姓名、业务类型…',
      filters: `
        <label><span>业务类型</span><select data-v128-filter="type">${options('全部', unique('filterType'))}</select></label>
        <label><span>本月缴费</span><select data-v128-filter="due"><option value="">全部</option><option value="1">本月应缴</option><option value="0">本月不缴</option></select></label>
        <label><span>金额规则</span><select data-v128-filter="mode"><option value="">全部</option><option value="variable">变动</option><option value="fixed">固定</option></select></label>
        <label><span>优惠状态</span><select data-v128-filter="promo">${options('全部', unique('filterPromo'))}</select></label>
        <label><span>发票组</span><select data-v128-filter="invoice">${options('全部', unique('filterInvoice'))}</select></label>`,
      apply: shell => {
        const q = normalize(shell.querySelector('[data-v128-query]').value);
        const values = Object.fromEntries([...shell.querySelectorAll('select[data-v128-filter]')].map(el => [el.dataset.v128Filter, el.value]));
        let visible = 0;
        businessList.querySelectorAll('[data-business-row]').forEach(row => {
          let show = !q || rowText(row).includes(q);
          if (show && values.type) show = row.dataset.filterType === values.type;
          if (show && values.due) show = row.dataset.filterDue === values.due;
          if (show && values.mode) show = row.dataset.filterMode === values.mode;
          if (show && values.promo) show = row.dataset.filterPromo === values.promo;
          if (show && values.invoice) show = row.dataset.filterInvoice === values.invoice;
          row.hidden = !show;
          row.style.display = show ? '' : 'none';
          if (show) visible += 1;
        });
        const count = document.getElementById('businessVisibleCount');
        if (count) count.textContent = String(visible);
        return visible;
      },
      clear: shell => shell.querySelectorAll('input,select').forEach(el => { el.value = ''; }),
    });
  }

  // Exact-number work search lands on the business tab and visibly locates the row.
  const focusService = new URLSearchParams(location.search).get('focus_service');
  if (focusService && businessList) {
    const target = businessList.querySelector(`[data-business-row][data-service-id="${CSS.escape(focusService)}"]`);
    if (target) {
      const tab = root.querySelector('[data-customer-tab="services"]');
      if (tab && !tab.classList.contains('active')) tab.click();
      target.hidden = false;
      target.style.display = '';
      target.classList.add('v128-focus-hit');
      requestAnimationFrame(() => requestAnimationFrame(() => target.scrollIntoView({behavior:'smooth', block:'center'})));
      setTimeout(() => target.classList.remove('v128-focus-hit'), 6000);
    }
  }
})();
