(() => {
  const links = [...document.querySelectorAll('.v03-foxmail-helper-download')];
  links.forEach(link => {
    link.href = '/static/chen_foxmail_bootstrap.ps1';
    link.setAttribute('download', 'chen_foxmail_bootstrap.ps1');
    link.textContent = '安装 Windows 助手（自动更新）';
    link.title = '只需安装一次；以后助手会自动更新并自动恢复运行';
  });

  const note = document.querySelector('.v03-mail-template-note span');
  if (note) {
    note.textContent = 'TXT与EXCEL文件名分别保存；Windows助手会把核对后的TXT放入文件剪贴板，在Foxmail中按 Ctrl+V 即可添加附件，不再打开文件夹。';
  }
})();
