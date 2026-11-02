# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-11-02，Asia/Shanghai）

- 更新时间：2026-11-02（Asia/Shanghai）。本轮开发及部署完成，无活动功能PR。PR #189已squash合并，main功能提交f3b932c0e4d1377274501b6a6222b77738ceefb8；最终受检head1423215bda799a09ee61ad132e5f4076fe72a177。两者tree均为c77d1cc75fa0161fd13cbb9b230e56bad67ac3ea，源码一致。
- 已上线Web1.8.3、Windows0.5.22：Windows勾选框改DPI自适应圆角蓝色对勾，保留ttk原生绑定和布尔变量；提醒窗口白卡、间距/星期选择及保存按钮优化。网页提醒方式/类别/时间/循环明确用于手机，新增持久化手机接收独立开关，关闭取消未发送推送及测试；不改变Windows总开关。Windows规则继续在本机设置，网页通知总开关仍可暂停两端。
- 完整验收发现号码管理页读快照后清理写入与后台提醒并发可触发SQLITE_BUSY_SNAPSHOT/500，已将该页事务提前BEGIN IMMEDIATE；新增待处理/设置两视图并发回归，旧实现确定复现database is locked，修复后通过。未改变号码数据、清理规则或更新器。
- 最终PR Web完整CI41400606688 success；Windows41400606687的源码、EXE、原生界面、真实更新回滚/Excel锁全部success；稳定性41400606648、隔离41400606643、Foxmail41400606647均success。main完整CI41402351041的validate125136717838、生产稳定性125142086984及deploy125142226812均success；main独立稳定性41402351141、语法41402350950、Foxmail41402350915成功。
- 实际公网：PWA41402351429/job125136718509返回ONLINE VERIFIED v1.8.3，版本、精确资源和鉴权/找回及域名边界核验通过。Windows构建发布41402350948全部success（publish125138259575）；公网41402943929/job125138538239返回ONLINE VERIFIED v0.5.22：71709786 bytes，SHA256 c41f68fb4ec5503e7b2a1971a4bebecb89d0da47b5ca28e780feba2ede6198d2，完整EXE与release清单一致。不据此推断生产精确backend SHA。
- 实际安装和真机业务到达仍待用户反馈；未向生产发送测试通知或改写客户数据。旧冻结更新偶发停滞根因未定，本轮未改更新器，不声称修复该独立问题。本地浏览器安装下载受限，浏览器验收由上述完整CI提供；本地号码批量及并发契约、架构治理通过。
- 核心：Windows ui_styles.py/app.py/reminder_settings.py及原生验收脚本；app/reminder_policy.py、reminders.py、提醒模板/JS、v162_number_inbox.py及契约。原工作目录/workspace/scratch/6ecb72ebd96b/chen-assistant；本次连接器提交为远端权威，本地HEAD仍为旧映射，续用须先同步远端，勿重推旧本地history。分支feat/windows-checkbox-polish已合并，仅供历史追溯；云电脑#128及其他历史PR不属于本轮。
- 唯一下一步：用户在Windows“检查更新”安装0.5.22，刷新网页确认手机独立开关；按实际界面和提醒反馈继续，无新需求时不新增功能。

本文件是新聊天、新模型或中断后的固定入口。详细证据见docs/AI_HANDOFF.md。

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
