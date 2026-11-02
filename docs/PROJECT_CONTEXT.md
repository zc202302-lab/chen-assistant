# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-11-02，Asia/Shanghai）

- 2026-11-02（Asia/Shanghai）用户纠正Windows提醒边界：客户端单独设置提醒方式、类别、时间和重复；网页后台仅控制客户端提醒总开关。继续开发及检查后合并部署授权有效。活动分支feat/desktop-local-reminder-rules，基线main4b31c1d；上一PR187已上线Web1.8.1及Windows0.5.20，均有公网核验证据。
- 本轮候选Web1.8.2、Windows0.5.21。后端专用接口reminder_policy仅返回enabled；Windows将本地规则与远程总开关合成执行，忽略旧服务器额外下发的模式/类别/时间。网页模式/时间不再覆盖客户端；本地关闭亦停止接收。手机/Web Push自身规则保留。
- 新本机设置窗口含启用、即时/定时、未加号码/待办及全局/客户来源、每天/指定星期、最多12个北京时间点；本机config.json持久化，旧号码时间迁移保留。号码连接码/Excel设置和SMS/久坐/Foxmail不动；用户仍需客户端检查更新安装新版。
- 本地策略/配置迁移持久化/静默及号码持久弹窗单测已通过，新增原生设置保存/取消和服务器总闸门验收待CI。依赖安装中，后端契约/架构尚待执行。未合并或部署本轮，不发送生产测试通知。首次上一main冻结更新在文件复制后停滞但原安装包重跑通过，根因未确定，不可声称解决该独立偶发问题。
- 核心Windows reminder_settings.py、config.py、reminder_policy.py、app.py、todo_panel.py，后端app/reminder_policy.py及提醒页边界说明。目录/workspace/scratch/6ecb72ebd96b/chen-assistant。唯一下一步：完成检查并推送PR，按最终head完整Web/Windows验收后合并，分别核验两端发布。

本文件是新聊天、新模型或中断后的固定入口。仓库是可核对的项目记忆；聊天记忆只作辅助。

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
