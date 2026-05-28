# MyAgentWiki

MyAgentWiki 是一个面向 Codex 和 Claude Code 的本地 LLM Wiki Skill 项目。它的目标不是做一次性的 RAG 问答，而是让 Agent 在原始资料之上持续维护一个可追踪、可审计、可演化的个人知识 Wiki。

## 项目简介

这套系统采用分层思路组织知识：

- `raw`：原始资料，只读保留
- `normalized`：标准化后的可分析文本
- `chunks`：切块后的证据单元
- `claim`：独立知识声明层
- `wiki`：最终对人可读、可链接、可维护的知识页面

其中：

- 高频、固定、适合确定性实现的动作优先交给 Python 脚本
- 必须依赖大模型理解、抽取、比较、冲突判断、页面编写的动作交给 Agent

## 核心理念

MyAgentWiki 不是“每次提问都从原文临时拼答案”，而是把知识逐步编译成一个持续维护的 Wiki：

- 原始资料保留不动
- 标准化层负责把不同格式整理成稳定输入
- Chunk 和 Claim 层负责证据追踪与复用
- Wiki 页面负责承载概念、实体、综述和问答沉淀
- Git 负责本地版本管理与回滚

这让系统可以做到：

- Wiki 结论可追踪到具体 Claim
- Claim 可追踪到具体 Chunk 和 Source
- 同一 Claim 可反查被哪些 Wiki 页面引用
- 冲突、重复、覆盖等高风险更新进入审核队列

## V1 范围

V1 重点先把骨架和规则打稳，优先完成：

- Python `3.12+` CLI 基础入口
- `raw -> normalized -> chunk -> claim -> wiki` 主链路设计落地
- Word、Excel、PDF、Markdown、图片五类输入的标准化优先级
- Claim 声明层
- BM25 多字段检索与页面权重设计
- review 审核队列与状态恢复机制
- Windows / macOS / Linux 兼容边界

V1 当前不把这些当成必须前提：

- LibreOffice
- Pandoc
- pdftotext
- tesseract

这些系统工具属于可选增强能力，缺失时应通过 `doctor` 明确提示，并采用降级策略。

## 当前仓库结构

```text
MyAgentWiki/
├── Agent.md
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── MyAgentWiki系统详细设计-V1.md
├── pyproject.toml
├── config/
│   └── runtime_manifest.yml
├── docs/
│   ├── index.md
│   └── runtime-deps.md
├── src/
│   └── myagentwiki/
│       ├── __init__.py
│       └── cli.py
├── templates/
├── tests/
└── 项目资料/
```

主要文件说明：

- `MyAgentWiki系统详细设计-V1.md`
  - 当前版本的详细设计主文档

- `Agent.md`
  - 共享 Agent 核心规则源

- `AGENTS.md` / `CLAUDE.md`
  - Codex / Claude Code 入口适配文件

- `pyproject.toml`
  - Python 项目元信息、依赖和 CLI 入口规划

- `config/runtime_manifest.yml`
  - 运行环境和系统工具依赖清单

- `docs/runtime-deps.md`
  - 平台安装说明和运行依赖说明

- `项目资料/`
  - 现阶段的学习记录、工程思考和历史整理材料

## 环境要求

必需依赖：

- Python `3.12+`
- `git`

目标平台：

- Windows 11+
- macOS
- 主流 Linux 发行版

可选增强依赖：

- `tesseract`
- `libreoffice`
- `pandoc`
- `pdftotext`

## 计划中的 CLI 命令

当前已经预留这些命令入口：

- `myagentwiki init`
- `myagentwiki ingest`
- `myagentwiki query`
- `myagentwiki lint`
- `myagentwiki doctor`
- `myagentwiki bootstrap`
- `myagentwiki review-list`
- `myagentwiki review-apply`

当前实现状态：

- `myagentwiki doctor`
  - 已实现运行环境检查、Python 包检查、可选系统工具检查
- `myagentwiki bootstrap`
  - 已实现 Python 依赖安装与 `--dry-run`
- `myagentwiki init`
  - 已实现工作区初始化、模板生成、状态文件创建、Git 基线提交
- `myagentwiki ingest`
  - 已实现 `raw/` 递归扫描、来源登记、Markdown/纯文本标准化、Word/XLSX/PDF fallback 标准化、图片元数据标准化与 `tesseract` OCR 增强、`.doc / .xls` 老格式保守 fallback、最小 chunk 流程、规则式 Claim 草稿抽取、review 项生成，以及失败/降级信息写入 `state/error_log.jsonl`
  - 已实现两类基础 Wiki 页面：`source-summary` 与 `concept-summary`，会同步生成 `wiki/sources/*.md`、`wiki/concepts/*.md`、`state/pages.jsonl`、`wiki/index.md` 与 `wiki/log.md`
- `myagentwiki lint`
  - 已实现仓库骨架 / 工作区结构检查，以及 `chunk_id` / `claim_id` / `page_id` 唯一性、Claim 溯源、页面记录完整性、`reviews.jsonl` / `error_log.jsonl` / `pages.jsonl` 存在性检查
- `myagentwiki query`
  - 已实现基于 `pages + claims + wiki` 产物的多字段 BM25 检索
  - 当前会综合 `title`、`aliases`、`summary`、`headings`、`body`、`claim_text`、`source_refs` 打分，并叠加页面类型权重与页面状态权重
  - 当前输出候选页面、得分解释、命中字段与命中 token，并返回阅读包 `reading_pack`
  - `reading_pack` 当前包含匹配的 `claims`、`chunks`、来源摘要，以及 `section_path`、`previous_chunk`、`next_chunk` 等下钻线索
