# MyAgentWiki

MyAgentWiki 是一个面向 Codex 和 Claude Code 的本地 LLM Wiki Skill 项目。它的目标不是做一次性的 RAG 问答，而是让 Agent 在原始资料之上持续维护一个可追踪、可审计、可演化的个人知识 Wiki。

当前仓库既是：

- 一个可安装的 Python CLI 项目
- 一个可供 Codex / Claude Code 使用的 Skill 仓库
- 一个承载项目设计、工程决策与知识沉淀的母仓库

## 项目简介

这套系统采用分层思路组织知识：

- `raw`：工作区外 sibling 原始资料目录，只读保留
- `normalized`：标准化后的可分析文本
- `chunks`：切块后的证据单元
- `claim`：独立知识声明层
- `wiki`：最终对人可读、可链接、可维护的知识页面

其中：

- 高频、固定、适合确定性实现的动作优先交给 Python 脚本
- 必须依赖大模型理解、抽取、比较、冲突判断、页面编写的动作交给 Agent

当前版本采用 `deterministic first` 原则：

- 事实层、证据层、状态层优先由脚本和显式数据结构生成
- LLM 主要参与可读性改写、导览组织和表达优化
- 一切 LLM 改写都必须 grounded，无法回绑时自动回退到 deterministic 文案

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

## Git 边界与隐私

用户工作区默认会初始化 Git，但提交边界需要明确区分：

- sibling `raw/` 永远视为本地原始资料区，不会被 `init` 复制进工作区，也默认不纳入工作区 Git 基线。
- `init` 生成的基线提交只包含 MyAgentWiki 创建的骨架、配置、索引、账本和初始 Wiki 文件。
- `normalized/`、`chunks/`、`claims/`、`wiki/`、`reviews/`、`state/` 是否持续提交到 Git，由用户自己按隐私和协作需求决定。

如果你的资料包含敏感内容，不要因为外部 `raw/` 没进工作区 Git，就默认认为仓库可以公开。`normalized/`、`chunks/`、`claims/` 和 `wiki/` 里仍可能包含原文片段、摘要、结论或可回推出来源的信息；需要公开仓库时，请先审查这些目录，再决定是否继续纳入版本控制。

## V1 范围

V1 已完成并收口。当前版本重点是把骨架和规则打稳，已经完成：

- Python `3.12+` CLI 基础入口
- `raw -> normalized -> chunk -> claim -> wiki` 主链路设计落地
- Word、Excel、PDF、Markdown、图片五类输入的标准化优先级
- Claim 声明层
- BM25 多字段检索与页面权重设计
- review 审核队列与状态恢复机制
- Windows / macOS / Linux 兼容边界

V1 已通过本地全量测试和端到端验证：

- `python -m pytest`
  - `28 passed`
- `python scripts/validate_workflow.py`
  - 覆盖 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
- `python -m myagentwiki lint --json`
  - 当前仓库结构检查通过
- `python -m myagentwiki doctor --json`
  - 必需依赖检查通过

V1 不把这些当成必须前提：

- LibreOffice
- Pandoc
- pdftotext
- tesseract

这些系统工具属于可选增强能力，缺失时应通过 `doctor` 明确提示，并采用降级策略。

## Skill 安装与接入 / Skill Installation

当前仓库已经是一个可安装 / 可引用的 Skill 仓库，包含：

- [SKILL.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/SKILL.md)
- [agents/openai.yaml](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/agents/openai.yaml)
- [Agent.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/Agent.md)
- [AGENTS.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/AGENTS.md)
- [CLAUDE.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/CLAUDE.md)

这意味着它可以被 Codex 或 Claude Code 作为一个包含 `SKILL.md` 的目录加载。推荐优先用软链接 / 目录链接安装，这样仓库更新后 Skill 会同步生效。

面向 Agent 的核心约束是：

- 固定流程优先执行 CLI
- 证据追踪优先走 `wiki -> claim -> chunk -> source`
- review / state 恢复优先走 `review-list / review-apply`

