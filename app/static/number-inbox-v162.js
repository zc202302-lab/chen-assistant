document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-copy-value]');
  if (!target) return;
  const value = target.getAttribute('data-copy-value') || '';
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    const original = target.textContent;
    target.textContent = original + '  ✓';
    window.setTimeout(() => { target.textContent = original; }, 900);
  } catch (_) {
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
    if (health.batch_version !== 1) throw new Error('请先升级Windows助手后重试。');
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
    status.textContent = `已写入 ${result.count} 个号码：${result.path}。已保存上一次备份；号码仍保留在未加列表中。`;
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
});
