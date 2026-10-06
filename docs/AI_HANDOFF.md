# 晨的小助手 · AI 开发接力文档

## 当前交接快照（唯一当前状态）

- 更新时间：2026-10-06（Asia/Shanghai）。工作模式：开发中。用户新需求：全站输入框允许拖动选择部分文字，松开鼠标不能被自动全选覆盖。活动分支fix/preserve-input-text-selection（即将从本检查点建立），修复及浏览器回归待提交。
- 已定位全站app.js的延迟click全选与循环状态切换，以及v028.js、live-refresh-modules-v15.js的重复点击/焦点全选。保留首次普通单击与连续缴费录入的便利，拖选、后续点击、键盘选字使用原生行为。
- 上轮#132已完成，合并cf509e3844a7b3c552de136fc7cc4aeda4227b08；完整验收head dcc89366068983f4de7ea71c92b23980f68aaa21，validation37420879779/stability37420879714 success；生产验证37421656762 success。Web1.7.3，186条路由。当前新修复尚未部署。
- #128云电脑仍Draft，本轮不操作。核心范围app.js、v028.js、live-refresh-modules-v15.js及缓存版本/浏览器测试，保留原缴费与清单功能。
- 唯一下一步：提交选择交互修复，完成真实浏览器与完整CI后合并并验证生产。

---

## 历史记录（仅供追溯，不覆盖上方快照）

### 2026-10-06 #132完成快照（历史）


- 更新时间：2026-10-06（Asia/Shanghai）。本轮用户需求已完成：清单升级为网页Excel式表格，并全站审计清理纯说明性冗余文案；代码已合并，生产公网验证通过。PR #132已合并，功能合并提交 cf509e3844a7b3c552de136fc7cc4aeda4227b08；完整验收head dcc89366068983f4de7ea71c92b23980f68aaa21。文档提交不作为新功能，当前main SHA请实时查询。
- #132完整验证：validation [37420879779](https://github.com/zc202302-lab/chen-assistant/actions/runs/37420879779)、stability [37420879714](https://github.com/zc202302-lab/chen-assistant/actions/runs/37420879714) 均success。安全审计、清单/导入契约和真实浏览器、架构治理、原客户/缴费/资料/菜谱/提醒及桌面手机全量回归通过。用户明确删除的旧文案断言改为检查简洁展示与必要入口/字段，功能断言继续保留；旧页面同名定位精确化，异步保存等待实际导航，未删除或跳过测试。
- #132生产证据：[PWA公网验证 37421656762](https://github.com/zc202302-lab/chen-assistant/actions/runs/37421656762) / job112132129384 success，2026-10-06 14:04:54（Asia/Shanghai）返回 ONLINE VERIFIED v1.7.3。work-sheet.js、work-sheet.css及既有工作/清单/推送资产SHA256与本次源码一致，health、PWA manifest、根Service Worker scope和未登录提醒路由正常。部署切换期间首次404、第二次502，第三次完整验证通过；不存在持续失败。未读取生产git HEAD，不声称精确运行commit，也未在生产创建真实业务数据。
- 清单新建默认4个数据行、3列，标题与单元格直接编辑；增加行列、逐列筛选、清除筛选、Excel多格文本粘贴、拖动或键盘调整行高列宽，编辑后点击“保存表格”。大表每页100行，筛选覆盖全部记录；保留前导零与文本首尾空格。
- Excel导入归入“新建清单”菜单，清单首页为“我的清单 / 新建清单 / 已归档”。新建导入保留所选范围字体、填色、边框、对齐、数字格式、行列尺寸、内部空行与完整合并区域，导出真实XLSX恢复布局。向现有清单追加时跳过空行、不替换已有布局，保留重复校验、预览确认及数字精度/公式缓存限制。
- 数据兼容：继续使用既有字段和记录ID，关联客户、状态、备注、隐藏字段保留；整表事务保存检查清单与每条记录revision及完整行列快照，拒绝并发覆盖和部分写入，归档只读。原字段模板、记录详情和设置按需进入。没有新增URL，186条原路由保留，Web APP_VERSION仍1.7.3。
- 表格边界：支持上述编辑与常用Excel格式往返，公式读取Excel已保存结果；不运行宏，不提供公式计算引擎，图片、图表、条件格式不在此编辑器范围。导出公式样式文本为安全文本，不执行公式或URL。
- 核心代码：app/work_list_sheet.py（布局/事务保存/导出）、app/work_list_format.py（XLSX/XLS格式读取）、app/work_lists.py、app/work_list_excel.py、app/work_list_import.py、work_sheet_grid.html、work-sheet.js/css；新增tests/work_sheet_contract.py与tests/work_sheet_acceptance.py。
- 文案审计：检查原有全部63份HTML模板及46份静态JavaScript，21份文件删除或缩短产品背景、重复介绍及实现机制说明。必填、错误、状态、操作约束、安全边界和必要人工发送步骤保留。记录docs/SPREADSHEET_AND_COPY_AUDIT_2026-10-06.md；长期要求写入PRODUCT_REQUIREMENTS，分层原则继续适用于全站。
- 本轮前序交付继续保留：#129审阅修复/治理已合并并验证；#130清单分层已部署；#131工作首页紧凑正方形模块已合并部署，merge594718c55714576d88ba95ecfa5ab8f9f4dc1e17，公网验证37415137983成功。详细证据见历史区。
- 云电脑PR #128（feat/number-inbox-cloud-batch-export）仍为Draft，本轮未合并、未发布Windows包或操作真实云电脑业务。其余号码导出/云电脑改动仍需独立审阅与实机验收；不能借用#132网页验证声称云电脑已验收。手动单次更新、不注册Windows登录启动、本机E:\\ChenBridge与云电脑Y:\\ChenBridge等既定约束继续保留。
- 唯一下一步：本轮已完成，按用户下一项明确需求继续；如恢复云电脑工作，先独立检查#128实际head、CI及剩余实机验收，不直接合并历史Draft。


### 2026-10-06 清单改造前与实施检查点（历史）

- 更新时间：2026-10-06（Asia/Shanghai）；本轮新需求：清单网页Excel（默认4行3列、增行列、筛选、拖动行列尺寸、导入格式保留/导出）及全站冗余说明文案审计。活动分支feat/work-list-spreadsheet，实施中；用户要求/work客户管理等模块缩小、正方形并提升整体美观。工作首页改造#131已合并并部署，merge 594718c55714576d88ba95ecfa5ab8f9f4dc1e17，验收head d586cd5ef0a16c708f8a8bdea511f04cad4eeb34；#130清单分层已部署。
- #131验证：validation37414476957和stability37414476965均success；1450/768/390/320屏宽保持紧凑方形、内容无溢出、桌面三列/手机两列、三个入口跳转正常，原有功能全量回归通过。生产验证37415137983/job112111986996 success，公网work-architecture-v14.css与本次源码SHA256一致，health/PWA/清单/推送资源正常；未读取生产git HEAD。
- 本轮设计：工作首页三张紧凑方形入口，桌面三列、手机两列；蓝/绿/紫图标与简短说明，辅助入口轻量展示。样式限定work-launcher，不改客户/缴费数据或共享导航。
- 工作模式：清单分层已完成，PR #130合并提交a9fb5cb6f75fb992cf4c7fc7883b0698a911f1d9；验收head 0bdcb0761316abeb38be2373a1531e752442f49d。#129修复完成并已合并main；#128已同步同一修复，仍为Draft，未在本轮合并。未发布Windows安装包、安装或操作真实业务。
- #129合并提交：280ffe612d8e607c3b837502095ad13254b8720a；已验收修复head e905aee37c4298efb3c35cc163e7487159aab9c2。完整validation 37408544701和stability 37408544716均success；新增/work/customers桌面/手机内嵌搜索可见、名称/集团编码命中、键盘及点击导航真实浏览器验收success；原付款/导入/提醒/资料等回归通过。
- 修复：base.html在/work/customers加载v03.js，其他付款脚本继续按/customers加载，客户脚本顺序保持；架构契约覆盖精确路径、尾斜杠及其他页面边界。首页/资料/普通工作6脚本、客户管理首页7、生活8、客户37；29份CSS及43个被引用的历史模块受控保留。
- 主站治理已进入main：payments.py核心服务显式委托、项目模板适配、connection_scope及事务安全schema、schema启动阶段、routing登记/真实源码清单与架构CI门禁。186条原路由保留；APP_VERSION仍1.7.3。
- 云电脑活动分支feat/number-inbox-cloud-batch-export，PR #128；修复集成检查点8598397dbba1ac2a534e17f9eea0709d7a4c6b11。后续交接提交实时查询head，不把文档提交写成新功能。#128本轮CI需实时查询，不能借用#129结果声称云电脑全通过。
- #128此前云电脑验收功能提交5c3df6f81b45224414c3b79d4c1a6cb457d7f279：Windows 37407153901、validation 37407153889、stability 37407153940成功；Windows30项、PowerShell进程、两套EXE构建自检及协议2打包通过。仍需独立审阅剩余号码导出/云电脑改动及实机验收。
- 云电脑已实现逐行持久化、独占、中断不自动重办，Python唯一手动单次更新器及整体备份回滚；协议1旧安装需一次迁移，SHA256不是发布签名，同步副本不是分布式事务。E盘实机更新/恢复、集团DOM/分页/真实提交仍待验证。
- 保留主站/PWA/客户/缴费/旧久坐；云电脑离线、E盘安装；本机E:\\ChenBridge、云电脑Y:\\ChenBridge；永久号码加集团.xlsx无表头、A列5–20位数字、B列集团，只清空不删除。手动更新、不注册Windows登录启动、不长期开CMD。
- 生产：自动部署后公网验证37413519451/job112106993185成功，日志ONLINE VERIFIED v1.7.3；health、PWA、清单CSS及推送资产SHA256与本次源码一致。未读取生产git HEAD，不声称精确运行commit。
- #130验收：validation37412258653第二次success、stability37412258576success；清单桌面/手机、独立创建视图、编辑/字段/导入/归档恢复与既有客户/缴费全量回归通过。第一次付款搜索旧表头瞬时count断言失败，同提交原断言重跑通过；未弱化测试。
- 审阅及治理记录：docs/PR129_REVIEW_2026-10-06.md、docs/STRUCTURE_GOVERNANCE_2026-10-06.md；审阅P2已修复。三份旧孤立契约基线问题未删改弱化。代码、CI、部署、安装、真实业务分别记录。
- 页面长期原则已写入PRODUCT_REQUIREMENTS与AGENTS：功能分类→当前任务→具体操作；默认展示常用任务，完整表单及低频设置进入后展示。清单首页方向：我的清单为默认，新建清单/Excel导入/已归档各有明确入口；新建表单不常驻首页。页面已按最新需求调整为三个入口，Excel导入归入新建菜单；首页仅搜索和清单；新建表单在view=new独立视图，保留原创建/导入/归档/恢复能力。
- #132实现检查点：网页表格与文案审计完成，活动分支feat/work-list-spreadsheet；默认4行3列，表头/单元格编辑、增行列、多格粘贴、逐列筛选、拖动/键盘行列尺寸，保存检查列表及记录revision，保留客户/状态/备注/隐藏字段。导入归入新建菜单，保留所选范围字体/填色/边框/对齐/数字格式/尺寸/内部空行/合并区域，导出XLSX恢复布局；不执行宏或公式，公式使用已保存结果。
- 审计全部63份模板及46份静态JavaScript，21份文件清理/缩短纯介绍和实现机制说明；操作约束、必填/错误/状态、安全边界保留。详细记录docs/SPREADSHEET_AND_COPY_AUDIT_2026-10-06.md。
- #132 WIP验证：d4ad37c70a3d95884cb8919ea3450bcf6aff0e7b的新增数据完整性契约和桌面/手机网页表格浏览器验收通过，原清单测试同名表头定位需精确化后重跑；本条不代表完整CI或部署完成。
- 唯一下一步：完成#132完整CI与稳定性门禁后合并、验证生产并更新此快照；#128仍Draft，不在本轮合并。