### 在 Codex 中安装

Codex 会从个人技能目录中发现包含 `SKILL.md` 的 Skill 目录。默认位置是：

- macOS / Linux：`${CODEX_HOME:-$HOME/.codex}/skills/`
- Windows：`%USERPROFILE%\.codex\skills\`

macOS / Linux 推荐使用软链接：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s /path/to/MyAgentWiki "${CODEX_HOME:-$HOME/.codex}/skills/myagentwiki"
```

如果不想使用软链接，也可以复制一份：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R /path/to/MyAgentWiki "${CODEX_HOME:-$HOME/.codex}/skills/myagentwiki"
```

Windows PowerShell 推荐使用目录链接：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills"
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\.codex\skills\myagentwiki" `
  -Target "C:\path\to\MyAgentWiki"
```

安装后重启 Codex，让新的 Skill 被重新扫描。使用时可以直接说：

```text
使用 myagentwiki skill，帮我初始化并导入这个本地知识库。
```

如果已经在 MyAgentWiki 仓库或由 `init` 生成的用户工作区中，Codex 还会读取根目录的 `AGENTS.md`，它会把 Agent 引导到共享规则 `Agent.md` 和 CLI-first 工作流。

### 在 Claude Code 中安装

Claude Code 支持用户级和项目级 Skill：

- 用户级：`~/.claude/skills/`
  - 适合在所有项目中复用 MyAgentWiki
- 项目级：`.claude/skills/`
  - 适合只在某个项目中启用 MyAgentWiki

用户级安装，macOS / Linux：

```bash
mkdir -p "$HOME/.claude/skills"
ln -s /path/to/MyAgentWiki "$HOME/.claude/skills/myagentwiki"
```

项目级安装，macOS / Linux：

```bash
mkdir -p .claude/skills
ln -s /path/to/MyAgentWiki .claude/skills/myagentwiki
```

Windows PowerShell 用户级安装：

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\.claude\skills\myagentwiki" `
  -Target "C:\path\to\MyAgentWiki"
```

安装后重启 Claude Code。使用时可以直接说：

```text
使用 myagentwiki skill，执行 doctor、init、ingest、query 和 lint。
```

如果已经在 MyAgentWiki 仓库或由 `init` 生成的用户工作区中，Claude Code 还会读取根目录的 `CLAUDE.md`，它会把 Claude Code 引导到共享规则 `Agent.md` 和 review / state 恢复约定。

## 文档导航

如果你想先从文档理解项目，建议先看：

- [docs/index.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/index.md)
  - 文档总入口，包含主设计、运行说明、排障文档和项目资料导航
- [docs/MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前版本的系统详细设计主文档

## 快速开始 / Quick Start

### 1. 准备环境

Windows:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m pip install -e ".[dev]"
```

macOS / Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
```

### 2. 检查运行环境

```bash
python -m myagentwiki doctor
python -m myagentwiki bootstrap --dry-run --extra dev
```

### 3. 初始化一个用户工作区

```bash
python -m myagentwiki init \
  --source-dir /path/to/raw \
  --project-name MyNotesWiki \
  --target-dir /path/to/MyNotesWiki
