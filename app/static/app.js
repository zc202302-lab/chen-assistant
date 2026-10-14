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
    const focused = document.activeElement;
    (document.querySelector('dialog[open]') || document.body).appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (_) {}
    ta.remove();
    if (focused?.isConnected) focused.focus({preventScroll:true});
    return ok;
  };

  window.ChenToast = toast;
  window.ChenCopyText = copyText;

  // 首次普通鼠标单击可全选；拖选和同一次编辑中的后续点击完全交给浏览器。
  const selectionState = new WeakSet();
  let pointerGesture = null;
  const manualEditor = (el) => {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    return !['hidden','checkbox','radio','button','submit','reset','file','range','color'].includes(type);
  };
  const selectAllEditor = (el) => {
    if (!manualEditor(el)) return;
    try { el.focus({preventScroll:true}); } catch (_) { el.focus?.(); }
    // 同步完成，避免下一帧覆盖用户已经建立的光标或选区。
    try { el.select(); }
    catch (_) { try { el.setSelectionRange(0, String(el.value || '').length); } catch (_) {} }
    selectionState.add(el);
  };
  window.ChenSelectAllInput = selectAllEditor;

  document.addEventListener('pointerdown', (e) => {
    const el = e.target.closest?.('input,textarea');
    pointerGesture = manualEditor(el) ? {
      el, id:e.pointerId, x:e.clientX, y:e.clientY, moved:false,
      first:document.activeElement !== el && !selectionState.has(el),
      plain:e.pointerType === 'mouse' && e.button === 0 &&
        !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey
    } : null;
  }, true);
  document.addEventListener('pointermove', (e) => {
    if (pointerGesture?.id === e.pointerId &&
        (Math.abs(e.clientX - pointerGesture.x) > 0 || Math.abs(e.clientY - pointerGesture.y) > 0)) {
      pointerGesture.moved = true;
    }
  }, true);
  document.addEventListener('pointercancel', () => { pointerGesture = null; }, true);
  document.addEventListener('click', (e) => {
    const gesture = pointerGesture;
    pointerGesture = null;
    const el = e.target.closest?.('input,textarea');
    if (!manualEditor(el)) return;
    selectionState.add(el);
    if (!gesture || gesture.el !== el || !gesture.first || !gesture.plain ||
        gesture.moved || e.detail !== 1 || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
    selectAllEditor(el);
  }, true);
  document.addEventListener('keydown', (e) => {
    if (manualEditor(e.target)) selectionState.add(e.target);
  }, true);
  document.addEventListener('focusout', (e) => {
    if (manualEditor(e.target)) selectionState.delete(e.target);
  });

  document.querySelectorAll('.v028-payment-list').forEach(list => {
    const raw = list.getAttribute('style') || '';
    for (const key of ['attr', 'number', 'account', 'amount']) {
      const match = raw.match(new RegExp(`--col-${key}\\s*:\\s*(\\d+)px`, 'i'));
      if (match) list.style.setProperty(`--col-${key}`, `${Number(match[1])}px`);
    }
  });

  document.querySelectorAll('.v028-payment-header').forEach(header => {
    header.style.position = 'relative';
    header.style.top = 'auto';
    header.style.zIndex = '2';
  });

  // 列宽保存再加一层保险：v028 工作区负责实时拖动，这里在 pointerup 捕获后
  // 用最终 CSS 变量再次持久化，避免快速刷新/指针捕获边界导致只改了视觉宽度却没保存。
  document.addEventListener('pointerup', (e) => {
    const handle = e.target.closest?.('[data-resize-col]');
    if (!handle) return;
    const list = handle.closest?.('[data-column-width-url]');
    const workbench = handle.closest?.('[data-payment-workbench]');
    if (!list || !workbench) return;
    setTimeout(async () => {
      const vars = {attr:'--col-attr', number:'--col-number', account:'--col-account', amount:'--col-amount'};
      const style = getComputedStyle(list);
      const fd = new FormData();
      fd.append('csrf', workbench.dataset.csrf || '');
      for (const [key, cssVar] of Object.entries(vars)) {
        fd.append(key, String(parseInt(style.getPropertyValue(cssVar), 10) || 0));
      }
      try {
        await fetch(list.dataset.columnWidthUrl, {
          method:'POST', body:fd, credentials:'same-origin', keepalive:true
        });
      } catch (_) {}
    }, 0);
  }, true);

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

  document.addEventListener('click', async (e) => {
    const target = e.target.closest('[data-copy-silent],[data-business-row] .business-attribute');
    // Promotion names own their popover/inline-rename interaction.
    if (!target || target.matches('.promo-name-copy-v028,[data-promo-name-edit]')) return;
    const attribute = target.closest('[data-business-row] .business-attribute,[data-payment-row] [data-payment-business-cell]');
    if (attribute && !['number', 'account'].includes(attribute.dataset.attrKey || attribute.dataset.paymentAttrKey)) {
      // Also reject stale copy markers on a row waiting for normalization.
      e.stopImmediatePropagation();
      return;
    }
    const value = target.matches('.business-attribute')
      ? target.querySelector('strong')?.textContent?.trim()
      : target.dataset.copySilent;
    if (!value || value === '—') return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const ok = await copyText(value);
    toast(ok ? '已复制' : '复制失败，请重试');
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