# 晨的小助手 · AI 开发接力文档

## 历史接力状态（旧时点）

- GitHub 当前功能/发布基准：main `12962abe34a84058e91b6863b1af2bb010ad1155`（2026-09-28，PR #116 已合并：win-assistants v0.5.4 将号码提醒改为独立置顶持久提醒窗，不再拉起整个主程序）。
- 当前应用版本：Web main 为 `v1.6.5`；`win-assistants` main / release / 生产公网更新资产均为 `v0.5.4`。Web 生产版本如需声称必须另做 `/health` 取证。
- 当前功能合并基准：`44b9b9355e2641281b5989a5e03bfd87e16888ba`（Merge PR #83：win-assistants v0.5.0 内置久坐助手）；之后 main 还有发布/文档类提交，因此“功能基准”不要误当作当前 main SHA。
- 当前发布基准：`win-assistants v0.5.4` 已正式发布。`win-assistants-release/update.json` 实际为 v0.5.4，EXE 大小 `71,630,014` 字节，SHA256 `f64069e77af4e76878ac3d36b862c5f2c2dcc7a39e4fa33d68e66cdbd5861d70`。main push run `36386314073` 完成 source validation、Windows tests、PyInstaller、GUI smoke、PE 校验、artifact 上传与 release 分支发布；一次性验证 PR #117 从 self-hosted Runner 实际请求公网 update.json 并下载公网 EXE，版本/大小/SHA256/MZ 全部通过，PR #117 已关闭且未合并。
- Windows 客户端 rollout：v0.5.4 继续保留 v0.5.3 的可靠统一 updater，并把号码提醒改为独立小窗：新号码不再 `_show_window()` 拉起整个主程序，也不依赖几秒消失的系统通知；改为右下角置顶的“待录入号码提醒”窗，多条新号码集中追加，显示号码/提交人/备注，提供“复制号码 / 打开待录入 / 关闭这条提醒”。提醒不会自动消失；窗口右上角关闭按钮会保持提醒可见；只有用户逐条明确关闭后才移除。关闭本机提醒不会自动修改 Web 待处理状态，服务器待处理队列仍是唯一业务状态源。
- Web 生产：v1.6.3 已实际部署并从公网取证。一次性验证 PR #108 的 `verify-number-reminders-production` job 返回 `health {'ok': True, 'version': '1.6.3'}`；号码收集后台现包含独立“Windows 提醒连接码”，只读 API `/api/number-inbox/pending` 使用 Bearer token，与同事提交 token 分离。
- CI / Runner：新 self-hosted Runner `chen-assistant-ci-192-255-130-71` 已实际承接并成功执行 validation / stability / win-assistants cross-build。Draft PR #82 仍是 Runner 迁移历史 WIP，但它当前 head 已落后 main 49 commits；收尾前必须重新基于当前 main 审核，不能直接合并旧分支。
- 其他既存 Open PR（包括 #77/#74/#73/#66/#64/#55/#43/#41/#39）属于历史或其他方向，不能仅因仍 Open 就视为当前开发。
- GitHub 项目长期记忆机制已通过 PR #96 合并完成；`docs/PROJECT_CONTEXT.md` 现为跨聊天固定接管入口，不再需要粘贴超长项目提示词。\n- Web UI：PR #98 已合并，`/work` 页面“客户管理 / 工作资料”主模块已改为真正两列并排的小方块，简化卡片内容，并将 `work-architecture-v14.css` 缓存版本更新为 `v=1402`，解决 iPhone 继续使用旧 CSS 的问题。合并 commit：`572aaffe6f4ffbcef38a74b60510e2853f6e324d`。PR CI 与 main validation/stability 均已通过；GitHub deploy production job 已识别为 Web 运行时变更并按设计交由已完成实机 bootstrap 的生产侧 `chen-assistant-auto-deploy.timer` 自动部署。
- 号码收集 / Windows 提醒：Web 已包含号码收集与 Windows Bearer 只读提醒 API；win-assistants v0.5.4 使用独立持久提醒窗等待用户处理。Windows 仍只做提醒，不自动录入、不自动改变 Web 状态；服务器待处理队列仍是唯一数据源。
- 新的固定接管入口：`docs/PROJECT_CONTEXT.md`。长期产品规则、架构、开发约束、重要决策分别存放在 `PRODUCT_REQUIREMENTS.md`、`ARCHITECTURE.md`、`DEVELOPMENT_RULES.md`、`DECISIONS.md`。
- 注意：本文件下方存在较早时期的历史状态段落（例如旧版本/旧生产基准），仅作历史记录；发生冲突时，以本节“当前接力状态”和 GitHub 实际代码/PR/Actions 为准。
- 下一步：用户实际 Windows 电脑应先处于 v0.5.3 或以上，然后通过唯一“检查更新”升级到 v0.5.4；由同事提交一个测试号码，实机确认：主程序不被拉起、右下角独立提醒窗出现并持续存在、多个新号码可累积、复制号码/打开待录入可用、逐条关闭提醒后才消失。若实机体验仍需调整，再基于这个持久提醒窗优化尺寸/位置/交互，不回退到弹整个主程序。

### 新聊天接管协议

当聊天接近长度上限或需要开启新对话时，不复制整段旧聊天。新聊天第一条消息直接发送：

> 继续开发我的“晨的小助手”。仓库：https://github.com/zc202302-lab/chen-assistant。先读取当前 main 和 docs/AI_HANDOFF.md，以仓库实际代码为准。不要根据旧聊天猜测状态。确认当前版本、main、生产基准、已完成事项、未完成事项后继续上次开发。

AI 接管时必须遵循：

1. 先读取 GitHub 当前 `main` 最新提交。
2. 再读取 `docs/AI_HANDOFF.md`，优先查看本节“当前接力状态”。
3. 以实际代码为最高优先级；本文件仅用于解释已确定的产品决策、生产状态和未完成任务。
4. 若聊天中形成新的重要决定、完成一次合并、完成一次生产部署或改变下一步任务，必须同步更新本节，避免信息只留在聊天里。
5. 不要求用户重复讲历史，不从记忆猜测仓库状态。

---

> 用途：当 ChatGPT 聊天达到长度上限、切换新聊天、换模型或隔一段时间继续开发时，先读本文件，再读当前 `main` 分支实际代码，然后继续工作。
>
> **优先级规则：当前 `main` 实际代码 > 本文件记录的产品决策/开发状态 > 旧聊天记录。** 如果三者有冲突，不要自行猜测或重新设计；先定位冲突原因，再向用户说明并更新本文件。

---

## 1. 项目身份

- 项目名称：晨的小助手（Chen Assistant）
- GitHub：`zc202302-lab/chen-assistant`
- 当前应用版本：`v1.5.9`
- 当前线上代码基准：`985ac41`（2026-09-20 已部署成功，v1.5.8）；当前 `main` 为 `d2ff643` / v1.5.9，尚未部署
- 生产服务器应用目录：`/opt/chen-assistant`
- systemd 服务名：`chen-assistant`
- 技术形态：FastAPI / Starlette + SQLite + Jinja 模板 + 原生 JS/CSS + systemd
- 生产部署入口：`cd /opt/chen-assistant && bash deploy.sh`

### 2026-09-20 生产状态

`v1.5.8` 已完成部署并通过部署脚本自检：

- 数据库备份成功
- Git 更新成功
- Python / JavaScript 检查通过
- `/health` 返回 `ok=true`、`version=1.5.8`
- 静态资源一致性检查通过
- 远程资料存储通道在线

因此后续开发必须以 `v1.5.8` 为稳定基线，不能为了新功能破坏既有客户、缴费、资料、导入等历史功能。

---

## 2. 工作模块的总架构（已经确定，不要重新拆）

工作模块只有两个用户侧一级业务域：

### A. 客户管理

围绕“一个个客户”组织业务数据。每个客户拥有自己的：

- 基础资料
- 缴费
- 业务
- 优惠
- 联系人
- 客户资料
- 待办
- 跟进
- 属性设置
- 其他客户级状态

**核心原则：客户实例数据彼此独立。** 所有客户实际业务值必须归属于明确的 `customer_id`，不可因为模板共用而串客户。

### B. 工作资料

保存与具体客户无关、可跨客户复用、需要持续维护的公共工作知识，例如：

- 产品资料
- 资费资料
- 开通流程
- 操作指南
- 系统截图
- 制度规范
- 模板文件
- 其他通用资料

**核心原则：公共资料只保存一份。** 客户业务以后可以“关联”工作资料，但不复制一份到每个客户名下。

### C. 内部共享规则层（不是第三个一级导航）

用于定义结构、默认值和规则，例如：

- 业务模板
- 业务属性模板
- 缴费模板结构
- 客户属性模板
- 产品定义
- 分类与标签

模板只定义结构和默认值，不拥有、也不能覆盖已经存在的客户实例数据。

当前架构代码位于 `app/work_architecture.py`。

---

## 3. 当前已实现并需要长期保持的客户管理能力

### 3.1 客户页面结构

当前客户页面已经形成高密度工作台，主要包含：

