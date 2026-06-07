# 文档索引

本目录用于沉淀 `MyAgentWiki` 项目本身的文档资产，而不是某个用户知识库工作区里的内容。

主要承载：

- 详细设计
- 运行依赖与环境说明
- 常见问题与排障
- 项目学习资料与历史思考记录

## 核心文档

- [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前版本的主设计文档，适合先理解系统目标、数据模型、工作流、`deterministic first` 原则，以及 `query / overview` 的最新实现边界。
  - 其中已包含 `query -> answer handoff contract`，用于定义 `reading_pack` 如何作为上层回答器/Agent 的标准输入。
  - 当前也已包含 `answer-ready output layer`，用于说明 `answer-query`、`query --answer-ready` 及其 `prompt/messages/chatml` 输出格式。
  - 当前也已包含 Phase 6 迁移骨架，说明 `compat-report / migrate / migrate-schema-confirm / migrate-decisions / migrate-followups` 的设计边界。

- [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
  - 当前重构计划主文档。
  - 其中 Phase 6 已记录迁移框架现状、schema transition graph、确认 ledger、灰区 decision/followup queue 与 registry 自校验。

- [runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
  - 运行依赖、平台差异、安装方式与降级能力说明。

- [troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)
  - 初始化、依赖安装、ingest、query、review、lint 相关问题的排查入口。

## 项目资料

- [project-materials/LLM-Wiki知识库搭建学习总结20260524.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki知识库搭建学习总结20260524.md)
  - 项目早期的学习总结，适合理解整体理念和方法论来源。

- [project-materials/工程落地补充清单.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/工程落地补充清单.md)
  - 偏工程实现和长期运行稳定性的补充清单。

- [project-materials/LLM-Wiki学习与思考记录20260524.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki学习与思考记录20260524.md)
  - 早期问题整理与概念拆解记录。

- [project-materials/LLM-Wiki学习与思考记录20260527.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki学习与思考记录20260527.md)
  - 围绕 Codex 落地、检索、Claim、上下文管理等问题的后续深化记录。

- [project-materials/LLM-Wiki-卡帕西.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki-卡帕西.md)
  - 与 LLM-Wiki 来源背景相关的补充材料。

## 建议阅读顺序

1. [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
2. [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
3. [runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
4. [troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)
5. [project-materials/LLM-Wiki知识库搭建学习总结20260524.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki知识库搭建学习总结20260524.md)
6. [project-materials/工程落地补充清单.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/工程落地补充清单.md)

## 边界说明

- `docs/` 服务的是母仓库本身。
- `init` 生成的用户工作区不会把这里的全部文档复制进去。
- 用户知识内容、状态账本和 Wiki 页面应保留在用户工作区，而不是回写到这里。
