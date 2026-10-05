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

(() => {
  'use strict';

  const button = document.querySelector('[data-group-batch-export]');
  const status = document.getElementById('group-batch-export-status');
  if (!button || !status) return;

  const DB_NAME = 'chen-number-inbox-export-v1';
  const STORE = 'shared-folder';
  const FILE_NAME = '号码加集团.xlsx';
  let directoryHandle = null;

  const openDb = () => new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  const loadDirectory = async () => {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const request = db.transaction(STORE).objectStore(STORE).get('directory');
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
    });
  };

  const saveDirectory = async handle => {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(handle, 'directory');
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  };

  loadDirectory().then(handle => { directoryHandle = handle; }).catch(() => {});

  const createWorkbookFile = async handlePromise => {
    button.disabled = true;
    status.textContent = '正在创建批量任务文件…';
    try {
      const directory = await handlePromise;
      let permission = await directory.queryPermission({mode: 'readwrite'});
      if (permission !== 'granted') permission = await directory.requestPermission({mode: 'readwrite'});
      if (permission !== 'granted') throw new Error('没有获得共享文件夹写入权限');
      directoryHandle = directory;
      await saveDirectory(directory);

      try {
        const existing = await (await directory.getFileHandle(FILE_NAME)).getFile();
        const tail = new TextDecoder().decode(await existing.slice(-19).arrayBuffer());
        if (!tail.endsWith('CHEN_EMPTY_RELAY_V1')) {
          throw new Error('中转文件还有待处理内容，请等云电脑助手清空后再导出。');
        }
      } catch (error) {
        if (error?.name !== 'NotFoundError') throw error;
      }

      const response = await fetch('/work/number-inbox/export-group-batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'},
        body: new URLSearchParams({csrf: button.dataset.csrf || ''}),
      });
      if (!response.ok) {
        let message = '生成任务文件失败';
        try {
          const payload = await response.json();
          message = payload.detail || payload.error || message;
        } catch (_) {}
        throw new Error(message);
      }

      const file = await directory.getFileHandle(FILE_NAME, {create: true});
      const writable = await file.createWritable();
      try {
        await writable.write(await response.blob());
        await writable.close();
      } catch (error) {
        await writable.abort().catch(() => {});
        throw error;
      }
      const count = Number(response.headers.get('X-Number-Count') || 0);
      status.textContent = `已生成 ${FILE_NAME}，共 ${count} 个号码，等待云电脑助手读取。`;
    } catch (error) {
      status.textContent = error?.name === 'AbortError'
        ? '已取消选择共享文件夹。'
        : (error.message || '生成批量任务文件失败');
    } finally {
      button.disabled = false;
    }
  };

  button.addEventListener('click', () => {
    if (!window.showDirectoryPicker) {
      status.textContent = '当前浏览器不支持选择共享文件夹，请使用最新版 Chrome 或 Edge。';
      return;
    }
    let handlePromise;
    try {
      // Invoke the picker or permission prompt in the original click gesture.
      handlePromise = directoryHandle
        ? directoryHandle.requestPermission({mode: 'readwrite'}).then(result => {
            if (result === 'granted') return directoryHandle;
            directoryHandle = null;
            throw new Error('共享文件夹权限已失效，请再次点击按钮重新选择共享文件夹。');
          })
        : window.showDirectoryPicker({id: 'chen-number-group-share', mode: 'readwrite'});
    } catch (error) {
      status.textContent = error.message || '无法打开共享文件夹选择窗口';
      return;
    }
    createWorkbookFile(handlePromise);
  });
})();