- 缴费
- 业务
- 优惠
- 联系人
- 资料
- 待办
- 跟进

顶部保留客户核心信息、复制能力、编辑资料等入口。

### 3.2 全局前进 / 后退导航

`v1.4.3` 已加入页面历史前进 / 后退控制。

实现时曾出现浏览器自动化测试竞态：HTML 按钮先可点击、JS 尚未挂载。最终约定为：

- 按钮初始 `disabled`
- JS 完成历史导航初始化后再按真实历史状态启用

不要回退为“页面一加载按钮就可点”的实现。

### 3.3 客户整体启用 / 停用

`v1.4.3` 已加入客户整体状态控制。后续所有相关功能都要尊重这一状态语义，不应仅做视觉开关。

---

## 4. 缴费模块：必须保留的业务规则

这是成熟核心模块，新开发不得随意简化或重写。

### 4.1 金额与核对

- 金额只保留一个当前编辑框，不额外并列“本月 / 上月金额”。
- 新周期应继承上一次金额状态，用户直接在同一个金额框上修改。
- 金额编辑应尽量高效：点击即可进入可输入状态，不要求先手动删除旧值。
- 修改金额后可以通过既定交互确认（历史要求包含回车确认）。
- 每行具有自己的金额核对状态。
- 其他未修改行的核对状态不能因为某一行变更而被重置。

### 4.2 金额修改后的流程回退

无论缴费流程进行到哪个阶段，只要**缴费金额发生实际修改**：

- 自动回退到“金额确认 / 金额核对”阶段
- 不弹窗打断操作
- 其他没有修改的数据核对状态保持不变
- 如果之前已经完成缴费，应通过已有快照/兼容恢复逻辑安全回滚，而不是伪造历史数据

`v1.4.3` 对老历史记录增加了兼容回滚逻辑，代码位于 `app/v143_payment_controls_patch.py`。

### 4.3 固定 / 非固定缴费

- 一条号码/业务可随时切换固定或非固定缴费。
- 切换时当前金额应保留。
- 固定模式可立即视为该金额已确认。
- 切到非固定模式时应回到待核对状态，并让工作流回退到金额核对阶段。
- 即使已经进入后续缴费环节，也允许按既定兼容规则切换。

### 4.4 四阶段缴费流程

核心流程维持：

1. 金额核对
2. 通知客户
3. 发起缴费
4. 完成缴费

已确定的交互原则：

- “通知客户”不使用多余确认弹窗
- “发起缴费”不使用多余确认弹窗
- 完成后如果发生需要回退的数据变化，应按数据规则回退，而不是仅改变按钮视觉状态

### 4.5 缴费模板与文件

- **缴费模板按客户独立，不同客户之间不可通用实际模板内容。**
- 客户未填写模板时应明确提示，不要自行补充或猜一个模板。
- `payment.txt` / txt 缴费文件生成功能必须长期保留。
- 发起缴费涉及附件时，必须保证附件真正进入既定流程，不能出现“界面发起成功但没有附件”的假成功。

---

## 5. 客户资料模块：v1.4.3 当前状态

“客户资料”不是单纯文件上传区，而是由两类资料共同组成。

### 5.1 信息资料（已实现）

每条信息资料支持：

- 类型：用户自由填写，不做固定枚举
- 名称
- 内容
- 备注
- 后续编辑
- 删除

当前数据库表：`customer_resource_items_v143`

关键边界：

- 必须绑定 `customer_id`
- 不同客户资料彼此隔离
- “名称”和“内容”至少填写一项
- 类型是自由文本，不应重新改回硬编码分类

当前后端：`app/v143_customer_resources.py`

### 5.2 文件资料（已实现并沿用远程存储）

- 沿用 `v1.3` 已验证的远程文件存储链路
- 文件资料仍然属于具体客户
- 文件“类型/分类”已经允许用户自由填写，不再局限于原固定分类
- 远程文件本体不应因为新增信息资料功能而迁回 ECS 本地

### 5.3 信息资料的交互方向

已经确定：

- URL/网址类内容可直接打开
- 普通文本内容便于复制
- 信息资料支持继续编辑和删除
- “资料”必须同时容纳信息资料和文件资料

---

## 6. 工作资料模块：当前只完成架构，内容管理尚未开发

当前页面：`/work/library`

当前模板：`app/templates/work_library_v14.html`

现阶段已经建立分类和边界，但页面仍明确显示：

> 架构已建立 · 内容功能待开发

### 6.1 已确定分类

- 产品资料 `product`
- 资费资料 `pricing`
- 开通流程 `process`
- 操作指南 `guide`
- 系统截图 `screenshot`
- 制度规范 `policy`
- 模板文件 `template`
- 其他资料 `other`

### 6.2 已确定的每条资料基础概念

后续正式开发至少应考虑：

- 标题
- 分类
- 关联产品（一个或多个）
- 版本 / 生效日期
- 正文
- 附件
- 标签
- 状态：有效 / 待更新 / 已失效 / 归档

### 6.3 与客户管理的关系

- 工作资料是公共知识资产，只保存一份。
- 客户自己的合同、报价单、营业执照、现场照片等仍属于客户资料。
- 客户的某项业务以后可以关联工作资料中的资费、流程、指南等。
- “关联”不等于复制文件或复制正文。

---

## 7. 下一阶段开发主线

**下一主线：把“工作资料”从架构页做成真正可使用的资料管理模块。**

建议按以下顺序推进，但每一步必须先结合当前代码再实施：

1. 建立工作资料数据模型和数据库迁移/建表逻辑。
2. 实现资料新增、查看、编辑、删除。
3. 同一条资料同时支持“正文信息 + 附件”，不要再次退化成纯文件夹。
4. 支持用户可维护的分类/标签，同时保留当前一级分类语义。
5. 加入状态、版本、生效日期，保证资费和政策可以新旧并存。
6. 附件优先复用已经验证的远程存储能力，不重复造一套不稳定文件链路。
7. 做搜索和筛选，使资料可按标题、正文、分类、标签、产品快速找到。
8. 后续再实现“客户业务 ↔ 工作资料”的关联关系。

在正式编码前，应先给用户看清楚**页面结构 + 数据结构 + 关键操作流**，确认后再做，避免一次性造出大量不符合实际工作习惯的页面。

---

## 8. 已确定的产品设计原则

这些原则来源于实际长期使用反馈，除非用户明确改变想法，否则不要推翻：

- 操作效率优先，避免无意义确认弹窗。
- 高频页面采用高密度单行/紧凑布局，不追求“漂亮但低效率”的大卡片堆叠。
- 单击优先承担复制、进入输入等高频动作；修改类动作要清楚但不繁琐。
- 数据状态必须是真实业务状态，不能只做前端视觉假状态。
- 修改局部数据时只影响必要范围，不做整页/整客户无差别重置。
- 不同客户的实际数据严格隔离。
- 模板共用的是“结构/规则”，不是客户实际值。
- 公共知识只保存一份，以关联方式复用。
- 已成熟功能优先兼容，不能为了新架构随意重写导致回归。

---

## 9. 测试与合并原则

`v1.4.3` 合并前，GitHub Actions 已通过完整兼容验证，包括：

- stability gate
- v1.2 validation
- v1.4.2 导航和行核对验收
- v1.4.3 居中导航 / 客户状态验收
- v1.4.3 缴费控制验收
- 历史客户导入浏览器验收
- 历史缴费工作流浏览器验收
- 历史客户页面浏览器验收
- runtime-fix / insert-order / review-reset 等兼容验收

长期原则：

- 不为了让 CI 变绿而删除、弱化或绕过历史测试。
- 新功能和旧功能必须一起绿后再合并。
- 测试失败首先定位实现冲突，不把“测试太严格”当默认结论。

---

## 10. 部署规则

生产更新默认使用：

```bash
cd /opt/chen-assistant && bash deploy.sh
```

`deploy.sh` 当前承担：

- 部署前数据库备份
- Git 拉取 / 快进更新
- Python 依赖安装
- Python 编译检查
- JavaScript 语法检查
- 版本/路由/表结构自检
- systemd 服务重启
- `/health` 验证
- 静态资源哈希一致性验证
- 远程存储健康检查

### 特别注意：deploy.sh 自更新场景

曾发生一次正常现象：旧版 `deploy.sh` 启动时记住旧 `EXPECTED_VERSION=1.4.2`，运行中 Git 把代码和脚本更新到 `1.4.3`，于是第一次进程用旧变量检查新代码时出现：

```text
AssertionError: ('1.4.3', '1.4.2')
```

重新执行新版 `deploy.sh` 后完整成功。

以后看到类似“脚本自己被本次更新替换，进程仍持有旧变量”的情况，先判断是否属于自更新，不要误判为应用代码故障。

---

## 11. 新聊天接力流程

当聊天即将达到长度上限，或已经换到新聊天时，AI 应按这个顺序恢复上下文：

1. 打开仓库 `zc202302-lab/chen-assistant`。
2. 读取当前 `main` 分支，而不是凭旧聊天猜代码。
3. 读取本文件 `docs/AI_HANDOFF.md`。
4. 查看最近 commit / PR / CI，确认本文件是否落后于代码。
5. 用 5～10 句话向用户复述：当前版本、线上状态、已完成模块、当前主线、下一步。
6. 再继续编码或讨论，不要求用户重新讲一遍历史。

用户在新聊天可直接发送：

```text
继续开发我的“晨的小助手”。
仓库：https://github.com/zc202302-lab/chen-assistant
先读取当前 main 和 docs/AI_HANDOFF.md，以仓库实际代码为准。
请先告诉我你读取到的当前版本、已完成功能、当前待办，然后继续上次开发。
```

---

## 12. 每个开发阶段结束时必须更新本文件

每次完成一个实质阶段后，应同步维护：

- 当前版本
- 最新稳定线上提交
- 新增功能
- 新的产品决策
- 已知问题
- 下一阶段任务
- 已否决方案（如果以后可能再次误提）

**不要把关键产品决策只留在聊天里。** 聊天是工作过程，GitHub 代码和本文件才是长期接力基础。

---

## 13. 2026-09-15 全量代码核查与稳定性加固

在继续“工作资料”新功能前，已对当前 `v1.4.3` 代码进行一次跨历史版本的全量核查。此次阶段**不增加产品功能、不改变应用版本号**，目标是把已成熟能力的回归、安全和部署防线补齐。

### 13.1 已修复 / 加固的问题

