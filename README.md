# MyAgentWiki

MyAgentWiki 是一个面向 Codex 和 Claude Code 的本地知识编译系统（local knowledge compiler）与 Skill 仓库。它的目标不是做一次性 RAG 问答，而是让 Agent 在原始资料之上持续维护一个可追踪、可审计、可演化的个人知识 Wiki。

当前仓库既是：

- 一个可安装的 Python CLI 项目
- 一个可供 Codex / Claude Code 使用的 Skill 仓库
- 一个承载项目设计、工程决策与知识沉淀的母仓库

## 项目简介

这套系统采用“证据层 -> 语义层 -> 展示层”的分层思路组织知识：

- `raw`：工作区外部 sibling 原始资料目录，只读保留
- `normalized`：标准化后的文档中间表示
- `chunks`：切块后的证据单元
- `claims`：独立知识声明层
- `semantic decisions`：语义决策层，保存结构化语义判断
- `wiki`：最终对人可读、可链接、可维护的知识页面
- `reading_pack / answer-ready`：面向上层回答器和 Agent 的交接层

其中：

- 高频、固定、适合确定性实现的动作优先交给 Python 脚本
- 必须依赖语义理解的灰区判断交给 Agent 或 LLM
- 高风险冲突、归属不清或证据不足的场景升级为人工判断

当前项目的总原则是“确定性证据优先，按需使用语义判断（deterministic evidence first, semantic where needed）”：

- 事实层、证据层、状态层优先由脚本和显式数据结构生成
- LLM 主要参与文档结构判定、Claim 角色判定、页面意图判定和 grounded 改写
- 一切 LLM 输出都必须 grounded，无法回绑时自动回退到保守 deterministic 路径

如果只看主链路，可以先把系统理解成：

`raw -> normalized -> chunks -> claims -> semantic decisions -> reviews / stable promotion -> wiki / indexes / reading_pack / answer-ready`

同时，项目的运行定位是：

- 默认假设它会运行在 Codex 或 Claude Code 这样的 Agent 环境里
- 固定流程由 CLI 保证可重复和可回滚
- 需要语义判断的步骤优先交给 Agent / LLM hook 自动推进
- 只有在高风险冲突、归属不清或 hook 没给出高置信结论时，才升级为人工判断

## 核心理念

MyAgentWiki 不是“每次提问都从原文临时拼答案”，而是把知识逐步编译成一个持续维护的 Wiki：

- 原始资料保留不动
- 标准化层负责把不同格式整理成稳定输入
- Chunk 和 Claim 层负责证据追踪与复用
- 语义决策层负责补充脚本难以稳定给出的结构角色和页面意图
- Wiki 页面、索引、阅读包和回答交接载荷负责把证据组织成可消费视图
- Git 负责本地版本管理与回滚

这让系统可以做到：

- Wiki 结论可追踪到具体 Claim
- Claim 可追踪到具体 Chunk 和 Source
- 页面、审核单和语义决策之间可以互相回查
- 同一 Claim 可反查被哪些 Wiki 页面引用
- 冲突、重复、覆盖等高风险更新进入审核队列

## Git 边界与隐私

用户工作区默认会初始化 Git，但提交边界需要明确区分：

- sibling `raw/` 永远视为本地原始资料区，不会被 `init` 复制进工作区，也默认不纳入工作区 Git 基线。
- `init` 生成的基线提交只包含 MyAgentWiki 创建的骨架、配置、索引、账本和初始 Wiki 文件。
- `normalized/`、`chunks/`、`claims/`、`wiki/`、`reviews/`、`state/` 是否持续提交到 Git，由用户自己按隐私和协作需求决定。

如果你的资料包含敏感内容，不要因为外部 `raw/` 没进工作区 Git，就默认认为仓库可以公开。`normalized/`、`chunks/`、`claims/` 和 `wiki/` 里仍可能包含原文片段、摘要、结论或可回推出来源的信息；需要公开仓库时，请先审查这些目录，再决定是否继续纳入版本控制。

## 当前能力与边界

当前版本重点是把骨架、规则和主闭环打稳，已经完成：

- Python `3.12+` CLI 基础入口
- `raw -> normalized -> chunks -> claims -> wiki` 主链路打通
- Word、Excel、PDF、Markdown、图片五类输入的标准化优先级
- Claim 声明层
- BM25 多字段检索与页面权重设计
- review 审核队列与状态恢复机制
- Windows / macOS / Linux 兼容边界