```

说明：

- `raw/` 需要与 `MyNotesWiki/` 平级。
- 如果 `/path/to/raw` 已存在，就直接复用。
- 如果不传 `--source-dir`，`init` 会自动在工作区旁边创建一个空的 `raw/`。
- `init` 不会再复制或预填充 `raw/` 内容，放什么文件由用户自己决定。

### 4. 导入资料并生成第一版 Wiki

```bash
python -m myagentwiki ingest --target-dir /path/to/MyNotesWiki
python -m myagentwiki lint --target-dir /path/to/MyNotesWiki
```

### 5. 查询与审核

```bash
python -m myagentwiki query "什么是知识声明层" --target-dir /path/to/MyNotesWiki
python -m myagentwiki query "如何生成 wiki 页面" --reading-depth deep --target-dir /path/to/MyNotesWiki
python -m myagentwiki review-list --target-dir /path/to/MyNotesWiki
```

## 推荐使用流程 / Recommended Workflow

推荐给最终用户和 Agent 的稳定顺序是：

1. `doctor`
2. `bootstrap`
3. `init`
4. `ingest`
5. `lint`
6. `query`
7. `review-list / review-apply`

如果是对已有工作区增量更新，通常从 `ingest` 开始即可。

## 当前仓库结构

```text
MyAgentWiki/
├── Agent.md
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── config/
│   └── runtime_manifest.yml
├── docs/
│   ├── MyAgentWiki系统详细设计.md
│   ├── index.md
│   ├── runtime-deps.md
│   ├── troubleshooting.md
│   └── project-materials/
├── src/
│   └── myagentwiki/
│       ├── __init__.py
│       └── cli.py
├── templates/
├── tests/
└── scripts/
```

主要文件说明：

- `docs/MyAgentWiki系统详细设计.md`
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
- `docs/troubleshooting.md`
  - 常见问题、降级行为与排障路径
- `SKILL.md`
  - MyAgentWiki Skill 的入口说明
- `agents/openai.yaml`
  - Skill UI 元数据

- `docs/project-materials/`
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

## V1 CLI 命令实现状态

V1 已实现这些命令入口：

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
  - 已输出 Windows / macOS / Linux 的推荐自举命令示例
- `myagentwiki bootstrap`
  - 已实现 Python 依赖安装与 `--dry-run`
  - 当前直接调用运行中的 Python 解释器，不依赖 shell 专属语法
- `myagentwiki init`
  - 已实现工作区初始化、模板生成、状态文件创建、Git 基线提交
  - 当前会初始化 `indexes/aliases.json`、工作区级 `AGENTS.md` / `CLAUDE.md`、以及 query/agent 基础配置
- `myagentwiki ingest`
  - 已实现 `raw/` 递归扫描、来源登记、Markdown/纯文本标准化、Word/XLSX/PDF fallback 标准化、图片元数据标准化与 `tesseract` OCR 增强、`.doc / .xls` 老格式保守 fallback、最小 chunk 流程、规则式 Claim 草稿抽取、review 项生成，以及失败/降级信息写入 `state/error_log.jsonl`
  - 当前规则式 Claim 草稿抽取采用“整句优先，子句只作候选补充”的策略：先保留完整句，再只把可独立理解的子句作为补充候选，避免把逗号后的半句话直接推进到 Claim 层
  - 当前 Claim 抽取会主动过滤一批明显不适合作为知识声明的噪声，例如 HTML 注释里的 `turn_id / speaker / time` 元信息、`Alice:` 这类对话发言前缀，以及纯日期标题；同时会对 `旨在`、`具体细节`、`这是一份思路文件` 这类从句或元描述降权，避免它们抢占代表陈述
  - 当正文抽不出可用 Claim、但章节标题本身是 `YYYY-MM-DD` 这样的完整日期时，系统会补一条日期型 Claim，保留时间线入口页，避免日期标题完全消失
  - 已实现两类基础 Wiki 页面：`source-summary` 与 `concept-summary`，会同步生成 `wiki/sources/*.md`、`wiki/concepts/*.md`、`state/pages.jsonl`、`wiki/index.md` 与 `wiki/log.md`
  - 当前概念页选择“代表陈述 / 核心陈述”时，不再单纯偏向更长的句子，而会优先选择更像定义、能独立理解、且更适合直接展示给人的 Claim；`一种……的模式` 这类定义短语会优先于说明性长句
  - 当前概念页展示层会把“概念名 + 定义短语”组合成更可读的代表陈述，例如 `LLM Wiki 一种利用 LLM 构建个人知识库的模式`
  - 当前概念页里的 `Source Pages / Source Evidence` 会优先用更适合人阅读的多行结构展示来源摘要页、原始来源文件、证据 chunk 和次级 ID，方便顺着 `wiki -> claim -> chunk -> source` 继续下钻
  - `wiki/index.md` 与页面间 Markdown 链接会对空格等特殊字符做 URL 编码，尽量兼容不同查看器
  - 当前 concept 聚合已改为与 claim review 更接近的归一化分组思路，减少同主题页面分裂
  - 当前已自动生成人类可读 `concept` 页与工作区级 `overview` 页，且默认渲染模式为 `llm_assisted`
  - `concept` 与 `overview` 的 LLM 改写都要求 grounded；不合格时会自动回退到 deterministic fallback
  - `overview` 页当前支持 grounded overview rewrite，并在 `llm_assisted` 成功时显示折叠式 `Rewrite Traceability`
- `myagentwiki lint`
  - 已实现仓库骨架 / 工作区结构检查，以及 `chunk_id` / `claim_id` / `page_id` 唯一性、Claim 溯源、页面记录完整性、`reviews.jsonl` / `error_log.jsonl` / `pages.jsonl` 存在性检查
  - 已补充 `canonical_id` 唯一性、alias registry 覆盖、search index 覆盖、lint 报告文件写回
- `myagentwiki query`
  - 已实现基于 `pages + claims + wiki` 产物的多字段 BM25 检索
  - 当前会综合 `title`、`aliases`、`summary`、`headings`、`body`、`claim_text`、`source_refs` 打分，并叠加页面类型权重与页面状态权重
  - 当前已接入第一版 query normalization、alias 扩展、canonical 命中回传、轻量意图识别
  - alias/title/canonical 精确命中会参与排序加权；definition/evidence 等意图会对更合适的页面类型做轻微调权
  - `evidence` 类问题会更偏向 `source-summary`，并在阅读包里优先保留可回链的 claim/chunk 证据线索
  - `compare / timeline / how_to` 也会在阅读包中返回不同 focus，帮助 Agent 判断优先读声明、时间线证据还是步骤性 chunk
  - `timeline` 类问题会额外返回按来源分组的 `timeline_sources`
  - 当前支持 `--reading-depth standard|deep`
  - `deep` 模式会在保持 deterministic 的前提下返回更厚的 `reading_pack`，并额外给出按来源聚合的 `source_trail`
  - 当前输出候选页面、得分解释、命中字段与命中 token，并返回阅读包 `reading_pack`
  - `reading_pack` 当前包含匹配的 `claims`、`chunks`、来源摘要，以及 `section_path`、`previous_chunk`、`next_chunk` 等下钻线索；`deep` 模式下还会附带 `source_trail`
- `myagentwiki review-list`
  - 已实现 review 队列查看，可列出待处理项、候选 claim、推荐动作与允许动作
- `myagentwiki review-apply`
  - 已实现最小人工裁决闭环，当前支持 `keep_both`、`archive_one`、`merge`、`edit_then_resume`、`assign_alias`、`remove_alias` 六种动作
  - `assign_alias` 当前用于 alias conflict review，可把冲突 alias 指定给某个页面并写入持久化覆盖层
  - `remove_alias` 当前用于 alias conflict review，可把冲突 alias 从覆盖层中移除
  - review 动作会把被淘汰 claim 转入历史态，并保留 `original_claim_id` 便于追踪
  - `merge` / `archive_one` 执行后，会自动清理其他仍处于 `open` 状态的 review 中已经失效的候选 claim 引用
  - `edit_then_resume` 支持“人工先修改 `claims/*.json`，再让系统从当前 review 状态继续收口”，不会要求整条 ingest 全量重跑
  - review 动作执行后会即时刷新受影响的自动页面、`state/pages.jsonl`、`wiki/index.md` 与页面检索索引

## Windows 兼容性 / Windows Compatibility

当前版本已经按这些原则实现：

- 路径统一使用 `pathlib`
- 子进程调用不依赖 `bash` / `zsh`
- `bootstrap` 直接复用当前 Python 解释器
- `raw/` 扫描支持子目录递归
- 核心标准化主路径优先采用纯 Python

当前真实边界也要说明白：

- 我们在这个仓库里已经提供了 Windows 命令示例与跨平台验证脚本
- 但本轮开发环境不是 Windows，因此这里能交付的是“面向 Windows 的实现约束、脚本和清单”，不是本机实跑截图

## 计划中的使用方式

面向最终用户的大致流程会是：

1. 在 Codex 或 Claude Code 中安装或接入 MyAgentWiki Skill
2. 准备自己的 `raw/` 原始知识目录，放在目标工作区同级
3. 运行 `init`，创建 Wiki 工程并复用或创建 sibling `raw/`
4. 使用 Agent 执行 `ingest`
5. 检查 `normalized/`、`chunks/`、`claims/`、`wiki/` 和 `state/*.jsonl` 结果，重点关注 `state/error_log.jsonl`、`state/reviews.jsonl`、`state/pages.jsonl`
6. 使用 `lint` 和 review 机制维护知识库健康
7. 使用 `query` 先查候选页面，再决定是否继续读取 claim、chunk 和 source

## 工作流验证 / Workflow Validation

为了把“能不能交给别人跑”这件事落到实处，当前仓库已经补上：

- [scripts/validate_workflow.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/scripts/validate_workflow.py)
  - 串行执行 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
  - 会自动准备一个最小 sibling `raw/` 样例资料集
  - 样例包含 `raw/` 子目录，能顺便验证递归扫描

执行方式：

```bash
python scripts/validate_workflow.py
```

如果你想保留验证生成的临时工作区：

```bash
python scripts/validate_workflow.py --keep-workspace
```

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
  - 当前来源摘要页里的 `Chunks` 列表会直接链接到对应 `chunks/<source_id>.jsonl`，并附带 `section_path` 与行号，便于继续定位证据
- `wiki/concepts/*.md`
  - 基于 Claim 聚合出的概念候选页，作为后续综述页、主题页的起点
  - 当前已加入一层轻量命名清洗，优先使用 `section_path` 和短主题短语生成更像 Wiki 的页面名
  - 当前概念页里的 `Source Pages / Source Evidence` 会分别展示来源摘要页入口、原始来源文件入口、覆盖范围，以及按条列出的证据切块链接
  - 页面文件名若包含空格等特殊字符，目录页与页面间链接会自动使用 URL 编码后的相对路径
- `wiki/overview/index.md`
  - 工作区级综述入口页，默认在有多个稳定可读概念页时自动生成
  - 当前支持 grounded 的 `llm_assisted` 摘要、主题导览和推荐阅读路径改写
  - 当 overview 改写成功时，会额外生成折叠式 `Rewrite Traceability` 区块，展示改写句与回绑页面
- `state/*.jsonl`
  - 全局索引与状态账本，包括 `sources`、`normalized`、`chunks`、`claims`、`reviews`、`pages`、`error_log`
  - 其中 `state/pages.jsonl` 会保留已被自动移除页面的历史记录，便于追踪页面演化；但 `removed` 页面不会继续进入在线检索与页面索引
- `indexes/search_pages.jsonl`
  - query 使用的页面检索派生索引，保存字段文本、tokens 和基础页面元数据
  - 当前已支持按页面级内容签名做增量复用，未变化页面会复用既有索引记录
- `indexes/aliases.json`
  - alias / canonical registry，供 query normalization、lint 和 Agent 规则共用
  - 当前会记录 live page 的 `canonical_id`、`title`、`aliases`，并标出 alias 冲突
- `reviews/*.json`
  - 需要人工确认的冲突、重复、近似重复等审核项
  - 当前 V1 使用“前缀 bucket + token 倒排召回 + 否定极性 / 文本相似度复核”来生成审核候选，优先减少明显漏检
  - 当前 alias registry 检测到同一 alias 指向多个 canonical 页面时，也会自动生成 `alias_conflict` review

当前这版最重要的是把“可追踪链路”先打通：

- Wiki 页面可以回指到 Claim
- Claim 可以回指到 Chunk 与 Source
- review 记录可以反查受影响的候选页面
- 页面索引会进入 `state/pages.jsonl`
- 冲突和重复风险会进入 `reviews/` 与 `state/reviews.jsonl`
- 查询会优先命中高价值页面类型，并给出字段级打分解释
- 查询结果已经可以附带第一版 claim/chunk/source 阅读包，方便 Agent 继续证据阅读
- `deep` 查询模式当前还能返回按来源收束的 `source_trail`，帮助 Agent 用更大的上下文窗口继续追证据，但仍保持 deterministic first
- query 已接入持久化页面检索索引，索引存在时优先读取 `indexes/search_pages.jsonl`
- query 已接入 alias registry，alias 命中时会回传 canonical 目标
- 可读 `concept` 页与 `overview` 页默认允许 `llm_assisted` 改写，但所有改写都要通过 grounded 校验，否则自动回退

## 文档说明

如果你想快速理解项目，建议阅读顺序如下：

1. `README.md`
2. `docs/MyAgentWiki系统详细设计.md`
3. `docs/runtime-deps.md`
4. `docs/project-materials/` 中的学习与工程记录
5. `docs/troubleshooting.md`

## 开发说明

V1 已经完成收口，当前仓库重点从“打通主链路”转为“保持 V1 稳定、准备 V1.1 增强”。

V1.1 可以继续推进：

- 工作区 schema 版本检查、版本守卫与显式迁移入口
  - V1.1 更适合先把“能否继续安全读写旧工作区”的判断机制建起来，而不是预先实现一个没有明确目标 schema 的通用迁移器
  - 若后续版本引入破坏性账本变更，再补具体的 `migrate` 路径、备份策略和 dry-run 机制
- 更深入的 `stable / disputed` Claim 治理
- `qa-note` 正式页面提升流程
- entity / overview 等更高层 Wiki 页面生成
- 更细的 lint 子命令与结构化日志
- Windows 真机回归验证
- 可选 Office / PDF / OCR 高保真工具集成

## 测试说明

当前仓库已经加入一组 review 回归测试：

- [tests/test_review_apply.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_review_apply.py)
  - 覆盖 `review-apply merge` 后，其他 `open review` 的候选 claim 自动改写与过期引用清理
  - 覆盖 `review-apply keep_both` 后，无其他待审项时 claim 会退出 `needs_review`
  - 覆盖 `review-apply edit_then_resume` 对人工修改后 claim 文件的重新加载与续跑

- [tests/test_normalizers.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_normalizers.py)
  - 覆盖 `.doc / .xls` 老格式 fallback
  - 覆盖图片在“无 tesseract”与“有 OCR 文本”两种情况下的标准化输出

- [tests/test_query_alias_and_lint.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_query_alias_and_lint.py)
  - 覆盖 alias/canonical 命中、intent focus、lint 报告写回
  - 覆盖 alias conflict review、`assign_alias / remove_alias`、以及 re-ingest 后的持久化行为

- [tests/test_e2e_workflow.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_e2e_workflow.py)
  - 覆盖 `init -> ingest -> query -> review -> lint` 主闭环
  - 覆盖 `raw/` 子目录递归扫描与 alias conflict 收口

建议先安装开发依赖：

```bash
python -m pip install -e ".[dev]"
```

然后执行：

```bash
python -m pytest tests
```

如果当前环境里还没有 `pytest`，也可以先执行：

```bash
python scripts/validate_workflow.py
```

## 故障排查 / Troubleshooting

常见问题请直接看：

- [docs/runtime-deps.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/runtime-deps.md)
- [docs/troubleshooting.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/troubleshooting.md)

## 许可证

本项目采用仓库中的 `LICENSE` 许可证文件。