- 修复菜谱基础 schema/种子数据及 Excel 模板导入在异常中可能提交半成品事务的问题；异常现在必须完整回滚。
- 菜谱数值输入拒绝 `NaN`、`Infinity`、非正标准重量和非法配料用量。
- 菜谱、烹饪知识重名从数据库 UNIQUE 异常导致的 500，改为明确的业务级 409，且失败请求不能产生部分数据修改。
- 客户远程文件上传在建立青岛数据库索引前，必须核对远程节点返回的文件大小与 SHA256；不一致时删除远端对象并拒绝建立索引。
- 文件名清理覆盖控制字符，避免异常下载文件名。
- 远程存储节点的 `CHEN_STORAGE_MAX_FILE_MB` 配置值非法时回退为安全默认值，不因一个错误环境变量导致服务启动失败。
- `deploy.sh` 在 Git 更新导致部署脚本自身发生变化时，会自动重新执行新版脚本，避免旧进程继续拿旧版本变量检查新代码。
- 部署阶段不再维护容易漏项的静态资源手工列表：所有顶层 JS 都做语法检查，全部 JS/CSS 都做服务器返回内容 SHA256 一致性核验。

### 13.2 依赖与安全基线

审计后 Python 依赖基线为：

- `fastapi==0.136.0`
- `starlette==1.6.0`
- `python-multipart==0.0.32`
- `cryptography==50.0.1`
- 其余依赖按 `requirements.txt` 当前实际内容为准

之所以保留 FastAPI 0.136 并升级到安全版 Starlette，是为了在修补当前依赖漏洞的同时，不引入 FastAPI 后续路由内部结构变更对现有大量历史兼容路由的破坏。Starlette 新版已移除旧 `TemplateResponse(name, context)` 调用形式，因此新增 `app/starlette_compat.py` 作为窄兼容层，只转换旧调用形式，不改变新 API 行为，避免为了依赖升级大规模重写成熟页面。

CI 已加入：

- `pip-audit` 依赖漏洞扫描
- `bandit` 高危 Python 静态安全扫描
- 所有 JavaScript 语法检查
- Python 全量编译检查
- 模板静态资源引用检查
- 关键路由实际归属检查
- 首个生效 POST 路由的 CSRF 覆盖检查
- 事务异常回滚验证
- 远程文件完整性保护检查

### 13.3 兼容回归结果

审计分支已经完整通过：

- stability gate
- 依赖安全扫描
- v1.4.4 审计合同与真实 HTTP 异常输入验收
- v1.2 架构 / 菜谱工具合同
- 全部历史工作系统兼容合同
- production regressions
- 菜谱工具浏览器验收
- 工作空间隔离验收
- 精确号码/表格定位验收
- 缴费流程回退与 stale-UI server-first 验收
- 客户远程资料验收
- v1.4.2 导航与行核对验收
- v1.4.3 客户状态与缴费控制验收
- 历史客户导入、缴费、客户页、runtime-fix、insert-order、review-reset 浏览器验收

审计过程中任何为了测试而产生的误修改都必须在合并前从 PR diff 中清除；成熟历史业务代码不能因为审计本身被无意简化。

### 13.4 审计后的开发状态

- 产品版本仍为 `v1.4.3`。
- 生产服务器尚未因为本次审计自动更新；部署仍需独立执行。
- 本次审计没有改变“客户管理 + 工作资料”两大业务域。
- 下一条产品开发主线仍是：把 `/work/library` 从架构页实现为真正的工作资料 CRUD / 正文 + 附件 / 搜索筛选模块。
- 后续每次实质开发都必须继续跑本次建立的全量回归与安全防线，不能退回只测新功能。

---

## 14. 2026-09-17 v1.5.4 全局顶部导航

v1.5.4 将首页原有的一级导航提升为所有页面共用的全局顶部导航，业务路由和数据逻辑保持不变。

### 14.1 已确定的导航契约

- 顶部中央固定显示“首页 / 工作 / 生活”，并根据当前路径标记唯一的活动区域。
- 品牌“晨的助手”始终返回系统首页，不再根据当前区域改变目标。
- 页面前进 / 后退控制保留既有真实浏览历史逻辑，移动到顶部右侧操作区，与搜索入口并列。
- 历史按钮仍须初始禁用，等待 JavaScript 完成状态初始化后再启用，避免恢复旧竞态。
- 主导航在桌面端保持屏幕居中；窄屏时进入独立第二行，不能挤压品牌和右侧操作。
- 支持浏览器时使用同源跨文档 View Transitions；用户启用“减少动态效果”时关闭过渡动画。
- 全局导航静态资源变更必须同步更新模板缓存版本号，避免部署后继续命中旧脚本或旧样式。

### 14.2 版本与部署状态

- 仓库候选版本为 `v1.5.4`，应用版本和 `deploy.sh` 期望版本必须一致。
- 生产服务器仍以已确认的 `v1.4.3` 为稳定线上基准；代码合并不会自动代表生产已部署。
- 合并前必须让 stability gate、完整 validation 和全部历史浏览器验收同时通过。
- 合并后可继续使用标准命令：`cd /opt/chen-assistant && bash deploy.sh`。

---

## 15. 2026-09-17 v1.5.5 Excel 菜谱 A4 打印

菜谱打印页以用户提供的《菜谱.xlsm》为唯一版式基准，复刻每张菜谱工作表左侧打印区域。右侧辅助区不进入打印页。

### 15.1 固定版式契约

- A4 纵向，页面内容对应 Excel 的 `B1:K15`（少数旧表虽从 A 列起始，但有效模板结构仍为左侧 10 列）。
- 打印内容内部不增加网页标题、版本说明、来源页脚、彩色卡片或装饰区。
- 表格固定 10 列、15 行：前 9 列等宽，最后“备注/原理”列约为普通列的 2.089 倍。
- 第 1 行为主材；第 2～9 行为 4 组配料名称/用量；第 10～11 行为“步骤 / 方法 / 原理”合并表头；第 12～15 行为 4 个制作阶段。
- 对应 Excel 合并关系：每个配料组名称纵向合并 2 行，配料备注纵向合并 8 行，方法区域横向合并 8 列。
- 行高按 Excel 原始行高和 72% 打印缩放折算；字体为微软雅黑，黑色细边框、白底，无额外填充色。
- 屏幕上的返回和打印工具栏只用于操作，进入打印介质后必须隐藏。
- 糖醋排骨浏览器验收必须同时验证 10×15 网格结构、关键单元格内容、物理尺寸和单页 A4。

### 15.2 数据映射

- `主材`组进入第 1 行，以“名称 / 用量”成对排列。
- 其余配料组按既有排序进入 4 个双行区域，上行为名称，下行为用量。
- 配料备注集中进入右侧纵向合并的备注格。
- 步骤标题、方法和原理分别进入第 12～15 行的三块区域；火候、时长和判断补入方法，风险提示补入原理。
- 数据超过固定 Excel 网格容量时不得静默丢弃；额外配料汇总到备注，额外步骤并入最后一个步骤区域。

### 15.3 版本与部署状态

- 仓库候选版本为 `v1.5.5`，生产环境仍以已确认版本为准，不因分支提交自动部署。
- 合并前必须通过完整 validation、stability gate 和菜谱单页打印浏览器验收。


---

## 16. 2026-09-20 v1.5.6 缴费 Excel 导出

客户缴费工作区在“生成缴费TXT”左侧增加“生成缴费EXCEL”。

### 16.1 导出契约

- Excel 与当前客户、当前缴费周期绑定，继续复用正式缴费数据的金额核对规则。
- 导出内容以页面当前选择的两个“展示属性”为准，并包含页面固定展示的号码、账号和金额。
- 不导出隐藏属性、核对状态、固定/变动控制、客户说明、月份说明、合计或其他文字。
- 工作簿只有一个“缴费”工作表，内容只有一张带表头的数据表。
- 号码和账号按文本保存，金额按数值保存。
- Excel 文件名沿用客户缴费模板中的 TXT 附件文件名，只把扩展名替换为 `.xlsx`。
- Excel 与 TXT 按钮共用金额核对就绪状态，且 Excel 按钮固定显示在 TXT 左侧。

### 16.2 版本与部署状态

- 应用与部署目标版本为 `v1.5.6`。
- 合并前必须通过 stability gate、完整 validation、路由合同和浏览器真实下载验收。


---

## 17. 2026-09-20 v1.5.7 缴费 Excel 纯数据导出

根据实际使用反馈，对 v1.5.6 的缴费 Excel 进行收敛：

- 导出字段继续严格跟随客户缴费页当前设置的两个展示属性，并保留页面固定展示的号码、账号、金额；未在页面展示的业务属性不得额外导出。
- Excel 不再套用彩色表格样式、不冻结首行、不添加边框、底色、专用金额格式或其他装饰。
- 工作表仅保留普通表头和数据；号码、账号及展示属性按文本写入，金额按数值写入。
- 仅根据实际内容自动调整合理列宽，并设置统一的舒适行高；这是唯一允许的版式处理。
- 文件名、金额核对规则、当前客户/当前周期绑定关系及 TXT 导出逻辑保持不变。
- 应用与部署目标版本更新为 `v1.5.7`。


---

## 18. 2026-09-20 v1.5.8 缴费 Excel 严格跟随当前显示列

v1.5.7 仍错误复用了旧版“两个展示属性”设置，导致网页实际只显示“号码 / 账号 / 缴费金额”时，Excel 仍额外导出“类型 / 姓名”等列。

v1.5.8 修正为：

- Excel 直接读取当前客户缴费工作区的 `payment_columns_v0211:{customer_id}` 实际列设置，与网页当前显示列完全一致。
- 网页未显示的业务属性不得导出；例如只显示“号码 / 账号 / 缴费金额”时，Excel 也只能有这三列。
- 列顺序跟随网页设置，包括“缴费金额”被拖到中间时也必须按相同顺序导出。
- 业务属性按网页可见文本导出；空值保持网页同样的“—”。
- 缴费金额始终按数值写入，不依赖它是否处于最后一列。
- v1.5.7 已确定的“纯数据、无彩色表格、无冻结、仅合理列宽行高”继续保持。
- 应用与部署目标版本更新为 `v1.5.8`。


---

## 19. 2026-09-20 代码治理审计启动

用户确认客户文件本身没有高保密要求，因此本阶段把重点从“文件机与 CI 主机隔离”调整为**稳定性和历史代码治理**，不改变产品功能和界面。

本阶段原则：