- `myagentwiki review-list`
  - 已实现 review 队列查看，可列出待处理项、候选 claim、推荐动作与允许动作
- `myagentwiki review-apply`
  - 已实现最小人工裁决闭环，当前支持 `keep_both`、`archive_one`、`merge`、`edit_then_resume` 四种动作
  - review 动作会把被淘汰 claim 转入历史态，并保留 `original_claim_id` 便于追踪
  - `merge` / `archive_one` 执行后，会自动清理其他仍处于 `open` 状态的 review 中已经失效的候选 claim 引用
  - `edit_then_resume` 支持“人工先修改 `claims/*.json`，再让系统从当前 review 状态继续收口”，不会要求整条 ingest 全量重跑
  - review 动作执行后会即时刷新受影响的自动页面、`state/pages.jsonl`、`wiki/index.md` 与页面检索索引

## 计划中的使用方式

面向最终用户的大致流程会是：

1. 在 Codex 或 Claude Code 中安装或接入 MyAgentWiki Skill
2. 准备自己的原始知识目录
3. 运行 `init`，在原始知识目录同级创建 Wiki 工程
4. 使用 Agent 执行 `ingest`
5. 检查 `normalized/`、`chunks/`、`claims/`、`wiki/` 和 `state/*.jsonl` 结果，重点关注 `state/error_log.jsonl`、`state/reviews.jsonl`、`state/pages.jsonl`
6. 使用 `lint` 和 review 机制维护知识库健康
7. 使用 `query` 先查候选页面，再决定是否继续读取 claim、chunk 和 source

## 当前已落地的产物

执行一次 `myagentwiki ingest` 之后，当前版本通常会生成这些内容：

- `normalized/*.md`
  - 标准化后的文本结果，保留来源元数据，供后续切块和抽取使用
- `chunks/*.jsonl`
  - 按来源拆分的切块结果，每条记录带 `chunk_id`、前后邻接关系和来源信息
- `claims/*.json`
  - 按 Claim 单文件保存的知识声明草稿，便于后续审核与回链
- `wiki/sources/*.md`
  - 首批自动生成的来源摘要页，每个来源至少对应一个 `source-summary` 页面
- `wiki/concepts/*.md`
  - 基于 Claim 聚合出的概念候选页，作为后续综述页、主题页的起点
  - 当前已加入一层轻量命名清洗，优先使用 `section_path` 和短主题短语生成更像 Wiki 的页面名
- `state/*.jsonl`
  - 全局索引与状态账本，包括 `sources`、`normalized`、`chunks`、`claims`、`reviews`、`pages`、`error_log`
  - 其中 `state/pages.jsonl` 会保留已被自动移除页面的历史记录，便于追踪页面演化；但 `removed` 页面不会继续进入在线检索与页面索引
- `indexes/search_pages.jsonl`
  - query 使用的页面检索派生索引，保存字段文本、tokens 和基础页面元数据
  - 当前已支持按页面级内容签名做增量复用，未变化页面会复用既有索引记录
- `reviews/*.json`
  - 需要人工确认的冲突、重复、近似重复等审核项

当前这版最重要的是把“可追踪链路”先打通：

- Wiki 页面可以回指到 Claim
- Claim 可以回指到 Chunk 与 Source
- review 记录可以反查受影响的候选页面
- 页面索引会进入 `state/pages.jsonl`
- 冲突和重复风险会进入 `reviews/` 与 `state/reviews.jsonl`
- 查询会优先命中高价值页面类型，并给出字段级打分解释
- 查询结果已经可以附带第一版 claim/chunk/source 阅读包，方便 Agent 继续证据阅读
- query 已接入持久化页面检索索引，索引存在时优先读取 `indexes/search_pages.jsonl`

## 文档说明

如果你想快速理解项目，建议阅读顺序如下：

1. `README.md`
2. `MyAgentWiki系统详细设计-V1.md`
3. `docs/runtime-deps.md`
4. `项目资料/` 中的学习与工程记录

## 开发说明

当前阶段仓库重点是：

- 固化设计
- 建立跨平台骨架
- 为后续实现准备规则、模板和入口

下一步会继续补：

- Word / 图片 OCR 的进一步增强，以及 `.doc` / `.xls` 的更完整兼容
- Claim 层与 Agent 增强抽取、冲突审核队列深化
- 概念页 / 主题页等更高层的 Wiki 页面生成与回链
- 更稳定的中文分词、增量重建索引、以及更智能的阅读预算控制

## 测试说明

当前仓库已经加入一组 review 回归测试：

- [tests/test_review_apply.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_review_apply.py)
  - 覆盖 `review-apply merge` 后，其他 `open review` 的候选 claim 自动改写与过期引用清理
  - 覆盖 `review-apply keep_both` 后，无其他待审项时 claim 会退出 `needs_review`
  - 覆盖 `review-apply edit_then_resume` 对人工修改后 claim 文件的重新加载与续跑

- [tests/test_normalizers.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_normalizers.py)
  - 覆盖 `.doc / .xls` 老格式 fallback
  - 覆盖图片在“无 tesseract”与“有 OCR 文本”两种情况下的标准化输出

建议先安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

然后执行：

```bash
python -m pytest tests/test_review_apply.py
```

## 许可证

本项目采用仓库中的 `LICENSE` 许可证文件。
