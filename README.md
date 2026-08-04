# MyAgentWiki

MyAgentWiki 是一个面向 Codex 的本地知识编译系统（local knowledge compiler）与 Skill 仓库。它的目标不是做一次性 RAG 问答，而是让 Agent 在原始资料之上持续维护一个可追踪、可审计、可演化的个人知识 Wiki。

新工作区默认启用统一 LLM 调度器：先请求在线客户端；在线配置缺失、不可用或重试仍失败时，自动改用 Codex CLI 客户端。语义批处理、审核和页面生成等直接调用线路的流程会在两条线路都失败时以非零状态结束；Markdown 内嵌图片属于单附件降级边界，图片理解失败时会保留正文、图片占位和告警。

在线客户端读取当前用户单独填写的 `.env`。这份文件不应提交到 Git，仓库只提供 `.env.example`。没有在线配置时无需中断配置流程，调度器会直接尝试 CLI 客户端。完全不使用 LLM 时，必须把相关任务显式设为 `deterministic`。

当前仓库既是：

- 一个可安装的 Python CLI 项目
- 一个可供 Codex 使用的 Skill 仓库
- 一个承载项目设计、工程决策与知识沉淀的母仓库

## 项目简介

这套系统采用“证据层 -> 语义层 -> 展示层”的分层思路组织知识：

- `raw`：工作区外部 sibling 原始资料目录，只读保留
- `normalized`：标准化后的文档中间表示
- `structure_blocks / evidence_blocks / knowledge_units`：结构化证据与候选知识对象层
- `chunks`：检索、摘要、相邻上下文和增量处理用的粗粒度容器
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
- LLM 主要参与文档结构判定、Claim 质量与角色判定、页面意图、自动审核、Claim 提稳、概念标题复核、grounded 改写和图片理解
- 一切 LLM 输出都必须经过 Function Calling 合同、JSON 修复、Schema 和业务检查；直接依赖该结果的流程在主备结果都无效时失败，Markdown 内嵌图片按单附件降级规则继续处理正文

如果只看主链路，可以先把系统理解成：

`source -> normalized -> structure_block -> evidence_block -> knowledge_unit -> claim / metadata -> semantic decisions -> reviews / stable promotion -> page / indexes / reading_pack / answer-ready`

同时，项目的运行定位是：

- 默认假设它会运行在 Codex 这样的 Agent 环境里
- 固定流程由 CLI 保证可重复和可回滚
- 需要语义判断的步骤由 LLM 调度器自动选择在线主线路或 CLI 备用线路
- 高风险冲突、归属不清或模型明确给出低置信结论时升级为人工判断；线路错误不会伪装成人工判断结果

## 核心理念

MyAgentWiki 不是“每次提问都从原文临时拼答案”，而是把知识逐步编译成一个持续维护的 Wiki：

- 原始资料保留不动
- 标准化层负责把不同格式整理成稳定输入
- Evidence Block、Knowledge Unit 和 Claim 层负责精确证据追踪与复用
- Chunk 层负责检索召回、摘要、相邻上下文和增量处理，不再作为最小证据原子
- 语义决策层负责补充脚本难以稳定给出的结构角色和页面意图
- Wiki 页面、索引、阅读包和回答交接载荷负责把证据组织成可消费视图
- Git 负责本地版本管理与回滚

这让系统可以做到：

- Wiki 结论可追踪到具体 Claim
- Claim 可追踪到 Knowledge Unit、Evidence Block 和 Source，并可按需回到匹配 Chunk 补足上下文
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
- `source -> normalized -> structure_block -> evidence_block -> knowledge_unit -> claim / metadata -> page` 主证据链打通，并保留 chunk 作为检索和增量处理容器
- MarkItDown 统一文档转换，以及 Markdown、图片的专用标准化路径
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

当前仓库还包含一套“真实用户工程形态”的本地测试实验场：

- `python3 scripts/run_user_workspace_lab.py --clean --scenario baseline`
  - 在 `tests/runtime/user_project_lab/` 下本地生成 `raw/`、`assets/`、`workspace/`、`reports/`
  - 覆盖 `init -> ingest -> query -> review-list -> lint` 主闭环
  - 覆盖原始资料更新 / 新增、Markdown 表格与本地图片混排、中文为主少量英文混编、页面关联扩展读取
- 这套实验场的定义文件保留在 `tests/fixtures/user_project_lab/`
- 运行时产生的完整派生数据与结果数据只保留在本地 runtime 目录，不提交到 Git

当前 CLI 输出还有一条额外约定：

- `init / ingest / lint / query / answer-query / semantic-batch / review-list / review-auto / review-apply` 的 JSON 输出会统一带 `workspace_summary`
- `workspace_summary` 当前至少包含工作区绝对路径、入口页路径、lint 报告路径；涉及外部原始资料区的命令还会带 `raw_dir`
- 纯文本模式也会显式打印这些绝对路径，避免 UI 或上层 Agent 只显示目录名时造成“好像跑错目录”的误解

