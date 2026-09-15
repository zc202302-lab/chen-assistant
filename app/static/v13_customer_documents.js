(() => {
  const root = document.querySelector('.v0211-workspace[data-customer-id]');
  if (!root || root.dataset.v13DocumentsReady === '1') return;
  root.dataset.v13DocumentsReady = '1';

  const customerId = root.dataset.customerId;
  const tabs = root.querySelector('.customer-module-tabs');
  const panels = root.querySelector('.customer-module-panels');
  if (!customerId || !tabs || !panels) return;

  const csrf = root.querySelector('input[name="csrf"]')?.value || '';
  const tab = document.createElement('button');
  tab.type = 'button';
  tab.dataset.customerTab = 'documents';
  tab.className = 'v13-documents-tab';
  tab.innerHTML = '资料 <span class="tab-count v13-doc-count" hidden>0</span>';
  const contacts = tabs.querySelector('[data-customer-tab="contacts"]');
  if (contacts?.nextSibling) tabs.insertBefore(tab, contacts.nextSibling);
  else tabs.appendChild(tab);

  const panel = document.createElement('section');
  panel.className = 'customer-panel v13-documents-panel';
  panel.dataset.customerPanel = 'documents';
  panel.hidden = true;
  panel.innerHTML = `
    <section class="card v13-doc-card">
      <div class="v13-doc-head">
        <div><span class="eyebrow">远程资料库</span><h2>客户资料</h2><p>资料与当前客户绑定，文件本体保存在远程存储节点。</p></div>
        <span class="v13-storage-state" data-v13-storage-state>检查存储…</span>
      </div>
      <form class="v13-upload" data-v13-upload>
        <select name="category" aria-label="资料分类">
          <option>营业执照</option><option>合同</option><option>报价单</option><option>方案</option><option>身份证明</option><option>其他</option>
        </select>
        <label class="v13-file-picker"><input type="file" name="file" required accept=".pdf,.jpg,.jpeg,.png,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.zip,.rar,.7z"><span data-v13-file-label>选择文件</span></label>
        <button class="primary" type="submit" data-v13-upload-button>上传资料</button>
      </form>
      <div class="v13-upload-progress" data-v13-upload-progress hidden></div>
      <div class="v13-doc-list" data-v13-doc-list><div class="v13-doc-empty">正在读取资料…</div></div>
    </section>`;
  panels.appendChild(panel);

  const countBadge = tab.querySelector('.v13-doc-count');
  const state = panel.querySelector('[data-v13-storage-state]');
  const list = panel.querySelector('[data-v13-doc-list]');
  const form = panel.querySelector('[data-v13-upload]');
  const fileInput = form.querySelector('input[type="file"]');
  const fileLabel = form.querySelector('[data-v13-file-label]');
  const uploadButton = form.querySelector('[data-v13-upload-button]');
  const progress = panel.querySelector('[data-v13-upload-progress]');
  let loaded = false;
  let storageConfigured = false;

  const escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const humanSize = bytes => {
    const n = Number(bytes || 0);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  };
  const humanTime = value => {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString('zh-CN', {year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
  };
  const iconFor = name => {
    const ext = String(name || '').split('.').pop().toLowerCase();
    if (['jpg','jpeg','png','webp'].includes(ext)) return '▧';
    if (ext === 'pdf') return 'PDF';
    if (['doc','docx'].includes(ext)) return 'W';
    if (['xls','xlsx'].includes(ext)) return 'X';
    return '▤';
  };

  async function readError(response) {
    try {
      const data = await response.json();
      return data.detail || data.error || `请求失败（${response.status}）`;
    } catch (_) {
      return `请求失败（${response.status}）`;
    }
  }

  function render(items) {
    countBadge.textContent = String(items.length);
    countBadge.hidden = items.length === 0;
    if (!items.length) {
      list.innerHTML = '<div class="v13-doc-empty"><b>还没有客户资料</b><span>可上传营业执照、合同、报价单、方案等文件。</span></div>';
      return;
    }
    list.innerHTML = items.map(item => `
      <article class="v13-doc-row" data-v13-document-id="${item.id}">
        <div class="v13-doc-icon">${escapeHtml(iconFor(item.original_name))}</div>
        <div class="v13-doc-main"><b title="${escapeHtml(item.original_name)}">${escapeHtml(item.original_name)}</b><span>${escapeHtml(item.category)} · ${humanSize(item.size)} · ${escapeHtml(humanTime(item.created_at))}</span></div>
        <a class="secondary small v13-doc-download" href="/customers/${customerId}/documents-v13/${item.id}/download">下载</a>
        <button type="button" class="ghost small danger v13-doc-delete" data-v13-delete="${item.id}" data-name="${escapeHtml(item.original_name)}">删除</button>
      </article>`).join('');
  }

  async function load(force = false) {
    if (loaded && !force) return;
    list.classList.add('is-loading');
    try {
      const response = await fetch(`/customers/${customerId}/documents-v13`, {headers:{'Accept':'application/json'}});
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      storageConfigured = Boolean(data.storage_configured);
      state.textContent = storageConfigured ? `美国节点 · 单文件≤${data.max_file_mb}MB` : '远程存储未配置';
      state.classList.toggle('offline', !storageConfigured);
      uploadButton.disabled = !storageConfigured;
      form.classList.toggle('is-disabled', !storageConfigured);
      render(data.items || []);
      loaded = true;
    } catch (error) {
      state.textContent = '资料服务异常';
      state.classList.add('offline');
      list.innerHTML = `<div class="v13-doc-empty error"><b>无法读取资料</b><span>${escapeHtml(error.message)}</span></div>`;
    } finally {
      list.classList.remove('is-loading');
    }
  }

  function openDocuments() {
    root.querySelectorAll('[data-customer-tab]').forEach(el => el.classList.toggle('active', el === tab));
    root.querySelectorAll('[data-customer-panel]').forEach(el => { el.hidden = el !== panel; });
    root.dataset.activeTab = 'documents';
    const url = new URL(location.href);
    url.searchParams.set('tab', 'documents');
    history.replaceState(null, '', url);
    load();
  }

  tab.addEventListener('click', openDocuments);
  tabs.querySelectorAll('[data-customer-tab]:not([data-customer-tab="documents"])').forEach(existing => {
    existing.addEventListener('click', () => {
      panel.hidden = true;
      tab.classList.remove('active');
    });
  });

  fileInput.addEventListener('change', () => {
    fileLabel.textContent = fileInput.files?.[0]?.name || '选择文件';
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (!storageConfigured) return;
    const file = fileInput.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append('csrf', csrf);
    body.append('category', form.elements.category.value);
    body.append('file', file, file.name);
    uploadButton.disabled = true;
    progress.hidden = false;
    progress.textContent = `正在上传 ${file.name}…`;
    try {
      const response = await fetch(`/customers/${customerId}/documents-v13`, {method:'POST', body});
      if (!response.ok) throw new Error(await readError(response));
      progress.textContent = '上传完成';
      form.reset();
      fileLabel.textContent = '选择文件';
      await load(true);
      setTimeout(() => { progress.hidden = true; }, 1200);
    } catch (error) {
      progress.textContent = error.message;
      progress.classList.add('error');
    } finally {
      uploadButton.disabled = !storageConfigured;
    }
  });

  list.addEventListener('click', async event => {
    const button = event.target.closest('[data-v13-delete]');
    if (!button) return;
    const name = button.dataset.name || '该文件';
    if (!confirm(`确定删除“${name}”吗？\n美国节点上的文件本体也会同时删除。`)) return;
    button.disabled = true;
    const body = new URLSearchParams({csrf});
    try {
      const response = await fetch(`/customers/${customerId}/documents-v13/${button.dataset.v13Delete}/delete`, {
        method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body,
      });
      if (!response.ok) throw new Error(await readError(response));
      await load(true);
    } catch (error) {
      alert(error.message);
      button.disabled = false;
    }
  });

  const requestedTab = new URL(location.href).searchParams.get('tab');
  if (requestedTab === 'documents') openDocuments();
})();
