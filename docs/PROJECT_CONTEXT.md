# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-11-02，Asia/Shanghai）

- 2026-11-02（Asia/Shanghai）用户要求重排提醒设置页，使页面简洁、清晰、逻辑性强。继续开发及检查后合并发布授权有效。活动分支feat/reminder-settings-layout，基线main d5713e4；线上基准Web1.8.3、Windows0.5.22。
- 候选Web1.8.4，仅调整网页提醒设置布局和文案：总开关→手机规则（方式/内容/定时循环合并）→当前设备通知→默认折叠高级设置（设备登记/测试通知）。设备显示登记时间及最近提交推送时间，说明登记不等于实体设备，不含Windows。保留既有接口、开关存储和通知边界；不修改Windows客户端、发送策略或客户数据。
- 本地提醒策略契约、架构治理、JS语法、编译/diff检查通过；已有浏览器回归扩展验证分组层级、高级默认折叠、设备启停、时间信息及桌面/手机截图。本地1440桌面/390手机真实浏览器全部通过，截图已查看几何，无横向溢出；本地无中文字体，未声称本地中文字体视觉验收。完整CI及公网部署待核验，未宣称上线。
- 核心app/templates/reminders.html、app/static/reminders.css/js、base.html及tests/reminders_settings_acceptance.py；目录/workspace/scratch/5c7c7f3fea41/chen-assistant-layout。唯一下一步：完成浏览器验证并推送PR，最终head完整检查通过后合并并核验Web1.8.4公网发布。

详细证据及历史见docs/AI_HANDOFF.md。

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
