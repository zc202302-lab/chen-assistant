(() => {
  'use strict';

  const root = document.querySelector('[data-customer-tabs]');
  const workbench = document.querySelector('[data-payment-workbench]');
  if (!root || !workbench || !window.showDirectoryPicker) return;

  const customerId = Number(root.dataset.customerId || 0);
  const csrf = workbench.dataset.csrf || '';
  const DB_NAME = 'chen-payment-bridge';
  const STORE = 'handles';
  let bridgeHandle = null;

  const openDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  const storedHandle = async () => {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const request = db.transaction(STORE).objectStore(STORE).get('bridge');
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  };

  const saveHandle = async handle => {
    const db = await openDb();
    await new Promise((resolve, reject) => {
      const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(handle, 'bridge');
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  };

  const ensureBridge = async () => {
    let handle = bridgeHandle;
    if (handle) {
      let permission = await handle.queryPermission({mode: 'readwrite'});
      if (permission !== 'granted') permission = await handle.requestPermission({mode: 'readwrite'});
      if (permission === 'granted') return bridgeHandle = handle;
    }
    handle = await showDirectoryPicker({id: 'chen-payment-bridge', mode: 'readwrite'});
    await saveHandle(handle);
    bridgeHandle = handle;
    return handle;
  };

  storedHandle().then(handle => { bridgeHandle = handle; }).catch(() => {});

  const writeJson = async (directory, filename, value) => {
    const file = await directory.getFileHandle(filename, {create: true});
    const stream = await file.createWritable();
    await stream.write(JSON.stringify(value, null, 2));
    await stream.close();
  };

  const readResult = async (directory, filename) => {
    try {
      const handle = await directory.getFileHandle(filename);
      return JSON.parse(await (await handle.getFile()).text());
    } catch (error) {
      if (error?.name === 'NotFoundError') return null;
      throw error;
    }
  };

  const waitResult = async (directory, filename, timeoutMs = 30000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const result = await readResult(directory, filename);
      if (result) return result;
      await new Promise(resolve => setTimeout(resolve, 750));
    }
    throw new Error('30秒内没有收到云电脑结果，请确认查询代理正在运行');
  };

  const queryValue = row => {
    const account = row.querySelector('[data-kind="账号"]')?.dataset.copy?.trim();
    const number = row.querySelector('[data-kind="号码"]')?.dataset.copy?.trim();
    return account || number || '';
  };

  const applyResult = async (serviceId, task, result) => {
    if (!result.ok) throw new Error(result.error || '业务系统查询失败');
    if (String(result.task_id) !== task.task_id || Number(result.service_id) !== serviceId) {
      throw new Error('结果与当前缴费行不一致，已拒绝回填');
    }
    const body = new URLSearchParams({
      csrf,
      amount: String(result.amount),
      task_id: task.task_id,
      query_value: task.query_value,
    });
    const response = await fetch(`/services/${serviceId}/payment-auto-query-result`, {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
      body,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.detail || data.error || '自动回填失败');
    return data;
  };

  const run = async (button, row) => {
    if (button.disabled) return;
    const serviceId = Number(row.dataset.serviceId || 0);
    const value = queryValue(row);
    if (!serviceId || !/^\d{6,24}$/.test(value)) {
      alert('该行没有可用于查询的号码或账号');
      return;
    }
    button.disabled = true;
    button.textContent = '连接…';
    let results;
    let filename;
    try {
      const bridge = await ensureBridge();
      const requests = await bridge.getDirectoryHandle('requests', {create: true});
      results = await bridge.getDirectoryHandle('results', {create: true});
      const taskId = `${Date.now()}_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`;
      filename = `${taskId}.json`;
      const task = {
        version: 1,
        task_id: taskId,
        customer_id: customerId,
        service_id: serviceId,
        query_value: value,
        created_at: new Date().toISOString(),
      };
      await writeJson(requests, filename, task);
      button.textContent = '查询中…';
      const result = await waitResult(results, filename);
      button.textContent = '回填中…';
      const data = await applyResult(serviceId, task, result);
      await results.removeEntry(filename).catch(() => {});
      button.textContent = `已核对 ¥${data.display_amount}`;
      setTimeout(() => location.reload(), 700);
    } catch (error) {
      button.textContent = '重试';
      button.title = error.message || '自动查询失败';
      alert(`自动查询失败：${error.message || '未知错误'}`);
      button.disabled = false;
    }
  };

  document.querySelectorAll('[data-payment-row]').forEach(row => {
    const amount = row.querySelector('.dense-amount');
    if (!amount || amount.querySelector('[data-auto-payment-query]')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost small auto-payment-query';
    button.dataset.autoPaymentQuery = '1';
    button.textContent = '查询';
    button.title = '从业务支撑系统自动查询缴费金额';
    button.addEventListener('click', () => run(button, row));
    amount.appendChild(button);
  });
})();