- 先建立当前实际生效代码的可验证清单，再删除历史代码；禁止凭文件名或版本号猜测“旧文件没用了”。
- 路由治理以运行时 app.router.routes 的实际顺序为准，记录同一 method/path 的第一生效 owner 和所有后续历史 owner。
- 静态资源治理先统计模板实际引用与未引用资产；未引用不等于可立即删除，必须继续检查 JS 动态加载、Windows 下载地址、测试/部署依赖。
- 新增 tests/code_governance_inventory.py，用于输出路由重复签名和静态资源引用基线，并锁定关键当前 owner（客户页、缴费 Excel/TXT、金额核对、工作搜索等）。
- 第一阶段只建立基线和防回归，不删除成熟历史模块；待清单稳定后分批清理，每批都必须通过完整 validation 与历史浏览器验收。

### 19.1 第一批静态资产清理

治理基线首次扫描发现：

- 运行时共有 139 个 method/path 路由签名，其中 44 个存在历史重复 owner；当前第一生效 owner 已被治理脚本锁定，后续新增重复签名会直接导致 CI 失败。
- 顶层 JS/CSS/PS1 共 88 个，其中 26 个没有被模板直接引用；进一步扫描全仓库文本引用后，确认 16 个文件在代码、模板、测试、部署、工作流和文档中均无引用，可作为真正孤儿资产删除。
- 第一批已删除：current.js、v02.css、v021.css、v022.css/js、v023.css/js、v024.css/js、v025.css/js、v025_minor.js、v026.css/js、v027.css/js。
- Foxmail 脚本、sw.js、v0212.js、home-top-nav-v153.css、business-editor-hotfix.js 等虽然不是模板直接引用，但仍被部署、测试、动态代码或 Windows 更新链使用，**不得按“未被模板引用”误删**。
- 本批仅删除确认零引用的静态孤儿文件，不修改路由、数据库、页面结构或业务行为，应用版本保持 v1.5.8。

### 19.2 运行时路由唯一 owner 治理

在第一阶段清单中发现 139 个 method/path 路由签名里有 44 个历史重复 owner。Starlette 实际只执行排在最前面的第一个匹配路由，因此后续同签名路由长期处于“代码存在但运行时不可达”的状态，也容易让后续开发误读旧实现。

本阶段先不删除这些历史 Python 源码，而是在 app/main.py 的最终路由表组装阶段统一按“path + methods”保留第一个实际 owner，删除后续完全同签名的运行时路由项：

- 保持原 _ordered 优先级不变，因此当前所有第一生效 owner 不变。
- 历史实现源码仍保留，可随时回滚和继续比对。
- tests/code_governance_inventory.py 从“允许既有 44 个重复签名”升级为“运行时重复签名必须为 0”。
- 客户页、缴费 Excel/TXT、金额核对、搜索等关键 owner 继续单独锁定。
- 只有完整 validation、历史浏览器验收全部通过后才允许合并；若任何历史流程依赖后置重复路由，应视为治理方案有误并停止合并。
- 本阶段仍不改变页面、数据库结构和业务规则，应用版本保持 v1.5.8。

### 19.3 历史路由源码清理前置清单

运行时 44 个重复路由签名已经在上一阶段消除，但对应旧 Python 实现源码仍然保留。为了避免直接按版本号删除旧模块，本阶段新增 `tests/dead_route_source_inventory.py`：

- 按 `app/main.py` 中每个历史路由来源组统计 total / live / dead。
- 只把已经不在最终 `app.router.routes` 中的 route object 标记为 DEAD。
- 额外标记“整个来源组没有任何 live route”的 FULLY_DEAD_GROUP，作为以后删除整组 import/include 的候选。
- 当前阶段仍只做清单，不删除 Python 历史实现；下一步必须以该清单 + 全仓库直接引用检查 + 完整浏览器验收三者共同确认后再清理。
- 运行时路由唯一 owner 仍是硬性 CI 契约。

### 19.4 解除整组已不可达路由的运行时挂载

历史路由源码清单确认 7 个来源组已经没有任何 live route：

- _v0212_payment_routes
- _v022_routes
- _v024_routes
- _v025_home_routes
- _v026_home_routes
- _v027_home_routes
- _v029_routes

本阶段只从 app/main.py 移除这些组的 router import / include / _ordered 挂载，不删除对应 Python 源文件。这样可降低启动时加载和后续误判旧实现的概率，同时保留源码供历史测试、直接 import 和回滚使用。任何功能或测试如果仍依赖这些模块本身，文件仍然存在；只是它们不再参与生产运行时路由表。

### 19.5 已解除挂载模块的源码删除前置检查

7 个整组不可达 router 已经从 app/main.py 解除挂载并通过完整回归，但对应 Python 源文件仍保留。本阶段新增 tests/dead_module_reference_inventory.py，扫描这些模块在 app/tests/docs/workflows 中是否还有直接引用，并把引用分为 runtime / tests / other。

只有 runtime_refs=0 的模块才可进入后续“源码删除候选”；即便 runtime 为 0，如果仍有 tests 或文档引用，也必须先判断这些引用是历史合同、直接函数复用还是仅说明文字，不能直接删除文件。

### 19.6 删除首批零运行时/零测试引用的历史路由模块

基于 detached module reference inventory，确认以下 3 个历史模块已经同时满足：

- 不再挂载到 app/main.py；
- runtime_refs=0；
- 除治理清单自身外没有测试直接依赖；
- 没有文档/工作流/部署直接引用。

因此本批正式删除：

- app/v022_routes.py
- app/v024_routes.py
- app/v029_routes.py

同时在 tests/dead_module_reference_inventory.py 中把它们加入 REMOVED_MODULES，CI 会断言这些历史模块不能被无意重新引入。

以下模块暂不删除：

- v0212_payment_routes：虽无运行时引用，但 ui_v0212_contract.py 仍直接导入其中的周期计算函数；需先迁移该公共逻辑再处理。
- v025_home / v026_home / v027_home：仍被当前运行时代码直接 import/动态 patch，其中 v027_home 还是 /work/customers 的实际页面实现，不能删除。

本阶段没有用户可见功能、路由 owner、数据库或页面变化，应用版本继续保持 v1.5.8。

### 19.7 模板引用治理清单

在首批历史 Python 路由模块删除后，继续治理与这些旧页面配套的 Jinja 模板。新增 tests/template_reference_inventory.py：

- 扫描 app/templates 顶层所有 HTML；
- 统计每个模板在 app / tests / docs / workflow 等文本中的直接引用；
- runtime_refs=0 且 test_refs=0 且 other_refs=0 的模板只标记为 ORPHAN_TEMPLATE，不立即删除；
- 必须先跑完整 validation，确认清单本身不会漏掉 Jinja extends/include、Python TemplateResponse、测试静态合同等引用，再进入下一批实际删除。

本阶段仍不改变产品功能、页面布局或数据库，应用版本保持 v1.5.8。


---

## 20. 2026-09-21 v1.5.9 发起缴费可靠性与 TXT 安全加固

本阶段来自实际缴费工作流反馈，优先级高于代码治理与工作资料新功能。目标是不改变既有四阶段业务语义的前提下，加固“发起缴费”这一涉及真实金额与对外 TXT 的关键环节。

### 20.1 “待确认 · 发起缴费”必须持久化

- 第一次点击“发起缴费”并成功打开 Foxmail / 准备 TXT 后，写入数据库 `initiate_prepared_at`。
- 页面刷新、浏览器重开或间隔较长时间后，仍显示“待确认 · 3 发起缴费”，不能退回未准备状态。
- 只有金额/核对状态改变导致流程失效、撤回通知、正式确认发起缴费等业务动作，才能清除该待确认状态。
- “待确认”不是“已发起”：真正 `initiated_at` 仍只在用户确认邮件已发送后写入。

### 20.2 Foxmail TXT 改为文件剪贴板交接

- 不再打开资源管理器，也不再要求用户从文件夹手动选择 TXT。
- Windows 助手打开 Foxmail 写信窗口后，把已核验 TXT 放入 Windows FileDrop 剪贴板；用户在 Foxmail 中按 `Ctrl+V` 添加附件。
- 助手仍不自动发送邮件。
- FileDrop 必须依赖一个真实临时文件，因此 TXT 只写入系统临时目录，不进入下载目录；临时目录定时自动清理，避免长期残留。
- 助手写入前后校验服务器提供的 SHA256，浏览器只有收到“窗口已打开 + 临时文件已写入 + 剪贴板回读一致 + SHA256 一致”后才进入待确认状态。

### 20.3 TXT 与 EXCEL 文件名完全分离

缴费模板新增独立字段：

- TXT附件文件名：只用于正式 TXT 下载与 Foxmail TXT 附件。
- EXCEL附件文件名：只用于“生成缴费EXCEL”。

两者分别保存、分别校验、互不推导。旧客户没有填写 EXCEL 文件名时明确提示，不从 TXT 文件名自动改扩展名猜测。

### 20.4 正式缴费 TXT 安全契约

正式 TXT 继续固定为每行：

```text
号码|金额
```

并固定使用 CRLF 行分隔。生成链路必须：

- 使用当前缴费工作区同一份 authoritative payment snapshot；
- 任意正金额行只要未核对（包括固定金额被手动改为待核对）就拒绝生成；
- 正金额必须有号码；
- 号码不得包含换行或 `|` 分隔符；
- 金额必须有限且非负，输出继续复用成熟 `format_fee`；
- 生成后再次反向解析，逐行核对“号码 + 格式化金额”与 snapshot 一一对应；
- 对交给 Windows 助手的最终 UTF-8 字节计算 SHA256，Windows 端写盘后再次验证。

新增 `tests/v159_payment_initiate_safety_contract.py` 锁定上述关键规则；完整 CI、stability gate 和历史浏览器回归必须全绿后才能合并。

### 20.5 版本与部署

- 候选版本：`v1.5.9`。
- 当前生产仍是 `v1.5.8 / 985ac41`。
- 合并不等于部署；生产必须继续通过标准 `deploy.sh` 完整自检后，才能把生产基准更新为 v1.5.9。

### 20.6 CI 当前门禁记录

- `v1.2 validation` 在提交 `469a105` 已完整全绿：包含安全审计、代码治理、成熟工作系统兼容、生产回归与全部历史浏览器验收。
- `stability gate` 在同一提交已全绿。
- `Windows Foxmail helper validation` 自本阶段起在 GitHub-hosted Windows runner 上连续出现 job `steps=null`、无日志、任务创建后立即 failure；将 runner 从 `windows-latest` 固定到 `windows-2022` 后仍为相同行为，说明当前可观察证据指向 runner/Actions 基础设施而非脚本 parse/test 失败。
- 不允许为了消除该基础设施红灯删除或弱化 Windows PowerShell 5.1 解析测试；需要真正启动 steps 后才能判断脚本是否通过。

