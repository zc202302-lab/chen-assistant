# 晨的小助手 · 当前架构

本文件描述当前高层架构。精确版本、分支和部署状态以 AI_HANDOFF 与 GitHub 实际状态为准。

## Web 主应用

- 技术形态：FastAPI / Starlette + SQLite + Jinja 模板 + 原生 JavaScript / CSS。
- 生产运行由 systemd 管理。
- 生产目录历史约定为 `/opt/chen-assistant`，部署入口为 `deploy.sh`；部署前必须再次以当前仓库与生产实际状态核验。
- 主要业务域包括客户管理、缴费、客户资料、工作资料、导入等。

## Windows 助手

`win-assistants` 是 Windows 端统一宿主和发布单元。

当前已整合的能力包括：

- 短信相关能力
- Foxmail 相关能力
- 久坐助手
- 统一托盘 / 主界面
- 统一检查更新

久坐模块以同一 EXE 的内置模式运行，不再依赖独立久坐仓库的本地 Python 启动路径。

## 发布关系

Web 与 Windows 助手必须分别判断“代码已合并”“已构建”“已发布”“生产已验证”。

- PR 合并不等于部署。
- main 更新不等于生产更新。
- Windows 构建成功不等于更新资产已发布。
- 只有生产实际部署/发布并验证后，才能更新生产基准。

## 动态基础设施

GitHub Actions Runner、构建服务器、部署节点均属于动态基础设施，不在本文件写死为永久事实。

涉及 CI、构建、部署或发布时，应重新检查：

- workflow 当前代码
- Runner 实际接单情况
- Runner 标签
- 最近 Actions 运行记录
- 构建与发布是否真正成功

具体当前状态写入 AI_HANDOFF。