当前仓库已通过本地测试和端到端验证：

- `python -m pytest`
  - 当前以仓库内测试套件为准；请在本地运行以获取最新通过数
- `python scripts/validate_workflow.py`
  - 覆盖 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
- `python3 -m myagentwiki lint --json`
  - 当前仓库结构检查通过
- `python3 -m myagentwiki doctor --json`
  - 必需依赖检查通过

当前 CLI 输出还有一条额外约定：

- `init / ingest / lint / query / answer-query / review-list / review-apply` 的 JSON 输出会统一带 `workspace_summary`
- `workspace_summary` 当前至少包含工作区绝对路径、入口页路径、lint 报告路径；涉及外部原始资料区的命令还会带 `raw_dir`
- 纯文本模式也会显式打印这些绝对路径，避免 UI 或上层 Agent 只显示目录名时造成“好像跑错目录”的误解

当前系统不把这些当成必须前提：

- LibreOffice
- Pandoc
- pdftotext
- tesseract

这些系统工具属于可选增强能力，缺失时应通过 `doctor` 明确提示，并采用降级策略。

需要说明的是：

- 主详细设计文档已经不再按 `V1 / V1.1 / Phase` 方式组织章节
- README 也不再把版本叙事作为首页主线
- 版本迁移、兼容动作和实施分期属于专题内容，应优先在设计文档和实施计划文档中维护

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
使用 myagentwiki skill，帮我基于当前顶层 raw/ 初始化这个知识库工作区，并只导入这个 raw/ 里的资料。
```

如果你想限制导入范围，建议在指令里直接点名资料源，例如现有顶层 `raw/`；不要只说“导入这个本地知识库”，否则上层 Agent 更容易把当前目录里的其他材料也当成候选来源。

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
使用 myagentwiki skill，围绕当前顶层 raw/ 执行 doctor、init、ingest、query 和 lint，不要把其他目录并入导入源。
```

如果已经在 MyAgentWiki 仓库或由 `init` 生成的用户工作区中，Claude Code 还会读取根目录的 `CLAUDE.md`，它会把 Claude Code 引导到共享规则 `Agent.md` 和 review / state 恢复约定。

## 文档导航

如果你想先从文档理解项目，建议先看：

- [docs/index.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/index.md)
  - 文档总入口，包含主设计、运行说明、排障文档和项目资料导航