### 20.7 PR #56 已合并

- PR #56 已于 2026-09-21 合并到 `main`，merge commit：`d2ff6432538538206d4a4ad404b3f825b97af0fe`。
- 合并前 `v1.2 validation` 全绿，包含成熟工作系统兼容、production regressions、全部历史浏览器验收；`stability gate` 全绿。
- Windows Foxmail 专项 workflow 仍是 GitHub-hosted runner 0-step / 无日志基础设施失败；未观察到 PowerShell 代码级失败。该问题不得通过弱化测试来规避。
- 合并不代表已部署。生产仍是 `985ac41` / v1.5.8，下一步必须执行标准 `deploy.sh` 并验证 `/health`、静态资源、远程存储和实际 Foxmail/TXT 交接。

---

## 21. 2026-09-21 v1.5.10 Windows 助手自更新热修

### 21.1 实际故障

用户在 v1.5.9 页面点击“发起缴费”时，被安全门禁提示“检测到旧版 Windows 邮箱助手”。页面升级成功，但本机 bridge 仍返回旧协议。

代码审计确认：旧版 `chen_foxmail_bootstrap.ps1` 只会周期性更新 helper，不会更新 bootstrap 自身；并且旧安装的 helper 检查周期为 30 分钟。因此服务端 helper 行为切换后，会出现“网页已更新、本机 helper 仍旧”的窗口期。v1.5.9 新 helper 已保留旧 bootstrap 所需的兼容标记，所以旧安装最终可以接受新 helper，但不能保证立即升级。

### 21.2 v1.5.10 决策

- bootstrap 增加独立版本 `1.0`。
- Watch 模式同时检查 bootstrap 与 helper；bootstrap 有新版本时先下载、ASCII/PowerShell 语法/关键标记校验、SHA256 比较，再原子覆盖安装文件。
- bootstrap 更新后启动新 bootstrap Watch 进程并退出旧进程，使新的更新逻辑真正生效。
- 自动检查周期从 30 分钟缩短到 5 分钟。
- helper 的 SHA256、协议、附件剪贴板与缴费安全规则不降低。
- 浏览器检测到旧助手时继续阻止真实缴费，不允许为了兼容而绕过版本/协议检查；提示中明确旧安装可能有 30 分钟窗口期，急用时可重新安装一次最新版。完成 v1.5.10 bootstrap 后，后续无需因 bootstrap 升级重复手工安装。

### 21.3 合并条件

应用候选版本为 `v1.5.10`。必须通过完整 validation、stability gate、Windows bootstrap/helper 合同和全部历史浏览器验收后才能合并。Windows GitHub-hosted runner 若仍是 0-step / 0-log 基础设施失败，应继续与代码级失败区分，不能删除或弱化 PowerShell 5.1 校验。

### 21.4 实机启动失败补充修复

用户重新运行安装器后输出 `Helper running: no`。该结果说明不是浏览器缓存问题，而是本机 bridge 未成功启动。审计发现历史 helper 曾直接从 `chen_foxmail_helper_v07.ps1` / `v08.ps1` 等版本化文件启动；旧 bootstrap 的 `Get-BridgeProcesses` 只匹配 `chen_foxmail_helper.ps1`，因此可能漏掉历史 bridge，旧进程继续占用 18763，新 v0.9 listener 随即退出。

v1.5.10 进一步加固：

- `Get-BridgeProcesses` 改为识别 `chen_foxmail_helper*.ps1` + `-BridgeMode`，覆盖版本化历史 helper；
- `Stop-Bridge` 额外检查 127.0.0.1:18763 listener，但只有 owner 命令行明确属于晨的小助手 Foxmail helper 时才终止，禁止误杀其他应用；
- `Start-Bridge` 不再只看进程存在，而是在最多约 3 秒内请求 `http://127.0.0.1:18763/health`，确认 `ok=true` 且 `version=0.9` 才报告 Helper running=yes。

这部分属于真实缴费前置安全门禁，必须保留严格验证，不允许用“只要进程在就算成功”的方式回退。

### 21.5 缴费金额 Enter 导航全客户一致性修复

实机反馈发现：部分客户页面在缴费金额按 Enter 保存后，没有按预期跳到下一条未核对金额并复制下一条账号。核查当前运行时确认所有 `/customers/{id}` 实际由同一个 owner `app.v0212_routes.customer_workspace_v0212` 渲染 `customer_workspace_v0211.html`，不是不同客户使用了不同页面模板。

根因有两处：

1. `v028.js` 的 `nextPendingBelow()` 仍使用旧条件 `mode === 'variable' && confirmed === '0'`。成熟规则已允许固定金额行手动取消核对，因此固定行也可能是真实待核对项；旧条件会在这类客户上跳过它。
2. 自动复制账号没有稳定的数据源；若客户隐藏“账号”显示列，DOM 中可能没有账号单元格，不能依赖可见列完成自动复制。

修复契约：

- 回车保存后，下一条候选只看 `data-confirmed='0'`，不再按 fixed/variable 排除；
- 每个缴费行始终携带 `data-payment-account`，独立于当前显示列；
- 找到下一条后，先把该行账号写入剪贴板，再聚焦并全选该行金额；
- 固定金额行的视觉/DOM 核对状态严格跟随后端 `confirmed`，不再因为 `mode='fixed'` 强制显示成已确认；
- 浏览器验收增加“固定金额手动取消核对 + 账号列被移除/隐藏 + 上一行 Enter 保存”的场景，要求焦点准确跳到固定待核对行且剪贴板得到该行账号。

由于当前所有客户共用同一运行时模板和同一 `v028.js`，该修复覆盖全部客户页面，而不是对单个客户打补丁。

补充审计：后加载的 `high-frequency-v152.js` 也维护了金额 Enter / 手动核对后的高频跳转辅助逻辑。其下一条筛选已按 `data-confirmed=0`，但账号读取仍依赖可见 `.identifier-copy[data-kind="账号"]` 单元格。现已统一优先读取行级 `data-payment-account`，并刷新静态资源版本，确保隐藏账号列时主链路与高频辅助链路行为一致。

为避免双 owner 竞态，已删除 `high-frequency-v152.js` 对金额 Enter / focusin 的二次监听。金额 Enter 的唯一 owner 现在是 `v028.js`；`high-frequency-v152.js` 只负责手动点击行级核对按钮后的自动前进。这样实时刷新、新增行、隐藏列和不同客户配置均复用同一 Enter 保存链路。

### 21.6 Linux CI runner 可靠性修复

2026-09-22 实际观察到 `v1.2 validation` 与 `stability gate` 长时间保持 queued，job steps 为空；两者 workflow 均写死 `runs-on: [self-hosted, linux, x64, chen-assistant]`。对比 2026-09-21 同一 workflow 的成功执行记录，确认当前阻塞是自托管 Linux runner 未接单，而不是测试代码失败。

为避免开发/合并门禁依赖单台自托管机器，本分支将 Linux `v1.2 validation` 与 `stability gate` 改为 GitHub 托管 `ubuntu-24.04`。测试集合、完整 validation、历史浏览器验收、稳定性合同均不删减；Playwright 改为 `python -m playwright install --with-deps chromium`，显式安装浏览器系统依赖。Windows PowerShell 5.1 专项仍保持独立 Windows workflow，不以 Linux 测试替代。

### 21.7 Actions 基础设施诊断补充

为区分自托管 runner 离线与测试代码失败，曾在 PR #57 临时将 Linux validation/stability 切到 GitHub 托管 `ubuntu-24.04`。实际结果：托管 Linux validation 与 Windows PowerShell workflow 一样，在任何 step 启动前直接 failure，steps 为空且无日志。因此当前同时存在：自托管 Linux runner 不接单，以及 GitHub 托管 runner 无法正常 provision 的仓库/账号级 Actions 基础设施问题。由于托管切换没有提供有效测试能力，已立即恢复仓库既有 self-hosted Linux workflow，不保留 CI 架构变化。产品代码与测试合同不因此降级或绕过。

### 21.8 CI 排队去重

由于 PR #57 在 runner 故障期间产生了多轮 queued validation/stability，若自托管 runner 恢复，可能先执行已过时提交。现为 `v1.2 validation` 与 `stability gate` 增加 PR 级 `concurrency`，`cancel-in-progress: true`：同一 PR 只保留最新提交对应的一轮门禁，旧 queued/running 任务自动取消。测试步骤、覆盖范围和合并标准不变，仅减少 runner 恢复后的无效排队。

---

## 22. 2026-09-22 win-assistants 统一 Windows 客户端启动

用户将统一客户端正式命名为 `win-assistants`。第一阶段采用“统一壳 + 成熟模块子进程”的渐进迁移方案，不直接重写短信、久坐或 Foxmail 已验证逻辑。

### 22.1 第一阶段范围

- 新增目录：`windows/win-assistants`。
- 统一管理三个模块：短信助手、久坐助手、“晨的小助手”本地连接。
- 提供统一窗口、统一托盘、单实例保护、模块启停、延迟启动和程序路径选择。
- 配置保存在 `%APPDATA%\\win-assistants\\config.json`；现有三个工具的数据目录暂不迁移。
- “接管旧工具的开机启动”只能在用户明确点击后执行；只删除已知旧启动入口，不删除程序或设置，并把 `win-assistants` 设为唯一开机入口。
- 新增 Windows 构建脚本和 GitHub Actions，目标产物为 `win-assistants.exe`。

### 22.2 迁移约束

- 久坐模块必须以 `chen-sit-guard v2.8.0` 当前人体存在检测、摄像头异常暂停、强制休息状态机为基线，不能重写后退。
- 短信模块迁入统一进程时，保留当前 ntfy 长连接、DPAPI/用户级令牌保护、4～8 位验证码识别、单实例和托盘行为。
- Foxmail 模块迁入统一进程时，保留仅监听 `127.0.0.1`、来源限制、FileDrop 剪贴板、TXT SHA256/号码金额校验及绝不自动发送邮件的边界。
- 第一阶段允许子进程存在；只有各模块内置并通过真实 Windows 验收后，才能退出原独立版。

### 22.3 当前分支状态

- 分支：`feat/win-assistants-shell`
- 首个实现提交：`380158866c0105b48ee3c06dffffc991e5f9d9c7`
- 当前分支最新功能提交：`4463c327127bb2c753c5124fdf83abd5c8d129c6`。
- 本地 Python 编译检查通过，16 个标准库单元测试通过。
- 尚未合并到 main，尚未发布安装包，不改变晨的小助手 v1.5.9 / 生产 v1.5.8 的现有基准。


