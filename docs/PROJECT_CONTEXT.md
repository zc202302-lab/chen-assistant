# 晨的小助手 · 项目上下文入口

本文件是新聊天、新模型或中断后恢复开发时的固定入口。目标是让 GitHub 成为项目长期记忆，不再依赖超长聊天提示词。

## 接管顺序

1. 读取当前 `main` 最新提交。
2. 读取 `docs/AI_HANDOFF.md` 顶部“当前接力状态”。
3. 检查当前 Open PR、Draft PR，以及 AI_HANDOFF 明确标记为正在开发的分支。
4. 需要理解长期产品规则时读取 `docs/PRODUCT_REQUIREMENTS.md`。
5. 需要理解系统组成与模块关系时读取 `docs/ARCHITECTURE.md`。
6. 涉及开发、测试、CI、部署、发布、历史代码治理时读取 `docs/DEVELOPMENT_RULES.md`。
7. 对“为什么这样做”有疑问时读取 `docs/DECISIONS.md`。
8. 必要时再读取 `docs/CHAT_START.md` 和历史记录。

## 状态优先级

明确进行中的 PR / 开发分支实际代码
>
当前 main 实际代码
>
AI_HANDOFF 顶部当前状态
>
长期规则与架构文档
>
历史聊天 / 历史文档段落

若冲突，以实际代码为准，并同步修正文档。

## 新聊天最短提示词

> 继续开发“晨的小助手”。先读取仓库当前 main、docs/PROJECT_CONTEXT.md、docs/AI_HANDOFF.md 和当前 Open/Draft PR，以 GitHub 实际状态为准直接继续。

原则上不再需要粘贴完整项目历史。

## 文档职责

- `AI_HANDOFF.md`：动态状态，只回答“现在做到哪里、下一步是什么”。
- `PRODUCT_REQUIREMENTS.md`：长期产品边界和稳定业务规则。
- `ARCHITECTURE.md`：当前系统架构、模块关系和运行边界。
- `DEVELOPMENT_RULES.md`：开发、CI、部署、测试和治理约束。
- `DECISIONS.md`：重要长期决策及原因。
- GitHub PR / commit / Actions：事实证据，不由文档替代。

动态信息必须优先更新 AI_HANDOFF；长期规则变化再更新对应文档。
