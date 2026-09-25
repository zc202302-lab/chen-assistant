# win-assistants

`win-assistants` 是“晨的小助手”的统一 Windows 客户端。目标是让 Windows 登录时只启动一个入口，再由它统一管理：

- 短信助手
- 久坐助手
- “晨的小助手”本地连接（当前为 Foxmail/TXT 桥接）

## 当前阶段：v0.4.1 统一托盘启动与自更新

第一阶段优先保护已经稳定的功能，不重写久坐识别和 Foxmail 交接逻辑。`win-assistants` 负责：

- 一个统一状态窗口；
- 一个统一托盘图标和单实例保护；
- 一个开机启动入口；启用后使用 `--background` 静默启动并直接进入系统托盘；
- 各模块启停与延迟启动；
- 自动发现常见安装位置，也允许手动选择程序；
- 显式“接管旧工具的开机启动”，只移除已知旧启动项，不删除程序和设置。
- 短信验证码接收已迁入统一进程，不再启动独立短信 EXE。
- Foxmail 本地桥接已迁入统一进程，不再依赖独立 PowerShell watchdog。
- 主窗口和托盘都提供“检查更新”；更新包完成 SHA-256 / 大小 / Windows EXE 校验后原位替换，随后自动以 `--background` 重启并恢复托盘运行。
- 桥接继续只监听 `127.0.0.1:18763`，只接受指定站点与本机来源，并在打开草稿前后校验 TXT SHA256。
- 系统只把 TXT 放入 Windows 文件剪贴板，仍由用户在 Foxmail 按 `Ctrl+V` 并手动发送；程序绝不自动发送邮件。
- 首次运行自动读取 `%APPDATA%\iPhoneSmsBridgeNoServer\config.json`，并通过当前 Windows 用户解密旧令牌后重新用 DPAPI 保存。

久坐检测继续保持成熟独立代码，由 `win-assistants` 展示状态并提供设置/更新入口；短信与 Foxmail 旧版文件和设置均不删除，仍可回退。

## 运行

```powershell
cd windows\win-assistants
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe main.py
```

首次打开后配置短信模块并检查久坐助手路径。勾选“随 Windows 登录静默启动（直接进入托盘）”后，Windows 登录时不会弹主窗口。确认功能正常后再点击“接管旧工具的开机启动”；该操作会移除已知旧入口并停止旧 Foxmail bridge/watchdog，不删除旧程序或设置。

## 数据位置

统一壳配置保存在：

```text
%APPDATA%\win-assistants\config.json
```

久坐助手原有配置目录暂不迁移。短信助手只读取旧配置做一次迁移；Foxmail 旧脚本继续保留作回退，两者都不会被删除。

## 开发验证

```powershell
py -m compileall main.py win_assistants tests
py -m unittest discover -s tests -v
```

## 生成 EXE

在 Windows PowerShell 中运行：

```powershell
.\build.ps1
```

产物为 `dist\win-assistants.exe`。拉取请求会先运行平台无关测试，再通过 Wine 中的官方 Windows Python 运行同一组测试并生成 PE 格式 EXE。Wine 构建用于绕过当前 GitHub-hosted Windows runner 的 0-step 基础设施故障，不替代最终 Windows 实机验收。

## 后续迁移顺序

1. 在真实 Windows + Foxmail 环境验收内置桥接和文件剪贴板交接。
2. 将久坐助手作为内置模块加载，保留 v2.8.0 当前人体存在检测和强制休息状态机。
3. 最后停用其余独立启动入口，发布单一安装包与统一更新器。
