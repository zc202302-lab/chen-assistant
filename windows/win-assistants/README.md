# win-assistants

`win-assistants` 是“晨的小助手”的统一 Windows 客户端。

## 当前阶段：v0.5.8 四模块统一内置

v0.5.0 将原先独立运行的久坐守护成熟代码迁入 `win-assistants`。现在一个发布 EXE 统一包含：

- 短信助手：iPhone 短信验证码接收、提取与复制；
- 久坐助手：RTSP 摄像头人体存在检测、1～5 个检测区域、久坐状态机与强制休息；
- Foxmail / 缴费本地桥接：继续监听 `127.0.0.1:18763`，保持 TXT 校验、文件剪贴板与人工发送边界；
- 号码提醒：通过独立 Bearer 连接码读取待处理队列；新号码即时弹出独立提醒窗，可直接“已完成”同步 Web 状态；窗口可关闭，并按最多 5 个自定义时间点再次提醒未完成号码。

迁移原则是保留成熟业务规则，不重新设计久坐识别和 Foxmail 缴费交接。久坐核心直接来自 `chen-sit-guard` 当前 main，并保留原有 `%APPDATA%\久坐提醒` 设置、RTSP 密码、统计和状态文件，因此升级后不需要重新配置摄像头。

## 顶部导航

客户端采用短信、久坐、缴费连接、号码提醒、设置五个顶部标签，默认短信。模块启停、连接配置、开机启动、旧工具接管与统一检查更新位于设置页。切换页面不停止后台模块。

## 统一生命周期

- Windows 登录只需要启动 `win-assistants --background`；
- 主程序负责统一托盘、单实例、模块启停和更新；
- 久坐运行时由同一个 `win-assistants.exe` 以内部 `--sedentary --embedded --startup` 模式启动，不再依赖 `D:\Tools\chen-sit-guard\main.py`；
- 内置久坐模式不再创建第二个托盘图标，也不再维护独立 Git 更新入口；
- “检查更新”一次更新短信、久坐、Foxmail、号码提醒四部分；
- “接管旧工具的开机启动”仍只移除已知旧启动项，不删除旧程序、设置或数据，便于回退。

## 安全与业务边界

- 摄像头视频只在本机处理，不上传公网；
- RTSP 密码继续使用 Windows DPAPI 保存；
- Foxmail 桥接只接受允许站点/本机来源，并校验 TXT SHA-256；
- 程序只把 TXT 放入 Windows 文件剪贴板，仍由用户在 Foxmail 中粘贴并人工发送，绝不自动发送邮件；
- Foxmail 与“晨的小助手”缴费模块既有业务协议保持不变。

## 数据位置

```text
%APPDATA%\win-assistants\config.json
%APPDATA%\久坐提醒\settings.json
%APPDATA%\久坐提醒\daily-stats.json
```

短信旧配置仍支持首次迁移；Foxmail 旧脚本与原 `chen-sit-guard` 文件不会自动删除。

## 本地运行

```powershell
cd windows\win-assistants
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\pythonw.exe main.py
```

## 开发验证

```powershell
py -m compileall main.py win_assistants sedentary tests
py -m unittest discover -s tests -v
```

## 生成 EXE

```powershell
.\build.ps1
```

产物为 `dist\win-assistants.exe`。PR 会先运行平台无关测试，再在 self-hosted Linux Runner 上通过 Wine + 官方 Windows Python 构建并 smoke test Windows PE。最终发布仍需要 Windows 实机验收摄像头、Foxmail 和开机托盘行为。

v0.5.8 的正式发布仍以 `main` / merged-PR cross-build 实际写入 `win-assistants-release/update.json` 为准；只有 manifest 与 EXE 发布成功后，客户端唯一“检查更新”才会看到本版本。号码提醒连接码在 Web 的“工作 → 号码收集 → Windows 提醒连接”中获取，连接码使用 Windows 用户级保护保存。


<!-- v0.5.0 release trigger after merged-PR publishing fix -->
