/* Work-list spreadsheet. Text-only DOM rendering; no workbook code is executed. */
(() => {
  'use strict';
  const root = document.querySelector('[data-work-sheet]');
  if (!root) return;
  const fresh = root.dataset.new === '1';
  const readonly = root.dataset.readonly === '1';
  let model = fresh ? {
    title: '', revision: 1,
    fields: Array.from({length: 3}, (_, i) => ({id: 'new_c' + i, label: '列' + String.fromCharCode(65 + i), kind: 'text', options: []})),
    rows: Array.from({length: 4}, (_, i) => ({id: 'new_r' + i, revision: 0, values: ['', '', '']})),
    layout: {mode: 'grid', legacy: false, widths: {}, heights: {}, cells: {}, merges: []},
  } : JSON.parse(document.getElementById('work-sheet-data').textContent);
  let dirty = false, busy = false, serial = 10, page = 0;
  const filters = new Map();
  const stage = root.querySelector('[data-sheet-stage]');
  const notice = root.querySelector('[data-sheet-notice]');
  const save = root.querySelector('[data-sheet-save]');
  const before = root.querySelector('[data-sheet-prev]');
  const after = root.querySelector('[data-sheet-next]');
  const display = value => Array.isArray(value) ? value.join('、') : String(value ?? '');
  const formatted = (value, style = {}) => {
    const text = display(value), fmt = style.number_format || '';
    if (!style.numeric) return text;
    if (/^\d{4}-\d{2}-\d{2}/.test(text) && /[yd]/i.test(fmt)) {
      const [y, m, d] = text.slice(0, 10).split('-');
      return fmt.replace(/"([^"]*)"/g, '$1').replace(/yyyy|yy|mm|m|dd|d/gi, token => ({yyyy:y, yy:y.slice(2), mm:m, m:String(Number(m)), dd:d, d:String(Number(d))})[token.toLowerCase()]);
    }
    if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
    const n = Number(text); if (!Number.isFinite(n)) return text;
    const decimals = Math.min(20, (fmt.split('.')[1] || '').replace(/[^0]/g, '').length);
    if (/^0{2,30}$/.test(fmt) && Number.isInteger(n) && n >= 0) return text.padStart(fmt.length, '0');
    if (fmt.includes('%')) return (n * 100).toFixed(decimals) + '%';
    if (/^[#0,.]+$/.test(fmt)) return n.toLocaleString('en-US', {useGrouping: fmt.includes(','), minimumFractionDigits: decimals, maximumFractionDigits: decimals});
    return text;
  };
  const lower = value => display(value).trim().toLocaleLowerCase();
  const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const mark = () => {
    dirty = true;
    notice.textContent = '未保存';
    if (save) save.disabled = readonly || busy;
  };
  const layout = () => {
    model.layout.widths ||= {};
    model.layout.heights ||= {};
    model.layout.cells ||= {};
    model.layout.merges ||= [];
    return model.layout;
  };
  const applyStyle = (el, style = {}) => {
    if (style.font) el.style.fontFamily = style.font;
    if (style.size) el.style.fontSize = style.size + 'pt';
    if (style.bold !== undefined) el.style.fontWeight = style.bold ? '700' : '400';
    if (style.italic) el.style.fontStyle = 'italic';
    if (style.underline) el.style.textDecoration = 'underline';
    if (style.color) el.style.color = style.color;
    if (style.background) el.style.backgroundColor = style.background;
    if (style.align) el.style.textAlign = style.align;
    if (style.valign) el.style.verticalAlign = style.valign === 'center' ? 'middle' : style.valign;
    if (style.wrap) el.style.whiteSpace = 'pre-wrap';
    for (const edge of ['left', 'right', 'top', 'bottom']) {
      const border = style['border_' + edge];
      if (border) {
        const kind = border.style === 6 ? 'double' : [3,8,9,10,11,12,13].includes(border.style) ? 'dashed' : [4,7].includes(border.style) ? 'dotted' : 'solid';
        el.style.setProperty('border-' + edge, border.style ? (border.style === 6 ? 3 : [2,5].includes(border.style) ? 2 : 1) + 'px ' + kind + ' ' + (border.color || '#475569') : '0');
      }
    }
  };
  const resize = (target, axis, key, initial, update) => {
    const handle = node('span', axis === 'x' ? 'ws-col-resize' : 'ws-row-resize');
    handle.tabIndex = readonly ? -1 : 0;
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', axis === 'x' ? 'vertical' : 'horizontal');
    handle.setAttribute('aria-label', (axis === 'x' ? '调整列宽 ' : '调整行高 ') + key);
    handle.setAttribute('aria-valuemin', '12');
    handle.setAttribute('aria-valuemax', axis === 'x' ? '800' : '500');
    handle.setAttribute('aria-valuenow', String(initial));
    if (!readonly) {
      const change = value => {
        value = Math.max(12, Math.min(axis === 'x' ? 800 : 500, value));
        layout()[axis === 'x' ? 'widths' : 'heights'][key] = value;
        handle.setAttribute('aria-valuenow', String(value));
        update(value);
        mark();
      };
      handle.addEventListener('pointerdown', event => {
        event.preventDefault();
        const start = axis === 'x' ? event.clientX : event.clientY;
        const size = layout()[axis === 'x' ? 'widths' : 'heights'][key] || initial;
        handle.setPointerCapture(event.pointerId);
        const move = e => change(Math.round(size + (axis === 'x' ? e.clientX : e.clientY) - start));
        const end = () => {
          handle.removeEventListener('pointermove', move);
          handle.removeEventListener('pointerup', end);
          handle.removeEventListener('pointercancel', end);
        };
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', end);
        handle.addEventListener('pointercancel', end);
      });
      handle.addEventListener('keydown', event => {
        const minus = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
        const plus = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
        if ([minus, plus].includes(event.key)) {
          event.preventDefault();
          change((layout()[axis === 'x' ? 'widths' : 'heights'][key] || initial) + (event.key === plus ? 8 : -8));
        }
      });
    }
    target.append(handle);
  };
  const matchedRows = () => model.rows.map((r, i) => ({r, i})).filter(({r}) => [...filters].every(([c, q]) => !q || lower(r.values[c]).includes(q)));
  const render = () => {
    const formats = layout();
    const matched = matchedRows();
    page = Math.min(page, Math.max(0, Math.ceil(matched.length / 100) - 1));
    const visible = matched.slice(page * 100, (page + 1) * 100);
    stage.replaceChildren();
    const table = node('table', 'ws-grid');
    table.setAttribute('aria-label', '清单表格');
    const cols = node('colgroup');
    const gutter = node('col'); gutter.style.width = '42px'; cols.append(gutter);
    const colElements = model.fields.map(f => {
      const col = node('col'); col.style.width = (formats.widths[f.id] || 150) + 'px'; cols.append(col); return col;
    });
    table.append(cols);
    const head = node('thead');
    const letters = node('tr', 'ws-letters');
    letters.append(node('th', 'ws-corner', ''));
    model.fields.forEach((field, c) => {
      const th = node('th', '', (() => { let n = c + 1, s = ''; while (n) { n--; s = String.fromCharCode(65 + n % 26) + s; n = Math.floor(n / 26); } return s; })());
      resize(th, 'x', field.id, formats.widths[field.id] || 150, size => { colElements[c].style.width = size + 'px'; });
      letters.append(th);
    });
    head.append(letters);
    const headers = node('tr', 'ws-headers');
    headers.style.height = (formats.heights.h || 36) + 'px';
    const headerIndex = node('th', 'ws-index', '标题');
    resize(headerIndex, 'y', 'h', formats.heights.h || 36, size => { headers.style.height = size + 'px'; });
    headers.append(headerIndex);
    const headerCovered = new Set(), headerAnchors = new Map();
    for (const merge of formats.merges.filter(m => m.rows.includes('h'))) {
      headerAnchors.set(merge.cols[0], merge.cols.length);
      merge.cols.slice(1).forEach(c => headerCovered.add(c));
    }
    model.fields.forEach((field, c) => {
      if (headerCovered.has(field.id)) return;
      const th = node('th', 'ws-header-cell');
      if (headerAnchors.has(field.id)) th.colSpan = headerAnchors.get(field.id);
      applyStyle(th, formats.cells['h|' + field.id]);
      const input = node('input', 'ws-header-input');
      input.value = field.label; input.maxLength = 80; input.readOnly = readonly;
      input.setAttribute('aria-label', '第' + (c + 1) + '列标题');
      input.addEventListener('input', () => { field.label = input.value; mark(); });
      const trigger = node('button', 'ws-filter-button', '▾');
      trigger.type = 'button'; trigger.setAttribute('aria-label', '筛选第' + (c + 1) + '列');
      const pop = node('div', 'ws-filter-popover');
      pop.hidden = true; pop.dataset.filterCol = String(c);
      const filter = node('input');
      filter.type = 'search'; filter.placeholder = '筛选内容'; filter.value = filters.get(c) || '';
      filter.setAttribute('aria-label', '第' + (c + 1) + '列筛选内容');
      const clear = node('button', '', '清除'); clear.type = 'button';
      const run = () => { filters.set(c, lower(filter.value)); page = 0; render(); const next = stage.querySelector('.ws-filter-popover[data-filter-col="' + c + '"]'); next.hidden = false; next.querySelector('input').focus(); };
      filter.addEventListener('change', run);
      filter.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); run(); } });
      clear.addEventListener('click', () => { filters.delete(c); render(); });
      pop.append(filter, clear);
      trigger.setAttribute('aria-expanded', 'false');
      trigger.classList.toggle('has-filter', !!filters.get(c));
      trigger.addEventListener('click', () => {
        const open = pop.hidden;
        stage.querySelectorAll('.ws-filter-popover').forEach(e => { e.hidden = true; });
        stage.querySelectorAll('.ws-filter-button').forEach(e => e.setAttribute('aria-expanded', 'false'));
        pop.hidden = !open; trigger.setAttribute('aria-expanded', String(open));
        if (open) filter.focus();
      });
      th.append(input, trigger, pop); headers.append(th);
    });
    head.append(headers); table.append(head);
    const body = node('tbody');
    const visibleIds = visible.map(v => v.r.id);
    const covered = new Set(), anchors = new Map();
    for (const merge of formats.merges) {
      if (merge.rows.includes('h')) continue;
      const mr = merge.rows.filter(r => visibleIds.includes(r));
      const mc = merge.cols.filter(c => model.fields.some(f => f.id === c));
      if (!mr.length || !mc.length) continue;
      const origin = model.rows.find(r => r.id === merge.rows[0]);
      const originCol = model.fields.findIndex(f => f.id === merge.cols[0]);
      anchors.set(mr[0] + '|' + mc[0], {rowspan: mr.length, colspan: mc.length, value: origin?.values[originCol], origin, originCol});
      mr.forEach(r => mc.forEach(c => { if (r !== mr[0] || c !== mc[0]) covered.add(r + '|' + c); }));
    }
    visible.forEach(({r, i}) => {
      const tr = node('tr'); tr.dataset.row = String(i);
      const height = formats.heights[r.id] || 32;
      tr.style.height = height + 'px';
      const index = node('th', 'ws-index', String(i + 1));
      index.scope = 'row';
      resize(index, 'y', r.id, height, size => { tr.style.height = size + 'px'; });
      tr.append(index);
      model.fields.forEach((field, c) => {
        const key = r.id + '|' + field.id;
        if (covered.has(key)) return;
        const td = node('td', 'ws-data-cell');
        applyStyle(td, formats.cells[key]);
        const merge = anchors.get(key);
        if (merge) { td.rowSpan = merge.rowspan; td.colSpan = merge.colspan; }
        const cell = node('textarea', 'ws-cell');
        cell.rows = 1; cell.maxLength = 4000; cell.readOnly = readonly;
        const currentValue = () => merge ? merge.origin.values[merge.originCol] : r.values[c];
        cell.value = formatted(currentValue(), formats.cells[key]);
        cell.addEventListener('focus', () => { cell.value = display(currentValue()); });
        cell.addEventListener('blur', () => { cell.value = formatted(currentValue(), formats.cells[key]); });
        cell.dataset.row = String(i); cell.dataset.col = String(c);
        cell.setAttribute('aria-label', '第' + (i + 1) + '行 ' + field.label);
        cell.addEventListener('input', () => {
          const target = merge ? merge.origin : r, col = merge ? merge.originCol : c;
          target.values[col] = field.kind === 'multi' ? cell.value.split(/[、,，;；\n]/).map(v => v.trim()).filter(Boolean) : cell.value;
          mark();
        });
        cell.addEventListener('keydown', e => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            stage.querySelector('.ws-cell[data-row="' + (i + 1) + '"][data-col="' + c + '"]')?.focus();
          }
        });
        cell.addEventListener('paste', e => {
          const text = e.clipboardData?.getData('text/plain');
          if (!text || (!text.includes('\t') && !text.includes('\n')) || readonly || merge) return;
          e.preventDefault();
          if ([...filters.values()].some(Boolean)) { notice.textContent = '先清除筛选再粘贴多格'; return; }
          const matrix = text.replace(/\r/g, '').replace(/\n$/, '').split('\n').map(line => line.split('\t'));
          if (i + matrix.length > 5000 || c + Math.max(...matrix.map(line => line.length)) > 50) {
            notice.textContent = '粘贴范围不能超过5000行、50列'; return;
          }
          const crossingMerge = layout().merges.some(m => matrix.some((line, ri) => line.some((_, ci) => m.rows.includes(model.rows[i + ri]?.id) && m.cols.includes(model.fields[c + ci]?.id))));
          if (crossingMerge) { notice.textContent = '合并区域请逐格编辑'; return; }
          while (model.fields.length < c + Math.max(...matrix.map(line => line.length))) addColumn(false);
          while (model.rows.length < i + matrix.length) addRow(false);
          matrix.forEach((line, ri) => line.forEach((value, ci) => {
            const f = model.fields[c + ci];
            model.rows[i + ri].values[c + ci] = f.kind === 'multi' ? value.split(/[、,，;；]/).filter(Boolean) : value;
          }));
          mark(); render();
        });
        td.append(cell); tr.append(td);
      });
      body.append(tr);
    });
    table.append(body); stage.append(table);
    root.querySelector('[data-sheet-count]').textContent = matched.length + ' / ' + model.rows.length + ' 行 · ' + model.fields.length + ' 列';
    if (before) before.disabled = page === 0;
    if (after) after.disabled = (page + 1) * 100 >= matched.length;
  };
  const addRow = (paint = true) => {
    if (readonly || model.rows.length >= 5000) return;
    model.rows.push({id: 'new_r' + serial++, revision: 0, values: model.fields.map(f => f.kind === 'multi' ? [] : '')});
    mark(); if (paint) { page = Math.floor((model.rows.length - 1) / 100); render(); }
  };
  const addColumn = (paint = true) => {
    if (readonly || model.fields.length >= 50) return;
    model.fields.push({id: 'new_c' + serial++, label: '列' + (model.fields.length + 1), kind: 'text', options: []});
    model.rows.forEach(r => r.values.push(''));
    mark(); if (paint) render();
  };
  root.querySelector('[data-sheet-add-row]')?.addEventListener('click', () => addRow());
  root.querySelector('[data-sheet-add-col]')?.addEventListener('click', () => addColumn());
  root.querySelector('[data-sheet-clear-filters]')?.addEventListener('click', () => { filters.clear(); page = 0; render(); });
  before?.addEventListener('click', () => { page--; render(); });
  after?.addEventListener('click', () => { page++; render(); });
  document.addEventListener('pointerdown', e => {
    if (!e.target.closest('.ws-header-cell')) {
      stage.querySelectorAll('.ws-filter-popover').forEach(el => { el.hidden = true; });
      stage.querySelectorAll('.ws-filter-button').forEach(el => el.setAttribute('aria-expanded', 'false'));
    }
  });
  window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  if (fresh) {
    const form = root.closest('form');
    form.addEventListener('submit', () => {
      model.title = form.querySelector('[name=title]').value;
      form.querySelector('[name=sheet_payload]').value = JSON.stringify(model);
      dirty = false;
    });
    form.querySelector('[name=preset]')?.addEventListener('change', event => {
      root.hidden = event.target.value !== 'blank';
    });
  } else if (save) {
    save.disabled = true;
    save.addEventListener('click', async () => {
      if (busy || readonly) return;
      busy = true; root.inert = true; save.disabled = true; notice.textContent = '正在保存';
      try {
        const response = await fetch(root.dataset.saveUrl, {method: 'POST', credentials: 'same-origin',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...model, csrf: root.dataset.csrf})});
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(typeof error.detail === 'string' ? error.detail : '保存失败，请重试');
        }
        model = await response.json(); dirty = false; notice.textContent = '已保存'; render(); window.location.reload();
      } catch (error) {
        notice.textContent = error.message; save.disabled = false;
      } finally { busy = false; root.inert = false; }
    });
  }
  const details = document.querySelector('[data-record-details]');
  if (details) {
    const key = 'work-list-record-details:' + root.dataset.listId;
    try { details.open = sessionStorage.getItem(key) === '1'; } catch (_) { /* optional */ }
    details.addEventListener('toggle', () => { try { sessionStorage.setItem(key, details.open ? '1' : '0'); } catch (_) { /* optional */ } });
  }
  render();
})();
