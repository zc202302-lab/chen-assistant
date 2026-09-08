(() => {
  const root = document.querySelector('.v026-workspace');
  if (!root) return;
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';

  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 160); }, 1000);
  };

  const selectEditor = (el) => {
    if (!el || el.readOnly || el.disabled) return;
    if (el.tagName === 'SELECT' || el.type === 'checkbox' || el.type === 'radio' || el.type === 'hidden') return;
    requestAnimationFrame(() => {
      try { el.select(); } catch (_) {
        try { el.setSelectionRange(0, el.value.length); } catch (_) {}
      }
    });
  };

  // 所有文本/数字编辑项：单击直接全选，减少“先删除旧值”的动作。
  root.addEventListener('click', (e) => {
    const el = e.target.closest('input,textarea');
    if (el) selectEditor(el);
  });

  // 日期一律手输 YYYY/MM/DD；输入时自动补斜杠，提交前用浏览器原生约束再校验一次。
  const formatDateDigits = (value) => {
    const d = String(value || '').replace(/\D/g, '').slice(0, 8);
    if (d.length <= 4) return d;
    if (d.length <= 6) return d.slice(0, 4) + '/' + d.slice(4);
    return d.slice(0, 4) + '/' + d.slice(4, 6) + '/' + d.slice(6);
  };
  root.querySelectorAll('.manual-date').forEach(input => {
    input.autocomplete = 'off';
    input.addEventListener('input', () => { input.value = formatDateDigits(input.value); input.setCustomValidity(''); });
    input.addEventListener('blur', () => {
      if (!input.value) return input.setCustomValidity('');
      const ok = /^\d{4}\/\d{2}\/\d{2}$/.test(input.value);
      input.setCustomValidity(ok ? '' : '日期格式必须为 1900/07/07');
    });
  });

  // 核对状态可撤销/恢复。固定金额不允许人工撤销，需先切换成变动。
  workbench?.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-review-toggle]');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    const row = btn.closest('[data-payment-row]');
    if (!row || btn.dataset.saving === '1') return;
    btn.dataset.saving = '1';
    const fd = new FormData(); fd.append('csrf', csrf);
    try {
      const r = await fetch(`/services/${row.dataset.serviceId}/payment-review-toggle`, {method:'POST', body:fd, credentials:'same-origin'});
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) return toast(data.error || '核对状态修改失败');
      row.dataset.confirmed = data.confirmed ? '1' : '0';
      const done = data.mode === 'fixed' || !!data.confirmed;
      btn.textContent = done ? '✓' : '○';
      btn.classList.toggle('confirmed', done); btn.classList.toggle('pending', !done);
      row.classList.toggle('is-confirmed', done); row.classList.toggle('is-pending', !done);
      const pending = document.getElementById('pendingCount'); if (pending) pending.textContent = data.pending;
      const total = document.getElementById('paymentGrandTotal');
      if (total) {
        const v = Number(data.total || 0); total.textContent = '¥' + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''));
      }
      const readiness = document.getElementById('paymentReadiness');
      if (readiness) readiness.textContent = data.pending ? `还有 ${data.pending} 项金额未核对` : '本月应缴业务金额已全部核对';
      const txt = document.getElementById('paymentTxtButton');
      if (txt) {
        txt.setAttribute('aria-disabled', data.txt_ready ? 'false' : 'true');
        txt.classList.toggle('disabled', !data.txt_ready);
        txt.classList.toggle('primary', data.txt_ready);
        txt.classList.toggle('secondary', !data.txt_ready);
      }
      const notify = root.querySelector('[data-payment-action="notify"]');
      if (notify && !notify.classList.contains('done')) notify.disabled = Number(data.pending || 0) !== 0;
      const label = document.getElementById('paymentRunLabel');
      if (label && !data.confirmed) label.textContent = '正在核对金额';
      toast(data.confirmed ? '已恢复核对' : '已撤销核对');
    } catch (_) { toast('网络异常，核对状态未修改'); }
    finally { delete btn.dataset.saving; }
  }, true);

  // 业务总览多维标签筛选：每一维单选，不同维度叠加。
  const filterRoot = root.querySelector('[data-business-filters]');
  const businessRows = [...root.querySelectorAll('[data-business-row]')];
  const filterState = {type:'', due:'', mode:'', promo:'', invoice:''};
  const applyFilters = () => {
    let visible = 0;
    businessRows.forEach(row => {
      const ok = (!filterState.type || row.dataset.filterType === filterState.type)
        && (!filterState.due || row.dataset.filterDue === filterState.due)
        && (!filterState.mode || row.dataset.filterMode === filterState.mode)
        && (!filterState.promo || row.dataset.filterPromo === filterState.promo)
        && (!filterState.invoice || row.dataset.filterInvoice === filterState.invoice);
      row.hidden = !ok;
      if (ok) visible++;
    });
    const count = document.getElementById('businessVisibleCount'); if (count) count.textContent = visible;
  };
  filterRoot?.addEventListener('click', e => {
    const btn = e.target.closest('[data-business-filter]');
    if (!btn) return;
    const group = btn.dataset.businessFilter;
    filterState[group] = btn.dataset.value || '';
    filterRoot.querySelectorAll(`[data-business-filter="${group}"]`).forEach(x => x.classList.toggle('active', x === btn));
    applyFilters();
  });
  root.querySelector('[data-business-filter-reset]')?.addEventListener('click', () => {
    Object.keys(filterState).forEach(k => filterState[k] = '');
    filterRoot?.querySelectorAll('[data-business-filter]').forEach(btn => btn.classList.toggle('active', !btn.dataset.value));
    applyFilters();
  });
})();
