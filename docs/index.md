# 文档索引

本目录用于沉淀 `MyAgentWiki` 项目本身的文档资产，而不是某个用户知识库工作区里的内容。

主要承载：

- 详细设计
- 运行依赖与环境说明
- 常见问题与排障
- 项目学习资料与历史思考记录

## 核心文档

- [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前唯一的主详细设计文档，适合先理解系统定位、处理流程、目录边界、数据模型、证据链、语义链、审核恢复链，以及 `reading_pack / answer-ready` 的交接契约。
  - 文档结构已经按处理流程重排，适合作为后续读代码、看实现和继续收口设计时的主入口。

- [全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
  - 当前保留为专题设计稿，聚焦 LLM 在全链路中的职责边界、语义分析阶段划分、批处理原则和 grounded 约束。
  - 不再承担主设计文档职责；若与主文档表述重复或冲突，以主文档为准。

- [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
  - 当前重构计划主文档，适合配合主详细设计文档一起看“下一步准备怎么落”。
  - 版本迁移、兼容性收口、实施分期等更偏执行规划的内容，建议放在这里持续维护，而不是回灌到主详细设计正文。

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
2. [全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
3. [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
4. [runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
5. [troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)
6. [project-materials/LLM-Wiki知识库搭建学习总结20260524.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki知识库搭建学习总结20260524.md)
7. [project-materials/工程落地补充清单.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/工程落地补充清单.md)

## 边界说明

- `docs/` 服务的是母仓库本身。
- `init` 生成的用户工作区不会把这里的全部文档复制进去。
- 用户知识内容、状态账本和 Wiki 页面应保留在用户工作区，而不是回写到这里。
