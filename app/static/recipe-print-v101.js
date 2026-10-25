(() => {
  const sheet = document.querySelector('.recipe-print-sheet');
  const fit = () => {
    if (!sheet) return;
    sheet.style.zoom = '1';
    requestAnimationFrame(() => {
      const targetHeight = 1040;
      const height = Math.max(sheet.scrollHeight, 1);
      const scale = Math.max(.55, Math.min(1, targetHeight / height));
      sheet.style.zoom = String(scale);
    });
  };
  window.addEventListener('load', fit);
  window.addEventListener('beforeprint', fit);
  const panel = document.querySelector('[data-recipe-pdf-panel]');
  const status = document.querySelector('[data-recipe-pdf-status]');
  const prepare = document.querySelector('[data-recipe-pdf-prepare]');
  const share = document.querySelector('[data-recipe-pdf-share]');
  const download = document.querySelector('[data-recipe-pdf-download]');
  let pdfFile;
  let loading = false;
  const preparePdf = async () => {
    if (loading || pdfFile) return;
    loading = true;
    prepare.disabled = true;
    status.textContent = '正在生成 PDF…';
    try {
      const response = await fetch(download.href, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || !response.headers.get('Content-Type')?.startsWith('application/pdf')) {
        throw new Error('PDF unavailable');
      }
      const blob = await response.blob();
      pdfFile = new File([blob], '菜谱.pdf', {type: 'application/pdf'});
      const canShare = navigator.share && navigator.canShare?.({files: [pdfFile]});
      share.hidden = !canShare;
      prepare.hidden = true;
      status.textContent = canShare ? 'PDF 已准备好。点击“打开打印菜单”，再选择“打印”。' :
        'PDF 已准备好。请点“保存 PDF”，从“文件”打开后点分享 → 打印。';
    } catch {
      pdfFile = undefined;
      status.textContent = 'PDF 生成失败，请检查网络或重新登录后重试。也可直接点“保存 PDF”。';
    } finally {
      loading = false;
      prepare.disabled = false;
    }
  };
  prepare?.addEventListener('click', preparePdf);
  share?.addEventListener('click', () => {
    if (!pdfFile) return;
    // File preparation happens before this click, preserving iOS user activation.
    try {
      navigator.share({files: [pdfFile]}).catch(error => {
        status.textContent = error.name === 'AbortError' ? '已取消，可再次打开打印菜单。' :
          '系统菜单暂不可用。请保存 PDF 后从“文件”中打印。';
      });
    } catch {
      status.textContent = '系统菜单暂不可用。请保存 PDF 后从“文件”中打印。';
    }
  });
  document.querySelector('[data-recipe-pdf-close]')?.addEventListener('click', () => {
    panel.hidden = true;
  });
  document.querySelector('[data-recipe-print]')?.addEventListener('click', () => {
    // Home Screen iOS web apps can silently ignore window.print(). Export a
    // real PDF and use file sharing, which has its own native system menu.
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    const standalone = navigator.standalone === true || window.matchMedia('(display-mode: standalone)').matches;
    if (ios && standalone && panel) {
      panel.hidden = false;
      panel.scrollIntoView({block: 'nearest'});
      preparePdf();
      return;
    }
    fit();
    // Keep printing in the click gesture: Safari may ignore deferred print calls.
    window.print();
  });
})();
