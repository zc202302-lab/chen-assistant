(() => {
  let toastEl = null;
  let toastTimer = null;
  const toast = (msg) => {
    if (!toastEl || !document.body.contains(toastEl)) {
      toastEl = document.createElement('div');
      toastEl.className = 'app-toast';
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = msg;
    if (toastTimer) clearTimeout(toastTimer);
    requestAnimationFrame(() => toastEl?.classList.add('show'));
    toastTimer = setTimeout(() => {
      toastEl?.classList.remove('show');
    }, 900);
  };

  const copyText = async (value) => {
    if (!value) return false;
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(value); return true; } catch (_) {}
    }
    const ta = document.createElement('textarea');
    ta.value = value;
    ta.setAttribute('readonly', '');
    Object.assign(ta.style, {position:'fixed', opacity:'0', left:'-9999px'});
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    return ok;
  };

  // Strict CSP blocks the server-rendered inline CSS variables at parse time.
  // Re-apply only these four numeric variables through the CSSOM before the
  // customer workspace controller runs, preserving per-customer saved widths.
  document.querySelectorAll('.v028-payment-list').forEach(list => {
    const raw = list.getAttribute('style') || '';
    for (const key of ['attr', 'number', 'account', 'amount']) {
      const match = raw.match(new RegExp(`--col-${key}\\s*:\\s*(\\d+)px`, 'i'));
      if (match) list.style.setProperty(`--col-${key}`, `${Number(match[1])}px`);
    }
  });

  // The payment header belongs in normal flow. Making it sticky inside the
  // horizontal scrolling container pushes it down over payment rows in real
  // customer pages. Keep only the customer summary/tabs sticky.
  document.querySelectorAll('.v028-payment-header').forEach(header => {
    header.style.position = 'relative';
    header.style.top = 'auto';
    header.style.zIndex = '2';
  });

  document.addEventListener('submit', (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) e.preventDefault();
  });

  // Global copy buttons (customer name, group code, tax id, account pages).
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

  // Current customer-workspace controllers own the actual copy action for
  // identifiers/promotions because they also preserve the amount-editor focus.
  // Show feedback in capture phase without changing focus or propagation.
  document.addEventListener('click', (e) => {
    if (e.target.closest('.identifier-copy,[data-copy-silent]')) {
      setTimeout(() => toast('已复制'), 0);
    }
  }, true);

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
      const r = await fetch(`/accounts/${reveal.dataset.accountId}/password`, {method:'POST', body:fd, credentials:'same-origin'});
      if (!r.ok) return toast('读取失败');
      const data = await r.json();
      document.getElementById('passwordValue').textContent = data.password || '未保存密码';
      if (data.password) {
        const ok = await copyText(data.password);
        toast(ok ? '密码已复制' : '复制失败');
      }
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
  }
})();