### 22.4 v0.2.0 短信模块已内置

- 短信助手不再作为独立 EXE 子进程启动，ntfy JSON 流接收、验证码识别、测试发送和剪贴板复制已迁入 `win-assistants` 进程。
- 首次启动会只读导入 `%APPDATA%\\iPhoneSmsBridgeNoServer\\config.json`；旧令牌由当前 Windows 用户通过 PowerShell 解密，再使用 `win-assistants` 自己的 Windows DPAPI 密文保存。
- 旧配置和旧 EXE 不删除，实机验证完成前始终可回退。
- 保留原规则：服务器必须是 HTTPS；主题只允许字母、数字、横线、下划线；验证码优先匹配带语义标签的 4～8 位数字，再使用通用数字回退。
- 接收线程加入 generation 隔离；快速重连后，旧阻塞线程即使稍后返回也不能继续投递消息或覆盖新连接。
- Windows runner 仍存在 0 step / 0 log 基础设施故障；Linux `v1.2 validation` 与 `stability gate` 已通过，Windows EXE 尚未生成。


### 22.5 v0.3.0 Foxmail 本地桥接已内置

- Foxmail 本地 HTTP 桥接已迁入 `win-assistants` 进程，不再需要独立 PowerShell helper/watchdog 维持服务。
- 继续只绑定 `127.0.0.1:18763`，拒绝无 Origin、非本机以及非 `ziboxiaozhushou.cn` 根域/子域来源。
- 保持 v0.9 网页兼容协议：`/health`、`/compose`、直接 Foxmail.exe + mailto、写信窗口检测、TXT 文件剪贴板，以及 `auto_send=false`。
- TXT 请求限制 12 MB；附件文件名必须安全归一化前后完全一致；输入字节和落盘文件均校验服务器提供的 SHA256。
- 并发 compose 请求串行处理，避免两个缴费任务争抢文件剪贴板。
- 旧 PowerShell 文件和配置不删除。端口已由兼容独立版占用时，统一程序识别并复用；只有用户明确点击“接管旧工具的开机启动”后，才停止精确匹配的旧 bridge/watchdog 并切换到内置桥接。
- 版本更新为 `win-assistants v0.3.0`；本地全量编译和 16 个标准库单元测试通过。
- 提交 `5b515a4` 的跨平台源码验证、`v1.2 validation` 与 `stability gate` 均通过。Windows EXE 构建已实际运行，便携 Wine 与运行库下载成功，首次因未显式指定同包内 `wineserver64` 失败；`e1a7871` 已设置 `WINESERVER`，合入最新 main 后重新验证。尚不能声称 EXE 已生成或 Windows 实机验收完成。


### 22.6 v0.3.0 Windows 构建产物已生成并完成静态验收

- PR：#58，分支：`feat/win-assistants-shell`。
- 已确认用于构建的 head：`21fa5d7b67f1114b07f76a1539cee59cd314bd30`。
- GitHub Actions `win-assistants cross build` run #23（Run ID `35707202191`）已成功；其中 `source-validation` 和 `build-windows-exe` 均实际执行并成功，PE 校验步骤成功。
- 同阶段 `v1.2 validation` run #775 与 `stability gate` run #393 已成功。
- `Windows Foxmail helper validation` run #115 仍是 GitHub 托管 Windows runner 的 0 steps / 无日志基础设施失败；没有代码执行证据，因此不得把它解释成业务代码或测试失败，也不得因此弱化测试。
- Artifact：`win-assistants-windows`，Artifact ID `10684494468`，ZIP 大小 `15,380,215` 字节，过期时间 2026-12-21。
- Artifact ZIP SHA-256：`e073406889f8f5f306d78b4f9d196ed8c18d3847356d9a5e4a3a5e4b91b89155`；已重新下载并验证与 GitHub Artifact digest 完全一致，ZIP 完整性通过。
- ZIP 内仅包含：`win-assistants.exe` 与 `win-assistants.exe.sha256`。
- `win-assistants.exe` 大小：`15,585,024` 字节；SHA-256：`9d54f5376443f32e6e0f76430e72104fa75ea80105fc16c768d5600e8ef91c37`，与包内校验文件一致。
- 静态 PE 检查：文件为标准 `PE32+` / x86-64 Windows GUI 可执行文件，7 个节；启用 `HIGH_ENTROPY_VA`、`DYNAMIC_BASE`、`NX_COMPAT`、`GUARD_CF`。Security Directory 为空，当前产物未做 Authenticode 代码签名，因此首次运行出现 Windows SmartScreen“未知发布者”提示属于预期现象。
- 源码复核继续满足安全边界：Foxmail bridge 仅绑定 `127.0.0.1:18763`；严格 Origin 限制；附件 Base64 与 SHA256 校验；写盘后二次 SHA256 校验；通过 CF_HDROP 文件剪贴板交接；`/health` 明确 `auto_send=false`；只打开 Foxmail 写信/草稿窗口，不自动发送邮件。

**重要状态区分：**以上只代表 CI 构建、源码测试、Artifact 完整性与静态检查通过。尚未完成真实 Windows 机器运行验收，不能写成“Windows 实机验证成功”。

真实 Windows 验收剩余事项：

1. 在用户真实 Windows 电脑直接启动 `win-assistants.exe`，确认单实例、窗口/托盘、配置目录和旧启动项接管行为。
2. 验证内置短信助手真实 ntfy 接收、验证码识别、剪贴板复制。
3. 验证 `127.0.0.1:18763/health` 与网页来源限制。
4. 从“晨的小助手”网页实际执行一次“发起缴费”：只应打开 Foxmail 写信窗口，把校验后的 TXT 放入文件剪贴板；用户手动 `Ctrl+V` 添加附件并人工发送，程序不得自动发送。
5. 验证 TXT 文件名、内容、SHA256、临时目录自动清理，以及旧 PowerShell Foxmail helper/旧短信启动项接管与回退。
6. 久坐助手当前仍按既定成熟子进程方案运行；其内置迁移继续放在真实 Windows 验收之后。


### 22.7 v0.3.1 实机启动缺失 tkinter 修复

- 用户首次在真实 Windows 机器启动 v0.3.0 Artifact 后，程序立即报错：`ModuleNotFoundError: No module named 'tkinter'`。这次反馈确认 v0.3.0 不能视为真实 Windows 可运行产物。
- 根因：旧 `win-assistants cross build` 使用 Python 3.12 embeddable ZIP。该 Windows Python 发行包不包含 Tcl/Tk；此前 CI 只验证编译、测试、PyInstaller 生成 PE 与静态 PE 类型，没有实际启动最终 GUI EXE，因此漏掉运行时缺失。
- 修复分支：`fix/win-assistants-tk-runtime`；PR #59；修复 head：`dc8252caa9b481e19e2cbe57e9474e96f684950a`；已合并到 main，merge commit：`4b97170c51852ec226aae732107d562a50b15e84`。
- 版本更新：`win-assistants v0.3.1`。
- 构建链路改为在 Wine 中静默安装完整 Windows Python 3.12.10，并显式包含 Tcl/Tk；构建前必须实际 `import tkinter`、创建/隐藏/销毁 Tk 窗口。
- PyInstaller 构建后新增最终 EXE smoke launch：在 Wine/Xvfb 中启动 `win-assistants.exe --background`，程序必须持续运行到 smoke timeout；若像 v0.3.0 一样启动即异常退出，CI 直接失败。
- `build.ps1` 同步增加 Tk runtime 创建窗口测试，避免本地构建与 CI 标准不一致。
- CI：`win-assistants cross build` run #26（Run ID `35802617895`）成功；`source-validation` 与 `build-windows-exe` 均成功，其中 `Prepare full Windows Python with Tcl/Tk`、`Test with Windows Python`、`Build Windows executable`、`Smoke launch built executable`、`Verify PE executable` 全部实际执行成功。
- 同提交 `v1.2 validation` run #780 成功；`stability gate` run #398 成功。
- `Windows Foxmail helper validation` run #119 仍为既有 GitHub-hosted Windows runner 的 0-step / 无日志基础设施失败，没有执行代码，不得解释为业务代码失败。
- 新 Artifact：`win-assistants-windows`，Artifact ID `10726063664`，ZIP 大小 `18,730,671` 字节，GitHub digest / 本地重算 SHA-256：`0aaca7c759c631884e5cfa12838d838334538e3cb22fdad984f9daf2881bdff4`。
- ZIP 内包含：`win-assistants.exe` 与 `win-assistants.exe.sha256`。
- 新 EXE 大小：`19,004,171` 字节；SHA-256：`9caf076ccbf39e53750cb7fbf2a0f10dd50aa44b5b1e49f7cf154f785faa9cc9`，与包内校验文件一致。
- 静态文件类型：标准 `PE32+` / x86-64 Windows GUI，7 个节。
- **状态边界：**v0.3.1 已通过 CI 中的实际 Tk 创建与最终 EXE 启动 smoke test，但仍不能写成“真实 Windows 机器验收成功”。必须等待用户在真实 Windows 上启动新 EXE 并继续验证功能。


### 22.8 v0.3.1 真实 Windows 首轮验收

- 用户已在真实 Windows 机器启动 `win-assistants v0.3.1`，主界面正常显示，确认 v0.3.0 的 `ModuleNotFoundError: No module named 'tkinter'` 已在真实机器修复。
- 内置短信助手真实运行状态已显示“已连接，等待新验证码”；此前同一实机界面已经收到并提取验证码，说明短信 ntfy 接收/验证码提取链路在真实 Windows 上可工作。
- 久坐助手首次界面曾显示“已退出（0）”，用户随后手动点击“立即启动”后状态稳定为“运行中”；因此当前不把首次退出视为持续故障，后续继续观察开机自动启动场景。
- Foxmail / 小助手连接当前显示“兼容独立版正在运行”，说明 127.0.0.1:18763 仍由旧兼容 helper 占用，统一程序尚未正式接管；这符合迁移设计。
- 仍未完成：单实例明确确认、托盘退出/恢复、正式接管旧启动项、内置 Foxmail bridge /health、严格 Origin、真实“发起缴费”写信窗口 + TXT CF_HDROP 剪贴板、绝不自动发送邮件等验收。


## 23. v1.5.11 缴费首页三阶段看板

用户目标：解决原“已通知未缴费”把“已通知但尚未发起缴费”和“已经发起缴费、等待同事完成缴费”混在一起的问题。

