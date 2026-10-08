(() => {
  'use strict';
  const script = document.querySelector('script[data-home-shortcut-script]');
  const csrf = script?.dataset.csrf || '';
  const endpoint = '/home/shortcuts';
  const permitted = href => /^\/(?:(?:work|info|life)(?:\/[a-z][a-z0-9_-]*){0,2}|customers|products|search)$/.test(href);
  let items = [];
  async function load() {
    const response = await fetch(endpoint, {credentials: 'same-origin'});
    if (!response.ok) throw new Error('读取首页模块失败');
    const data = await response.json();
    items = Array.isArray(data.items) ? data.items : [];
  }
  async function save(next) {
    const form = new FormData();
    form.set('csrf', csrf);
    form.set('items', JSON.stringify(next));
    const response = await fetch(endpoint, {method: 'POST', body: form, credentials: 'same-origin'});
    if (!response.ok) throw new Error('保存首页模块失败');
    items = next;
  }
  function button(label, onClick) {
    const el = document.createElement('button');
    el.type = 'button'; el.textContent = label;
    el.className = 'home-shortcut-action';
    el.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); onClick(el); });
    return el;
  }
  function status(message) {
    let notice = document.querySelector('[data-home-shortcut-notice]');
    if (!notice) {
      notice = document.createElement('p');
      notice.dataset.homeShortcutNotice = '';
      notice.setAttribute('role', 'status');
      notice.className = 'home-shortcut-notice';
      document.querySelector('[data-home-shortcuts], [data-work-entries], .v10-shell')?.prepend(notice);
    }
    notice.textContent = message;
  }
  async function pin(href, title, element) {
    if (!permitted(href)) return;
    if (items.some(item => item.href === href)) { status('该模块已经在首页'); return; }
    if (items.length >= 30) { status('首页最多添加30个模块'); return; }
    element.disabled = true;
    try { await save([...items, {href, title: title.trim().slice(0,40)}]); status('已发送至首页'); }
    catch (error) { status(error.message); }
    finally { element.disabled = false; }
  }
  const home = document.querySelector('[data-home-shortcuts]');
  if (home) {
    const grid = home.querySelector('[data-home-shortcut-grid]');
    const edit = home.querySelector('[data-home-shortcut-edit]');
    const cancel = home.querySelector('[data-home-shortcut-cancel]');
    let editing = false, snapshot = [];
    function render() {
      grid.replaceChildren();
      if (!items.length) {
        const blank = document.createElement('p'); blank.textContent = '还没有快捷模块，可在工作、资料或生活空间中发送至首页。';
        grid.append(blank);
      }
      items.forEach((item, index) => {
        const card = document.createElement('div'); card.className = 'home-shortcut-tile';
        const link = document.createElement('a'); link.href = item.href; link.textContent = item.title;
        card.append(link);
        if (editing) {
          const actions = document.createElement('span'); actions.className = 'home-shortcut-controls';
          const change = (i, j) => { [items[i], items[j]] = [items[j], items[i]]; render(); };
          if (index) actions.append(button('←', () => change(index, index - 1)));
          if (index < items.length - 1) actions.append(button('→', () => change(index, index + 1)));
          actions.append(button('移除', () => { items.splice(index,1); render(); }));
          card.append(actions);
        }
        grid.append(card);
      });
    }
    edit.addEventListener('click', async () => {
      if (!editing) { snapshot = items.map(x => ({...x})); editing = true; edit.textContent = '保存布局'; cancel.hidden = false; render(); return; }
      edit.disabled = true;
      try { await save(items); editing = false; cancel.hidden = true; edit.textContent = '编辑模块'; status('首页模块已保存'); render(); }
      catch (error) { status(error.message); }
      finally { edit.disabled = false; }
    });
    cancel.addEventListener('click', () => { items = snapshot; editing = false; cancel.hidden = true; edit.textContent = '编辑模块'; render(); });
    load().then(render).catch(error => status(error.message));
    return;
  }
  // Work has an existing edit mode: only show the pin control while editing.
  const work = document.querySelector('[data-work-entries]');
  if (work) {
    load().then(() => {
      work.querySelectorAll('[data-entry-key]').forEach(tile => {
        const link = tile.querySelector('.work-entry-link');
        if (!link || !permitted(link.getAttribute('href'))) return;
        const action = button('发送至首页', el => pin(link.getAttribute('href'), link.querySelector('h3')?.textContent || link.textContent, el));
        action.classList.add('work-home-pin'); action.hidden = true; tile.append(action);
      });
      const observer = new MutationObserver(() => {
        const editing = work.classList.contains('is-editing');
        work.querySelectorAll('.work-home-pin').forEach(el => { el.hidden = !editing; });
      });
      observer.observe(work, {attributes:true, attributeFilter:['class']});
    }).catch(error => status(error.message));
    return;
  }
  // Other section entry pages opt in without changing their business modules.
  const path = location.pathname;
  if (path !== '/info' && path !== '/life') return;
  const shell = document.querySelector('.v10-shell, .info-shell, main');
  if (!shell) return;
  const candidates = [...shell.querySelectorAll('a[href]')].filter(link =>
    permitted(link.getAttribute('href')) && link.getAttribute('href') !== path &&
    link.closest('.v10-stat-grid, .v10-card-grid, .v10-life-feature, .info-module-grid, .info-home-grid'));
  if (!candidates.length) return;
  const toolbar = document.createElement('div'); toolbar.className = 'home-shortcut-toolbar';
  const toggle = button('编辑模块', () => {
    const editing = !toolbar.classList.contains('is-editing');
    toolbar.classList.toggle('is-editing', editing);
    toggle.textContent = editing ? '完成编辑' : '编辑模块';
    toolbar.querySelectorAll('[data-pin-other]').forEach(el => { el.hidden = !editing; });
  });
  toolbar.append(toggle);
  shell.prepend(toolbar);
  load().then(() => {
    const seen = new Set();
    candidates.forEach(link => {
      const href = link.getAttribute('href');
      if (seen.has(href)) return;
      seen.add(href);
      const action = button('发送至首页', el => pin(href, link.querySelector('span,strong,h2,h3')?.textContent || link.textContent, el));
      action.dataset.pinOther = ''; action.hidden = true;
      link.insertAdjacentElement('afterend', action);
      toolbar.append(action);
    });
  }).catch(error => status(error.message));
})();