当前 query / answer-ready 输出还新增了一层页面关联扩展约定：

- 工作区会生成 `indexes/page_links.json`
- `state/pages.jsonl` 中的 live 页面会补充：
  - `outgoing_page_ids`
  - `incoming_page_ids`
  - `related_page_ids`
- `query` / `answer-query` 支持 `--link-expansion off|auto|deep`
- `reading_pack` 会补充：
  - `linked_pages`
  - `retrieval_context.link_expansion_used`
  - `retrieval_context.link_expansion_reason`
  - `retrieval_context.linked_page_paths`

这层扩展不是替代 `alias / canonical / hierarchy / source_refs`，而是在这些已有证据链之上补充“页面之间还应该继续读什么”。

当前文档转换不要求安装 LibreOffice、Pandoc 或 pdftotext。PDF、Word、Excel、PowerPoint、HTML、JSON/XML、ZIP、EPUB、Outlook 等常见文档格式默认先通过 [microsoft/markitdown](https://github.com/microsoft/markitdown) 及其 Python 依赖处理，失败后再进入已有备用转换器。

`tesseract` 只作为图片 OCR 的可选增强工具；缺失时由 `doctor` 明确提示。独立 `raw/` 图片当前保留元数据占位，Markdown 内嵌图片则可按配置尝试 LLM 图片理解。

需要说明的是：

- 主详细设计文档已经不再按 `V1 / V1.1 / Phase` 方式组织章节
- README 也不再把版本叙事作为首页主线
- 当前仓库以 `3.1.0` 作为当前正式发布版本；`2.0.0` 是首个正式发布版本。当前不提供旧页型或账本 schema 的自动迁移流程；旧 LLM 任务级 `command` 配置只会被识别并返回人工迁移提示，不会被继续执行或自动改写

## Skill 安装与接入 / Skill Installation

当前仓库已经是一个可安装 / 可引用的 Skill 仓库，包含：

- [SKILL.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/SKILL.md)
- [agents/openai.yaml](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/agents/openai.yaml)
- [Agent.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/Agent.md)
- [AGENTS.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/AGENTS.md)

这意味着它可以被 Codex 作为一个包含 `SKILL.md` 的目录加载。推荐优先用软链接 / 目录链接安装，这样仓库更新后 Skill 会同步生效。

面向 Agent 的核心约束是：

- 固定流程优先执行 CLI
- 证据追踪优先走 `page -> claim -> knowledge_unit -> evidence_block -> source`，必要时再读取匹配 chunk 补足上下文
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

如果 Codex 要触发脚本里的在线模型调用链路，也应先检查当前工作区是否已经配置 `.env`；未配置时应先提醒补配，而不是把 API-Key 写进仓库跟踪文件。

## 文档导航

如果你想先从文档理解项目，建议先看：

- [docs/index.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/index.md)
  - 文档总入口，包含主设计、运行说明、排障文档和项目资料导航
- [RELEASING.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/RELEASING.md)
  - 仓库正式发版流程、版本策略和发布后检查清单
- [docs/MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 当前唯一的主详细设计文档
  - 按处理流程展开系统定位、目录边界、数据模型、证据链、语义链、审核恢复链，以及 `reading_pack / answer-ready` 契约
- [docs/全链路规则与LLM协同判定设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路规则与LLM协同判定设计.md)
  - LLM 协同判定专题文档，聚焦语义分析阶段、批处理原则和 grounded 边界

- [docs/调试模式与全链路追踪设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/调试模式与全链路追踪设计.md)
  - 工作区调试目录、步骤与数据关系格式、完整快照、LLM 请求记录、保留策略和安全边界

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
python3 -m myagentwiki query "什么是知识声明层" --intent definition --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki query "如何生成 wiki 页面" --intent how_to --reading-depth deep --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki query "什么是知识声明层" --intent definition --answer-ready --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "这个结论的来源证据是什么" --intent evidence --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "什么是知识声明层" --intent definition --format prompt --target-dir /path/to/MyNotesWiki
python3 -m myagentwiki answer-query "什么是知识声明层" --intent definition --format messages --target-dir /path/to/MyNotesWiki
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

当前新初始化工作区会为十个已实现任务启用统一 LLM 调度器。任务配置只声明策略、合同任务名、超时、置信度和批次参数，不再配置 Python 命令或指定某条线路：

```yaml
llm:
  contract_version: "v2"
  routing:
    primary: "online"
    fallback: "cli"
  retry:
    online_max_retries: 2
    backoff_seconds: [1.0, 2.0]
    jitter_max_seconds: 0.25
    http_statuses: [408, 409, 429]
    http_status_min: 500
  context:
    document_max_chars: 24000
    image_max_bytes: 20971520
    image_mime_types: ["image/png", "image/jpeg", "image/webp", "image/gif"]
  cli:
    executable: "codex"
    timeout_seconds: 120
    model: ""

automation:
  mode: "safe_auto"
  post_ingest:
    review_auto: true
  review_auto:
    strategy: "llm_assisted"
    task_name: "review_auto_decision"
    timeout_seconds: 45
    min_confidence: 0.8
  stable_promotion:
    strategy: "llm_assisted"
    task_name: "claim_stable_promotion"
    timeout_seconds: 45
    min_confidence: 0.85

rendering:
  readable_concept:
    mode: "llm_assisted"
    task_name: "render_readable_concept_page"
    timeout_seconds: 20
  overview:
    mode: "llm_assisted"
    task_name: "render_workspace_overview_page"
    timeout_seconds: 20
```

线路顺序固定如下：

- 在线客户端每个逻辑请求最多执行三次，即首次加两次重试。
- 连接失败、超时、HTTP 408/409/429、5xx 和结果合同错误可重试。
- 其他 4xx、在线配置错误和 TLS 配置错误跳过剩余在线尝试，立即改用 CLI 客户端。
- CLI 客户端只执行一次。主备都失败时抛出 `LLMRouteError`，不返回空结果，也不调用确定性处理器掩盖失败。
- 不同逻辑请求之间没有额外等待；每个逻辑请求创建并关闭自己的在线客户端。

在线客户端存在有效配置时优先使用；配置缺失时直接尝试 Codex CLI。CLI 可通过下面的环境变量调整：

```bash
export MYAGENTWIKI_CODEX_MODEL="gpt-5.1-codex"
export MYAGENTWIKI_CODEX_BIN="codex"
export MYAGENTWIKI_CODEX_TIMEOUT_SECONDS="120"
```

OpenAI 兼容 `.env` 示例：

```dotenv
MYAGENTWIKI_LLM_PROTOCOL="openai_compatible"
MYAGENTWIKI_LLM_BASE_URL="https://example.com/v1"
MYAGENTWIKI_LLM_MODEL="your-model-name"
MYAGENTWIKI_LLM_API_KEY="your-api-key"
MYAGENTWIKI_LLM_TIMEOUT_SECONDS="120"
MYAGENTWIKI_LLM_API_STYLE="responses"
MYAGENTWIKI_LLM_VERIFY_SSL="true"
```

`transport.api_style` 支持 `responses` 和 `chat_completions`，默认 `responses`。两者都强制唯一函数调用、关闭并行调用并使用非流式请求。CLI 客户端使用同一参数 Schema，通过 `codex exec --output-schema` 返回 `function_name + arguments_json`；图片用 `-i` 传入绝对路径。

函数参数先经 `json_repair.loads` 处理常见 JSON 问题，再使用同一份 JSON Schema 和任务业务规则检查。十个已实现合同见 [LLM 主备线路与 Function Calling 设计](docs/LLM主备线路与Function%20Calling设计.md)。`qa_note`、`concept_update` 尚无实际合同，因此保持禁用。

如需完全离线、确定性执行，可把具体任务的 `strategy` 或 `mode` 显式改为 `deterministic`。旧工作区中的任务级 `command` 不再执行；加载器会针对三个已知旧模块给出迁移建议，自定义命令必须人工选择新线路或确定性模式。

- 默认 `safe_auto` 提稳不再要求多个独立来源；单一来源的 claim 只要可追踪、无开放 review / duplicate / conflict，且文本本身不是明显碎片或噪声，也可以提升为 `stable`
- 对短句 / 短 claim，系统当前不再主要依赖固定字符数阈值；脚本只过滤明显垃圾，短句灰区会进入 `claim_candidate_quality` 语义批处理，由函数合同返回 `quality_label / review_required / safe_auto_ready` 等结构化结论

如果 `automation.post_ingest.review_auto: true`，那么每次 `ingest` 结束后，系统会自动接着跑一轮 `review-auto`。
这意味着默认推荐流程会尽量串成一条连续自动化链：
- `ingest` 负责发现新 claim、重建页面、刷新索引
- 如果这次没有新 source，但 `claim_role` 写回改动了某组 claim 的 `knowledge_role / page_intent_hints / concept_candidate_score`，`ingest` 仍会把它视作上游变化，继续重跑对应 bucket 的页面路由与旧页清理，而不是误判为“无变化可跳过”
- `review-auto` 会优先自动收口高把握 review，并尝试提升可安全稳定化的 claim
- 当 claim 真正被提升为 `stable` 后，系统会继续自动生成或刷新可读 `concept` 页
- 当工作区里已有多个稳定可读概念页时，系统会继续自动生成或刷新工作区级 `overview` 页
- `concept` 与 `overview` 默认都会先尝试 grounded 的 `llm_assisted` 改写；函数结果通过合同后，如果页面级 grounding 仍不足，使用确定性页面模板；若主备请求本身都失败，命令直接失败
- 只有仍然 escalated 的 review 才需要人工判断

如果你主要是在 Codex 这类 Agent 界面里使用，推荐把它当成“我描述目标，Agent 负责执行流程”的工具，而不是自己记内部命令或状态结构。

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

## 当前仓库主要结构

```text
MyAgentWiki/
├── Agent.md
├── AGENTS.md
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
│       ├── cli.py
│       ├── cli_parser.py
│       ├── cli_components/
│       ├── app_services/
│       ├── repositories/
│       ├── deterministic_processor.py
│       └── llm/
│           ├── contracts.py
│           ├── online_client.py
│           ├── cli_client.py
│           ├── router.py
│           ├── repair.py
│           ├── errors.py
│           └── diagnostics.py
├── templates/
├── tests/
└── scripts/
```

主要文件说明：

- `docs/MyAgentWiki系统详细设计.md`
  - 当前版本的详细设计主文档

- `Agent.md`
  - 共享 Agent 核心规则源

- `AGENTS.md`
  - Codex 入口适配文件

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
- `markitdown[docx,pdf,pptx,xls,xlsx,outlook]>=0.1.6,<0.2.0`，以及 `pyproject.toml` 声明的转换、图片、LLM、JSON 修复和 Schema 校验依赖

目标平台：

- Windows 11+
- macOS
- 主流 Linux 发行版

可选增强依赖：

- `tesseract`

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
- `myagentwiki render-page`
- `myagentwiki semantic-batch`
- `myagentwiki claim-set-status`
- `myagentwiki debug-list`
- `myagentwiki debug-show`

除 `init / doctor / bootstrap` 外，上述工作区业务命令都支持 `--debug`。启用后，本次运行会在命令结果中附带 `debug_run`，并把完整记录写到工作区 `logs/debug/<run_id>/`。其中 `record_complete` 用于区分业务状态与调试记录本身是否完整。

常用查看方式：

```bash
python3 -m myagentwiki ingest --target-dir /path/to/workspace --debug
python3 -m myagentwiki debug-list --target-dir /path/to/workspace
python3 -m myagentwiki debug-show --target-dir /path/to/workspace --run-id latest
python3 -m myagentwiki debug-show --target-dir /path/to/workspace --run-id latest --source-id <source_id> --json
```

调试目录默认保留 7 天，由工作区 `config/project.yml` 的 `debug.retention_days` 控制。记录含完整文本和结构化中间数据，属于敏感资料；模板已将 `logs/debug/` 加入 Git 忽略。API Key、认证头和已知凭据值会被排除或替换，原始二进制文件只记录路径、大小、类型和哈希，不复制内容。

当前实现状态：

- `myagentwiki render-page`
  - 当前公开支持的 render target 为 `readable_concept / guide / duty / example / topic / reference / timeline / overview`
  - `qa_note / concept_update` 仍属于内部保留配置名，不作为当前正式 CLI 入口对外暴露

- `myagentwiki claim-set-status`
  - 支持把 active Claim 更新为 `draft / stable / disputed / needs_review`
  - 状态更新后会重建受影响页面；历史态 Claim 不允许通过该命令直接改写

- `myagentwiki doctor`
  - 已实现运行环境检查、Python 包检查、可选系统工具检查
  - 已输出 Windows / macOS / Linux 的推荐自举命令示例
- `myagentwiki bootstrap`
  - 已实现 Python 依赖安装与 `--dry-run`
  - 当前直接调用运行中的 Python 解释器，不依赖 shell 专属语法
- `myagentwiki init`
  - 已实现工作区初始化、模板生成、状态文件创建、Git 基线提交
  - 当前会初始化 `indexes/aliases.json`、工作区级 `AGENTS.md`、以及 query/agent 基础配置
- `myagentwiki ingest`
  - 已实现 `raw/` 递归扫描、来源登记、MarkItDown 统一文档转换、Markdown/纯文本专用标准化、图片元数据与 `tesseract` OCR 增强、Structure IR / Evidence Block / Knowledge Unit 编译、chunk 上下文容器生成、规则式 Claim 草稿抽取、review 项生成，以及失败/降级信息写入 `state/error_log.jsonl`
  - PDF、DOCX、XLS/XLSX、CSV、PPTX、HTML、JSON/XML、ZIP、EPUB、IPYNB、Outlook MSG 等非 Markdown 文档默认先走 `MarkItDown.convert_local()`；插件默认关闭，不会自动连接云服务
  - MarkItDown 转换失败时，已存在的 PDF、Word、Excel 保守转换器才会接手，并在 `warnings` 中记录 `markitdown_conversion_failed:<错误类型>`
  - 每次导入会核对 `normalizer_version`；MarkItDown 结果还会核对转换器版本。版本变化时即使原文件内容未变，也会复用原 `source_id` 重新生成该来源及其下游数据
  - 扫描 `raw/` 时当前会统一跳过所有 `.` 开头的文件和目录，例如 `.DS_Store`、`.obsidian/` 及其子内容，不把这些隐藏项纳入 ingest
  - 当前 Markdown 标准化会尝试下载内嵌的远程图片，并把下载结果落到工作区外部 sibling `assets/` 目录；图片存储路径按 `source_id / image_index` 组织，便于后续回链
  - 远程图片下载会先严格校验证书；若命中证书校验失败，脚本会默认只对 Markdown 图片下载自动重试一次不校验证书的受控回退；如需关闭该行为，可显式传入 `--disable-insecure-download-retry`
  - 当前规则式 Claim 草稿抽取采用“整句优先，子句只作候选补充”的策略：先保留完整句，再只把可独立理解的子句作为补充候选，避免把逗号后的半句话直接推进到 Claim 层
  - 当前 Claim 抽取会主动过滤一批明显不适合作为知识声明的噪声，例如 HTML 注释里的 `turn_id / speaker / time` 元信息、`说话人A:` 这类对话发言前缀，以及纯日期标题；同时会对 `旨在`、`具体细节`、`这是一份思路文件` 这类从句或元描述降权，避免它们抢占代表陈述
  - 当正文抽不出可用 Claim、但章节标题本身是 `YYYY-MM-DD` 这样的完整日期时，系统会补一条日期型 Claim，保留时间线入口页，避免日期标题完全消失
  - 当前已经实现来源视图页与可读概念页，并会同步生成对应页面、`state/pages.jsonl`、`wiki/index.md` 与 `wiki/log.md`
  - 当前概念页选择“代表陈述 / 核心陈述”时，不再单纯偏向更长的句子，而会优先选择能独立理解、且更适合直接展示给人的 Claim；`一种……的模式` 这类短语会优先于说明性长句
  - 当前概念页展示层直接展示选出的代表 Claim，不再靠中文“是 / 用于”等词面把短语强行改写成定义句
  - 当前概念页里的 `Source Pages / Source Evidence` 会优先用更适合人阅读的多行结构展示来源摘要页、原始来源文件、匹配 chunk 和次级 ID，方便顺着 `page -> claim -> knowledge_unit -> evidence_block -> source` 主证据链继续下钻，并按需读取 chunk 上下文
  - 当前概念页生成已加入四层处理规则：先用强规则过滤明显坏标题，再做标题质量评分；灰区候选才会交给 LLM 调度器做受限判别；最终 `lint` 会把低质量概念标题显式报成 warning
  - 强规则当前会优先拦截 `示例`、`总结`、单字中文标题、问句壳标题这类明显更像结构节点而不是概念名的候选，减少“章节标题被误生成为概念页”
  - 标题质量评分会综合标题本身、canonical claim 可读性、是否跨来源、是否只是 topic shell、是否像定义句等信号，避免继续单纯依赖 `section_path` 最后一段命名
  - 灰区标题函数合同只允许返回 `accept / reject / rename`，`rename` 还必须有输入证据支持；不直接把无约束文本写成 canonical，优先保证 `canonical_id` 稳定
  - `wiki/index.md` 与页面间 Markdown 链接会对空格等特殊字符做 URL 编码，尽量兼容不同查看器
  - 当前 concept 聚合已改为与 claim review 更接近的归一化分组思路，减少同主题页面分裂
  - 当前已支持自动生成人类可读 `concept` 页；工作区级 `overview` 页会在满足生成条件时自动产出，两个页面族默认都会先尝试 `llm_assisted` 渲染
  - 当前新初始化工作区默认已经接上统一 LLM 调度器，目标是让 `ingest -> review-auto -> stable -> concept/overview` 作为一条连续自动化链默认运行；完全离线时需要显式选择确定性模式
  - `concept` 与 `overview` 的 LLM 改写都要求 grounded；函数结果已经通过合同、但页面级 grounding 不合格时会使用确定性页面模板，主备请求本身都失败时命令直接失败
  - `overview` 页当前支持 grounded overview rewrite，并在 `llm_assisted` 成功时显示折叠式 `Rewrite Traceability`
- `myagentwiki lint`
  - 已实现仓库骨架 / 工作区结构检查，以及 `chunk_id` / `claim_id` / `page_id` 唯一性、Claim 溯源、页面记录完整性、`reviews.jsonl` / `error_log.jsonl` / `pages.jsonl` 存在性检查
  - 已补充 `canonical_id` 唯一性、alias registry 覆盖、search index 覆盖、lint 报告文件写回
  - 当前已新增 `concept_pages_title_quality` warning，用于显式标出“标题像结构词、过短、问句壳、或整体质量过低”的概念页
- `myagentwiki query`
  - 已实现基于 `pages + claims + wiki` 产物的多字段 BM25 检索
  - 当前会综合 `title`、`aliases`、`summary`、`headings`、`body`、`claim_text`、`source_refs` 打分，并叠加页面类型权重与页面状态权重
  - 当前已接入第一版 query normalization、alias 扩展、canonical 命中回传，以及英文轻量意图识别；中文等自然语言意图建议由调用方显式传入 `--intent`
  - alias/title/canonical 精确命中会参与排序加权；显式 `definition / evidence / how_to / timeline / compare / overview` 等意图会对阅读路径和页面类型做轻微调权
  - `evidence` 类问题会更偏向 `source-summary`，并在阅读包里优先保留可回链的 claim、knowledge_unit、evidence_block、source 线索，同时保留匹配 chunk 作为上下文入口
  - `compare / timeline / how_to` 也会在阅读包中返回不同 focus，帮助 Agent 判断优先读声明、时间线证据还是步骤性上下文
  - `timeline` 类问题会额外返回按来源分组的 `timeline_sources`
  - 当前支持 `--reading-depth standard|deep`
  - `deep` 模式会在保持 deterministic 的前提下返回更厚的 `reading_pack`，并额外给出按来源聚合的 `source_trail`
  - 当前输出候选页面、得分解释、命中字段与命中 token，并返回阅读包 `reading_pack`
  - `reading_pack` 当前包含匹配的 `claims`、`matched_chunks`、来源摘要，以及 `section_path`、`previous_chunk`、`next_chunk` 等下钻线索；其中 Claim 会保留 `knowledge_unit_ids / evidence_block_ids / source_refs`，`matched_chunks` 负责补足检索上下文，`deep` 模式下还会附带 `source_trail`
  - 标题树相关信息已经不再只保留为扁平 `section_path`：
    - chunk 和 claim source refs 当前都会保留 `section_path_parts / section_title / parent_section_path / heading_level`
    - concept 聚合、命名和别名已开始消费这套层级字段，避免“同名叶子标题但父节点不同”的内容被压平成同一主题
  - query 排序当前也已消费 hierarchy 字段：
    - page 检索会把章节路径、父级路径、层级别名和页面标题一起作为 hierarchy 检索字段参与 BM25
    - chunk 检索会对 `section_title / parent_section_path / section_path_parts` 的命中给轻量加权
  - `reading_pack.retrieval_context` 当前会显式解释层级命中：
    - `hierarchy_hits`
    - `hierarchy_paths`
    - `hierarchy_anchor_reason`
    - `hierarchy_anchor_reason_text`
    - 并且 hierarchy 原因已经进入统一的 `ranking_reasons`
  - JSON 输出当前会统一附带 `workspace_summary`，便于上层 Agent 直接拿到工作区绝对路径、入口页和 lint 报告路径
  - 纯文本输出当前也会先打印 `Workspace / Entry page / Lint report` 这类绝对路径摘要，再展开候选结果
  - `query --answer-ready` 和 `answer-query` 会把 `reading_pack.answer_handoff` 渲染成给上层 Agent 直接消费的回答就绪摘要，显式返回推荐读序、必读证据路径、风险标记与降级动作
  - `--format prompt` 会进一步把回答就绪摘要压成可直接喂给上层 LLM/Agent 的 prompt block；JSON 模式下也会附带 `prompt_text`
  - `--format messages` 会返回可直接传给聊天 API 的 messages 数组；`--format chatml` 会同时返回 messages 和 ChatML 文本
  - answer-ready 当前也会继续透传 hierarchy 锚点，包含：
    - `selected_result.hierarchy_*`
    - `answer_context.hierarchy_*`
    - `agent_summary` 中的人类可读 hierarchy anchor / hierarchy reason
    - `prompt / messages / chatml` 中给上层模型直接消费的 hierarchy anchor / hierarchy reason
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
- `myagentwiki semantic-batch`
  - 已实现 `document_analysis / claim_candidate_quality / claim_role / page_intent` 四类可单跑的语义批处理入口
  - 当前支持批处理、缓存命中、dry-run 和统一语义账本写回
  - `claim_candidate_quality` 当前专门处理短句灰区：它不会替代确定性噪声过滤，而是批量判断短 claim 更像可保留陈述、上下文碎片、结构壳标题，还是可安全进入 `safe_auto`
  - `page_intent` 的缓存命中当前会显式依赖 claim 侧的 `knowledge_role / page_intent_hints / concept_candidate_score`；如果 `claim_role` 结果发生变化，对应页面路由会自动失效重算，而不会继续沿用旧的页型判断
  - `page_route` 当前会在页面路由阶段自动落账到 `state/semantic_decisions.jsonl`，用于保留 `route_target / route_reason / rejected_alternatives` 等可回放信息；它不作为独立 `semantic-batch --task` 对外暴露

## Windows 兼容性 / Windows Compatibility

当前版本已经按这些原则实现：

- 路径统一使用 `pathlib`
- 子进程调用不依赖 `bash` / `zsh`
- `bootstrap` 直接复用当前 Python 解释器
- `raw/` 扫描支持子目录递归
- `raw/` 扫描会跳过所有 `.` 开头的文件和目录
- 常见文档的标准化主路径使用 MarkItDown Python 包；Markdown、纯文本和图片使用 MyAgentWiki 专用路径，MarkItDown 失败后再使用已有 Python 转换器或占位文档

当前真实边界也要说明白：

- 我们在这个仓库里已经提供了 Windows 命令示例与跨平台验证脚本
- 但本轮开发环境不是 Windows，因此这里能交付的是“面向 Windows 的实现约束、脚本和清单”，不是本机实跑截图

## 推荐使用方式

面向最终用户的大致流程会是：

1. 在 Codex 中安装或接入 MyAgentWiki Skill
2. 准备自己的 `raw/` 原始知识目录，放在目标工作区同级
3. 运行 `init`，创建 Wiki 工程并复用或创建 sibling `raw/`
4. 使用 Agent 执行 `ingest`
5. 检查 `normalized/`、`chunks/`、`claims/`、`wiki/` 和 `state/*.jsonl` 结果，重点关注 `state/structure_blocks.jsonl`、`state/evidence_blocks.jsonl`、`state/knowledge_units.jsonl`、`state/error_log.jsonl`、`state/reviews.jsonl`、`state/pages.jsonl`
6. 使用 `lint` 和 review 机制维护知识库健康
7. 使用 `query` 先查候选页面，再决定是否继续读取 claim、knowledge_unit、evidence_block、source 和匹配 chunk 上下文

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
  - 标准化后的文本结果，保留来源元数据，供后续 Structure IR、Evidence Block、Knowledge Unit、chunk 和 Claim 生成使用
- `state/structure_blocks.jsonl`、`state/evidence_blocks.jsonl`、`state/knowledge_units.jsonl`
  - 结构化证据账本和知识单元账本，是 Claim 精确回链的主证据层
- `chunks/*.jsonl`
  - 按来源拆分的上下文容器，每条记录带 `chunk_id`、前后邻接关系和来源信息，主要服务检索、摘要、相邻上下文和增量处理
- `claims/*.json`
  - 按 Claim 单文件保存的知识声明草稿，便于后续审核与回链
- `wiki/sources/*.md`
  - 首批自动生成的来源摘要页，每个来源至少对应一个 `source-summary` 页面
  - 当前来源摘要页里的 `Chunks` 列表会直接链接到对应 `chunks/<source_id>.jsonl`，并附带 `section_path` 与行号，便于继续定位证据
- `wiki/concepts/**/*.md`
  - 基于 Claim 聚合出的概念候选页，作为后续综述页、主题页的起点
  - 当前已加入一层轻量命名清洗，优先使用 `section_path` 和短主题短语生成更像 Wiki 的页面名
  - 当前概念页里的 `Source Pages / Source Evidence` 会分别展示来源摘要页入口、原始来源文件入口、覆盖范围，以及按条列出的匹配 chunk 链接
  - 页面文件名若包含空格等特殊字符，目录页与页面间链接会自动使用 URL 编码后的相对路径
- `wiki/guides/**/*.md`、`wiki/duties/**/*.md`、`wiki/examples/**/*.md`、`wiki/topics/**/*.md`、`wiki/references/**/*.md`、`wiki/timelines/**/*.md`
  - 按 `page_intent` 路由生成的正式页面族；只有组级角色、内容标签或结构证据足够时才进入专门页型
- `wiki/overview/index.md`
  - 工作区级综述入口页，默认在有多个稳定可读概念页时自动生成
  - 当前支持 grounded 的 `llm_assisted` 摘要、主题导览和推荐阅读路径改写
  - 当 overview 改写成功时，会额外生成折叠式 `Rewrite Traceability` 区块，展示改写句与回绑页面
- `state/*.jsonl`
  - 全局索引与状态账本，包括 `sources`、`normalized`、`structure_blocks`、`evidence_blocks`、`knowledge_units`、`chunks`、`claims`、`semantic_decisions`、`reviews`、`pages`、`ingest_state`、`error_log`
  - 其中 `state/pages.jsonl` 会保留已被自动移除页面的历史记录，便于追踪页面演化；但 `removed` 页面不会继续进入在线检索与页面索引
- `semantic/batches/*.json`
  - 语义批处理的批次报告与缓存产物；语义决策的权威账本仍是 `state/semantic_decisions.jsonl`
- `indexes/search_pages.jsonl`
  - query 使用的页面检索派生索引，保存字段文本、tokens 和基础页面元数据
  - 当前已支持按页面级内容签名做增量复用，未变化页面会复用既有索引记录
- `indexes/aliases.json`
  - alias / canonical registry，供 query normalization、lint 和 Agent 规则共用
  - 当前会记录 live page 的 `canonical_id`、`title`、`aliases`，并标出 alias 冲突
- `reviews/*.json`
  - 需要人工确认的冲突、重复、近似重复等审核项
  - 当前实现使用“前缀 bucket + token 倒排召回 + 否定极性 / 文本相似度复核”来生成审核候选，优先减少明显漏检
  - 当前 alias registry 检测到同一 alias 指向多个 canonical 页面时，也会自动生成 `alias_conflict` review
  - 当前 alias conflict review 若已不再对应真实 alias 冲突，会在 `review-list / review-apply / ingest` 的收口过程中自动转入历史态，而不是继续保留为 active/open

当前这版最重要的是把“可追踪链路”先打通：

- Wiki 页面可以回指到 Claim
- Claim 可以回指到 Knowledge Unit、Evidence Block 与 Source，并按需回到匹配 Chunk 补上下文
- review 记录可以反查受影响的候选页面
- 页面索引会进入 `state/pages.jsonl`
- 冲突和重复风险会进入 `reviews/` 与 `state/reviews.jsonl`
- 查询会优先命中高价值页面类型，并给出字段级打分解释
- 查询结果已经可以附带 claim、matched chunk、source 阅读包；其中主证据追踪以 Claim、Knowledge Unit、Evidence Block 和 Source 为准，matched chunk 负责补上下文
- `deep` 查询模式当前还能返回按来源收束的 `source_trail`，帮助 Agent 用更大的上下文窗口继续追证据，但仍保持 deterministic first
- query 已接入持久化页面检索索引，索引存在时优先读取 `indexes/search_pages.jsonl`
- query 已接入 alias registry，alias 命中时会回传 canonical 目标
- 可读 `concept` 页与 `overview` 页默认允许 `llm_assisted` 改写；函数结果通过合同但页面级 grounded 校验不合格时使用确定性页面模板，主备请求失败时命令失败

## 文档说明

如果你想快速理解项目，建议阅读顺序如下：

1. `README.md`
2. `RELEASING.md`
3. `docs/MyAgentWiki系统详细设计.md`
4. `docs/调试模式与全链路追踪设计.md`
5. `docs/全链路规则与LLM协同判定设计.md`
6. `docs/全链路重构实现计划.md`
7. `docs/runtime-deps.md`
8. `docs/project-materials/` 中的学习与工程记录
9. `docs/troubleshooting.md`

## 开发说明

当前仓库重点已经从“先打通主链路”转为“保持主闭环稳定，并继续把结构层、语义层、页面层和可追溯性收口得更清楚”。

版本发布约定：

- 日常开发和普通 `push` 默认不升级版本号
- 只有准备正式发布时，才统一更新 `pyproject.toml` 中的版本号并创建对应 Git tag / GitHub Release
- 向后兼容的 bugfix 使用 patch 版本，例如 `2.0.1`
- 向后兼容的新能力使用 minor 版本，例如 `2.1.0`
- 阶段性重构或不兼容变更使用 major 版本，例如 `3.0.0`

接下来适合继续推进的方向包括：

- Markdown Structure IR、Evidence Block、Knowledge Unit 与 Claim 的覆盖率报告继续增强
- 语义决策账本与页面路由的 schema 校验继续收口
- 更深入的 `stable / disputed` Claim 治理
- `qa-note` 问答笔记能力的后续正式化路径
- entity 等更高层 Wiki 页面生成，以及 overview 与统一页面族谱的继续完善
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

- `tests/test_runtime_services_converters.py`
  - 使用真实 DOCX、XLSX、PPTX、HTML 验证 MarkItDown 主转换路径
  - 覆盖 MarkItDown 失败后的告警、旧转换器备用路径和转换器版本判断

- [tests/test_query_alias_and_lint.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_query_alias_and_lint.py)
  - 覆盖 alias/canonical 命中、intent focus、lint 报告写回
  - 覆盖 alias conflict review、`assign_alias / remove_alias`、re-ingest 后的持久化行为，以及过期 alias review 自动收口

- [tests/test_e2e_workflow.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/tests/test_e2e_workflow.py)
  - 覆盖 `init -> ingest -> query -> review -> lint` 主闭环
  - 覆盖 `raw/` 子目录递归扫描与 alias conflict 收口
  - 覆盖原文件不变时，旧标准化版本的自动重新处理

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
