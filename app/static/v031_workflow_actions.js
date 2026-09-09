(() => {
  const root = document.querySelector('.v0211-workspace');
  const customerId = root?.dataset.customerId || '';
  const paymentList = document.getElementById('paymentSortable');
  const totalNode = document.getElementById('paymentGrandTotal');
  if (!root || !customerId) return;

  const FOXMAIL_BRIDGE = 'http://127.0.0.1:18763';

  const fetchJson = async (url, options = {}) => {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) {
      throw new Error(data.detail || data.error || `请求失败（${response.status}）`);
    }
    return data;
  };

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
      } else {
        line = next;
      }
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
      let width = Math.max(78, probe.measureText(col.label).width + 26);
      rows.forEach(row => {
        width = Math.max(width, Math.min(260, probe.measureText(String(row[i] ?? '')).width + 26));
      });
      return Math.ceil(Math.min(260, width));
    });
    const padding = 24;
    const natural = widths.reduce((a, b) => a + b, 0);
    const maxTable = 1450;
    if (natural > maxTable) {
      const ratio = maxTable / natural;
      widths.forEach((width, i) => { widths[i] = Math.max(70, Math.floor(width * ratio)); });
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
        if (lines.length === 1) {
          ctx.fillText(lines[0], x + widths[i] / 2, y + rowHeight / 2);
        } else {
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

  const prepareNotice = async () => {
    const blob = await paymentImageBlob();
    try {
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
        throw new Error('浏览器不支持图片剪贴板');
      }
      await navigator.clipboard.write([new ClipboardItem({'image/png': blob})]);
      return {mode: 'clipboard'};
    } catch (clipboardError) {
      const customerName = root.querySelector('.v023-name-line h1')?.textContent?.trim() || '客户';
      const period = root.querySelector('.v023-payment-title-line .eyebrow')?.textContent?.trim() || '';
      downloadImage(blob, `${customerName}_${period}_缴费明细.png`);
      return {mode: 'download', warning: clipboardError.message || '剪贴板写入失败'};
    }
  };

  const bridgeFetch = async (path, options = {}, timeoutMs = 22000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(`${FOXMAIL_BRIDGE}${path}`, {
        mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal, ...options,
      });
    } catch (err) {
      if (err?.name === 'AbortError' || controller.signal.aborted) {
        throw new Error('Windows Foxmail助手响应超时，请确认助手正在运行后重试');
      }
      if (err instanceof TypeError) {
        throw new Error('无法连接Windows Foxmail助手，请确认本机助手正在运行');
      }
      throw err;
    } finally {
      clearTimeout(timer);
    }
  };

  const prepareInitiate = async () => {
    // The local helper now waits for a stable, foreground Foxmail compose window,
    // verifies the file-drop clipboard, and only then sends the single paste.
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
    }, 22000);
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok !== true || result.verified !== true) {
      throw new Error(result.error || 'Foxmail写邮件窗口未确认打开');
    }
    return {mode: result.mode || 'foxmail'};
  };

  window.ChenPaymentWorkflowActionsV031 = {
    prepareNotice,
    prepareInitiate,
  };
})();