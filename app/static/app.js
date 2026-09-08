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

  document.addEventListener('submit', (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) e.preventDefault();
  });

  document.addEventListener('click', async (e) => {
    const generic = e.target.closest('.copy-btn');
    if (generic) {
      e.preventDefault();
      await copyText(generic.dataset.copy || '');
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
      const r = await fetch(`/accounts/${reveal.dataset.accountId}/password`, {method:'POST', body:fd, credentials:'same-origin'});
      if (!r.ok) return toast('读取失败');
      const data = await r.json();
      document.getElementById('passwordValue').textContent = data.password || '未保存密码';
      if (data.password) await copyText(data.password);
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
  }
})();
