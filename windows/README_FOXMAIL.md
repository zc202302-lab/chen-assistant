# 晨的助手：Windows Foxmail 本地桥接

## 作用

晨的助手网站运行在阿里云 Linux，网页本身不能直接启动 Windows 桌面程序。这个本地桥接只监听本机 `127.0.0.1:18763`，用于接收网页已经生成好的 `.eml` 草稿并交给 Windows 打开。

邮件主题、正文仍保存在晨的助手的客户资料中；每个客户一套，长期使用。正文允许为空。本月缴费 TXT 会作为附件自动放入 `.eml`。

## 安装

1. 把 `foxmail_bridge.ps1` 和 `install_foxmail_bridge.ps1` 放在同一个文件夹。
2. 右键 PowerShell，或在该文件夹打开 PowerShell。
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_foxmail_bridge.ps1
```

4. 安装完成后，桥接文件会复制到：

```text
%LOCALAPPDATA%\ChenAssistant\foxmail_bridge.ps1
```

5. 登录 Windows 时会自动启动。

## Foxmail 设置

请确保 Windows 的 `.eml` 文件默认使用 Foxmail 打开。网页调用本地助手后，Windows 会打开生成的 `.eml`；如果 `.eml` 默认关联的是 Foxmail，就会直接进入 Foxmail。

## 网页行为

- 检测到本地助手：按钮显示“调用Foxmail”，点击后直接打开本地邮件草稿。
- 未检测到本地助手：自动回退为下载 `.eml`，不会阻塞缴费工作。

## 安全边界

- 只监听 `127.0.0.1`，不接受局域网或公网连接。
- 只接受来自 `ziboxiaozhushou.cn` 及其子域名，以及 localhost 的网页请求。
- 邮件草稿临时保存在：

```text
%LOCALAPPDATA%\ChenAssistant\FoxmailDrafts
```

- 自动清理 7 天以前的临时 `.eml`。
