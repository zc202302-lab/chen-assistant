# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-11-02，Asia/Shanghai）

- 2026-11-02（Asia/Shanghai）用户纠正Windows提醒边界：客户端单独设置方式、类别、时间和循环；网页仅控制客户端是否启动提醒。PR #188已squash合并，功能main b4aad19cf0d70923c45195ac1039b5df279a59ce，最终受检head064eb9da6deeffb5eebc88fc467aab969b85eaa9。继续开发/推送及检查后部署授权有效，当前仅部署核验。
- 候选Web1.8.2、Windows0.5.21：后端号码/待办专用接口只下发reminder_policy.enabled。Windows本机持久化即时/定时、未加号码/待办及全局/客户来源、最多12个北京时间点、每天/指定星期；本地暂停和网页总开关共同拦截提醒，忽略旧服务器多发的方式/类别/时间字段。网页明确独立边界，手机/Web Push自身规则保留。
- 新原生“本机提醒规则”窗口从号码连接设置及待办提醒设置进入；保留旧本地号码时间，config.json保存/重启恢复，不保存为网页配置。号码/待办按合成策略决策；专用令牌鉴权、客户摘要只读与全局任务编辑边界、SMS/久坐/Foxmail/Excel不变。用户实际安装版本与真机提醒未知，需电脑“检查更新”安装0.5.21。
- 最终PR Web完整CI41380142668（validate125068943137、production preflight125068943494）success；Windows41380142637源码/EXE/原生界面125068943223/真实冻结更新回滚及Excel锁125069944044全部success。模块隔离41380142673、稳定性41380142703、Foxmail41380142680均success。新增原生保存/取消、配置迁移持久化、旧服务字段隔离、服务器总开关拦截、两专用接口仅总开关契约通过；本地112个Windows单测（15项需GUI跳过）及后端/架构通过，GUI已由CI补足。
- main部署链41382044036、PWA公网41382044014、Windows构建发布41382043928仍待核验；不能把PR通过冒充实际公网新版。上次已核验线上基线Web1.8.1、Windows0.5.20。无生产测试通知或业务写入。本轮未改更新器；旧偶发冻结验收停滞根因未定，不能声称修复该独立问题。
- 核心Windows reminder_settings.py/config.py/reminder_policy.py/app.py/todo_panel.py，后端app/reminder_policy.py、提醒模板及tests。分支feat/desktop-local-reminder-rules保留部署交接（main入口指向此分支），目录/workspace/scratch/6ecb72ebd96b/chen-assistant。唯一下一步：核对Web1.8.2及Windows0.5.21公网版本/资源与完整EXE；main链完成后同步最终主分支交接。

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
