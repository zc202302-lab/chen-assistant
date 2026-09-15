(() => {
  const root = document.querySelector('.v0211-workspace[data-customer-id]');
  if (!root || root.dataset.v143ResourcesReady === '1') return;
  root.dataset.v143ResourcesReady = '1';

  const customerId = root.dataset.customerId || '';
  const panel = root.querySelector('[data-customer-panel="documents"]');
  const card = panel?.querySelector('.v13-doc-card');
  if (!customerId || !panel || !card) return;

  const csrf = root.querySelector('input[name="csrf"]')?.value
    || root.querySelector('[data-payment-workbench]')?.dataset.csrf
    || '';
  const tab = root.querySelector('[data-customer-tab="documents"]');
  const countBadge = tab?.querySelector('.v13-doc-count');
  const fileList = panel.querySelector('[data-v13-doc-list]');
  const uploadForm = panel.querySelector('[data-v13-upload]');

  const headCopy = panel.querySelector('.v13-doc-head > div');
  if (headCopy) {
    const eyebrow = headCopy.querySelector('.eyebrow');
    const title = headCopy.querySelector('h2');
    const note = headCopy.querySelector('p');
    if (eyebrow) eyebrow.textContent = '客户专属资料';
    if (title) title.textContent = '客户资料';
    if (note) note.textContent = '信息资料保存在青岛数据库；文件本体保存在远程存储节点。';
  }

  // File type is intentionally free-form. The existing upload handler reads the
  // current form.elements.category value, so replacing the fixed select keeps the
  // proven upload/download pipeline while removing the category restriction.
  const oldCategory = uploadForm?.querySelector('select[name="category"]');
  if (oldCategory) {
    const input = document.createElement('input');
    input.type = 'text';
    input.name = 'category';
    input.maxLength = 80;
    input.placeholder = '文件类型（自己填写，如 合同 / 营业执照 / 方案）';
    input.value = '';
    input.className = 'v143-file-type-input';
    oldCategory.replaceWith(input);
  }

  const section = document.createElement('section');
  section.className = 'v143-resource-section';
  section.innerHTML = `
    <div class="v143-resource-head">
      <div>
        <span class="eyebrow">信息资料</span>
        <h3>账号、网址和其他信息</h3>
        <p>类型不固定，由你自己填写；同一客户可以保存任意多条信息。</p>
      </div>
      <button type="button" class="ghost small" data-v143-resource-reset hidden>取消编辑</button>
    </div>
    <form class="v143-resource-form" data-v143-resource-form>
      <input type="hidden" name="item_id" value="">
      <label><span>类型</span><input name="resource_type" maxlength="60" placeholder="例如：网址、账号、邮箱、系统入口" value="资料"></label>
      <label><span>名称</span><input name="name" maxlength="160" placeholder="例如：集团后台 / 财务账号"></label>
      <label class="v143-resource-value-field"><span>内容</span><textarea name="value" rows="2" maxlength="8000" placeholder="填写网址、账号、编号或其他需要长期保存的内容"></textarea></label>
      <label class="v143-resource-note-field"><span>备注</span><input name="note" maxlength="4000" placeholder="可选"></label>
      <button class="primary" type="submit" data-v143-resource-save>保存资料</button>
    </form>
    <div class="v143-resource-list" data-v143-resource-list><div class="v143-resource-empty">正在读取信息资料…</div></div>
  `;

  const upload = panel.querySelector('[data-v13-upload]');
  if (upload) card.insertBefore(section, upload);
  else card.appendChild(section);

  if (upload) {
    const divider = document.createElement('div');
    divider.className = 'v143-file-divider';
    divider.innerHTML = '<span class="eyebrow">文件资料</span><b>上传文件</b><small>文件类型同样由你自己填写</small>';
    card.insertBefore(divider, upload);
  }

  const form = section.querySelector('[data-v143-resource-form]');
  const list = section.querySelector('[data-v143-resource-list]');
  const reset = section.querySelector('[data-v143-resource-reset]');
  const saveButton = section.querySelector('[data-v143-resource-save]');
  let items = [];

  const escapeHtml = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
  const isWebUrl = value => /^https?:\/\//i.test(String(value || '').trim());

  async function readError(response) {
    try {
      const data = await response.json();
      return data.detail || data.error || `请求失败（${response.status}）`;
    } catch (_) {
      return `请求失败（${response.status}）`;
    }
  }

  const updateCombinedCount = () => {
    if (!countBadge) return;
    const fileCount = fileList?.querySelectorAll('.v13-doc-row').length || 0;
    const total = fileCount + items.length;
    countBadge.textContent = String(total);
    countBadge.hidden = total === 0;
  };

  const resetForm = () => {
    form.reset();
    form.elements.item_id.value = '';
    form.elements.resource_type.value = '资料';
    saveButton.textContent = '保存资料';
    reset.hidden = true;
  };

  const render = () => {
    if (!items.length) {
      list.innerHTML = '<div class="v143-resource-empty"><b>还没有信息资料</b><span>可以保存网址、账号、邮箱、系统入口、编号等任意信息。</span></div>';
      updateCombinedCount();
      return;
    }
    list.innerHTML = items.map(item => {
      const value = String(item.value || '');
      const open = isWebUrl(value)
        ? `<a class="secondary small" href="${escapeHtml(value.trim())}" target="_blank" rel="noopener noreferrer">打开</a>`
        : '';
      return `
        <article class="v143-resource-row" data-v143-resource-id="${item.id}">
          <div class="v143-resource-type">${escapeHtml(item.resource_type || '资料')}</div>
          <div class="v143-resource-main">
            <b>${escapeHtml(item.name || '未命名资料')}</b>
            <pre>${escapeHtml(value || '—')}</pre>
            ${item.note ? `<small>${escapeHtml(item.note)}</small>` : ''}
          </div>
          <div class="v143-resource-actions">
            ${open}
            ${value ? '<button type="button" class="secondary small" data-v143-resource-copy>复制</button>' : ''}
            <button type="button" class="ghost small" data-v143-resource-edit>编辑</button>
            <button type="button" class="ghost small danger" data-v143-resource-delete>删除</button>
          </div>
        </article>`;
    }).join('');
    updateCombinedCount();
  };

  async function load() {
    list.classList.add('is-loading');
    try {
      const response = await fetch(`/customers/${customerId}/resource-items-v143`, {
        headers: {'Accept': 'application/json'}, cache: 'no-store', credentials: 'same-origin'
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      items = Array.isArray(data.items) ? data.items : [];
      render();
    } catch (error) {
      list.innerHTML = `<div class="v143-resource-empty error"><b>无法读取信息资料</b><span>${escapeHtml(error.message)}</span></div>`;
    } finally {
      list.classList.remove('is-loading');
    }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saveButton.disabled) return;
    const body = new URLSearchParams();
    body.set('csrf', csrf);
    body.set('item_id', form.elements.item_id.value || '');
    body.set('resource_type', form.elements.resource_type.value || '资料');
    body.set('name', form.elements.name.value || '');
    body.set('value', form.elements.value.value || '');
    body.set('note', form.elements.note.value || '');
    saveButton.disabled = true;
    try {
      const response = await fetch(`/customers/${customerId}/resource-items-v143`, {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'Accept': 'application/json'},
        body, credentials: 'same-origin'
      });
      if (!response.ok) throw new Error(await readError(response));
      resetForm();
      await load();
    } catch (error) {
      if (window.ChenToast) window.ChenToast(error.message);
      else alert(error.message);
    } finally {
      saveButton.disabled = false;
    }
  });

  reset.addEventListener('click', resetForm);

  list.addEventListener('click', async event => {
    const row = event.target.closest('[data-v143-resource-id]');
    if (!row) return;
    const id = Number(row.dataset.v143ResourceId || 0);
    const item = items.find(x => Number(x.id) === id);
    if (!item) return;

    if (event.target.closest('[data-v143-resource-copy]')) {
      const text = String(item.value || '');
      try {
        await navigator.clipboard.writeText(text);
        window.ChenToast?.('已复制');
      } catch (_) {
        const ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); window.ChenToast?.('已复制'); } catch (_) {}
        ta.remove();
      }
      return;
    }

    if (event.target.closest('[data-v143-resource-edit]')) {
      form.elements.item_id.value = String(item.id);
      form.elements.resource_type.value = item.resource_type || '资料';
      form.elements.name.value = item.name || '';
      form.elements.value.value = item.value || '';
      form.elements.note.value = item.note || '';
      saveButton.textContent = '保存修改';
      reset.hidden = false;
      form.elements.resource_type.focus();
      form.scrollIntoView({behavior: 'smooth', block: 'center'});
      return;
    }

    if (event.target.closest('[data-v143-resource-delete]')) {
      if (!confirm(`确定删除“${item.name || item.resource_type || '这条资料'}”吗？`)) return;
      const body = new URLSearchParams({csrf});
      try {
        const response = await fetch(`/customers/${customerId}/resource-items-v143/${item.id}/delete`, {
          method: 'POST',
          headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'Accept': 'application/json'},
          body, credentials: 'same-origin'
        });
        if (!response.ok) throw new Error(await readError(response));
        if (String(form.elements.item_id.value) === String(item.id)) resetForm();
        await load();
      } catch (error) {
        if (window.ChenToast) window.ChenToast(error.message);
        else alert(error.message);
      }
    }
  });

  if (fileList) new MutationObserver(updateCombinedCount).observe(fileList, {childList: true, subtree: true});
  tab?.addEventListener('click', () => load());
  load();
})();
