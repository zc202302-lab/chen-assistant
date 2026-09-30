(() => {
  const root = document.querySelector('.v0211-workspace');
  if (!root) return;
  // Keep full-list indices while filtering, so a row retains its reference number.
  const renumber = list => {
    list.querySelectorAll('[data-payment-row],[data-business-row]').forEach((row, index) => {
      const cell = row.querySelector('[data-row-number]');
      const value = String(index + 1);
      if (cell && cell.textContent !== value) cell.textContent = value;
    });
    const header = list.querySelector('.business-table-header-drag-v0211');
    if (header && header.textContent !== '序号') header.textContent = '序号';
  };
  root.querySelectorAll('#paymentSortable,[data-business-list]').forEach(list => {
    renumber(list);
    // Reorder and live refresh both change the list's children.
    new MutationObserver(() => renumber(list)).observe(list, {childList:true, subtree:true});
  });
  root.addEventListener('click', async event => {
    const target = event.target.closest('[data-customer-copy]');
    if (!target) return;
    event.preventDefault();
    const ok = await window.ChenCopyText(target.dataset.customerCopy || '');
    window.ChenToast(ok ? '已复制' : '复制失败，请重试');
  });
})();
