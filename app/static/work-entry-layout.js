(() => {
  const root = document.querySelector('[data-work-entries]');
  if (!root) return;
  const edit = root.querySelector('[data-entry-edit]');
  const cancel = root.querySelector('[data-entry-cancel]');
  const feedback = root.querySelector('[data-entry-feedback]');
  const zones = [...root.querySelectorAll('[data-entry-zone]')];
  let saved, editing = false, saving = false, drag = null;
  const layout = () => Object.fromEntries(zones.map(zone => [zone.dataset.entryZone,
    [...zone.querySelectorAll('[data-entry-key]')].map(tile => tile.dataset.entryKey)]));
  const restore = value => zones.forEach(zone => value[zone.dataset.entryZone].forEach(key => {
    zone.append(root.querySelector(`[data-entry-key="${key}"]`));
  }));
  function mode(value) {
    editing = value;
    root.classList.toggle('is-editing', value);
    edit.textContent = value ? '保存布局' : '编辑模块';
    edit.setAttribute('aria-pressed', String(value));
    cancel.hidden = !value;
    root.querySelectorAll('[data-entry-handle]').forEach(handle => { handle.hidden = !value; });
    root.querySelectorAll('[data-entry-link], .work-entry-link').forEach(link => { link.tabIndex = value ? -1 : 0; });
  }
  edit.addEventListener('click', async () => {
    if (saving) return;
    if (!editing) {
      saved = layout(); mode(true);
      feedback.textContent = '拖动右上角移动模块；也可用方向键排序、空格切换区域。';
      return;
    }
    saving = true; edit.disabled = cancel.disabled = true;
    feedback.textContent = '正在保存…';
    try {
      const form = new FormData(); form.set('csrf', root.dataset.csrf); form.set('layout', JSON.stringify(layout()));
      const response = await fetch('/work/entry-layout', {method: 'POST', body: form});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('保存失败，请重试');
      const result = await response.json(); if (!result.ok) throw new Error('保存失败，请重试');
      mode(false); feedback.textContent = '布局已保存';
    } catch (error) { feedback.textContent = error.message; }
    finally { saving = false; edit.disabled = cancel.disabled = false; }
  });
  cancel.addEventListener('click', () => { if (saving) return; restore(saved); mode(false); feedback.textContent = ''; });
  root.addEventListener('click', event => { if (editing && event.target.closest('.work-entry-link')) event.preventDefault(); });
  root.addEventListener('pointerdown', event => {
    const handle = event.target.closest('[data-entry-handle]');
    if (!editing || saving || !handle || event.button !== 0) return;
    event.preventDefault();
    drag = {tile: handle.closest('[data-entry-key]'), handle, id: event.pointerId};
    drag.tile.classList.add('is-dragging'); handle.setPointerCapture(event.pointerId);
  });
  root.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    event.preventDefault();
    if (event.clientY < 110) window.scrollBy(0, -14);
    else if (event.clientY > window.innerHeight - 90) window.scrollBy(0, 14);
    const hit = document.elementFromPoint(event.clientX, event.clientY);
    const zone = hit?.closest('[data-entry-zone]');
    zones.forEach(z => z.classList.toggle('is-drop-target', z === zone));
    if (!zone || !root.contains(zone)) return;
    const target = hit.closest('[data-entry-key]');
    if (target && target !== drag.tile) {
      const box = target.getBoundingClientRect();
      zone.insertBefore(drag.tile, event.clientX < box.left + box.width / 2 ? target : target.nextSibling);
    } else if (!target) zone.append(drag.tile);
  });
  function finish(event) {
    if (!drag || event.pointerId !== drag.id) return;
    drag.tile.classList.remove('is-dragging');
    if (drag.handle.hasPointerCapture(event.pointerId)) drag.handle.releasePointerCapture(event.pointerId);
    drag = null; zones.forEach(z => z.classList.remove('is-drop-target'));
  }
  root.addEventListener('pointerup', finish); root.addEventListener('pointercancel', finish);
  root.addEventListener('keydown', event => {
    const handle = event.target.closest('[data-entry-handle]');
    if (!editing || saving || !handle) return;
    const tile = handle.closest('[data-entry-key]');
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault(); zones.find(z => z !== tile.parentElement).append(tile);
    } else if (['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key)) {
      event.preventDefault();
      if (['ArrowLeft', 'ArrowUp'].includes(event.key)) {
        if (tile.previousElementSibling) tile.parentElement.insertBefore(tile, tile.previousElementSibling);
      } else if (tile.nextElementSibling) tile.parentElement.insertBefore(tile.nextElementSibling, tile);
    } else return;
    handle.focus(); feedback.textContent = `已移动到${tile.parentElement.dataset.entryZone === 'common' ? '常用入口' : '辅助入口'}`;
  });
})();
