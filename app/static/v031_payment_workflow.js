(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;

  const customerId = root.dataset.customerId || '';
  const workbench = root.querySelector('[data-payment-workbench]');
  const csrf = workbench?.dataset.csrf || '';
  const paymentList = document.getElementById('paymentSortable');
  const pendingCount = document.getElementById('pendingCount');
  const totalNode = document.getElementById('paymentGrandTotal');
  if (!customerId || !workbench) return;

  const FOXMAIL_BRIDGE = 'http://127.0.0.1:18763';
  let state = null;
  let busy = false;
  let ignoreMutationsUntil = 0;
  let lastPendingText = pendingCount?.textContent || '';
  let lastTotalText = totalNode?.textContent || '';
  let invalidationTimer = 0;

  const toast = msg => {
    if (window.ChenToast) return window.ChenToast(msg);
    let el = document.querySelector('.app-toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'app-toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => el.classList.remove('show'), 4200);
  };

  const fetchJson = async (url, options = {}) => {
    const r = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await r.json().catch(() => ({}));
    if (!r.ok || data.ok === false) throw new Error(data.detail || data.error || '操作失败');
    return data;
  };

  const postAction = async action => {
    const fd = new FormData();
    fd.append('csrf', csrf);
    fd.append('action', action);
    return fetchJson(`/customers/${customerId}/payment-workflow-v031`, {method: 'POST', body: fd});
  };

  const bytesToBase64 = bytes => {
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  };

  /* ---------------- 标题栏：左侧操作 + 右侧四步流程 ---------------- */
  const paymentHead = root.querySelector('.v025-payment-head');
  const titleLine = root.querySelector('.v023-payment-title-line');
  if (paymentHead) paymentHead.classList.add('v03-payment-head-two-row', 'v031-payment-head');

  let tools = paymentHead?.querySelector('[data-v03-payment-head-tools]');
  if (!tools && paymentHead) {
    tools = document.createElement('div');
    tools.className = 'v03-payment-head-tools';
    tools.dataset.v03PaymentHeadTools = '1';
    tools.innerHTML = '<div class="v03-payment-head-tools-left"></div><div class="v03-payment-head-tools-right"></div>';
    paymentHead.appendChild(tools);
  }
  const toolsLeft = tools?.querySelector('.v03-payment-head-tools-left');
  const toolsRight = tools?.querySelector('.v03-payment-head-tools-right');

  const oldFlow = root.querySelector('[data-v03-payment-flow]');
  const flow = document.createElement('div');
  flow.className = 'v03-payment-flow v031-payment-flow';
  flow.dataset.v031PaymentFlow = '1';
  [
    ['review', '金额核对'],
    ['notify', '已通知客户'],
    ['initiate', '发起缴费'],
    ['paid', '完成缴费'],
  ].forEach(([action, label], index) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'v03-flow-step';
    btn.dataset.v031FlowAction = action;
    btn.dataset.step = String(index + 1);
    btn.textContent = `${index + 1} ${label}`;
    flow.appendChild(btn);
  });
  if (oldFlow) oldFlow.replaceWith(flow);
  else if (toolsRight) toolsRight.appendChild(flow);
  else titleLine?.appendChild(flow);
  if (toolsRight && flow.parentElement !== toolsRight) toolsRight.appendChild(flow);

  let imageButton = root.querySelector('[data-v031-payment-image]');
  if (!imageButton) {
    imageButton = document.createElement('button');
    imageButton.type = 'button';
    imageButton.className = 'secondary small v031-image-button';
    imageButton.dataset.v031PaymentImage = '1';
    imageButton.textContent = '生成缴费图片';
    toolsLeft?.appendChild(imageButton);
  }

  const oldFoxmail = root.querySelector('[data-v03-foxmail-draft]');
  let foxmailButton = null;
  if (oldFoxmail) {
    // Clone to detach every old v0.3 listener, whose prerequisite was incorrectly
    // "完成缴费". v0.3.1 owns the button from this point onward.
    foxmailButton = oldFoxmail.cloneNode(true);
    foxmailButton.disabled = false;
    foxmailButton.removeAttribute('disabled');
    foxmailButton.textContent = '调用Foxmail';
    foxmailButton.classList.remove('primary');
    foxmailButton.classList.add('secondary', 'small', 'v031-foxmail-button');
    oldFoxmail.replaceWith(foxmailButton);
    toolsLeft?.appendChild(foxmailButton);
  }

  const attributeButton = root.querySelector('[data-payment-columns-settings]');
  if (attributeButton && toolsLeft && attributeButton.parentElement !== toolsLeft) toolsLeft.prepend(attributeButton);
  const templateButton = root.querySelector('[data-v03-mail-template]');
  if (templateButton && toolsLeft && templateButton.parentElement !== toolsLeft) toolsLeft.appendChild(templateButton);
  if (imageButton && toolsLeft && imageButton.parentElement !== toolsLeft) toolsLeft.appendChild(imageButton);
  if (foxmailButton && toolsLeft && foxmailButton.parentElement !== toolsLeft) toolsLeft.appendChild(foxmailButton);

  const editControls = () => root.querySelectorAll('.quick-amount,[data-review-toggle],[data-fixed-toggle],[data-defer-payment-v0212]');

  const setEditingLock = () => {
    const locked = !!state?.paid;
    editControls().forEach(control => {
      if (control.matches('.quick-amount')) control.readOnly = locked;
      else control.disabled = locked;
    });
    root.classList.toggle('v03-payment-locked', locked);
    root.classList.toggle('v031-payment-editable-after-notice', !!state?.notified && !locked);
  };

  const renderState = () => {
    if (!state) return;
    const defs = [
      ['review', '金额核对', !!state.reviewed],
      ['notify', '已通知客户', !!state.notified],
      ['initiate', '发起缴费', !!state.initiated],
      ['paid', '完成缴费', !!state.paid],
    ];
    defs.forEach(([action, label, done], index) => {
      const btn = flow.querySelector(`[data-v031-flow-action="${action}"]`);
      if (!btn) return;
      btn.textContent = done ? `✓ ${label}` : `${index + 1} ${label}`;
      btn.classList.toggle('done', done);
      const current = !done && (
        (action === 'review' && state.ready) ||
        (action === 'notify' && state.reviewed) ||
        (action === 'initiate' && state.notified) ||
        (action === 'paid' && state.initiated)
      );
      btn.classList.toggle('current', current);

      let disabled = busy;
      let title = '';
      if (action === 'review') {
        disabled ||= done ? !!(state.notified || state.initiated || state.paid) : !state.ready;
        title = done
          ? (disabled ? '请先撤回后续步骤' : '点击撤回金额核对')
          : (state.ready ? '确认本月全部金额已核对' : `还有 ${state.pending || 0} 项金额未核对`);
      } else if (action === 'notify') {
        disabled ||= done ? !!(state.initiated || state.paid) : !state.reviewed;
        title = done
          ? (disabled ? '请先撤回后续步骤' : '点击撤回客户通知状态')
          : '把缴费图片通过微信发给客户后点击确认';
      } else if (action === 'initiate') {
        disabled ||= done ? !!state.paid : !state.notified;
        title = done
          ? (disabled ? '请先撤回完成缴费' : '点击撤回发起缴费状态')
          : '先调用Foxmail并实际发送邮件，再点击确认';
      } else {
        disabled ||= !done && !state.initiated;
        title = done ? '点击撤回完成缴费并恢复缴费前周期' : '确认已实际完成支付';
      }
      btn.disabled = !!disabled;
      btn.title = title;
      btn.setAttribute('aria-pressed', done ? 'true' : 'false');
    });

    if (imageButton) {
      imageButton.disabled = busy || !state.reviewed || !!state.paid;
      imageButton.title = state.reviewed ? '生成当前页面高密度缴费表并复制到剪贴板' : '先完成金额核对';
    }
    if (foxmailButton) {
      foxmailButton.disabled = busy || !state.notified || !!state.paid;
      foxmailButton.title = state.notified ? '打开Foxmail写邮件窗口，发送后再确认“发起缴费”' : '先完成客户通知';
    }
    const label = document.getElementById('paymentRunLabel');
    if (label) label.textContent = state.label || '';
    setEditingLock();
  };

  const updateStats = stats => {
    if (!stats) return;
    ignoreMutationsUntil = Date.now() + 350;
    const required = document.getElementById('requiredCount');
    const pending = document.getElementById('pendingCount');
    const readiness = document.getElementById('paymentReadiness');
    const exportButtons = ['paymentExcelButton', 'paymentTxtButton'].map(id => document.getElementById(id)).filter(Boolean);
    if (required && stats.required !== undefined) required.textContent = String(stats.required);
    if (pending && stats.pending !== undefined) pending.textContent = String(stats.pending);
    if (readiness && stats.pending !== undefined) {
      readiness.textContent = Number(stats.pending)
        ? `还有 ${stats.pending} 项金额未核对`
        : '本月应缴业务金额已全部核对';
    }
    if (stats.txt_ready !== undefined) {
      exportButtons.forEach(button => {
        button.classList.toggle('disabled', !stats.txt_ready);
        button.classList.toggle('primary', !!stats.txt_ready);
        button.classList.toggle('secondary', !stats.txt_ready);
        button.setAttribute('aria-disabled', stats.txt_ready ? 'false' : 'true');
      });
    }
    lastPendingText = pendingCount?.textContent || '';
    lastTotalText = totalNode?.textContent || '';
  };

  const paintWholeReview = data => {
    if (!paymentList) return;
    if (data.review_reset_all) {
      ignoreMutationsUntil = Date.now() + 500;
      paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
        row.dataset.confirmed = '0';
        row.classList.remove('is-confirmed');
        row.classList.add('is-pending');
        const mark = row.querySelector('[data-row-state]');
        if (mark) {
          mark.textContent = '○';
          mark.classList.remove('confirmed');
          mark.classList.add('pending');
        }
      });
    } else if (data.review_reconfirmed_service_ids) {
      ignoreMutationsUntil = Date.now() + 500;
      paymentList.querySelectorAll('[data-payment-row]').forEach(row => {
        row.dataset.confirmed = '1';
        row.classList.add('is-confirmed');
        row.classList.remove('is-pending');
        const mark = row.querySelector('[data-row-state]');
        if (mark) {
          mark.textContent = '✓';
          mark.classList.add('confirmed');
          mark.classList.remove('pending');
        }
      });
    }
  };

  const loadState = async () => {
    try {
      const data = await fetchJson(`/customers/${customerId}/payment-workflow-v031`);
      state = data.run || {};
      updateStats(data.stats);
      renderState();
      return state;
    } catch (err) {
      toast(`缴费流程读取失败：${err.message}`);
      return null;
    }
  };

  /* ---------------- 四步状态动作 ---------------- */
  flow.addEventListener('click', async e => {
    const btn = e.target.closest('[data-v031-flow-action]');
    if (!btn || btn.disabled || busy) return;
    const action = btn.dataset.v031FlowAction;

    if (action === 'notify' && !state?.notified) {
      if (!confirm('确认已经把本次缴费图片通过微信发送给客户？')) return;
    }
    if (action === 'initiate' && !state?.initiated) {
      if (!confirm('确认已经在Foxmail中将缴费邮件发送给同事？')) return;
    }
    if (action === 'paid' && !state?.paid) {
      if (!confirm('确认同事已收到邮件，并且你已经完成本次实际支付？')) return;
    }
    if (action === 'paid' && state?.paid) {
      if (!confirm('撤回“完成缴费”并恢复本次缴费前的周期状态？')) return;
    }

    busy = true;
    renderState();
    try {
      const data = await postAction(action);
      state = data.run || state;
      paintWholeReview(data);
      updateStats(data.stats);
      renderState();
      const messages = {
        review: state.reviewed ? '金额核对已确认' : '已撤回金额核对',
        notify: state.notified ? '已确认客户通知' : '已撤回客户通知',
        initiate: state.initiated ? '已确认发起缴费' : '已撤回发起缴费',
        paid: state.paid ? '本月缴费已完成' : '已撤回完成缴费并恢复缴费周期',
      };
      toast(messages[action] || '状态已更新');
    } catch (err) {
      toast(err.message || '缴费流程操作失败');
      await loadState();
    } finally {
      busy = false;
      renderState();
    }
  });

  /* ---------------- 金额改变：允许客户异议修改，并自动回退流程 ---------------- */
  workbench.addEventListener('beforeinput', e => {
    const input = e.target.closest?.('.quick-amount');
    if (!input || !state?.initiated || state.paid) return;
    if (input.dataset.v031RollbackConfirmed === '1') return;
    const ok = confirm('该客户已经发起缴费。修改金额后，原客户通知和已发送给同事的缴费内容都会失效，需要重新核对、重新通知客户并重新发起缴费。是否继续？');
    if (!ok) {
      e.preventDefault();
      return;
    }
    input.dataset.v031RollbackConfirmed = '1';
  }, true);

  workbench.addEventListener('focusout', e => {
    const input = e.target.closest?.('.quick-amount');
    if (input) delete input.dataset.v031RollbackConfirmed;
  }, true);

  const invalidateWorkflowAfterDataChange = () => {
    clearTimeout(invalidationTimer);
    invalidationTimer = setTimeout(async () => {
      if (Date.now() < ignoreMutationsUntil) return;
      if (!state) return void loadState();
      if (state.paid) return;
      if (!(state.reviewed || state.notified || state.initiated)) {
        return void loadState();
      }
      try {
        const wasInitiated = !!state.initiated;
        const wasNotified = !!state.notified;
        const data = await postAction('invalidate');
        state = data.run || state;
        updateStats(data.stats);
        renderState();
        toast(wasInitiated
          ? '金额已修改：请重新核对、重新通知客户并重新发起缴费'
          : wasNotified
            ? '金额已修改：原客户通知已失效，请重新核对并重新通知客户'
            : '金额已修改：请重新完成金额核对');
      } catch (err) {
        toast(err.message || '缴费流程回退失败');
        await loadState();
      }
    }, 220);
  };

  const watchSummary = node => {
    if (!node) return;
    new MutationObserver(() => {
      const pendingNow = pendingCount?.textContent || '';
      const totalNow = totalNode?.textContent || '';
      const changed = pendingNow !== lastPendingText || totalNow !== lastTotalText;
      lastPendingText = pendingNow;
      lastTotalText = totalNow;
      if (!changed || Date.now() < ignoreMutationsUntil) return;
      invalidateWorkflowAfterDataChange();
    }).observe(node, {childList: true, subtree: true, characterData: true});
  };
  watchSummary(pendingCount);
  if (totalNode !== pendingCount) watchSummary(totalNode);

  /* ---------------- 微信客户缴费图片：按当前页面显示列生成高密度长图 ---------------- */
  const textForCell = (row, key) => {
    const cell = row.querySelector(`[data-payment-attr-key="${CSS.escape(key)}"]`);
    if (!cell) return '—';
    if (key === 'payment_amount') return cell.querySelector('.quick-amount')?.value?.trim() || '0';
    return cell.querySelector('[data-payment-cell-value]')?.textContent?.trim() || cell.textContent?.trim() || '—';
  };

  const collectPaymentTable = () => {
    if (!paymentList) throw new Error('当前没有可生成的缴费表格');
    const headers = [...paymentList.querySelectorAll('[data-payment-column-head]')].map(head => ({
      key: head.dataset.paymentAttrKey || '',
      label: head.querySelector('span')?.textContent?.trim() || head.textContent?.trim() || '属性',
    })).filter(x => x.key);
    if (!headers.length) throw new Error('当前没有显示的缴费属性');
    const rows = [...paymentList.querySelectorAll('[data-payment-row]')].map(row =>
      headers.map(col => textForCell(row, col.key))
    );
    if (!rows.length) throw new Error('本月没有应缴数据');
    return {headers, rows};
  };

  const wrapText = (ctx, value, maxWidth) => {
    const raw = String(value ?? '');
    if (ctx.measureText(raw).width <= maxWidth) return [raw];
    const chars = [...raw];
    const lines = [];
    let line = '';
    for (const ch of chars) {
      const next = line + ch;
      if (line && ctx.measureText(next).width > maxWidth) {
        lines.push(line);
        line = ch;
      } else line = next;
      if (lines.length >= 2) break;
    }
    if (line && lines.length < 2) lines.push(line);
    if (lines.length === 2 && chars.join('').length > lines.join('').length) {
      let last = lines[1];
      while (last && ctx.measureText(last + '…').width > maxWidth) last = last.slice(0, -1);
      lines[1] = last + '…';
    }
    return lines;
  };

  const paymentImageBlob = async () => {
    const {headers, rows} = collectPaymentTable();
    const scale = 2;
    const probe = document.createElement('canvas').getContext('2d');
    probe.font = '14px system-ui, "Microsoft YaHei", sans-serif';
    const widths = headers.map((col, i) => {
      let w = Math.max(78, probe.measureText(col.label).width + 26);
      rows.forEach(row => { w = Math.max(w, Math.min(260, probe.measureText(String(row[i] ?? '')).width + 26)); });
      return Math.ceil(Math.min(260, w));
    });
    const padding = 24;
    const natural = widths.reduce((a, b) => a + b, 0);
    const maxTable = 1450;
    if (natural > maxTable) {
      const ratio = maxTable / natural;
      widths.forEach((w, i) => { widths[i] = Math.max(70, Math.floor(w * ratio)); });
    }

    const tableWidth = widths.reduce((a, b) => a + b, 0);
    const width = Math.max(620, tableWidth + padding * 2);
    const titleHeight = 82;
    const headHeight = 34;
    const rowHeight = 32;
    const footerHeight = 18;
    const height = titleHeight + headHeight + rowHeight * rows.length + footerHeight + padding;
    const canvas = document.createElement('canvas');
    canvas.width = width * scale;
    canvas.height = height * scale;
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    const customerName = root.querySelector('.v023-name-line h1')?.textContent?.trim() || '客户';
    const period = root.querySelector('.v023-payment-title-line .eyebrow')?.textContent?.trim() || '';
    const total = totalNode?.textContent?.trim() || '';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#111827';
    ctx.font = '700 21px system-ui, "Microsoft YaHei", sans-serif';
    ctx.fillText(customerName, padding, 25);
    ctx.font = '600 15px system-ui, "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#475467';
    ctx.fillText(`${period.replace('-', '年')}月缴费明细`, padding, 52);
    ctx.textAlign = 'right';
    ctx.fillText(`共 ${rows.length} 项  ·  合计 ${total}`, width - padding, 52);
    ctx.textAlign = 'left';

    let y = titleHeight;
    let x = padding;
    ctx.font = '700 14px system-ui, "Microsoft YaHei", sans-serif';
    headers.forEach((col, i) => {
      ctx.fillStyle = '#f2f4f7';
      ctx.fillRect(x, y, widths[i], headHeight);
      ctx.strokeStyle = '#d0d5dd';
      ctx.strokeRect(x, y, widths[i], headHeight);
      ctx.fillStyle = '#344054';
      ctx.textAlign = 'center';
      ctx.fillText(col.label, x + widths[i] / 2, y + headHeight / 2);
      x += widths[i];
    });

    ctx.font = '14px system-ui, "Microsoft YaHei", sans-serif';
    rows.forEach((row, rowIndex) => {
      y += rowIndex === 0 ? headHeight : rowHeight;
      x = padding;
      row.forEach((value, i) => {
        ctx.fillStyle = rowIndex % 2 ? '#fcfcfd' : '#ffffff';
        ctx.fillRect(x, y, widths[i], rowHeight);
        ctx.strokeStyle = '#e4e7ec';
        ctx.strokeRect(x, y, widths[i], rowHeight);
        const isAmount = headers[i].key === 'payment_amount';
        ctx.fillStyle = isAmount ? '#101828' : '#344054';
        ctx.font = isAmount ? '700 14px system-ui, "Microsoft YaHei", sans-serif' : '14px system-ui, "Microsoft YaHei", sans-serif';
        ctx.textAlign = 'center';
        const lines = wrapText(ctx, value, widths[i] - 12);
        if (lines.length === 1) ctx.fillText(lines[0], x + widths[i] / 2, y + rowHeight / 2);
        else {
          ctx.font = isAmount ? '700 12px system-ui, "Microsoft YaHei", sans-serif' : '12px system-ui, "Microsoft YaHei", sans-serif';
          ctx.fillText(lines[0], x + widths[i] / 2, y + 10.5);
          ctx.fillText(lines[1], x + widths[i] / 2, y + 23.5);
        }
        x += widths[i];
      });
    });

    ctx.textAlign = 'left';
    ctx.fillStyle = '#667085';
    ctx.font = '12px system-ui, "Microsoft YaHei", sans-serif';
    ctx.fillText('如对缴费金额有疑问，请及时联系确认。', padding, height - 15);

    return await new Promise((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('图片生成失败')), 'image/png');
    });
  };

  const downloadImage = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1200);
  };

  imageButton?.addEventListener('click', async () => {
    if (imageButton.disabled || busy) return;
    imageButton.disabled = true;
    imageButton.textContent = '正在生成…';
    try {
      const blob = await paymentImageBlob();
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') throw new Error('浏览器不支持图片剪贴板');
      await navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
      toast('缴费图片已复制到剪贴板，打开微信直接 Ctrl+V 粘贴即可');
    } catch (err) {
      try {
        const blob = await paymentImageBlob();
        const customerName = root.querySelector('.v023-name-line h1')?.textContent?.trim() || '客户';
        const period = root.querySelector('.v023-payment-title-line .eyebrow')?.textContent?.trim() || '';
        downloadImage(blob, `${customerName}_${period}_缴费明细.png`);
        toast(`自动复制失败（${err.message || '浏览器权限限制'}），已下载图片作为备用`);
      } catch (fallbackErr) {
        toast(fallbackErr.message || '缴费图片生成失败');
      }
    } finally {
      imageButton.textContent = '生成缴费图片';
      renderState();
    }
  });

  /* ---------------- Foxmail：阶段 2 后调用，发送后再确认阶段 3 ---------------- */
  const bridgeFetch = async (path, options = {}, timeoutMs = 7000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(`${FOXMAIL_BRIDGE}${path}`, {
        mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal, ...options,
      });
    } finally {
      clearTimeout(timer);
    }
  };

  foxmailButton?.addEventListener('click', async () => {
    if (foxmailButton.disabled || busy) return;
    busy = true;
    renderState();
    foxmailButton.textContent = '正在准备邮件…';
    try {
      const health = await bridgeFetch('/health', {}, 1400);
      const helper = await health.json().catch(() => ({}));
      if (!health.ok || helper.ok !== true || helper.verified_dispatch !== true) {
        throw new Error('未检测到可用的 Windows Foxmail 助手');
      }
      const payload = await fetchJson(`/customers/${customerId}/payment-mail-compose-v031`);
      const response = await bridgeFetch('/compose', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          recipient_b64: payload.recipient_b64 || '',
          subject_b64: payload.subject_b64 || '',
          body_b64: payload.body_b64 || '',
          attachment_filename_b64: payload.attachment_filename_b64 || '',
          attachment_content_base64: payload.attachment_content_base64 || '',
        }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true || result.verified !== true) {
        throw new Error(result.error || 'Foxmail写邮件窗口未确认打开');
      }
      toast('Foxmail写邮件窗口已打开；发送邮件后回到这里点击“发起缴费”');
    } catch (err) {
      toast(`Foxmail调用失败：${err.message || '未知错误'}`);
    } finally {
      busy = false;
      foxmailButton.textContent = '调用Foxmail';
      renderState();
    }
  });

  loadState();
})();