- [docs/MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前唯一的主详细设计文档
  - 按处理流程展开系统定位、目录边界、数据模型、证据链、语义链、审核恢复链，以及 `reading_pack / answer-ready` 契约
- [docs/全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
  - LLM 协同判定专题文档，聚焦语义分析阶段、批处理原则和 grounded 边界

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
python3 -m myagentwiki doctor
python3 -m myagentwiki bootstrap --dry-run --extra dev
```

### 3. 初始化一个用户工作区

```bash
python3 -m myagentwiki init \
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
python3 -m myagentwiki ingest --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki lint --target-dir /path/to/MyNotesWiki
```

如果 Markdown 文档里包含远程图片，还需要知道这几点：

- `ingest` 会在标准化阶段尝试下载 Markdown 内的远程图片，并把文件落到工作区外部 sibling `assets/` 目录。
- `raw/` 仍是唯一默认资料源；这个 sibling `assets/` 目录只是派生附件目录，不是独立导入源。
- 下载后的图片会按 `source_id / image_index` 组织存放，不会写回 `raw/` 原文。
- 只有当 `normalized metadata` 明确记录了 `asset_path` 回链时，Agent 才应按需读取对应附件。
- 程序会先严格校验 HTTPS 证书；如果代理 / VPN 把证书链改写了，脚本会只针对“证书校验失败”自动做一次受控重试。
- 404、超时、权限不足等非证书错误不会触发这条自动回退。
- 如果确实走了这条回退路径，metadata 里会记录 `markdown_remote_image_download_used_insecure_retry` 与 `download_mode: insecure_retry`，便于后续排查。
- 如果你明确不希望脚本自动做这次回退，可以显式关闭：

```bash
python3 -m myagentwiki ingest \
  --target-dir /path/to/MyNotesWiki \
  --disable-insecure-download-retry
```

### 5. 查询与审核

```bash
python3 -m myagentwiki query "什么是知识声明层" --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki query "如何生成 wiki 页面" --reading-depth deep --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki query "什么是知识声明层" --answer-ready --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "这个结论的来源证据是什么" --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "什么是知识声明层" --format prompt --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "什么是知识声明层" --format messages --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki review-list --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki review-auto --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki review-auto --target-dir /path/to/MyNotesWiki --dry-run
python3 -m myagentwiki review-auto --target-dir /path/to/MyNotesWiki --format prompt
python3 -m myagentwiki review-auto --target-dir /path/to/MyNotesWiki --format messages
```

推荐用法：
- 想先看检索候选页和证据包时，用 `query`
- 想直接把结果交给上层回答器或 API 时，用 `answer-query`
- 想保留 `query` 的调用方式但直接拿回答层输入时，用 `query --answer-ready`
- 想让 Agent 先自动收口高把握审核项，再把剩余需要你判断的部分整理成继续对话的输入时，用 `review-auto`

### 6. 工作区兼容与迁移

```bash
python3 -m myagentwiki compat-report --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki compat-report --target-dir /path/to/MyNotesWiki --to-schema-version v2
python3 -m myagentwiki migrate --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki migrate --target-dir /path/to/MyNotesWiki --format prompt
python3 -m myagentwiki migrate --apply --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki migrate --rollback --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki migrate-schema-confirm --confirm \
  --target-dir /path/to/MyNotesWiki \
  --from-version unversioned \
  --to-version v1
python3 -m myagentwiki migrate-followups --target-dir /path/to/MyNotesWiki
```

推荐用法：
- 想先看旧工作区与当前 CLI 的兼容风险时，用 `compat-report`
- 想拿到迁移计划、风险分层和 handoff 载荷时，用 `migrate`
- schema path 被降成 `report_only` 且提示需要确认时，用 `migrate-schema-confirm`
- 想恢复最近一次迁移前的关键状态与配置时，用 `migrate --rollback`
- 更完整的迁移边界、确认账本和 follow-up 机制，建议直接看详细设计文档与实现计划文档

当前新初始化工作区默认会把审核、stable 提升、可读概念页和综述页所需的包内 Agent hook 一并接好；后续是否真的产出 `stable / concept / overview`，仍取决于 review 收口结果、hook 判定和页面生成条件：

```yaml
automation:
  mode: "safe_auto"
  post_ingest:
    review_auto: true
  review_auto:
    strategy: "agent_assisted"
    command:
      - "/absolute/path/to/python"
      - "-m"
      - "myagentwiki.agent_hook"
    timeout_seconds: 45
    min_confidence: 0.8
  stable_promotion:
    strategy: "agent_assisted"
    command:
      - "/absolute/path/to/python"
      - "-m"
      - "myagentwiki.agent_hook"
    timeout_seconds: 45
    min_confidence: 0.85

rendering:
  readable_concept:
    mode: "llm_assisted"
    command:
      - "/absolute/path/to/python"
      - "-m"
      - "myagentwiki.agent_hook"
    timeout_seconds: 20
  overview:
    mode: "llm_assisted"
    command:
      - "/absolute/path/to/python"
      - "-m"
      - "myagentwiki.agent_hook"
    timeout_seconds: 20
  concept_update:
    mode: "llm_assisted"
    command:
      - "/absolute/path/to/python"
      - "-m"
      - "myagentwiki.agent_hook"
    timeout_seconds: 20
```

如果你希望改成自己的 Agent / LLM hook，也可以在工作区 `config/project.yml` 里覆盖：

```yaml
automation:
  mode: "safe_auto"
  post_ingest:
    review_auto: true
  review_auto:
    strategy: "agent_assisted"
    command:
      - "python3"
      - "/absolute/path/to/review_hook.py"
    timeout_seconds: 45
    min_confidence: 0.9
  stable_promotion:
    strategy: "agent_assisted"
    command:
      - "python3"
      - "/absolute/path/to/stable_hook.py"
    timeout_seconds: 45
    min_confidence: 0.9
```

约定很简单：
- hook 从标准输入接收 JSON payload
- 成功时向标准输出返回 JSON
- `review_auto` hook 可返回 `decision=auto_apply`，并附带 `action`、`primary_claim_id`、`secondary_claim_id`、`primary_page_id`、`alias_value`、`confidence`
- `stable_promotion` hook 可返回 `decision=promote` 与 `confidence`
- `readable_concept` hook 可返回 `summary`、`key_points`、`practical_notes`
- `overview` hook 可返回 `summary`、`theme_rows`、`reading_path`
- `concept_update` hook 当前也会被复用于灰区概念标题判别，输入 `review_concept_candidate` 任务，输出 `decision=accept|reject|rename`，并可附带 `suggested_title`
- 若 hook 失败、超时、低于置信阈值，系统会按当前环节回退到保守路径，而不是中断整个流程：
- `review_auto / stable_promotion` 会保留原状或升级为人工判断项
- `readable_concept / overview` 会回退到 deterministic render

如果 `automation.post_ingest.review_auto: true`，那么每次 `ingest` 结束后，系统会自动接着跑一轮 `review-auto`。
这意味着默认推荐流程会尽量串成一条连续自动化链：
- `ingest` 负责发现新 claim、重建页面、刷新索引
- 如果这次没有新 source，但 `claim_role` 写回改动了某组 claim 的 `knowledge_role / page_intent_hints / concept_candidate_score`，`ingest` 仍会把它视作上游变化，继续重跑对应 bucket 的页面路由与旧页清理，而不是误判为“无变化可跳过”
- `review-auto` 会优先自动收口高把握 review，并尝试提升可安全稳定化的 claim
- 当 claim 真正被提升为 `stable` 后，系统会继续自动生成或刷新可读 `concept` 页
- 当工作区里已有多个稳定可读概念页时，系统会继续自动生成或刷新工作区级 `overview` 页
- `concept` 与 `overview` 默认都会先尝试 grounded 的 `llm_assisted` 改写；若不满足校验或生成条件，会回退到 deterministic fallback，或暂不产出对应页面
- 只有仍然 escalated 的 review 才需要人工判断

如果你主要是在 Codex 或 Claude 这类 Agent 界面里使用，推荐把它当成“我描述目标，Agent 负责执行流程”的工具，而不是自己记内部命令或状态结构。

用户通常不需要重复说明查询规则。像“先看候选页面”“需要时继续回读证据”“有风险就明确提示不确定性”这些行为，本来就应该由 Agent 按 MyAgentWiki 约定自动完成。

可以直接这样说：

```text
请用 MyAgentWiki 帮我查一下：什么是知识声明层？
如果有不确定或待确认的地方，直接告诉我。
```

```text
请用 MyAgentWiki 帮我回答：这个结论的来源证据是什么？
回答时把证据链一起整理出来。
```

```text
请帮我看看当前有哪些待处理审核项，
按“是什么问题、为什么需要我判断、你建议怎么处理”给我总结一下。
```

```text
请处理这条审核单：review_id=...
如果你已经能判断怎么处理，就直接给我一个简单建议；
如果需要我决定，就用白话告诉我几个选项分别代表什么。
```

如果你想自己参与审核判断，也可以直接用白话说：

```text
这两条看起来像是在说同一件事，帮我合并成一条更清楚的结论。
```

```text
这两条虽然相似，但我觉得都应该保留，请帮我都保留下来。
```

```text
这两条里有一条应该淘汰，请帮我保留更准确的那条，并把另一条归档。
```

```text
我想先手工改一下这条 claim，改完之后你再继续把审核流程收口。
```

上面几句话在系统里大致对应这些处理方式：
- “合并成一条更清楚的结论” = `merge`
- “两条都保留” = `keep_both`
- “保留一条，另一条归档” = `archive_one`
- “我先手工改，再继续流程” = `edit_then_resume`

Agent 使用约定：
- 用户只需要表达目标，不需要记 `reading_pack`、`state/*.jsonl`、`review-apply` 这些内部结构
- 查询时，Agent 应先读页面摘要、命中解释和 `reading_pack`，不要把首条命中直接当最终答案
- 需要给上层回答器准备输入时，Agent 应优先使用 `answer-query` 或 `query --answer-ready`
- 需要给上层 Agent 准备“审核自动处理 + 剩余人工判断”的输入时，Agent 应优先使用 `review-auto --format prompt|messages|chatml`
- 审核前，Agent 应先读取 `state/reviews.jsonl` 与 `reviews/*.json`，再整理成适合人判断的白话说明
- 若希望先自动处理高把握审核项，Agent 应优先尝试 `review-auto`；只有 `agent_brief.should_ask_user=true` 时，再围绕 `escalation_handoff` 向用户追问
- 不直接批量手改 `state/*.jsonl`，统一通过 `review-apply`、`ingest`、`lint` 收敛状态

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

## 当前 CLI 命令实现状态

当前已实现这些命令入口：

- `myagentwiki init`
- `myagentwiki ingest`
- `myagentwiki query`
- `myagentwiki answer-query`
- `myagentwiki lint`
- `myagentwiki doctor`
- `myagentwiki bootstrap`
- `myagentwiki review-list`
- `myagentwiki review-apply`
- `myagentwiki review-auto`
- `myagentwiki compat-report`
- `myagentwiki migrate`
- `myagentwiki migrate-decisions`
- `myagentwiki migrate-followups`
- `myagentwiki migrate-schema-confirm`
- `myagentwiki semantic-batch`

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
  - 扫描 `raw/` 时当前会统一跳过所有 `.` 开头的文件和目录，例如 `.DS_Store`、`.obsidian/` 及其子内容，不把这些隐藏项纳入 ingest
  - 当前 Markdown 标准化会尝试下载内嵌的远程图片，并把下载结果落到工作区外部 sibling `assets/` 目录；图片存储路径按 `source_id / image_index` 组织，便于后续回链
  - 远程图片下载会先严格校验证书；若命中证书校验失败，脚本会默认只对 Markdown 图片下载自动重试一次不校验证书的受控回退；如需关闭该行为，可显式传入 `--disable-insecure-download-retry`
  - 当前规则式 Claim 草稿抽取采用“整句优先，子句只作候选补充”的策略：先保留完整句，再只把可独立理解的子句作为补充候选，避免把逗号后的半句话直接推进到 Claim 层
  - 当前 Claim 抽取会主动过滤一批明显不适合作为知识声明的噪声，例如 HTML 注释里的 `turn_id / speaker / time` 元信息、`Alice:` 这类对话发言前缀，以及纯日期标题；同时会对 `旨在`、`具体细节`、`这是一份思路文件` 这类从句或元描述降权，避免它们抢占代表陈述
  - 当正文抽不出可用 Claim、但章节标题本身是 `YYYY-MM-DD` 这样的完整日期时，系统会补一条日期型 Claim，保留时间线入口页，避免日期标题完全消失
  - 当前已经实现来源视图页与可读概念页，并会同步生成对应页面、`state/pages.jsonl`、`wiki/index.md` 与 `wiki/log.md`
  - 当前概念页选择“代表陈述 / 核心陈述”时，不再单纯偏向更长的句子，而会优先选择更像定义、能独立理解、且更适合直接展示给人的 Claim；`一种……的模式` 这类定义短语会优先于说明性长句
  - 当前概念页展示层会把“概念名 + 定义短语”组合成更可读的代表陈述，例如 `LLM Wiki 一种利用 LLM 构建个人知识库的模式`
  - 当前概念页里的 `Source Pages / Source Evidence` 会优先用更适合人阅读的多行结构展示来源摘要页、原始来源文件、证据 chunk 和次级 ID，方便顺着 `wiki -> claim -> chunk -> source` 继续下钻
  - 当前概念页生成已加入四层收口规则：先用强规则过滤明显坏标题，再做标题质量评分；灰区候选才会交给 Agent hook 做受限判别；最终 `lint` 会把低质量概念标题显式报成 warning
  - 强规则当前会优先拦截 `示例`、`总结`、单字中文标题、问句壳标题这类明显更像结构节点而不是概念名的候选，减少“章节标题被误生成为概念页”
  - 标题质量评分会综合标题本身、canonical claim 可读性、是否跨来源、是否只是 topic shell、是否像定义句等信号，避免继续单纯依赖 `section_path` 最后一段命名
  - 灰区标题当前只允许 Agent hook 返回 `accept / reject / rename` 这三种受限决策，不直接把自由生成的标题写成 canonical，优先保证 `canonical_id` 稳定
  - `wiki/index.md` 与页面间 Markdown 链接会对空格等特殊字符做 URL 编码，尽量兼容不同查看器
  - 当前 concept 聚合已改为与 claim review 更接近的归一化分组思路，减少同主题页面分裂
  - 当前已支持自动生成人类可读 `concept` 页；工作区级 `overview` 页会在满足生成条件时自动产出，两个页面族默认都会先尝试 `llm_assisted` 渲染
  - 当前新初始化工作区默认已经接上统一包内 Agent hook，目标是让 `ingest -> review-auto -> stable -> concept/overview` 作为一条连续自动化链默认运行，而不需要用户再手工补配置
  - `concept` 与 `overview` 的 LLM 改写都要求 grounded；不合格时会自动回退到 deterministic fallback
  - `overview` 页当前支持 grounded overview rewrite，并在 `llm_assisted` 成功时显示折叠式 `Rewrite Traceability`
- `myagentwiki lint`
  - 已实现仓库骨架 / 工作区结构检查，以及 `chunk_id` / `claim_id` / `page_id` 唯一性、Claim 溯源、页面记录完整性、`reviews.jsonl` / `error_log.jsonl` / `pages.jsonl` 存在性检查
  - 已补充 `canonical_id` 唯一性、alias registry 覆盖、search index 覆盖、lint 报告文件写回
  - 当前已新增 `concept_pages_title_quality` warning，用于显式标出“标题像结构词、过短、问句壳、或整体质量过低”的概念页
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
  - JSON 输出当前会统一附带 `workspace_summary`，便于上层 Agent 直接拿到工作区绝对路径、入口页和 lint 报告路径
  - 纯文本输出当前也会先打印 `Workspace / Entry page / Lint report` 这类绝对路径摘要，再展开候选结果
  - `query --answer-ready` 和 `answer-query` 会把 `reading_pack.answer_handoff` 渲染成给上层 Agent 直接消费的回答就绪摘要，显式返回推荐读序、必读证据路径、风险标记与降级动作
  - `--format prompt` 会进一步把回答就绪摘要压成可直接喂给上层 LLM/Agent 的 prompt block；JSON 模式下也会附带 `prompt_text`
  - `--format messages` 会返回可直接传给聊天 API 的 messages 数组；`--format chatml` 会同时返回 messages 和 ChatML 文本
  - answer-ready 输出当前使用独立版本 `answer_ready_query/v1`，与底层 `query_answer_handoff/v1` 分层演进
- `myagentwiki review-list`
  - 已实现 review 队列查看，可列出待处理项、候选 claim、推荐动作与允许动作
  - JSON 输出当前会附带 `workspace_summary`，纯文本输出会先打印工作区绝对路径摘要，降低多工作区场景下的路径歧义
  - 当前会先按最新 `state/pages.jsonl + indexes/aliases.json` 真实状态刷新 alias conflict 队列；已不再存在的 alias 冲突会自动从 active/open 视图收口到历史态，避免过期记录误导人工判断
- `myagentwiki review-apply`
  - 已实现最小人工裁决闭环，当前支持 `keep_both`、`archive_one`、`merge`、`edit_then_resume`、`assign_alias`、`remove_alias` 六种动作
  - `assign_alias` 当前用于 alias conflict review，可把冲突 alias 指定给某个页面并写入持久化覆盖层
  - `remove_alias` 当前用于 alias conflict review，可把冲突 alias 从覆盖层中移除
  - `assign_alias / remove_alias` 当前会先在内存里预演 alias 覆盖结果并重建 alias index；只有确认 alias 真正完成唯一归属或被完全清除时，命令才会成功，避免“命令成功但冲突仍存在”
  - `assign_alias / remove_alias` 写入 `state/page_alias_overrides.json` 时当前会做进程级串行化，避免多个 `review-apply` 并发时后写覆盖前写
- `myagentwiki review-auto`
  - 已实现一条保守自动审核路径：优先自动收口高把握 review，并把剩余需要人判断的项整理成可继续对话的 handoff
  - 当前会复用既有 `review-apply`、页面重建和状态账本收敛逻辑，不单独维护第二套审核状态机；review-auto 触发的页面重建也会继续走统一的 `page_intent` 路由，而不是只回填旧的 concept family
  - 当前支持 `--dry-run`，可先看计划中的自动动作与升级人工项，再决定是否执行
  - 当前支持 `--format prompt|messages|chatml`，可直接生成给上层 Agent 使用的 handoff；JSON 模式下会附带 `prompt_text`、`messages` 或 `chatml_text`
  - 当前会额外返回 `agent_brief`、`agent_summary` 和 `escalation_handoff`，帮助 Agent 判断“是否需要追问用户”以及“应该如何用白话解释选项”
  - review 动作会把被淘汰 claim 转入历史态，并保留 `original_claim_id` 便于追踪
  - `merge` / `archive_one` 执行后，会自动清理其他仍处于 `open` 状态的 review 中已经失效的候选 claim 引用
  - `edit_then_resume` 支持“人工先修改 `claims/*.json`，再让系统从当前 review 状态继续收口”，不会要求整条 ingest 全量重跑
  - JSON 输出当前会附带 `workspace_summary`，纯文本输出会显式打印工作区绝对路径与当前处理的 review 标识
  - review 动作执行后会即时刷新受影响的自动页面、`state/pages.jsonl`、`wiki/index.md` 与页面检索索引
- `myagentwiki compat-report`
  - 已实现工作区兼容性检查与迁移候选收口，统一返回 schema migration 与 compatibility cleanup 两类候选
  - 当前会输出 `action_catalog`、`schema_guard`、`target_schema_version`、`schema_registry` 诊断，以及 `auto_plan / report_only` 风险分层
  - 当前支持显式 `--to-schema-version`，可直接面向已知未来版本做 path planning
- `myagentwiki migrate`
  - 已实现 `--plan`、`--apply`、`--rollback` 三种模式
  - 当前 `--apply` 会先写 migration report 和 backup snapshot，再执行 schema migration / compatibility cleanup
  - 当前 `--rollback` 可恢复最近一次或指定 backup dir 的关键状态文件与配置
  - 当前 `--format prompt|messages|chatml` 只面向 `report_only` 灰区输出 handoff，不会把确定性 `apply_supported` 动作重新交给 LLM 判定
  - 当前计划输出会把 schema migration 放在前面，并显式区分“目标版本未知”“目标版本已知但 path 未注册”“path 需确认”“path 可自动规划”
- `myagentwiki migrate-schema-confirm`
  - 已实现显式确认型 schema path 的 ledger 收口
  - 当前确认记录写入 `state/schema_confirmations.jsonl`，后续重新规划时可把对应 schema path 从 `report_only` 恢复到 `auto_plan`
- `myagentwiki migrate-decisions`
  - 已实现外部 Agent / LLM 返回的 migration 灰区判断 ingest 与 apply
  - 当前标准化结果写入 `state/migration_decisions.jsonl`，而不是直接跳过账本改状态
- `myagentwiki migrate-followups`
  - 已实现 migration follow-up queue 的列出、完成和提升为 review
  - 当前 follow-up queue 写入 `state/migration_followups.jsonl`
- `myagentwiki semantic-batch`
  - 已实现 `document_analysis / claim_role / page_intent` 三类语义批处理入口
  - 当前支持批处理、缓存命中、dry-run 和统一语义账本写回
  - `page_intent` 的缓存命中当前会显式依赖 claim 侧的 `knowledge_role / page_intent_hints / concept_candidate_score`；如果 `claim_role` 结果发生变化，对应页面路由会自动失效重算，而不会继续沿用旧的页型判断

## Windows 兼容性 / Windows Compatibility

当前版本已经按这些原则实现：

- 路径统一使用 `pathlib`
- 子进程调用不依赖 `bash` / `zsh`
- `bootstrap` 直接复用当前 Python 解释器
- `raw/` 扫描支持子目录递归
- `raw/` 扫描会跳过所有 `.` 开头的文件和目录
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
  - 当前 alias conflict review 若已不再对应真实 alias 冲突，会在 `review-list / review-apply / ingest` 的收口过程中自动转入历史态，而不是继续保留为 active/open

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
3. `docs/全链路规则与LLM协同判定设计.md`
4. `docs/全链路重构实现计划.md`
5. `docs/runtime-deps.md`
6. `docs/project-materials/` 中的学习与工程记录
7. `docs/troubleshooting.md`

## 开发说明

当前仓库重点已经从“先打通主链路”转为“保持主闭环稳定，并继续把语义层、页面层和迁移层收口得更清楚”。

接下来适合继续推进的方向包括：

- 更真实的未来 schema transition 定义与对应 action handler
  - 当前迁移骨架、风险分层、confirmation ledger、decision/followup ledger 和 registry 自校验都已经具备
  - 但当前仍只内建最小 `unversioned -> v1` schema 升级动作；未来 `v2 / v3` 仍需要等真实 schema 变更出现后再补定向 transition
- 更深入的 `stable / disputed` Claim 治理
- `qa-note` 正式页面提升流程
- entity / overview 等更高层 Wiki 页面生成与统一页面族谱收口
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
  - 覆盖 alias conflict review、`assign_alias / remove_alias`、re-ingest 后的持久化行为，以及过期 alias review 自动收口

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
