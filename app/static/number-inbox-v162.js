document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-copy-value]');
  if (!target) return;
  const value = target.getAttribute('data-copy-value') || '';
  if (!value) return;
  try {
    if (!await window.ChenCopyText(value)) throw new Error('copy failed');
    const original = target.textContent;
    target.textContent = original + '  ✓';
    window.setTimeout(() => { target.textContent = original; }, 900);
  } catch (_) {
    window.ChenToast?.('复制失败，请重试');
    const range = document.createRange();
    range.selectNodeContents(target);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
});

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-number-batch]');
  if (!button || button.disabled) return;
  const status = document.querySelector('[data-number-batch-status]');
  button.disabled = true;
  const original = button.textContent;
  button.textContent = '正在写入…';
  status.textContent = '正在连接Windows助手，请允许浏览器访问本地网络。';
  const local = 'http://127.0.0.1:18764';
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, signal: AbortSignal.timeout(60000)});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || result.detail || '操作失败');
    return result;
  }
  try {
    const form = new FormData();
    form.set('csrf', button.dataset.csrf);
    const signed = await request('/work/number-inbox/batch-add', {method: 'POST', body: form});
    let health;
    try {
      health = await request(local + '/health');
    } catch (_) {
      throw new Error('无法连接Windows助手。请升级并启动助手，开启号码提醒，填写连接码和目标Excel路径，并允许浏览器访问本地网络。');
    }
    if (health.batch_version !== 1 || health.receipt_version !== 1) throw new Error('请先升级Windows助手后重试。');
    let result;
    try {
      result = await request(local + '/number-batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(signed)
      });
    } catch (error) {
      if (error.name === 'TimeoutError' || error.name === 'TypeError') {
        throw new Error('写入结果尚未确认，请先检查Excel，再决定是否重新生成。');
      }
      throw error;
    }
    if (!result.receipt) throw new Error('Excel写入成功，但客户端未返回回执。请检查更新；未更改号码状态。');
    try {
      await request('/work/number-inbox/batch-complete', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': button.dataset.csrf},
        body: JSON.stringify(result.receipt)
      });
    } catch (_) {
      status.textContent = `已写入 ${result.count} 个号码，网页状态尚未同步。Windows助手会自动重试，请勿重复批量添加。`;
      button.dataset.batchCommitted = 'true';
      return;
    }
    button.dataset.batchCommitted = 'true';
    status.textContent = `已写入 ${result.count} 个号码，已移至“已录号码”，保留5天。`;
    window.location.reload();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = button.dataset.batchCommitted === 'true';
    button.textContent = original;
  }
});
