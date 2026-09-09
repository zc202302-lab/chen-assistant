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
    note.textContent = '邮件主题、正文和TXT附件文件名长期绑定当前客户；Windows助手安装一次后自动更新，并在意外退出时自动恢复运行。';
  }
})();
