# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-11-02，Asia/Shanghai）

- 2026-11-02（Asia/Shanghai）用户要求继续完善提醒设置，将网站/手机/电脑客户端固定概念写进项目，补充禁止“本机”等模糊指代。继续开发及检查后发布授权有效。活动分支feat/two-reminder-destinations，基线main fad4be7；线上基准Web1.8.4、Windows0.5.22。
- 固定术语见docs/TERMINOLOGY.md，AGENTS及PRODUCT_REQUIREMENTS同步引用：网站=普通浏览器管理界面；手机=手机桌面图标应用；电脑/电脑客户端=Windows助手。只有手机与电脑客户端接收提醒，网站不接收。未来需求和界面明确写平台名。
- 候选Web1.8.5：总开关下只有手机、电脑两个接收区域，手机连接按钮纳入手机区域，只在手机桌面应用显示；网站不请求通知权限或注册订阅。新增持久化电脑独立开关，与总开关共同形成现有enabled闸门；电脑客户端规则及协议不改，Windows保持0.5.22。旧桌面浏览器登记停用并跳过待发队列，保留记录及手机配置，旧界面也不能重新启用该登记。
- 验证进行中：新增两端独立/重启保留/旧网站登记退出回归，并将浏览器验收明确拆分网站与手机；保留已有提醒交互断言。JS语法/diff检查通过；依赖环境恢复中，契约/浏览器/CI/公网尚未验证。未合并发布，不写入生产业务或发送测试通知。
- 核心app/reminders.py、reminder_policy.py、提醒模板及JS/CSS、tests/reminders_policy_contract.py、reminders_settings_acceptance.py。目录/workspace/scratch/5c7c7f3fea41/chen-assistant-reminder-ends。唯一下一步：完成隔离契约和网站/手机浏览器验收，推送PR，最终head完整检查通过后合并并核验Web1.8.5。

平台词义长期以docs/TERMINOLOGY.md为准；详细证据及历史见docs/AI_HANDOFF.md。

## 新聊天接管顺序

1. 读取本文件与默认分支 docs/AI_HANDOFF.md 顶部的唯一当前快照。
2. 首先检查工作模式：讨论中／暂停开发时，只讨论和读取；用户明确恢复开发后再修改功能代码。用户明确授权的交接文档维护可以继续。
3. 实时读取 main 最新提交、Open/Draft PR；按快照中的明确分支读取该分支的 AI_HANDOFF 和实际代码。不要把所有历史 Open PR 都当作当前任务。
4. 核对快照记录的功能提交、当前 head、CI、安装版本、业务结果。出现差异先说明，未知写未知，不让用户重讲整个历史。
5. 按需要读取 PRODUCT_REQUIREMENTS.md、ARCHITECTURE.md、DEVELOPMENT_RULES.md、DECISIONS.md。
6. 用简短中文说明：已确认进度、未解决问题、当前是否允许开发、下一步。确认自己接对位置后再按当前授权推进。

## 权威性与证据

- 用户最新要求决定工作模式和范围；代码存在不等于获得继续开发的授权。
- 功能事实以明确进行中的分支实际代码、当前 main、PR/Actions 为准。
- 运行事实以实际安装版本、用户截图/结果、生产验证为准。
- 交接快照解释决定与进度；历史记录不能覆盖当前快照。
- 代码已提交、CI通过、安装成功、业务端到端成功分别记录，不能相互推断。
- 自己的文档提交SHA不写死在同一次提交中；记录最后功能提交，当前head由GitHub实时查询。

## 固定职责

- AI_HANDOFF.md 顶部：唯一当前快照；旧阶段记录放在历史区。
- DEVELOPMENT_RULES.md：何时、如何提交交接以及检查要求。
- PRODUCT_REQUIREMENTS.md / ARCHITECTURE.md / DECISIONS.md：长期规则、架构与决策。
- main 的快照必须能指向未合并的活动分支；详细工作状态在活动分支维护，默认分支至少同步入口、工作模式和下一步。不要为了更新交接而合并功能PR。

## 新聊天提示词

> 接管 chen-assistant（zc202302-lab/chen-assistant）。先读取 docs/PROJECT_CONTEXT.md、docs/AI_HANDOFF.md 和明确进行中的分支及 PR，核对代码、CI、安装和业务验证状态；按交接中的工作模式继续，暂停开发时先讨论。保留现有功能，完成阶段后更新交接。

交接不是自动聊天同步服务。执行任务的助手需要遵守仓库规则，把检查点真正提交到GitHub；仅在聊天中说“已记录”不算持久交接。
