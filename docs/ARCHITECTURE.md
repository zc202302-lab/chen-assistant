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


## 本轮整理后的代码边界（2026-10-05）

- app/main.py：应用生命周期、提醒worker及HTTP响应策略。
- app/routing.py：唯一的路由注册/优先级入口、实际处理函数自检、运行时清单；历史模块的导入顺序保留，因为部分导入会安装兼容补丁。
- docs/RUNTIME_ROUTES.json：整理前实际生效的186条路由基线；tests/routing_registry_contract.py核对完整顺序、方法、处理函数及客户静态路径边界。
- app.state.route_source_groups：保留全部274条来源路由，含88条被优先级替代的来源，用于治理工具；不能把被替代的路由等同于整个模块无引用。
- 客户整库Excel导出显式禁止文本转公式/网址；tests/customer_export_text_contract.py验证真实导出文件。

云电脑独立Draft PR #128中的边界：

- member_add_agent.py：CLI、批次调度、结果和归档。
- member_models.py：任务/异常类型。
- member_workbook.py：有限大小的XLSX解析及永久空表格式。
- member_browser.py：CDP连接、frame/target和已知刷新弹窗。
- member_page.py：页面探针和控件脚本。
- member_flow.py：一条成员操作与集团身份、提交后核对。
- relay_store.py：永久中转文件的短时句柄租约及比较清空；Windows锁拒绝写入/替换，POSIX仅协作锁，不宣称跨同步副本事务。
- offline_update.py/sync_updates.ps1：更新链独立，仍只替换允许的EXE与版本文件。

本轮未删除历史业务实现、未更改URL/数据库结构/页面导航，也未改旧win-assistants久坐模块。后续逐业务域收敛要先查直接函数引用、模板、JS、测试及发布依赖，再删除确无引用的实现。
