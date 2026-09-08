(() => {
  const toast = (msg) => {
    const el = document.createElement('div');
    el.className = 'app-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 180); }, 1100);
  };

  const copyText = async (value) => {
    if (!value) return false;
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch (_) {}
    }
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    return ok;
  };

  const selectAmount = (input) => {
    if (!input) return;
    input.focus({ preventScroll: true });
    requestAnimationFrame(() => {
      try { input.setSelectionRange(0, input.value.length); } catch (_) { input.select?.(); }
    });
  };

  document.addEventListener('submit', (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) e.preventDefault();
  });

  document.addEventListener('click', async (e) => {
    const generic = e.target.closest('.copy-btn');
    if (generic) {
      e.preventDefault();
      const ok = await copyText(generic.dataset.copy || '');
      toast(ok ? '已复制' : '复制失败');
    }
    const disabled = e.target.closest('a[aria-disabled="true"]');
    if (disabled) e.preventDefault();
  });

  const filter = document.getElementById('serviceFilter');
  if (filter) {
    filter.addEventListener('input', () => {
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll('.service-group').forEach(group => {
        let matched = 0;
        group.querySelectorAll('.service-card').forEach(el => {
          const show = !q || (el.dataset.serviceText || '').toLowerCase().includes(q);
          el.style.display = show ? 'block' : 'none';
          if (show) matched++;
        });
        group.style.display = !q || matched ? 'block' : 'none';
        if (q && matched) group.open = true;
      });
    });
  }

  const reveal = document.getElementById('revealPassword');
  if (reveal) {
    reveal.addEventListener('click', async () => {
      const fd = new FormData();
      fd.append('csrf', reveal.dataset.csrf);
      const r = await fetch(`/accounts/${reveal.dataset.accountId}/password`, { method: 'POST', body: fd, credentials: 'same-origin' });
      if (!r.ok) return toast('读取失败');
      const data = await r.json();
      document.getElementById('passwordValue').textContent = data.password || '未保存密码';
      if (data.password) {
        const ok = await copyText(data.password);
        toast(ok ? '密码已显示并复制' : '密码已显示');
      }
    });
  }

  const workbench = document.querySelector('[data-payment-workbench]');
  if (!workbench) {
    if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
    return;
  }

  let activeFilter = workbench.dataset.defaultFilter || 'pending';
  let returnFocusInput = null;

  const money = (n) => {
    const v = Math.round((Number(n) || 0) * 100) / 100;
    return '¥' + (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''));
  };

  const rowVisibleFor = (row, kind) => {
    if (kind === 'pending') return row.dataset.confirmed === '0' && row.dataset.mode === 'variable';
    if (kind === 'changed') return row.dataset.changed === '1';
    if (kind === 'zero') return row.dataset.zero === '1';
    return true;
  };

  const applyPaymentFilter = (kind) => {
    activeFilter = kind;
    document.querySelectorAll('.payment-filter').forEach(b => b.classList.toggle('active', b.dataset.paymentFilter === kind));
    document.querySelectorAll('[data-payment-row]').forEach(row => row.classList.toggle('is-hidden', !rowVisibleFor(row, kind)));
  };

  document.querySelectorAll('.payment-filter').forEach(b => b.addEventListener('click', () => applyPaymentFilter(b.dataset.paymentFilter)));
  applyPaymentFilter(activeFilter);

  const setCurrentRow = (row) => {
    document.querySelectorAll('[data-payment-row].is-current').forEach(x => x.classList.remove('is-current'));
    row.classList.add('is-current');
    const input = row.querySelector('.quick-amount');
    returnFocusInput = input;
    selectAmount(input);
  };

  workbench.addEventListener('click', async (e) => {
    const idButton = e.target.closest('.identifier-copy');
    if (idButton) {
      e.preventDefault();
      const ok = await copyText(idButton.dataset.copy || '');
      const row = idButton.closest('[data-payment-row]');
      if (row) setCurrentRow(row);
      idButton.classList.add('copied');
      setTimeout(() => idButton.classList.remove('copied'), 600);
      toast(ok ? `已复制${idButton.dataset.kind || ''}` : '复制失败');
      return;
    }

    const amount = e.target.closest('.quick-amount');
    if (amount) {
      selectAmount(amount);
      return;
    }

    const fixed = e.target.closest('[data-fixed-toggle]');
    if (fixed) {
      e.preventDefault();
      const row = fixed.closest('[data-payment-row]');
      if (!row || fixed.dataset.saving === '1') return;
      fixed.dataset.saving = '1';
      const fd = new FormData();
      fd.append('csrf', workbench.dataset.csrf);
      try {
        const r = await fetch(`/services/${row.dataset.serviceId}/toggle-fixed`, { method: 'POST', body: fd, credentials: 'same-origin' });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.error || '切换失败');
        updateRowFromPayment(row, data);
        fixed.textContent = data.mode === 'fixed' ? '固定' : '变动';
        fixed.classList.toggle('is-fixed', data.mode === 'fixed');
        updateSummary(data);
        toast(data.mode === 'fixed' ? '已设为固定缴费' : '已取消固定缴费');
        applyPaymentFilter(activeFilter);
      } catch (_) {
        toast('网络异常');
      } finally {
        delete fixed.dataset.saving;
      }
      return;
    }

    const cancel = e.target.closest('[data-editor-cancel]');
    if (cancel) {
      e.preventDefault();
      cancel.closest('[data-payment-row]')?.classList.remove('is-editing');
    }
  });

  workbench.addEventListener('dblclick', (e) => {
    const trigger = e.target.closest('.quick-edit-trigger');
    if (!trigger) return;
    e.preventDefault();
    returnFocusInput = null;
    const row = trigger.closest('[data-payment-row]');
    if (!row) return;
    row.classList.add('is-editing');
    const form = row.querySelector('[data-quick-editor]');
    const targetName = trigger.querySelector('[data-display="number"]') ? 'number'
      : trigger.querySelector('[data-display="account"]') ? 'account'
      : 'service_type';
    const input = form?.elements?.[targetName];
    if (input) {
      input.focus();
      input.select?.();
    }
  });

  const updateSummary = (data) => {
    const p = document.getElementById('pendingCount');
    if (p) p.textContent = data.pending;
    const c = document.getElementById('changedCount');
    if (c) c.textContent = data.changed;
    const z = document.getElementById('zeroCount');
    if (z) z.textContent = data.zero;
    const total = document.getElementById('paymentGrandTotal');
    if (total) total.textContent = money(data.total);
    const readiness = document.getElementById('paymentReadiness');
    if (readiness) readiness.textContent = data.pending ? `还有 ${data.pending} 项待核对` : '本月金额已全部核对';
    const txt = document.getElementById('paymentTxtButton');
    if (txt) {
      txt.setAttribute('aria-disabled', data.txt_ready ? 'false' : 'true');
      txt.classList.toggle('disabled', !data.txt_ready);
      txt.classList.toggle('primary', data.txt_ready);
      txt.classList.toggle('secondary', !data.txt_ready);
    }
  };

  const updateRowFromPayment = (row, data) => {
    row.dataset.confirmed = data.confirmed ? '1' : '0';
    row.dataset.mode = data.mode;
    row.dataset.zero = data.confirmed && Number(data.amount) === 0 ? '1' : '0';
    row.dataset.changed = data.delta === null || data.delta === undefined ? '0' : '1';
    row.classList.toggle('is-pending', row.dataset.confirmed === '0' && row.dataset.mode === 'variable');

    const input = row.querySelector('.quick-amount');
    if (input && data.display_amount !== undefined) {
      input.value = data.display_amount;
      input.dataset.lastSaved = input.value;
    }

    const status = row.querySelector('.dense-status');
    if (status) {
      status.innerHTML = data.mode === 'fixed'
        ? '<span class="status-mark fixed-mark">◆</span>'
        : data.confirmed ? '<span class="status-mark ok-mark">✓</span>' : '<span class="status-mark pending-mark">○</span>';
    }

    const fb = row.querySelector('.amount-feedback');
    if (fb) {
      fb.innerHTML = '';
      if (data.delta !== null && data.delta !== undefined) {
        const em = document.createElement('em');
        em.className = 'delta-badge ' + (Number(data.delta) > 0 ? 'up' : 'down');
        em.textContent = (Number(data.delta) > 0 ? '+' : '') + String(Math.round(Number(data.delta) * 100) / 100);
        fb.appendChild(em);
      }
    }
  };

  const savePayment = async (input, jumpNext = true) => {
    if (!input || input.dataset.saving === '1') return;
    const raw = input.value.trim().replace(',', '.');
    if (raw === '') {
      toast('金额不能为空；本月不缴请填0');
      return selectAmount(input);
    }
    const row = input.closest('[data-payment-row]');
    input.dataset.saving = '1';
    row?.classList.add('is-saving');
    const fd = new FormData();
    fd.append('csrf', workbench.dataset.csrf);
    fd.append('amount', raw);
    try {
      const r = await fetch(`/services/${input.dataset.serviceId}/payment-current`, { method: 'POST', body: fd, credentials: 'same-origin' });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        toast(data.error || '保存失败');
        return selectAmount(input);
      }
      updateRowFromPayment(row, data);
      updateSummary(data);
      toast(data.delta === null || data.delta === undefined ? '已核对' : '已保存 · 金额异动');
      applyPaymentFilter(activeFilter);

      if (jumpNext) {
        const rows = [...document.querySelectorAll('[data-payment-row]')];
        const idx = rows.indexOf(row);
        const ordered = rows.slice(idx + 1).concat(rows.slice(0, idx + 1));
        const next = ordered.find(x => x.dataset.mode === 'variable' && x.dataset.confirmed === '0');
        if (next) {
          next.classList.remove('is-hidden');
          next.scrollIntoView({ behavior: 'smooth', block: 'center' });
          setTimeout(() => setCurrentRow(next), 180);
        } else {
          returnFocusInput = null;
        }
      }
    } catch (_) {
      toast('网络异常，未保存');
      selectAmount(input);
    } finally {
      delete input.dataset.saving;
      row?.classList.remove('is-saving');
    }
  };

  document.querySelectorAll('.quick-amount').forEach(input => {
    input.dataset.lastSaved = input.value;
    input.addEventListener('focus', () => selectAmount(input));
    input.addEventListener('click', () => selectAmount(input));
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        savePayment(input, true);
      }
      if (e.key === 'Escape') {
        input.value = input.dataset.lastSaved || input.value;
        input.blur();
      }
    });
  });

  document.querySelectorAll('[data-quick-editor]').forEach(form => {
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const row = form.closest('[data-payment-row]');
      const fd = new FormData(form);
      try {
        const r = await fetch(`/services/${row.dataset.serviceId}/quick-edit`, { method: 'POST', body: fd, credentials: 'same-origin' });
        const data = await r.json().catch(() => ({}));
        if (!r.ok || !data.ok) return toast(data.error || '保存失败');

        ['service_type', 'holder_name', 'number', 'account'].forEach(name => {
          const display = row.querySelector(`[data-display="${name}"]`);
          if (display) display.textContent = data[name] || '—';
        });

        const numberBtn = row.querySelector('[data-display="number"]')?.closest('.dense-id');
        if (numberBtn) {
          numberBtn.dataset.copy = data.number || '';
          numberBtn.dataset.kind = '号码';
          numberBtn.classList.toggle('identifier-copy', !!data.number);
          numberBtn.classList.toggle('dense-empty', !data.number);
        }
        const accountBtn = row.querySelector('[data-display="account"]')?.closest('.dense-id');
        if (accountBtn) {
          accountBtn.dataset.copy = data.account || '';
          accountBtn.dataset.kind = '账号';
          accountBtn.classList.toggle('identifier-copy', !!data.account);
          accountBtn.classList.toggle('dense-empty', !data.account);
        }

        row.classList.remove('is-editing');
        toast('属性已保存');
      } catch (_) {
        toast('网络异常');
      }
    });
  });

  window.addEventListener('focus', () => {
    if (returnFocusInput && document.contains(returnFocusInput)) setTimeout(() => selectAmount(returnFocusInput), 80);
  });

  if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
})();