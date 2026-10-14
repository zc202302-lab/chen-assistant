(() => {
  const root = document.querySelector('.v029-workspace');
  const list = root?.querySelector('[data-business-list]');
  if (!root || !list) return;

  let header = list.previousElementSibling;
  if (!header || !header.matches('[data-business-table-header]')) {
    header = document.createElement('div');
    header.className = 'business-table-header-v030';
    header.dataset.businessTableHeader = '1';
    list.parentNode.insertBefore(header, list);
  }

  let scheduled = false;
  const normalize = () => {
    scheduled = false;
    const rows = [...list.querySelectorAll('[data-business-row]')];
    const source = rows.find(row => row.querySelector('.business-attribute'));
    if (!source) {
      header.hidden = true;
      return;
    }
    header.hidden = false;

    const sourceAttrs = [...source.querySelectorAll('.business-attribute')];
    const labels = sourceAttrs.map(attr => attr.querySelector('small')?.textContent?.trim() || '属性');
    const count = Math.max(1, labels.length);
    header.style.setProperty('--business-visible-count', String(count));
    header.innerHTML = '';

    const dragGutter = document.createElement('span');
    dragGutter.className = 'business-table-header-drag-v0211';

    const fields = document.createElement('div');
    fields.className = 'business-table-header-fields-v030';
    fields.style.setProperty('--business-visible-count', String(count));
    labels.forEach((label, index) => {
      const cell = document.createElement('span');
      cell.className = 'business-table-header-cell-v030';
      cell.dataset.previewIndex = String(index);
      cell.textContent = label;
      fields.appendChild(cell);
    });
    const action = document.createElement('span');
    action.className = 'business-table-header-action-v030';
    action.textContent = '操作';
    header.append(dragGutter, fields, action);

    rows.forEach(row => {
      const grid = row.querySelector('.business-attribute-grid');
      grid?.style.setProperty('--business-visible-count', String(count));
      const attrs = [...row.querySelectorAll('.business-attribute')];
      attrs.forEach(attr => {
        attr.classList.remove('business-preview-hidden-v030');
        const label = attr.querySelector('small')?.textContent?.trim() || '属性';
        const value = attr.querySelector('strong')?.textContent?.trim() || '';
        if (['number', 'account'].includes(attr.dataset.attrKey) && value && value !== '—') {
          attr.dataset.copySilent = value;
          attr.setAttribute('role', 'button');
          attr.tabIndex = 0;
          attr.title = `点击复制${label}`;
          attr.classList.add('business-value-copy-v030');
        } else {
          delete attr.dataset.copySilent;
          attr.removeAttribute('role');
          attr.removeAttribute('tabindex');
          attr.classList.remove('business-value-copy-v030');
          attr.title = `${label}：${value || '—'} · 双击编辑`;
        }
      });
    });
  };

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(normalize);
  };

  list.addEventListener('keydown', e => {
    const cell = e.target.closest('.business-value-copy-v030');
    if (!cell || !['Enter', ' '].includes(e.key)) return;
    e.preventDefault();
    cell.click();
  });

  new MutationObserver(schedule).observe(list, {childList:true, subtree:true, characterData:true});
  normalize();
})();