- **未通知**：本期应缴费，但尚未通知客户。
- **已通知**：已通知客户，但 `initiated_at` 仍为空。
- **待缴费**：`initiated_at` 已存在且 `paid_at` 为空。
- **已完成缴费**：不进入缴费待处理看板。

实现：`app/v027_home.py` 按当期 `customer_payment_runs` 分类；`dashboard_v027.html` 三列展示；`work-home-polish-v121.css` 桌面三列/平板 2+1/手机单列；新增静态合同和浏览器验收。候选版本 `v1.5.11`。


### 22.9 v0.4.0 统一更新与久坐桥接

- 用户确认短信与 Foxmail 在真实 Windows 上功能无问题；久坐助手继续保持独立成熟代码，不把摄像头、人体检测、状态机、强制休息和设置页重写进 `win-assistants`。
- `chen-sit-guard v2.8.2` 增加本机同用户文件桥接：持续发布运行状态，并接受 `show_status`、`show_settings`、`check_update`。不新增网络端口，不改变 RTSP、检测算法、强制休息和隐私边界。
- `win-assistants v0.4.0` 增加久坐实时“工作中 / 已休息 / 检测异常”与分钟数显示，并增加“打开状态”“设置”按钮。
- 主窗口和托盘均增加“检查更新”。短信和 Foxmail 作为内置模块随主 EXE 更新；久坐助手由统一入口触发自身更新检查。
- 自更新安全校验：HTTPS 更新清单、版本比较、文件大小、SHA-256、MZ 头校验；下载到 staging 后等待旧进程退出，原位替换 EXE，再自动以 `--background` 重启。替换脚本已改为 PowerShell，兼容包含中文/Unicode 的 Windows 路径。
- PR #62 已合并；最终功能 head：`5160986a406f7abf3acc410ebbaf5afa8b37e180`。
- 最终 PR CI：`win-assistants cross build` run #34（Run ID `35806853138`）成功；`v1.2 validation` run #795 成功；`stability gate` run #413 成功。Windows Foxmail helper 专项仍是既有托管 Windows runner 0-step 基础设施问题。
- 最终 Artifact：`win-assistants-windows`，Artifact ID `10727779337`，ZIP 大小 `18,770,544` 字节，ZIP SHA-256 `b2962439b7aee4486e912cdc99020b0d1d41e0190d39a08de2531d15c336981b`。
- 最终 EXE：`win-assistants.exe`，大小 `19,044,718` 字节，SHA-256 `fc9a0a1b23e56bd8b7c1a08e261578eec8e1bfdc28dad23ec7302ca0083faff3`；标准 `PE32+` / x86-64 Windows GUI，7 个节；包内 SHA-256 文件一致。
- Windows 实机状态边界：v0.3.1 已在用户真实 Windows 上成功启动；短信与 Foxmail 已由用户确认功能无问题。v0.4.0 仍需用户真实 Windows 启动验证，尤其验证久坐状态/设置入口与自更新替换。
- 在线更新发布：workflow 已加入生产静态目录发布与远端 SHA 验证，但当前 main 的 `win-assistants/publish` commit status 为 `failure`。现有 self-hosted runner 位于独立 RackNerd CI VPS，并非生产业务主机，因此 runner 本地 `/opt/chen-assistant` 发布方案不能作为最终通道。未解决前不得声称“检查更新已线上可用”。


### 22.10 独立 release 分支与生产静态同步

- PR #65 已合并，merge commit：`ded806924102a80f2a632e000dd206edad767f85`。
- 原因：self-hosted runner 位于独立 RackNerd CI VPS，不是生产业务主机；直接写 runner 本地 `/opt/chen-assistant/app/static` 的发布设计无效。
- 新设计：Windows 构建成功后，workflow 用 Git plumbing 把 `win-assistants.exe` 与 `update.json` 发布到私有分支 `win-assistants-release`。该分支不触发主构建循环。
- PR #65 验证：`stability gate` run #432 成功；`v1.2 validation` run #814 成功；`win-assistants cross build` run #39 的 source-validation 与 build-windows-exe 均成功，包含 Tk runtime、Windows Python 测试、最终 EXE smoke launch、PE 校验与 Artifact 上传。
- main 合并后 `win-assistants/release-assets` commit status 已为 `success`，并已实际创建 `win-assistants-release` 分支。
- 当前 release manifest：version `0.4.0`；EXE SHA-256 `c3d23028c17b7a231eda4b65e5e7752269004bda0b0bfc63869e4d7ce50171a3`；size `19,044,627` 字节；目标公开 URL 仍为 `https://assistant.ziboxiaozhushou.cn/static/win-assistants/win-assistants.exe`。
- 新增 `scripts/sync_win_assistants_assets.sh`：生产机从 release 分支读取两个资产，验证版本清单、size、SHA-256 与 MZ 头后，原子替换到 `app/static/win-assistants`，并从公网 URL 复核 manifest；不会切换生产 Web main，也不会重启服务。
- 新增 `scripts/install_win_assistants_asset_sync.sh`：安装 systemd oneshot + timer；开机后 45 秒首次运行，此后每 2 分钟同步。一次安装后，后续 Windows 新版本无需人工进入服务器复制文件。
- 剩余唯一生产步骤：在生产主机执行一次 timer 安装并确认首轮同步成功。由于当前聊天没有生产 SSH/终端连接，本轮不能声称该服务器级步骤已经完成。


## 25. 2026-09-24 Web 主站自动生产部署

PR #67 已合并到 main，merge commit `4ee8d83e5fae4cb88d490dbba1742e3efcbb9d9f`。

### 25.1 自动部署架构

- `deploy.sh` 仍是唯一生产部署入口，新增 `CHEN_DEPLOY_TARGET_REV`，只允许部署属于 `origin/main` 的精确目标 SHA。
- 若生产已经超过待部署目标，则安全跳过过时任务且不回退；若不能快进则失败停止；不使用 force/reset。
- GitHub main workflow 在 validation 后再次执行 production stability contract；Web 运行时变更才进入 deploy job。
- CI runner 若与生产同机可本地部署；若配置完整 SSH secrets 可严格 known_hosts 远程部署。
- 当前实际 preflight 结果：`LOCAL_PRODUCTION_AVAILABLE=no`、`REMOTE_DEPLOY_SECRETS=incomplete`，所以不能从现有 runner 直接修改生产。

### 25.2 无 SSH secrets 的默认生产侧方案

新增：
- `scripts/auto_deploy_main.sh`
- `scripts/install_auto_deploy_timer.sh`

生产侧 worker 每 2 分钟 fetch `origin/main`：
- 没有新提交：退出；
- 只有非 Web 变更：只快进 checkout，不重启服务；
- Web 运行时有变化：从目标提交提取 `deploy.sh`，传入旧/新 SHA 后执行完整标准部署；
- 生产受管文件有本地修改、分支不能快进等异常：停止，不覆盖现场。

一次性安装：
```bash
cd /opt/chen-assistant
git fetch origin main
git show origin/main:scripts/install_auto_deploy_timer.sh | sudo bash
```

安装器会从 `origin/main` 读取并安装 worker，enable/start `chen-assistant-auto-deploy.timer`，并立即运行一次 `chen-assistant-auto-deploy.service`。首次 bootstrap 不应预先把生产 checkout merge 到 main，否则 worker 看不到旧→新的提交差异，可能只判断“already current”而不触发首轮 Web 重启。上述 `git show ... | sudo bash` 命令避免了这个问题。这是唯一仍需要人工进入生产机的一次 bootstrap；之后 Web main 更新自动部署。


### 24.5 生产自动部署已完成实机 bootstrap（2026-09-24）

用户提供生产终端截图确认：

- 当前生产代码：`20294be`，对应 main 提交 `20294bebaabd0fc3e5502821294e890d8a72202f`。
- 数据库备份完成：`/opt/chen-assistant/backups/app.db.20260924-134624`。
- Python 依赖未变化，跳过 pip install；v1.5.11 应用自检通过。
- `/health` 返回 `{"ok":true,"version":"1.5.11"}`。
- 全部 JS/CSS 静态资源一致；Foxmail 本次未变化，跳过重复校验。
- 远程资料存储健康检查 `127.0.0.1:18790` 连接拒绝；这是现有 deploy.sh 中明确的非阻塞告警，不影响本次 Web 部署成功。
- `chen-assistant-auto-deploy.timer` 已成功创建、enabled、active；下一次检查约 2 分钟后。
- oneshot `chen-assistant-auto-deploy.service` 完成后显示 `inactive (dead)` 且 `status=0/SUCCESS`，这是正常行为，不代表自动部署失效。
- 从此 Web main 更新无需再让用户手工 SSH 执行 `deploy.sh`；生产 timer 会按设计自动检查并部署。


## 25. v1.6.0 独立资料中心

### 25.1 产品定位

用户确认：不再继续把现有“账户库”修补成万能记录工具，也不再把该功能模块放在“工作”下面。建立独立一级“资料中心”：

- 顶部一级导航：`首页 / 工作 / 资料 / 生活`。
- 资料中心主入口：`/info`。
- “信息库”是核心，允许格式不固定的记录。
- 现有 `/accounts` 路由和账户数据继续保留，但视觉/导航归属改为“资料中心”，不再属于“工作”。
- 现有“工作资料”仍保持其原本含义：跨客户复用的工作知识资产，不与个人资料中心混为一谈。

### 25.2 v1.6.0 首批信息模型

新增 `information_records`：

- `title`：必填标题。
- `category`：自由文本分类，不预设死枚举。
- `tags`：自由标签。
- `body_enc`：正文 Fernet 密文。
- `link_url`：可选关联链接。
- `pinned`：置顶。
- `archived`：软归档。
- `created_at / updated_at`。

正文使用已有 `APP_ENCRYPTION_KEY`；列表/详情需要时在应用层解密。搜索可以匹配正文，但不新增明文正文索引。

### 25.3 v1.6.0 首批交互

- `GET /info`：信息库列表、分类过滤和全文搜索。
- `GET/POST /info/new`：新建。
- `GET /info/{id}`：详情。
- `GET/POST /info/{id}/edit`：编辑。
- `POST /info/{id}/archive`：软归档。
- 现有账户库继续使用 `/accounts`。
- 全局搜索新增“资料”结果分组。
- 资料中心的顶部搜索只提交到 `/info`，避免错误复用工作区即时搜索建议。

### 25.4 本期明确不做

- 附件 / 图片 / 文件库。
- 收藏夹。
- AI 自动整理/自动标签。
- 将工作资料迁入资料中心。
- 改写现有账户密码表结构或删除历史账户数据。


