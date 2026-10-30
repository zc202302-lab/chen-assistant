# 晨的小助手 · 项目上下文入口

## 当前活动工作（2026-10-30，Asia/Shanghai）

- 2026-10-30（Asia/Shanghai）用户要求全部客户页面每个客户可手动拖动调整位置，网站升级v1.8.0。工作模式开发/检查通过后合并部署，沿用GitHub推送部署授权。活动分支feat/customer-card-order，基线main2e74b1d（PR185），现网基准1.7.36。无须处理历史Open PR。
- 候选已实现：每张客户卡片独立拖动手柄，桌面两列/手机单列移动，边缘自动滚动，方向键调整；原卡片仍是进入客户详情的链接。排序保存在既有app_meta，不新增schema；筛选子集只替换这些客户在全局排序中的位置，隐藏客户位置不变；保存失败恢复原序，Esc/取消不保存，多窗口陈旧版本409提示刷新。新客户追加到已保存顺序末尾，删除客户自动剔除。
- 新增POST /customers/order，登录/CSRF校验、ID类型/重复/未知客户校验，BEGIN IMMEDIATE保证版本比较及写入原子；两份路由清单已登记。JS/CSS沿用app.js和responsive-polish-v161.css，资源参数1800，config/deploy版本1.8.0。
- 本地排序契约（持久化/筛选/新建删除/并发409/CSRF/登录）、架构治理、路由注册、稳定性、JS语法及diff检查通过。新增真实鼠标和触摸拖动浏览器验收、刷新保持、键盘、取消、失败回滚、详情跳转及两种宽度截图，CI待执行；本地无可用Chromium，不冒称浏览器验收已通过。
- 上轮PR185完整PR CI、main40984881284和实际公网PWA40984881267均success，1.7.36已上线；旧main交接未同步，本轮已校正。短信静默转发保持用户已成功配置，不改权限/令牌。
- 核心app/customer_order.py、v02_routes.py、routing.py、customers.html、app.js、responsive-polish-v161.css，测试customer_order_contract/acceptance。依赖/tmp/chen-order-venv。唯一下一步：推送并建立PR，核对最终head完整CI及拖动截图，通过后合并部署并公网核验1.8.0。

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
