# win-assistants

`win-assistants` 是“晨的小助手”的统一 Windows 客户端。目标是让 Windows 登录时只启动一个入口，再由它统一管理：

- 短信助手
- 久坐助手
- “晨的小助手”本地连接（当前为 Foxmail/TXT 桥接）

## 当前阶段：v0.2.0 短信模块内置

第一阶段优先保护已经稳定的功能，不重写久坐识别和 Foxmail 交接逻辑。`win-assistants` 负责：

- 一个统一状态窗口；
- 一个统一托盘图标和单实例保护；
- 一个开机启动入口；
- 各模块启停与延迟启动；
- 自动发现常见安装位置，也允许手动选择程序；
- 显式“接管旧工具的开机启动”，只移除已知旧启动项，不删除程序和设置。
- 短信验证码接收已迁入统一进程，不再启动独立短信 EXE。
- 首次运行自动读取 `%APPDATA%\iPhoneSmsBridgeNoServer\config.json`，并通过当前 Windows 用户解密旧令牌后重新用 DPAPI 保存。

此阶段久坐检测和本地桥接仍是独立子进程。后续再逐步迁入同一进程；迁移期间原独立版始终可回退。

## 运行

```powershell
cd windows\win-assistants
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe main.py
```

首次打开后检查三个模块的程序路径。确认都能从“立即启动”正常运行，再点击“接管旧工具的开机启动”。

## 数据位置

统一壳配置保存在：

```text
%APPDATA%\win-assistants\config.json
```

久坐助手和晨的小助手原有配置目录暂不迁移。短信助手只读取旧配置做一次迁移，不修改或删除旧文件。

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

产物为 `dist\win-assistants.exe`。拉取请求也会在 Windows runner 上验证并生成同名构建产物。

## 后续迁移顺序

1. 将 Foxmail 本地桥接迁入统一进程，保留仅监听 `127.0.0.1`、来源校验与 TXT SHA256 校验。
2. 将久坐助手作为内置模块加载，保留 v2.8.0 当前人体存在检测和强制休息状态机。
3. 最后停用其余独立启动入口，发布单一安装包与统一更新器。
