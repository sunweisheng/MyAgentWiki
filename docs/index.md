# 文档索引

本目录用于沉淀 `MyAgentWiki` 项目本身的文档资产，而不是某个用户知识库工作区里的内容。

主要承载：

- 详细设计
- 运行依赖与环境说明
- 常见问题与排障
- 项目学习资料与历史思考记录

## 核心文档

- [RELEASING.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/RELEASING.md)
  - 仓库正式发版流程、版本号策略、推荐命令和发布后检查清单。

- [3.0.0发版准备清单.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/3.0.0发版准备清单.md)
  - `3.0.0` 已发布后的历史发版档案，保留当时的发布判断、breaking changes 草案、5 步检查单和完成结论；当前发版流程以 `RELEASING.md` 为准。

- [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前唯一的主详细设计文档，适合先理解系统定位、处理流程、目录边界、数据模型、证据链、语义链、审核恢复链，以及 `reading_pack / answer-ready` 的交接契约。
  - 文档结构已经按处理流程重排，适合作为后续读代码、看实现和继续收口设计时的主入口。

- [全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
  - 当前保留为专题设计稿，聚焦 LLM 在全链路中的职责边界、语义分析阶段划分、批处理原则和 grounded 约束。
  - 不再承担主设计文档职责；若与主文档表述重复或冲突，以主文档为准。

- [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
  - 全链路重构的阶段计划与完成状态，适合配合主详细设计文档一起看“当时怎样推进、目前还剩什么”。
  - 结构优先链路的 Phase 1-7 已进入正式主干；剩余改进项继续在该文档的状态段维护。

- [CLI模块化设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/CLI模块化设计.md)
  - 当前 CLI 与 Python 模块边界的设计基线，同时记录已经拆出的 `cli_parser.py`、`cli_components/`、`app_services/`、`repositories/` 和尚未完成的 `cli.py` 瘦身工作。
  - 适合继续做代码级模块化重构时先阅读，用来统一依赖方向、拆分顺序和验收口径。

- [runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
  - 运行依赖、平台差异、安装方式与降级能力说明。

- [troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)
  - 初始化、依赖安装、ingest、query、review、lint 相关问题的排查入口。

## 测试与实验场

- [../tests/README.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/README.md)
  - 仓库测试目录说明，包含 CLI、标准化、review、query/lint 与 E2E 测试范围。

- [../tests/fixtures/user_project_lab/README.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/fixtures/user_project_lab/README.md)
  - 用户工程测试实验场入口，说明 fixture 定义、runtime 目录和运行命令。
  - 这套实验场会在本地生成完整 `raw/`、`assets/`、`workspace/`、`reports/`，但不会把运行结果提交到 Git。

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

1. [RELEASING.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/RELEASING.md)
2. [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
3. [全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
4. [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
5. [CLI模块化设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/CLI模块化设计.md)
6. [runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
7. [troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)
8. [project-materials/LLM-Wiki知识库搭建学习总结20260524.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/LLM-Wiki知识库搭建学习总结20260524.md)
9. [project-materials/工程落地补充清单.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/project-materials/工程落地补充清单.md)

## 边界说明

- `docs/` 服务的是母仓库本身。
- `init` 生成的用户工作区不会把这里的全部文档复制进去。
- 用户知识内容、状态账本和 Wiki 页面应保留在用户工作区，而不是回写到这里。
