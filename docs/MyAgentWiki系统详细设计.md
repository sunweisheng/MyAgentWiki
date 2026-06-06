# MyAgentWiki系统详细设计

## 概要 Summary

本设计将 `MyAgentWiki` 定义为一个由 Python 脚本和 Agent 协同驱动的本地 LLM Wiki 系统，服务于 Codex 和 Claude Code 两类 Agent。  
本文中的 `MyAgentWiki` 统一指母仓库 / 产品名；若需要举用户初始化后的工作区目录名示例，统一使用 `MyNotesWiki`。  
V1 的首要目标是先把 `raw -> normalized -> chunk -> claim -> wiki` 这条链路打通，其中 `raw -> normalized` 为最高优先级，并优先用 `Python 3.12+` 脚本完成文档格式转换；只有脚本无法稳定提取时，才允许 Agent 作为补充。当前产品定位已经进一步明确为 `agent_driven_local_llm_wiki`：默认假设系统运行在 Codex 或 Claude Code 这类 Agent 环境中，由脚本负责可重复、可回滚的确定性流水线，由 Agent / LLM hook 负责语义判断、审核裁决、stable 提升、概念页和综述页的 grounded 改写。

系统的关键能力是：
- 从用户原始知识目录同级初始化一个新的 Wiki 工程。
- 支持 `Word / Excel / PDF / Markdown / 图片` 五类输入。
- 引入独立的 `Claim` 知识声明层，建立 `page -> claim -> chunk -> source` 可追踪链路。
- 支持 Claim 到 Wiki 页面的反向引用统计与检索。
- 使用多字段 BM25 打分，并叠加页面类型权重和页面状态权重。
- 对冲突、近重复、替换稳定结论等高风险更新，进入结构化人工审核队列。

当前实现采用 `deterministic first`：
- 事实层、证据层、状态层优先由 Python 脚本和显式账本生成。
- LLM 主要参与页面可读性改写、导览组织、审核自动裁决和 stable 提升判断。
- LLM 产物不能成为新的事实来源；若改写或裁决无法 grounded 到既有 Claim/Page/Review，则必须自动回退到 deterministic fallback 或升级人工判断。

当前自动化哲学已经固定为：
- scripts own deterministic pipeline：扫描、标准化、切块、账本更新、索引重建、页面落盘、状态恢复都由 CLI 收口。
- Agent hooks own semantic judgment：冲突是否可保守自动处理、Claim 是否可提升为 `stable`、概念页/综述页如何在 grounded 前提下改写，由 Agent hook 提供高置信判断。
- human only for irreducible ambiguity：只有高风险冲突、归属不清、hook 未达置信阈值，或涉及敏感边界时才升级人工。

当前默认工程策略进一步固定为：
- `init` 生成的新工作区会默认把 `review_auto`、`stable_promotion`、`readable_concept` 与 `overview` 四类任务统一接到包内 Agent hook。
- 因而“自动审核 -> 自动提稳 -> 自动生成概念页 -> 自动生成综述页”不再只是可选能力，而是默认推荐工作流的一部分。
- 默认 hook 本身也遵守 grounded-first：只做可读性重写和保守裁决；一旦输出不通过校验，就回退到 deterministic 产物或升级人工。

## 系统结构 System Structure

### 母仓库职责
母仓库是开源 Skill 项目本体，负责交付：
- `Agent.md`：共享核心规则源。
- `AGENTS.md`：Codex 入口文件。
- `CLAUDE.md`：Claude Code 入口文件。
- `SKILL.md`：Skill 主入口。
- `agents/openai.yaml`：Skill UI 元数据。
- `pyproject.toml`：Python 依赖、可选依赖和 CLI 入口定义。
- Python 包与统一 CLI。
- 初始化模板工程。
- 运行环境清单与平台兼容说明。
- 项目自身知识沉淀目录 `docs/`。
- 工作流验证脚本与交付级排障文档。
- 面向用户工程的目录模板、配置模板、状态模板、审核模板。

### 用户工程职责
用户运行 `init` 后生成 sibling Wiki 工程，负责承载：
- 外部 sibling `raw/` 原始资料目录引用。
- 标准化中间产物。
- Chunk 与 Claim 层。
- Wiki 页面。
- 本地索引、状态、日志、审核队列。
- Git 版本历史。

### 母仓库与用户工程的生命周期边界
两者必须被视为不同对象：
- 母仓库负责“产品代码、模板、规则、脚本和测试”。
- 用户工程负责“用户知识资产、中间产物、索引、状态和审核记录”。

这条边界的工程含义固定如下：
- 母仓库升级时，默认不直接覆盖现有用户工程中的 `state/`、`claims/`、`reviews/`、`wiki/`。
- 用户工作区外部的 sibling `raw/` 视为原始资料区，不因为母仓库升级而自动重写。
- 模板演进优先通过“新工作区生成 + 老工作区渐进迁移”吸收，而不是要求 Agent 直接跳过 CLI 手改账本。
- 在未发生破坏性账本变更的前提下，工程目标是尽量保持旧工作区可继续被新版本 CLI 读取并执行 `ingest / query / lint / review-apply`；但这一点在当前 V1 里主要仍属于约定目标，尚未由工作区 schema 版本标记或统一版本守卫机制强制保证。

V1 当前约束：
- V1 不实现完整的自动迁移器。
- V1 文档必须清楚区分“母仓库升级”和“用户知识库内容更新”两类操作。
- V1 当前尚未完成工作区级 `schema_version`、统一兼容性检查或 `migrate` 命令；因此这里不应把跨版本安全读写表述成已落地能力。
- 若未来引入状态结构破坏性升级，应通过显式迁移命令或版本检查阻止静默写入。

V1.1 的推荐推进方式：
- 在尚不明确下一版本是否会修改账本结构时，不预先承诺“通用跨版本迁移器”。
- 优先补齐工作区级 `schema_version` 或等价版本标记，以及 CLI 读写前的兼容性检查。
- 若检测到未来版本与当前工作区存在破坏性不兼容，默认拒绝静默写入，并提示用户执行显式迁移。
- 先为未来迁移命令预留入口、备份约定和 `dry-run` 机制；等真实 schema 变更出现后，再实现针对性的迁移逻辑。
- 可重建产物与需谨慎迁移产物应区别对待：`indexes/`、部分聚合页更适合重建；`claims/`、`reviews/`、`state/*.jsonl` 更适合显式迁移或兼容读取。

## 目录设计 Directory Design

### 母仓库目录
- `Agent.md`：共享 Agent 核心规则。
- `AGENTS.md`：Codex 入口规则。
- `CLAUDE.md`：Claude Code 入口规则。
- `SKILL.md`：Skill 主入口。
- `agents/openai.yaml`：OpenAI Skill 元数据。
- `README.md`：项目总说明。
- `pyproject.toml`：Python 项目配置与依赖声明。
- `docs/`：设计文档、运行说明和项目资料。
- `src/myagentwiki/`：Python CLI 与核心实现。
- `templates/`：用户工作区初始化模板。
- `tests/`：自动化测试。
- `scripts/`：验证脚本与辅助工具。

### 初始化后的用户工程目录
若需要举具体目录名示例，统一使用 `MyNotesWiki/` 表示用户工作区，使用其同级 `raw/` 表示原始资料目录。

- `../raw/`：与工作区平级的原始资料目录。
- `normalized/`：标准化后的 Markdown 文本。
- `chunks/`：按来源展开的切块结果。
- `claims/`：单条 Claim 的展开 JSON 文件。
- `wiki/`：面向人阅读的 Wiki 页面。
- `indexes/`：搜索索引、别名索引等派生索引。
- `state/`：结构化账本。
- `reviews/`：单条审核项的展开 JSON 文件。
- `logs/`：预留的结构化运行日志目录。
- `outputs/`：预留的导出或临时输出目录。
- `config/`：工作区配置。
- `reports/lint/`：巡检报告目录。
- `wiki/index.md`：Wiki 首页。
- `wiki/log.md`：Wiki 变更日志。
- `config/project.yml`：工作区项目配置。
- `config/runtime_manifest.yml`：运行环境清单。
- `AGENTS.md`：工作区 Codex 入口规则。
- `CLAUDE.md`：工作区 Claude Code 入口规则。

### 工作区分层与写入边界
用户工程内部目录按职责分为四层：

1. 原始资料层
- `raw/`
- 位于工作区外部并与工作区平级，保存用户自己维护的原始资料及其目录结构。
- Agent 不自动修改该层内容。

2. 编译中间层
- `normalized/`
- `chunks/`
- `claims/`
- 这些目录保存可重建但又需要稳定落盘的中间产物。

3. 知识呈现层
- `wiki/`
- 对人可读、可链接、可引用。
- 允许自动页与后续人工维护页并存，但需要通过 `page_id / canonical_id` 纳入统一状态管理。

4. 状态与控制层
- `state/`
- `indexes/`
- `reviews/`
- `reports/`
- `logs/`
- 负责保存账本真相、检索索引、审核单、lint 报告和执行痕迹。

V1 约定：
- 自动流程主要写入第 2、3、4 层。
- 第 4 层中以 `state/*.jsonl` 为核心账本，以 `claims/*.json`、`reviews/*.json`、`wiki/*.md` 为面向人和 Agent 的展开视图。
- 若出现多份数据不一致，以账本与生命周期规则优先，再由 `ingest / review-apply / lint` 收敛。

### 运行依赖清单文件
母仓库需要额外提供：
- `pyproject.toml`：声明 Python 依赖、可选 extras、CLI 入口。
- `config/runtime_manifest.yml`：声明系统级依赖、是否必需、支持平台、检测命令、缺失时的降级策略。
- `docs/runtime-deps.md`：面向用户的依赖说明、平台安装指引和常见问题。
- `docs/troubleshooting.md`：交付级故障排查文档。
- `SKILL.md`：面向 Codex / Claude Code 的 Skill 入口。
- `agents/openai.yaml`：Skill UI 元数据。
- `scripts/validate_workflow.py`：跨平台 CLI 工作流验证脚本。

运行依赖分两层：
- Python 依赖：允许自动安装。
- 系统级软件依赖：优先检测，缺失时提示安装，不默认强制自动安装。

## 核心数据模型 Core Data Model

### 原始来源 Source
表示原始来源文件。
最小字段：
- `source_id`（来源ID）
- `source_path`（来源路径）
- `source_type`（来源类型）
- `source_hash`（来源内容哈希）
- `imported_at`（导入时间）
- `version_group`（版本分组）
- `status`（处理状态）
- `normalized_path`（标准化文件路径）
- `warnings`（告警信息）

V1 当前实现说明：
- 系统会为每个原始文件生成一个 `source_id`，并记录文件路径和内容哈希。
- 同一路径下的文件如果内容发生变化，会通过 `version_group` 归到同一组，表示它们是同一个来源的不同版本。
- `source_uri`、`dedupe_key` 以后可用于外部链接和跨路径去重；V1 先不强制写入状态文件。

### 标准化文档 NormalizedDocument
表示规范化后的统一文档对象。
最小字段：
- `source_id`（来源ID）
- `normalized_path`（标准化文件路径）
- `title`（标题）
- `location_map`（位置映射）
- `extraction_method`（提取方式）
- `extraction_quality`（提取质量）
- `warnings`（告警信息）
- `raw_hash`（原始内容哈希）
- `normalized_hash`（标准化内容哈希）
- `normalizer_version`（标准化器版本）

V1 当前实现说明：
- 标准化后的正文会保存成 `normalized/*.md` 文件，状态记录里只保存这个文件的路径和提取元数据。
- 这样做可以避免把大段正文塞进 `state/normalized.jsonl`，也方便人和 Agent 直接打开 Markdown 查看。
- `sections`、`artifacts` 这类更细的结构信息暂时不是 V1 必填项，后续需要更精细的章节或附件处理时再扩展。

### 文档切块 Chunk
表示从 normalized 文档切分出的处理单元和证据单元。
最小字段：
- `chunk_id`（切块ID）
- `source_id`（来源ID）
- `source_path`（来源路径）
- `section_path`（章节路径）
- `chunk_index`（切块序号）
- `start_line`（起始行号）
- `end_line`（结束行号）
- `page_range`（页码范围）
- `char_count`（字符数）
- `token_estimate`（Token 估算数）
- `summary`（摘要）
- `text`（正文文本）
- `previous_chunk`（前一切块ID）
- `next_chunk`（后一切块ID）
- `overlap_from_previous`（与前一切块的重叠内容）
- `hash`（切块内容哈希）
- `chunker_version`（切块器版本）

### 知识声明 Claim
表示独立知识声明，是系统的核心知识枢纽层。
最小字段：
- `claim_id`（声明ID）
- `text`（声明原文）
- `normalized_text`（归一化后的声明文本）
- `status`（声明状态）
- `confidence`（置信度）
- `source_ids`（来源ID列表）
- `chunk_ids`（切块ID列表）
- `page_ids`（关联页面ID列表）
- `conflict_group`（冲突分组）
- `duplicate_candidates`（重复候选列表）
- `review_reason`（进入审核的原因）
- `claim_type`（声明类型）
- `source_refs`（来源引用）
- `lifecycle_status`（生命周期状态）
- `superseded_by`（被哪些声明替代）
- `archived_at`（归档时间）
- `created_at`（创建时间）
- `updated_at`（更新时间）

V1 当前实现说明：
- 每条 Claim 会展开保存为 `claims/*.json`，方便人工查看、编辑和做 review。
- `state/claims.jsonl` 则保存一份可快速扫描的总账，供 ingest、query、lint 和 review 流程读取。
- Claim 被合并、归档或被新来源版本替代时，不会直接消失，而是转成历史记录。
- 历史记录会保留原始 Claim 的线索，例如 `original_claim_id`，并用带时间戳的历史 ID 记录它曾经存在过。

### Wiki页面 WikiPage
表示对用户可读的知识页面。
最小字段：
- `page_id`（页面ID）
- `title`（页面标题）
- `type`（页面类型）
- `canonical_id`（规范ID）
- `status`（页面状态）
- `automation_level`（自动化等级）
- `review_reason`（进入审核的原因）
- `summary`（页面摘要）
- `aliases`（别名列表）
- `redirect_to`（重定向目标）
- `claim_ids`（关联声明ID列表）
- `review_ids`（关联审核单ID列表）
- `source_refs`（来源引用）
- `lifecycle_status`（生命周期状态）
- `archived_at`（归档时间）
- `removed`（是否已移除）
- `created`（创建时间）
- `updated`（更新时间）

V1 当前实现说明：
- V1 目前主要自动生成两类页面：来源摘要页 `source-summary` 和概念摘要页 `concept-summary`。
- 页面本体保存为 `wiki/**/*.md`，页面清单和生命周期记录保存在 `state/pages.jsonl`。
- 如果某个自动页面因为来源变化或概念合并而不再需要，它会在账本里留下历史记录，但不会继续进入查询、索引和 wiki 目录。
- 概念页生成时会先按相似内容分组，再按最终的 `canonical_key` 做一次合并，尽量避免同一个概念长出多张活跃页面。

### 审核项 ReviewItem
表示人工审核单。
最小字段：
- `review_id`（审核单ID）
- `kind`（审核类型）
- `status`（审核状态）
- `lifecycle_status`（生命周期状态）
- `candidate_claim_ids`（候选声明ID列表）
- `candidate_page_ids`（候选页面ID列表）
- `reason`（审核原因）
- `recommended_action`（推荐动作）
- `allowed_actions`（允许执行的动作列表）
- `resume_from`（恢复起点）
- `evidence`（关键证据）
- `created_at`（创建时间）
- `resolved_at`（解决时间）
- `archived_at`（归档时间）

V1 当前实现说明：
- 每个审核项会展开保存为 `reviews/*.json`，方便人直接阅读候选对象、风险原因和推荐动作。
- `state/reviews.jsonl` 保存审核队列的总账，方便 CLI 快速列出、筛选和恢复处理流程。
- 已解决的审核项不会立即删除，而是保留 `status=resolved`，这样后面还能追溯当时为什么合并、保留或归档。
- `alias_conflict` 属于页面别名冲突，有时只涉及页面，不涉及 Claim，所以这类 review 可以只填写 `candidate_page_ids`。
- 当前已补一条保守自动审核路径 `review-auto`：先读取 live review 与页面/claim 现状，自动应用高把握动作，再把剩余需要人判断的项保留为 escalated handoff，而不是强行替用户做主。
- 当前 `review-auto` 已扩展到一组更完整、但仍然保守的自动场景，包括片段化/被包含的 conflict claim 归档、互补或问题型 claim 的 `keep_both`、以及噪声 alias 的唯一归属或移除；超出这层把握的 review 仍保持为 `open`，等待人工或 Agent 进一步解释后裁决。

### 状态、等级与关键术语说明

核心数据模型里有几类容易混淆的字段：`status` 表示“当前业务状态”，`lifecycle_status` 表示“这个对象是否还活跃”，`automation_level` 表示“系统能自动改到什么程度”。它们解决的是不同问题，不应混用。

#### Source.status（来源处理状态）

- `new`：新发现的来源文件，尚未完成处理。
- `normalized`：已经完成标准化，生成了 `normalized/*.md`。
- `chunked`：已经完成切块，生成了 chunk 记录。
- `claimed`：已经从 chunk 中抽取或生成 Claim。
- `generated`：已经生成或更新相关 Wiki 页面。
- `review_required`：处理过程中发现风险，需要人工审核。
- `failed`：处理失败，需要查看 `warnings` 或 `state/error_log.jsonl`。

#### Claim.status（声明状态）

- `draft`：草稿声明。V1 自动抽取出的 Claim 默认多为这个状态。
- `stable`：稳定声明。表示经过人工确认或长期使用后，可以作为可靠结论参与页面组织。
- `disputed`：有争议声明。表示它可能与其他声明冲突，但暂时保留。
- `needs_review`：需要审核。通常是因为检测到重复、近重复、冲突或来源更新风险。
- `archived`：已归档声明。表示它不再作为当前有效结论使用，但历史上曾经存在。

#### WikiPage.status（页面状态）

- `draft`：草稿页面。内容可用，但还没有被视为稳定知识页。
- `stable`：稳定页面。页面结构和核心结论相对可靠。
- `disputed`：争议页面。页面中包含未解决冲突或需要明确标注的不同观点。
- `needs_review`：需要审核。页面可能涉及自动合并、重命名、别名冲突或核心结论变化。
- `outdated`：过期页面。页面仍保留，但其内容可能已经被新来源或新版本替代。

#### ReviewItem.status（审核状态）

- `open`：待处理。表示审核单仍需要人工或 Agent 辅助裁决。
- `resolved`：已解决。表示已经执行了 `merge / keep_both / archive_one / edit_then_resume / assign_alias / remove_alias` 等动作。

#### Review action（审核动作）

审核动作表示“这张审核单最终怎么处理”。动作执行后，系统会同步更新相关 Claim、页面、索引和状态账本。

- `merge`（合并）：把两个或多个高度相似的 Claim 合并成一条主 Claim。适用于“表达不同但核心意思基本相同”的情况。
- `keep_both`（两者都保留）：确认候选 Claim 或页面虽然相似，但不是重复内容，应继续同时存在。适用于概念边界不同、语境不同或暂时不宜合并的情况。
- `archive_one`（归档其中一个）：把某个候选 Claim 从当前有效集合中移出，但保留历史记录。适用于一条结论已过期、被替代或明显不再需要参与当前页面生成的情况。
- `edit_then_resume`（先编辑再恢复流程）：允许人先手工修改 `claims/*.json` 等文件，再让系统从这张审核单继续恢复后续页面和索引更新。适用于自动合并不够准确、需要人工改写 Claim 文本的情况。
- `assign_alias`（指定别名归属）：在别名冲突时，把某个 alias 指定给某一个页面。适用于同一个别名被多个页面争用，但人能判断它应该属于哪个页面的情况。
- `remove_alias`（移除别名）：在别名冲突时，把某个 alias 从候选页面中移除。适用于这个别名本身不合适、容易误导或不应继续作为检索入口的情况。

#### lifecycle_status（生命周期状态）

`lifecycle_status` 用来回答“这个对象现在还算不算当前有效对象”。

- `active`：活跃对象。会参与当前 query、索引、页面生成或审核流程。
- `superseded`：已被替代。通常表示旧 Claim 被新 Claim 合并或替换。
- `archived`：已归档。表示对象不再参与当前主流程，但为了追踪历史而保留。
- `removed`：已移除。主要用于页面，表示页面文件已经不再保留为 live 页面，但账本中仍记录它曾经存在。

`status` 和 `lifecycle_status` 的区别：
- `status` 更像“这个对象当前处于什么业务状态”。
- `lifecycle_status` 更像“这个对象是否仍在当前知识库主路径上生效”。

例如一条 Claim 可以曾经是 `status=stable`，后来因为来源更新被替代，转为 `lifecycle_status=superseded`。此时它仍可追溯，但不应继续作为当前结论参与页面生成。

#### automation_level（自动化等级）

`automation_level` 用来限制系统能否自动修改页面或对象。

- `safe_auto`：安全自动。适合低风险、可重复生成、可回滚的修改。
- `auto_with_log`：允许自动修改，但必须记录变更原因和影响范围。
- `require_review`：必须进入审核队列，不能直接自动改写。
- `locked`：锁定对象。除非用户明确要求，否则 Agent 和 CLI 都不应自动修改核心内容。

#### confidence（置信度）

`confidence` 表示系统对 Claim 可靠程度的估计。V1 可以先使用简单等级或数值表达。

- `high`：来源明确、表达清楚、与现有知识不冲突。
- `medium`：来源可追踪，但表达可能需要进一步整理。
- `low`：来自低质量抽取、OCR、含糊表述或存在明显不确定性。

置信度不是事实真伪的最终判断，只是提醒系统和 Agent：这条 Claim 在进入稳定页面前需要多谨慎。

#### 归档 Archived

“归档”不是删除。

归档表示对象不再参与当前知识库的 live 主流程，但仍保留历史记录，方便以后回答这些问题：
- 这条结论以前是否存在过？
- 它为什么被替代、合并或废弃？
- 哪个 review 或来源更新导致了这次变化？

因此，归档对象通常不会进入默认 query 排名、自动页面生成和 live 索引，但仍应能通过状态账本追溯。

#### 证据 Evidence

“证据”指支撑某个结论、审核判断或页面内容的可追踪材料。

在 V1 中，证据通常来自：
- 原始来源文件 `raw/`
- 标准化文档 `normalized/*.md`
- 文档切块 `chunks`
- Claim 的 `source_refs`
- Review item 中的 `evidence`

证据的目标不是把所有原文都复制到页面里，而是让人或 Agent 能从页面结论一路追踪回“这句话为什么这么说”。

#### source_refs（来源引用）

`source_refs` 是系统中的证据指针，通常会把 Claim 或页面连接回具体来源、chunk、章节路径或页面范围。

它至少应帮助回答：
- 这个结论来自哪个来源文件？
- 对应哪个 chunk？
- 在原文或标准化文档中的大致位置在哪里？
- 如果来源更新了，哪些 Claim 或页面可能受影响？

`source_ids` 只能说明“来自哪些来源”，而 `source_refs` 应尽量说明“来自来源里的哪里”。

#### 账本 Ledger

“账本”是 MyAgentWiki 对 `state/*.jsonl` 这类状态文件的统一称呼。

它的作用不是给人直接阅读长内容，而是让系统稳定记录这些事实：
- 当前有哪些 Source、Chunk、Claim、Page、Review。
- 每个对象的 ID、状态、生命周期和相互引用关系是什么。
- 哪些对象是当前活跃对象，哪些对象已经归档、替代或移除。
- 某次 ingest、review 或页面更新之后，系统应该从哪里继续恢复。

可以把账本理解成“知识库的结构化记录系统”。Wiki 页面负责给人读，账本负责让系统知道这些页面、声明和证据之间到底是什么关系。

V1 中主要账本文件包括：
- `state/sources.jsonl`：来源账本，记录原始资料文件及其处理状态。
- `state/normalized.jsonl`：标准化账本，记录标准化文件路径、提取方式和提取质量。
- `state/chunks.jsonl`：切块账本，记录 chunk 与 source、章节、上下文的关系。
- `state/claims.jsonl`：声明账本，记录 Claim 的状态、来源、页面反链和生命周期。
- `state/reviews.jsonl`：审核账本，记录待处理和已解决的审核项。
- `state/pages.jsonl`：页面账本，记录 Wiki 页面 ID、路径、类型、关联 Claim 和生命周期。
- `state/ingest_state.jsonl`：流程账本，记录 ingest 的阶段、失败点和恢复线索。
- `state/error_log.jsonl`：错误账本，记录转换失败、降级处理、warning 和 error。

账本和普通 Markdown 页面最大的区别：
- 账本更适合机器读取和恢复流程。
- Wiki 页面更适合人阅读和整理知识。
- 索引更适合快速查询，但可以从账本和页面重建。

因此，当 `wiki/*.md`、`claims/*.json`、`reviews/*.json`、`indexes/*.jsonl` 与 `state/*.jsonl` 出现不一致时，系统应优先依据账本和生命周期规则判断当前有效对象，再通过 `ingest / review-apply / lint` 把其他文件收敛回来。

Agent 不应默认绕过 CLI 批量改写账本，因为账本里保存的是跨文件关系。手工改一处字段，可能同时影响页面反链、索引、review 状态和历史记录。

### 字段分层与权威源规则
为避免后续设计继续混淆“账本字段”和“展示字段”，V1 对核心模型字段作三类划分：

1. 权威字段
- 决定对象身份、生命周期、追踪链和恢复行为。
- 例如：`source_id`、`chunk_id`、`claim_id`、`page_id`、`review_id`、`canonical_id`、`lifecycle_status`、`source_refs`。
- 这类字段一旦落盘，不能被展示层静默覆盖。

2. 派生字段
- 可由权威字段和文件内容重新构建。
- 例如：`summary`、`page_signature`、检索索引文档、别名扩展结果、query 命中解释。
- 允许在 re-ingest 或 re-index 中重建。

3. 历史字段
- 用于保留演进链，而不是当前 live 对象本身。
- 例如：`archived_at`、`superseded_by`、`original_claim_id`、`original_review_id`。
- 不参与 live 查询主路径，但必须可回溯。

V1 统一规则：
- 对象身份以 ID 字段判定，不以标题或文本内容判定。
- 页面标题、claim 文本、alias 都允许变化，但其变化不能绕开对应的 ID 和生命周期记录。
- 同一对象的“人类可读文件”和“账本记录”必须能相互定位。

## 初始化工作流 Initialization Workflow

`init` 的行为固定如下：
1. 接收原始知识目录路径与项目名。
2. 在原始目录同级创建新的 Wiki 工程目录；例如项目名为 `MyNotesWiki` 时，生成的工作区目录即为 `MyNotesWiki/`。
3. 若同级 `raw/` 已存在则直接复用；若不存在则创建空的 `raw/`。
4. 生成全部模板目录和配置文件。
5. 写入 `AGENTS.md`、`CLAUDE.md`、`wiki/index.md`、`wiki/log.md`。
6. 初始化本地状态文件与索引占位文件。
7. 若目标目录不是 Git 仓库，则自动执行 Git 初始化并生成基线提交。

CLI 入口固定为：
- `python3 -m myagentwiki init`：初始化用户工作区。
- `python3 -m myagentwiki ingest`：导入并编译资料。
- `python3 -m myagentwiki query`：查询 Wiki 和阅读包。
- `python3 -m myagentwiki lint`：巡检结构与状态一致性。
- `python3 -m myagentwiki doctor`：检查运行环境。
- `python3 -m myagentwiki bootstrap`：安装或修复 Python 依赖。
- `python3 -m myagentwiki review-list`：列出审核队列。
- `python3 -m myagentwiki review-auto`：保守地自动处理高把握审核项，并把剩余需要人判断的项整理成 handoff。
- `python3 -m myagentwiki review-apply`：应用审核决策并恢复后续流程。

工作区配置当前默认会显式声明自动化定位：
- `project.positioning: agent_driven_local_llm_wiki`
- `automation.mode: safe_auto`
- `automation.philosophy: prefer_agent_automation_until_human_judgment_is_required`
- `automation.post_ingest.review_auto: true`
- `automation.review_auto.*`：控制审核自动处理 hook 的策略、命令、超时和置信阈值
- `automation.stable_promotion.*`：控制 Claim 提升为 `stable` 的 hook 策略、命令、超时和置信阈值
- `rendering.readable_concept / overview / qa_note / concept_update`：控制概念页、综述页、问答沉淀页的 `llm_assisted` 渲染

当前默认模板还会把这些任务统一指向包内入口：
- `python3 -m myagentwiki.agent_hook`
- 该统一入口会按 `task` 分发 `review_auto_decision`、`claim_stable_promotion`、`render_readable_concept_page`、`render_workspace_overview_page`
- 用户若有更强的外部 Agent / LLM 编排器，仍可在工作区配置里覆盖成自己的命令

CLI 输出约定：
- 这些主命令的 JSON 输出应优先保持“上层 Agent 可直接消费”的稳定结构。
- 当前 `init / ingest / lint / query / answer-query / review-list / review-auto / review-apply` 都会统一附带 `workspace_summary`。
- `workspace_summary` 至少包含：
  - `workspace_dir`：工作区绝对路径
  - `workspace_name`：工作区目录名，例如 `MyNotesWiki`
  - `entry_page_path`：`wiki/index.md` 的绝对路径
  - `wiki_log_path`：`wiki/log.md` 的绝对路径
  - `lint_report_path`：`reports/lint/lint_latest.md` 的绝对路径
  - `lint_report_exists`：最近一次 lint 报告是否已经实际生成
- 若该命令直接涉及外部原始资料目录，还应额外附带 `raw_dir`。
- 纯文本模式也应优先打印这一层路径摘要，避免 UI 或上层 Agent 只保留目录名时误导用户。

### 初始化后的基线约束
`init` 完成后，工作区应立即满足以下条件：
- 具备完整目录骨架。
- 具备可读取的 `config/project.yml` 与 `config/runtime_manifest.yml`。
- 具备空账本或占位账本文件，避免后续命令依赖“文件不存在”分支。
- 具备初始 alias registry、wiki 首页、wiki 日志页。
- 具备 Git 基线提交，保证后续 ingest 结果可 diff、可回滚、可审计。

V1 当前实现优先级：
- “先生成完整骨架并能立即跑 ingest/lint/query”优先于“初始化时就生成复杂默认内容”。
- 初始化模板应尽量简洁，复杂知识结构通过后续 ingest 和 review 自然长出来。

### 环境自检与初始化
V1 增加两个环境命令：

- `doctor`
  - 环境体检命令，用来检查当前机器是否适合运行 MyAgentWiki。
  - 检查 Python 版本是否满足 `3.12+`。
  - 检查必需 Python 包是否已安装。
  - 检查 `git` 是否可用。
  - 检查可选系统工具是否存在，例如 OCR、Office/PDF 转换工具。
  - 输出结构化环境报告，区分 `required`（必需）、`optional`（可选）、`missing`（缺失）。

- `bootstrap`
  - 环境自举命令，用来安装或修复项目需要的 Python 依赖。
  - 安装或修复 Python 依赖。
  - 生成运行环境报告。
  - 不默认静默安装系统级软件，只提示缺失项和平台安装建议。

### Skill 打包与入口 Skill Packaging And Entry

母仓库需要具备最小可安装 Skill 入口：

- 根目录 `SKILL.md`：Skill 主入口，说明什么时候使用 MyAgentWiki 以及 Agent 应遵守哪些规则。
- `agents/openai.yaml`：OpenAI Skill UI 元数据，用于描述 Skill 名称、说明和展示信息。
- 共享规则源 `Agent.md`：Codex 与 Claude Code 共用的核心行为规则。
- Codex / Claude Code 适配入口 `AGENTS.md`、`CLAUDE.md`：分别给不同 Agent 工具读取的入口说明。

V1 当前实现说明：

- 当前仓库已经补齐 `SKILL.md` 与 `agents/openai.yaml`。
- 当前 Skill 约束仍然坚持 CLI-first（优先调用 CLI），不允许 Agent 默认绕过命令直接批量修改账本。
- 当前 README、运行依赖文档、排障文档、验证脚本与测试目录说明，已经组成第一版可交付安装说明面。

## 标识与命名 Identity And Naming

### 原始来源ID规则 Source ID Rules
- `source_id`（来源ID）不能只依赖文件名，必须由内容哈希、来源类型、导入时间片段等稳定特征生成。
- 同内容但不同文件名默认视为同一来源，写入同一 `dedupe_key`（去重键）。
- 同一 `source_uri`（来源地址）内容更新时，不覆盖旧来源，默认在同一 `version_group`（版本分组）下生成新版本。
- 重复 ingest（导入处理）同一来源时，默认跳过已完成版本；若 `raw_hash`（原始哈希）或 `normalized_hash`（标准化哈希）变化，则进入增量更新流程。

V1 当前实现说明：
- 当前 `source_id` 基于 `raw/` 下相对路径和 `source_hash` 生成，避免子目录同名文件冲突。
- 当前“同一路径文件内容更新”采用原位演进：复用原 `source_id`，清理旧证据链后重建 normalized / chunk / claim / page，而不是新增一个并行活跃 source。
- `version_group` 当前已记录路径级演进关系。
- `dedupe_key`、`source_uri` 仍属于设计保留语义，当前未作为运行中主字段落地。

### 规范名治理 Canonical Naming
- 每个 `concept`（概念页）/ `entity`（实体页）/ `overview`（综述页）页面必须有稳定的 `canonical_id`（规范ID）。
- `title`（标题）是显示名，可调整；`canonical_id` 是长期主键，不应随重命名变化。
- 页面标题默认采用中文优先策略；英文术语、缩写、旧译名进入 `aliases`（别名列表）。
- 旧标题页默认不删除，改为 `type: redirect`（重定向页）并写 `redirect_to`（重定向目标）指向规范页。

### 别名注册表 Alias Registry
- V1 维护全局别名表，例如 `indexes/aliases.json` 或等价结构化索引。
- Alias registry（别名注册表）作为检索扩展、页面去重、自动加链接和别名冲突巡检的统一数据源。
- AI 或脚本在新建页面前，必须先查询 alias registry 和现有页面 `frontmatter`（页面元数据）。
- 如果同一 alias（别名）可能对应多个 `canonical_id`（规范ID），不自动合并，转入 `needs_review`（需要审核）。

V1 当前实现说明：
- 当前别名注册表已落地为 `indexes/aliases.json`。
- 当前人工 alias 修正独立持久化在 `state/page_alias_overrides.json`。
- `assign_alias / remove_alias` 当前基于 live page 的 alias 集合增删，避免人工处理单个 alias 时误伤该页原有其他 alias。
- `state/page_alias_overrides.json` 当前按进程级串行化方式更新，避免多个 `review-apply` 并发写入时发生后写覆盖前写。

## 标准化层 Normalization Layer

### 总体原则
- `raw -> normalized` 为 V1 第一优先级。
- 优先纯 Python 实现。
- 外部办公软件不是前提依赖。
- Agent 只做 Python 失败后的补充解析。

### 统一转换架构
标准化层采用“统一抽象 + 多转换器”设计：
- `BaseConverter`（基础转换器接口）：定义所有转换器共同的输入输出约定。
- `MarkdownConverter`（Markdown 转换器）：处理 Markdown 和纯文本类材料。
- `PdfConverter`（PDF 转换器）：处理 PDF 文档。
- `WordConverter`（Word 转换器）：处理 `.docx` / `.doc` 文档。
- `ExcelConverter`（Excel 转换器）：处理 `.xlsx` / `.xls` / `.csv` 表格。
- `ImageConverter`（图片转换器）：处理图片元数据和 OCR 文本。

所有转换器输出统一 `NormalizedDocument`。

### 依赖策略
- 标准化和核心流程优先依赖纯 Python 库，避免把外部软件作为 V1 主路径前提。
- 系统级工具例如 OCR、Office/PDF 高保真转换工具视为可选增强能力。
- 若某能力依赖系统工具，必须在 runtime manifest 中声明工具名、是否必需、支持平台、检测方法以及缺失时的降级行为。

### 标准化边界
- 标准化层只做输入整理，不生成正式 Wiki 页面，不做页面合并，不改写知识结论。
- Chunking 只能读取 `normalized/` 产物，不能直接以 `raw/` 作为默认输入。
- 标准化输出必须保留“从 normalized 回到 raw 的路径”，不能只产出干净正文。

### Markdown 文档 Markdown
行为：
- 保留标题层级、列表、代码块、表格、链接。
- 清理 BOM、空白噪声、非法换行。
- 记录行号映射。
默认完全由 Python 实现。

### PDF 文档 PDF
行为：
- 提取页级文本。
- 按页或逻辑段生成 Markdown。
- 记录 `page_range`（页码范围）与页级 `location_map`（位置映射）。
- 无法提取的页面写入 `warnings`（告警信息）。
兜底：
- 复杂排版页可标记待 Agent 辅助。

### Word 文档 Word
行为：
- 提取标题、段落、列表、表格、图片占位。
- 保持块顺序和章节结构。
- 输出 Markdown 和段落级映射。
兜底：
- 对复杂嵌套对象保留结构 `warning`（告警），不强行完美恢复。

V1 当前实现说明：
- `.docx` 当前已实现两条路径：`python-docx` 主路径 + `zip+xml` 纯 Python fallback。
- `.doc` 当前已实现纯 Python 二进制保守 fallback，优先提取可见文本片段和基础容器元数据，不保证高保真结构恢复。

### Excel 表格 Excel
行为：
- 读取 workbook、sheet、表头、数据区域。
- 每个 sheet 转为 Markdown 表格和结构化块。
- 保留 sheet 名、行列坐标、公式存在标记。
兜底：
- 对复杂合并单元格和不规则布局写 `warnings`（告警信息）。

V1 当前实现说明：
- `.xlsx` / `.csv` 当前已实现稳定 Python 路径。
- `.xls` 当前已实现纯 Python 二进制保守 fallback，优先提取可见文本片段和基础容器元数据，不保证工作表结构和公式高保真恢复。

### 图片
行为：
- 先提取文件元数据、EXIF、尺寸、文件名语义。
- 若本地 OCR 可用则提取基础 OCR 文本。
- 若 OCR 不可用或结果不足，则交由 Agent 做视觉理解。
- 无法识别时，至少生成占位 normalized 文档并标记待补充。

V1 当前实现说明：
- 当前已实现“元数据保底 + `tesseract` 可用时本地 OCR 增强”。
- 当前 OCR 结果会写入 normalized Markdown，并在 `location_map.ocr` 中记录 `used/ok/quality/char_count`。
- 当前尚未接入 Agent 视觉理解自动续跑，只保留降级说明与 `warnings`（告警信息）。

### 提取方式 Extraction Method
每个 normalized 产物必须标记一种方法：
- `python_only`（纯 Python 提取）：只使用 Python 库完成转换。
- `python_only+tesseract`（Python + Tesseract OCR）：Python 负责基础处理，Tesseract 负责图片 OCR。
- `python_plus_agent`（Python + Agent 补充）：Python 先提取结构，Agent 再补充语义或视觉理解。
- `agent_only_fallback`（仅 Agent 兜底）：脚本无法可靠提取时，由 Agent 辅助理解，但这不是 V1 主路径。

V1 当前实现说明：
- 当前实际已落地方法主要为 `python_only` 与 `python_only+tesseract`。
- `python_plus_agent`、`agent_only_fallback` 仍属于后续扩展保留值。

### 提取质量 Extraction Quality
每个 normalized 产物必须带质量等级：
- `good`（良好）
- `partial`（部分可用）
- `poor`（质量较差）
- `failed`（失败）

分流规则：
- `good`（良好）：正常进入 chunking（切块）。
- `partial`（部分可用）：进入 chunking，但保留 `warnings`（告警信息）。
- `poor`（质量较差）：仅允许生成 draft（草稿）级中间产物，不允许直接参与稳定结论写入。
- `failed`（失败）：写入 error log（错误日志），不进入 ingest（导入处理）主流程。

### 跨平台实现约束
为支持 Windows、macOS、Linux，V1 实现必须遵守：
- 路径处理统一使用 `pathlib`，不写死 `/`。
- 文件编码默认按 UTF-8 处理，并兼容 Windows 常见换行差异。
- 子进程调用不依赖 `bash`、`zsh` 或 POSIX 专属语法。
- Git、工具检测、文件扫描通过 Python 标准库和可移植命令实现。
- 文档转换优先纯 Python 库，避免一开始就绑定平台特有软件。

### 跨平台验证 Cross-platform Validation

V1 至少需要有一条可执行的验证路径，覆盖：

- `doctor`（环境体检）
- `bootstrap`（环境自举）
- `init`（初始化工作区）
- `ingest`（导入处理）
- `query`（查询）
- `lint`（巡检）

V1 当前实现说明：

- 当前已提供 `scripts/validate_workflow.py`
- 当前脚本会自动构造最小样例资料并验证 `raw/` 子目录递归扫描
- 当前仓库内尚未在真实 Windows 环境完成自动实跑，但脚本与命令示例已按 Windows 兼容约束设计

### 标准化器版本与哈希 Normalizer Version And Hash
- 同时保留 `raw_hash` 和 `normalized_hash`。
- 额外记录 `normalizer_version`，用于判断“原文件没变，但标准化规则变了”的场景。
- 若 `raw_hash` 不变但 `normalized_hash` 改变，应允许从 normalize 之后重新进入 chunk / claim / page 更新。

### 查询标准化 Query Normalization
查询标准化与来源标准化分离，单独实现 `query_normalizer`。

V1 最小要求：
- 去掉无意义口头词。
- 识别中英混写术语。
- 根据 alias registry 扩展同义词。
- 提取核心检索意图，例如 `compare`（对比）、`definition`（定义）、`timeline`（时间线）、`how_to`（操作方法）。
- 输出结构化查询对象，供 BM25 检索和页面选择使用。

V1 当前实现说明：
- 当前已实现的是多字段 BM25 检索与页面权重、状态权重叠加。
- 当前已实现第一版 query normalization：规范化查询、alias 精确命中扩展、canonical 目标回传。
- 当前已实现轻量意图识别，主要覆盖 `lookup / definition / compare / timeline / how_to / evidence`。
- 当前意图识别主要服务检索增强与页面类型轻量调权，尚未发展为复杂问句分析器。
- 当前 `evidence` 类查询已明确优先 `source-summary` 页面，而不是只做轻微偏向。

## 切块设计 Chunking Design

### 切分规则
默认切分策略：
- 先按 Markdown 标题切。
- 超长块再按段落切。
- 过短块与相邻块合并。
- V1 预留 overlap 字段，但当前不启用实际重叠文本。
- 代码块、表格、引用块尽量整体保留。

### 默认参数
- `target_tokens: 1000`（目标 Token 数）：单个 chunk 尽量接近的长度。
- `max_tokens: 1600`（最大 Token 数）：单个 chunk 不应超过的上限。
- `min_tokens: 200`（最小 Token 数）：过短 chunk 会尝试与相邻内容合并。
- `overlap_tokens: 0`（重叠 Token 数）：当前实现不复制相邻 chunk 的重叠文本。

V1 当前实现说明：
- 当前 chunk 参数已在代码中固化为 `target=1000 / max=1600 / min=200`。
- 当前 `overlap_from_previous` 字段已经存在，但默认仍为 `0`，尚未启用真正的 overlap 切块策略。
- 当前不启用 overlap 的主要原因是：V1 更重视证据去重、引用稳定和可追踪性。如果相邻 chunk 复制同一段文字，Claim 抽取时容易把同一句话当作两份证据，进而产生重复 Claim、重复 review 或混乱的 source_refs。
- 为了弥补无 overlap 带来的上下文不足，当前 chunk 会记录 `previous_chunk` 和 `next_chunk`。查询或审核需要更多上下文时，可以沿相邻 chunk 回读，而不是把重叠文本直接写进多个 chunk。
- 后续如果启用 overlap，应只把它作为阅读上下文缓冲，不能把 overlap 内容重复计入 Claim 抽取和证据统计。

### 稳定性规则
- `chunk_id` 必须稳定，不能因重复运行随机变化。
- overlap 只用于上下文缓冲，不得在 claim 抽取时重复计算为新增证据。
- 若 chunk 规则变化导致大规模 `chunk_id` 变更，应进入 `needs_review`，不能静默覆盖旧引用。

### 质量约束
- 尽量不切断代码块、表格、引用块。
- 对 OCR 结果或结构噪声较大的文档，允许保守合并短块，避免制造碎片 chunk。
- 每次 chunking 后都应通过 `chunk lint`，否则不得进入 claim 抽取。

### 作用
Chunk 同时承担：
- 检索单元
- 摘要单元
- Claim 抽取单元
- 溯源单元
- 增量更新单元

## 声明层设计 Claim Layer Design

### 设计原则
- Claim（知识声明）是从原始资料中提炼出的独立结论，不依附于某一个具体 Wiki 页面。
- Wiki 页面不直接把“结论”只绑到 source（来源），而是先绑定到 Claim，再由 Claim 追踪到 chunk 和 source。
- 同一条 Claim 可以被多个页面复用，例如一个概念页、一个综述页和一个来源摘要页可以共同引用同一条结论。
- Claim 必须支持正向和反向引用：既能从 Claim 找到来源，也能从页面反查自己引用了哪些 Claim。

### 文件与索引
- `claims/`：保存单条 Claim 的展开文件，方便人工查看、编辑和参与 review。
- `state/claims.jsonl`：保存 Claim 总账，方便 CLI 快速扫描全部 Claim。
- `indexes/claims.jsonl` 或等价索引：后续可用于加速“某条 Claim 被哪些页面引用”等反查。
- 权威源指“判断当前 Claim 是否存在、是否活跃、引用关系是什么时优先相信的数据”。V1 中 Claim 的权威信息主要由 `claims/*.json` 与 `state/claims.jsonl` 共同维护，索引只是可重建的派生数据。

V1 当前实现说明：
- 当前尚未单独落地 `indexes/claims.jsonl`。
- 当前 Claim 反查主要依赖 `state/claims.jsonl`、Claim 单文件以及页面索引聚合结果。

### 状态
V1 允许：
- `draft`（草稿）：自动抽取或初步整理出来的声明，还没有经过稳定性确认。
- `stable`（稳定）：经过人工确认、长期使用或多来源支撑后，可以作为可靠结论参与页面组织。
- `disputed`（有争议）：声明本身仍保留，但它可能与其他声明冲突，需要在页面或 review 中明确标注。
- `needs_review`（需要审核）：系统检测到重复、近重复、冲突、来源更新或其他风险，需要人工或 Agent 辅助判断。
- `archived`（已归档）：声明不再作为当前有效结论使用，但历史记录仍保留，方便追溯它为什么被替代或移出。

V1 当前实现说明：
- 当前规则抽取出来的 Claim 主要落在 `draft` / `needs_review`。
- `disputed` 目前仍更偏向后续人工或 Agent 深化治理状态，尚未在自动流程中完整展开使用。
- `stable` 则已经进入受控自动流程：系统可在 `review-auto` 阶段通过 `stable_promotion` hook，对来源覆盖、证据强度和语义清晰度都较好的 Claim 做保守提升；若 hook 未给出高置信 promote，则仍保持原状态。
- 原因是 `stable` 和 `disputed` 都需要比“抽取一句话”更强的判断：`stable` 需要确认来源可靠、语义清楚、没有被其他 Claim 明显反驳；`disputed` 则还需要确认候选 Claim 之间确实存在争议，而不是只是表达方式不同、上下文不同或抽取噪声。
- V1 的自动流程主要负责把候选结论、来源和风险信号整理出来，不默认替用户做最终知识裁决。这样可以避免系统过早把不成熟 Claim 标成稳定结论，或把误报冲突标成争议事实。
- 生命周期维度当前独立使用 `lifecycle_status` 表达 `active / superseded / archived`。
- 简单理解：`status` 说明 Claim 的知识可信状态，`lifecycle_status` 说明这条 Claim 当前还是否参与主流程。

### 声明类型 Claim Type
V1 建议支持：
- `definition`（定义类）：解释某个概念、对象或术语是什么。
- `fact`（事实类）：陈述一个可追踪、可引用的事实。
- `comparison`（对比类）：说明两个或多个对象之间的区别、相似点或优劣。
- `causal`（因果类）：描述原因、结果、影响或机制。
- `procedure`（步骤类）：描述操作步骤、流程或方法。
- `evaluation`（评价类）：表达判断、建议、优先级或取舍。
- `warning`（风险提示类）：提示限制、风险、反例、注意事项或不适用场景。

V1 当前实现说明：
- 当前自动抽取阶段主要先生成通用 Claim，声明类型可以先为空或使用粗粒度规则补充。
- 当前规则抽取采用“整句优先，子句只作候选补充”的策略：先保留完整句，再在长句中只挑可独立理解的子句作为补充候选，避免把逗号后的从句残片直接提升成 Claim。
- 当前规则抽取还会主动过滤一批高噪声片段，避免把“像文本但不是知识声明”的内容推进到 Claim 层。例如：HTML 注释里的 `turn_id / speaker / time` 元信息、`Alice:` / `Bob:` 这类对话发言前缀，以及孤立的纯日期标题。
- 当前规则会对 `旨在`、`具体细节`、`这是一份思路文件` 这类明显依赖前文的从句或元描述做降权，避免它们在概念页里抢占“代表陈述 / 核心陈述”。
- 对 `一种……的模式`、`一类……方法` 这类短定义短语，当前会直接识别为更适合展示的定义型 Claim，用于概念页命名和代表陈述选择。
- 当前当整段文本在句级切分后全部被判定为噪声时，不再把整段原文作为 fallback Claim 硬塞回去，避免会议记录、日志元信息或目录碎片继续误入概念页。
- 例外是：如果正文抽不出 Claim，但章节标题本身是 `YYYY-MM-DD` 这样的完整日期，系统会补一条日期型 Claim，保留时间线入口与日期概念页。
- 后续 Agent 增强抽取时，可以根据句式和上下文补全 `claim_type`，再用于页面组织、检索加权和 review 判断。

## 检索设计 Retrieval Design

### 默认查询顺序
- 先检索 `wiki pages`
- 再下钻 `claims`
- 最后按需回读 `chunks`

V1 当前实现说明：
- 当前 query 已实现这种读取顺序，并能返回 `reading_pack`（阅读包）。
- `reading_pack` 会把匹配到的 Claim、Chunk、来源摘要和相邻 Chunk 线索打包出来，方便 Agent 继续顺着证据链阅读。

### 多字段 BM25
至少对这些字段分别打分：
- `title`（页面标题）
- `aliases`（页面别名）
- `summary`（页面摘要）
- `headings`（页面标题层级）
- `body`（页面正文）
- `claim_text`（页面关联 Claim 文本）
- `source_refs`（来源引用）

总分公式固定为：
`final_score = Σ(field_weight * bm25(field)) * page_type_weight * page_status_weight`

公式含义：
- `bm25(field)`：查询词在某个字段里的 BM25 匹配分数。
- `field_weight`（字段权重）：不同字段的重要程度不同，标题命中通常比正文命中更重要。
- `page_type_weight`（页面类型权重）：不同页面类型的默认可信度和用途不同。
- `page_status_weight`（页面状态权重）：稳定页面优先，过期或待审核页面适当后排。
- `final_score`（最终分数）：综合字段命中、页面类型和页面状态之后的排序分数。

V1 当前实现说明：
- 当前 query 优先读取 `indexes/search_pages.jsonl`。
- `indexes/search_pages.jsonl` 是页面检索索引，保存页面字段文本、分词结果和必要元数据。
- `page_signature`（页面签名）用于判断页面内容是否变化；没有变化的页面可以复用旧索引，减少重复计算。
- `alias / title / canonical` 精确命中会额外加权：别名、标题或规范 ID 直接命中时，说明用户很可能在找这个页面。
- 当前已实现六类轻量查询意图：`lookup`（查找）、`definition`（定义）、`compare`（对比）、`timeline`（时间线）、`how_to`（操作方法）、`evidence`（证据来源）。
- `timeline` 查询会额外返回 `timeline_sources`（时间线来源分组），帮助 Agent 按来源组织时间线证据。
- `evidence` 查询会更强地提升 `source-summary`（来源摘要页），并相对压低 `concept-summary`（概念摘要页），确保“先看出处”的阅读顺序更稳定。

### 查询结果契约 Query Output Contract
V1 的 query 不只是返回排序结果，还必须返回一个足够驱动 Agent 继续阅读的结构化包。

最小输出应包含：
- 查询文本与标准化后的查询文本。
- 查询意图。
- alias（别名）命中与 canonical（规范页）命中线索。
- 候选页面列表。
- 每个页面的排序解释与命中字段。
- `reading_pack`（阅读包）。

`reading_pack` 最小包含：
- `query_intent`（查询意图）
- 匹配的 `claims`（知识声明）
- 匹配的 `chunks`（证据切块）
- 相关来源摘要
- chunk 的 `section_path`（章节路径）
- `previous_chunk`（前一切块）
- `next_chunk`（后一切块）

V1 当前实现说明：
- `query` 顶层当前已显式返回 `contract_version: query_answer_handoff/v1`。
- `query` 当前支持 `reading_depth`，默认 `standard`，可显式切到 `deep`。
- `standard` 适合先定位页面与核心证据；`deep` 会返回更厚的 `reading_pack`，并额外附带按来源聚合的 `source_trail`。
- `source_trail` 的目标不是做新的摘要生成，而是把已命中的 Claim/Chunk 沿来源维度重新收束，帮助 Agent 在大上下文窗口下继续做 deterministic 的证据阅读。
- `reading_pack` 当前除保留兼容字段外，也已显式返回 `query`、`page_context`、`retrieval_context`、`evidence_context`、`answer_guardrails`、`answer_handoff`。

工程约束：
- Agent 默认先读结果页和排序解释，再决定是否进入 `reading_pack.claims`。
- 若问题涉及证据、冲突、时间线或引用，不能只消费页面摘要，必须继续下钻 `claims/chunks/source summaries`。
- Query 输出的目标不是“直接替用户回答一切”，而是把正确阅读路径打包出来。
- 即使在 `deep` 模式下，也优先扩充结构化证据路径，而不是直接让 LLM 重新总结合成。

### Query -> Answer Handoff Contract
`reading_pack` 不应只被视为“检索结果附带的上下文”，还应被定义为上层回答器或 Agent 的标准输入。

这层 handoff contract 的目标不是替回答器直接生成最终答案，而是把“回答前必须消费的结构化证据上下文”稳定交接出去。

它至少要解决四个问题：
- 哪些字段是回答器可以稳定依赖的必备输入。
- 回答器面对不同 `query_intent` 时，应该先读什么、后读什么。
- 哪些问题可以先基于页面摘要和核心 Claim 作答，哪些问题必须继续下钻 Chunk 与 Source。
- 当证据不足、存在 review 风险或命中冲突时，回答器应该如何降级，而不是硬答。

V1 建议把 handoff contract 理解成一个语义稳定层。即使底层 query 排序、打分细节或内部字段继续演化，这层对回答器暴露的消费协议也应尽量保持稳定。

建议的 V1 contract 形态如下：

```json
{
  "contract_version": "query_answer_handoff/v1",
  "handoff_kind": "reading_pack",
  "query": {
    "text": "...",
    "normalized_text": "...",
    "intent": "lookup|definition|compare|timeline|how_to|evidence",
    "reading_depth": "standard|deep"
  },
  "page_context": {
    "page_id": "...",
    "title": "...",
    "page_path": "...",
    "type": "...",
    "status": "...",
    "summary": "...",
    "canonical_id": "...",
    "aliases": []
  },
  "retrieval_context": {
    "focus": "general_lookup|workspace_overview|compare_claims|timeline_evidence|procedural_chunks|source_evidence",
    "matched_fields": [],
    "ranking_reasons": [],
    "review_ids": []
  },
  "evidence_context": {
    "matched_claims": [],
    "matched_chunks": [],
    "timeline_sources": [],
    "source_trail": []
  },
  "answer_guardrails": {
    "can_answer_from_summary_only": false,
    "must_read_claims": true,
    "must_read_chunks": false,
    "must_read_sources": false,
    "cite_expectation": "none|light|strong",
    "risk_flags": []
  },
  "answer_handoff": {
    "answer_mode": "summary_first|claims_first|chunks_first|sources_first|no_match",
    "recommended_read_order": [],
    "required_evidence_paths": [],
    "should_cite_sources": false,
    "should_surface_uncertainty": false,
    "fallback_action": "answer_from_summary_and_claims|read_required_evidence_before_answering|answer_with_uncertainty|broaden_or_rephrase_query"
  }
}
```

字段含义：
- `contract_version`：显式声明回答器当前遵循的 handoff 版本，避免未来字段扩展时出现静默错配。
- `handoff_kind`：标明这是一份给回答器消费的阅读包，而不是裸检索结果。
- `query`：保存原始问题、标准化查询、意图和阅读深度，帮助回答器理解这次检索为什么会返回当前阅读路径。
- `page_context`：给出当前最优结果页的稳定页面上下文，作为回答器组织答案时的默认锚点。
- `retrieval_context`：描述检索器建议的阅读重心和风险入口，例如 `focus`、字段命中、排序解释和 `review_ids`。
- `evidence_context`：承载回答器真正可引用、可继续下钻的结构化证据对象。
- `answer_guardrails`：把“回答边界”显式化，避免回答器把 `reading_pack` 当作无约束素材池直接发挥。
- `answer_handoff`：把“先读什么、是否应引用、风险出现时如何降级”显式化，减少上层回答器自行猜测消费顺序。

V1 建议的消费规则：
1. 回答器先读取 `page_context.summary`、`retrieval_context.focus` 和排序解释，确认当前命中的是哪一类页面与阅读路径。
2. 若 `focus` 是 `workspace_overview` 或 `general_lookup`，且没有明显风险标记，可先基于页面摘要和高相关 Claim 组织简短回答。
3. 若 `focus` 是 `compare_claims`、`timeline_evidence`、`procedural_chunks` 或 `source_evidence`，则不能停在摘要层，必须继续消费 `matched_claims`，并按需下钻 `matched_chunks`、`timeline_sources`、`source_trail`。
4. 若 `review_ids` 非空、页面状态是 `needs_review` / `disputed`、或高相关 Claim / Chunk 明显不足，回答器必须输出不确定性提示，而不是把当前结果伪装成确定答案。
5. 若用户问题显式要求证据、来源、引用、时间顺序或冲突解释，`cite_expectation` 应至少提升到 `light`，并优先引用 `source_refs`、`section_path`、`source_trail` 等可回链对象。

V1 建议的 guardrail 推导规则：
- `lookup` / `definition`：通常允许 `can_answer_from_summary_only=true`，但若无高相关 Claim，则仍应提示证据较薄。
- `compare`：`must_read_claims=true`，必要时继续读 `matched_chunks`，避免只凭摘要做对比结论。
- `timeline`：`must_read_claims=true` 且 `must_read_sources=true`，优先消费 `timeline_sources` 与时间相关 Chunk。
- `how_to`：`must_read_chunks=true`，因为步骤型问题通常需要正文顺序和相邻 Chunk 线索。
- `evidence`：`must_read_chunks=true` 且 `must_read_sources=true`，不能只引用页面摘要或孤立 Claim。

与当前实现的映射关系：
- 现有 `reading_pack.query_intent` 可直接映射到 `query.intent`。
- 现有 `reading_pack.focus` 可直接映射到 `retrieval_context.focus`。
- 现有 `matched_claims`、`matched_chunks`、`timeline_sources`、`source_trail` 已经是 `evidence_context` 的主体。
- 现有结果页里的 `summary`、`page_id`、`page_path`、`type`、`status`、`aliases`、`canonical_id` 可归入 `page_context`。
- 现有结果里的命中字段、命中 token 和排序解释可归入 `retrieval_context`。
- `answer_guardrails` 与 `answer_handoff` 当前都已在 CLI JSON 中显式输出。

工程边界：
- handoff contract 服务的是“query 之后、answer 之前”的交接，不负责替回答器完成最终措辞。
- 它的首要价值是减少上层 Agent 对底层检索细节的猜测成本。
- 回答器若绕过这层 contract，直接把候选页正文或 raw 材料大段读入，就违背了 MyAgentWiki 的 CLI-first 和 deterministic-first 设计意图。

### Answer-Ready Output Layer
在 `reading_pack` 之上，当前实现已经补了一层面向上层回答器的 answer-ready 输出。

当前支持两种入口：
- `python3 -m myagentwiki query "..." --answer-ready`
- `python3 -m myagentwiki answer-query "..."`

这层输出的目标不是替回答器完成最终答案，而是把最适合回答阶段直接消费的内容再压一层，减少每个上层 Agent 都去手工解析 `reading_pack` 的重复工作。

当前 answer-ready payload 使用独立版本：
- `contract_version: answer_ready_query/v1`

最小结构包含：
- `workspace_summary`：工作区路径摘要，便于回答器或上层 Agent 在展示、跳转、恢复上下文时拿到绝对路径。
- `selected_result`：当前回答锚点页、`ready_state`、页面状态与得分。
- `alternatives`：次优候选页，供回答器在主锚点不稳时快速切换。
- `agent_brief`：回答模式、推荐读序、必读证据路径、风险标记、降级动作。
- `answer_context`：压缩后的 `page_summary`、`key_claims`、`key_chunks`、`key_sources`。
- `agent_summary`：给上层 Agent 直接阅读的一段紧凑交接摘要。

当前支持四种渲染格式：
- `summary`：回答就绪摘要，适合人读或轻量 Agent 直接消费。
- `prompt`：单段 prompt block，适合直接喂给上层 LLM。
- `messages`：聊天 API 可直接消费的 messages 数组。
- `chatml`：messages 的 ChatML 文本表示，同时保留结构化 messages。

工程约束：
- answer-ready 层只做“为回答阶段整理上下文”，不替代底层 query 排序与证据选择。
- 若顶层结果存在明显风险，answer-ready 层应优先输出 `answer_with_uncertainty` 或 `broaden_or_rephrase_query` 这类降级动作，而不是假装已有稳定答案。
- `messages` / `chatml` / `prompt` 三种格式应共享同一套 handoff 语义，避免不同渲染格式各自漂移。
- 即使在 `summary` 这种面向人读的文本渲染模式下，也应先显式给出工作区路径摘要，避免调用端把绝对路径压缩成仅剩目录名。

### Review-Auto Handoff Layer
在 `review-list / review-apply` 之上，当前实现又补了一层面向上层 Agent 的审核自动处理输出。

当前入口为：
- `python3 -m myagentwiki review-auto`

这层输出的目标不是替用户完成所有审核判断，而是先自动处理高把握审核项，再把剩余需要人判断的部分稳定交给上层 Agent 或对话层。

当前 review-auto payload 使用独立版本：
- `contract_version: review_auto_handoff/v1`

最小结构包含：
- `workspace_summary`：工作区路径摘要，便于 Agent 在多工作区或恢复场景中保持定位一致。
- `planned_actions`：本轮 review-auto 对每条 open review 的计划判断，区分 `auto_apply` 与 `escalate`。
- `applied_actions`：已自动执行的审核动作及其影响对象。
- `promoted_claims`：自动审核后，被保守提升为 `stable` 的 claim。
- `escalated_reviews`：仍需要人判断的 review 计划摘要。
- `escalation_handoff`：给上层 Agent 或对话层直接消费的升级人工条目，包含 `issue_summary`、`why_human_needed`、`choice_options` 与 `suggested_user_prompt`。
- `agent_brief`：是否应继续追问用户、下一步应该继续工作还是进入人工选择。
- `agent_summary`：给上层 Agent 直接阅读的一段紧凑摘要。

当前支持四种渲染格式：
- `summary`：审核自动处理摘要，适合人读或轻量 Agent 直接消费。
- `prompt`：把整轮审核自动处理结果压成可直接喂给上层 LLM/Agent 的 prompt。
- `messages`：聊天 API 可直接消费的 messages 数组。
- `chatml`：messages 的 ChatML 文本表示，同时保留结构化 messages。

工程约束：
- review-auto 层只做“先自动、再升级人工”的保守收口，不替代底层 review 账本、页面重建与状态恢复逻辑。
- 若 `agent_brief.should_ask_user=false`，上层 Agent 应继续后续工作，而不是重新要求用户裁决已被安全自动收口的 review。
- 若 `agent_brief.should_ask_user=true`，上层 Agent 应只围绕 `escalation_handoff` 中列出的审核项追问用户，并优先使用 `choice_options` 的白话标签解释选项。
- `messages` / `chatml` / `prompt` 三种格式应共享同一套 handoff 语义，避免不同渲染格式各自漂移。

当前实现边界已经比早期设计更进一步：
- `review-auto` 不再只覆盖“恰好两条候选 Claim 的 duplicate merge”和最窄的 alias 修正。
- 当前会优先读取 live review、live claim、live page 与 alias index 现状，再结合 deterministic 规则和可选 Agent hook 生成计划。
- 当前已补充的保守自动收口场景包括：
  - 片段化、明显过短或被更完整陈述包含的 `claim_conflict`，自动 `archive_one`
  - 两条都像问题、但语义焦点明显不同的 `claim_conflict`，自动 `keep_both`
  - 共享核心词但互补、且并非包含关系的两条非问句 Claim，自动 `keep_both`
  - 噪声 alias（例如 `一句话总结`、`注意`）在唯一 canonical 归属下的自动 `assign_alias`
  - 不适合作为检索入口、且不存在标题归属的噪声 alias，自动 `remove_alias`
- 若配置了 `automation.review_auto` 的 Agent hook，系统会先把 review、候选 claim、候选页面、允许动作和证据摘要打包给 hook；只有 hook 返回 `decision=auto_apply` 且达到最小置信阈值时，CLI 才真正落地动作。
- 自动动作执行完成后，系统会立即复用既有 `review-apply` 收口链，刷新相关 claim、review、页面、索引与 handoff 摘要，而不是只在内存里记一份临时决策。

### Stable Promotion Hook
除了审核自动处理，当前实现已经为 Claim 的 `stable` 提升补了一层 Agent-assisted hook。

当前入口仍然挂在：
- `python3 -m myagentwiki review-auto`

它的职责不是单独暴露成另一条命令，而是在自动审核完成、需要判断某条 live claim 是否可以被保守提升为 `stable` 时，作为受控子步骤运行。

当前约束：
- `stable_promotion` hook 接收单条 claim 的文本、来源覆盖、证据数量、置信度、页面关联等结构化信息。
- hook 只有返回 `decision=promote` 且 `confidence` 达到配置阈值时，CLI 才会把该 claim 提升为 `stable`。
- 若 hook 未启用、未返回 promote、或置信度不足，则 claim 保持原状，不会因为自动流程“顺手”被提稳。
- `review-auto` 的最终 payload 会把本轮自动提升为 `stable` 的 claim 汇总到 `promoted_claims`，供上层 Agent 判断后续是否继续生成概念页、综述页，或仍需人工确认。

当前默认触发链已经进一步收口为：
- `review-auto` 自动提升 claim 为 `stable` 后，不需要再等人工单独触发页面生成。
- 页面重建链会立刻把这些稳定 claim 编译为可读 `concept` 页。
- 当工作区里至少已有两个可读 `concept` 页时，同一条重建链会继续生成或刷新工作区级 `overview` 页。
- 因此 `stable` 不只是状态标签，也直接成为更高层可读页面自动生成的触发条件。

### 查询读取规则 Query Reading Rules
- 查询时先读 `index`（索引）、`frontmatter`（页面元数据）、`summary`（摘要）、`aliases`（别名）、`headings`（标题层级）。
- 命中相关页面后，再读取相关 `section`（章节）、`claim`（知识声明）、`chunk`（证据切块）。
- 判断型、冲突型、对比型问题不能只读孤立 chunk，因为孤立片段可能缺少页面语境和来源背景。
- 命中 chunk 时必须同时附带页面摘要、`section_path`（章节路径）、`previous_chunk`（前一切块）、`next_chunk`（后一切块）。
- 涉及证据、冲突或引用时，必须回读 claim 对应的 chunk/source，避免只根据页面摘要下结论。

### 查询标准化与扩展 Query Normalization And Expansion
- 搜索时必须同时查 `title`（标题）、`summary`（摘要）、`aliases`（别名）、`body`（正文）。
- alias（别名）精确命中、canonical（规范页）命中、redirect（重定向）指向规范页时，应参与加权。
- 中英混合查询默认启用 aliases（别名）扩展和 canonical（规范名）归一化，减少“同一个概念多种叫法”导致的漏检。

### 默认权重
字段权重：
- `title: 5.0`（页面标题）：标题命中通常最强，说明用户可能直接在找这个主题。
- `aliases: 4.0`（页面别名）：别名命中接近标题命中，适合处理简称、旧称、中英文混用。
- `summary: 3.0`（页面摘要）：摘要代表页面核心内容，权重高于普通正文。
- `headings: 2.5`（标题层级）：章节标题能反映局部主题，适合定位页面内部结构。
- `body: 1.0`（页面正文）：正文信息量最大，但噪声也最多，所以作为基础权重。
- `claim_text: 2.0`（关联声明文本）：Claim 是结构化结论，命中后应比普通正文更重要。
- `source_refs: 0.5`（来源引用）：来源引用主要用于证据类查询，不应在普通主题查询中过度放大。

页面类型权重：
- `overview: 1.25`（综述页）：适合回答宏观问题，默认优先级最高。
- `concept: 1.15`（概念页）：适合解释概念和主题。
- `concept-summary: 1.15`（概念摘要页）：V1 自动生成的概念页，权重与概念页接近。
- `entity: 1.10`（实体页）：适合回答人物、项目、工具、组织等对象问题。
- `source-summary: 1.00`（来源摘要页）：适合证据和出处问题，普通查询中保持中性权重。
- `qa: 0.95`（问答页）：适合具体问答，但不应默认压过正式概念页。
- `draft: 0.70`（草稿页）：内容还不稳定，默认后排。

页面状态权重：
- `stable: 1.10`（稳定）：可靠页面适当加权。
- `draft: 0.80`（草稿）：可读但尚未确认，适当后排。
- `disputed: 0.90`（有争议）：保留可见性，但提醒 Agent 谨慎阅读。
- `outdated: 0.60`（过期）：通常不应优先作为当前答案依据。
- `needs_review: 0.75`（需要审核）：存在待处理风险，默认后排。

### Codex / Claude Code 读取策略 Reading Strategy
V1 不实现复杂动态预算器，但规则文件中必须明确轻量阅读策略：
- 先读索引和候选页摘要，再决定是否下钻正文。
- 不默认大批量读取 raw。
- 长页面如频繁只读局部，应建议拆页。

## 更新与审核 Update And Review

### 自动写入默认策略
默认采用“常规自动写入 + 全程留痕”。

### 增量 ingest 与版本收口策略
V1 的 ingest 必须被定义为“增量编译”，而不是每次都把整个工作区当作全新项目处理。

来源级规则：
- `raw/` 按递归路径扫描，但会跳过任意层级中所有 `.` 开头的文件和目录。
- 同一路径来源的多次变化通过 `version_group` 归到同一演进链。
- 新 `source_hash` 出现时，允许生成新的 source 版本记录。
- 旧版本来源不直接物理删除，而是通过状态和引用关系退出 live 集合。

中间层规则：
- `normalized/chunks/claims/pages/indexes` 的 live 集合只围绕当前活跃来源重建。
- 由旧来源导出的 live Claim、自动页和索引项，在新版本来源稳定接管后进入历史态或移除态。
- 任何一次 ingest 都要优先保证“live 集合自洽”，再保留历史痕迹。

V1 当前实现方向：
- 允许保留历史 Claim、历史 Review、移除态页面。
- 自动页面支持 `prune stale auto pages`（清理过期自动页）：当某个自动页已经不再对应当前活跃来源或 Claim 时，把它移出 live 页面集合，并在页面账本中保留历史记录。
- search index（搜索索引）优先增量复用未变化页面的索引记录，避免每次 ingest 都全量重建。

V1 暂不承诺：
- 不承诺跨任意版本的完美最小 diff。
- 不承诺所有中间层文件都做对象级最细粒度复用。

当前 `ingest` 已经可以被配置成复合自动化流程，而不只是“写完中间产物就结束”：
- 当 `automation.post_ingest.review_auto: true` 时，每次 `ingest` 结束后，CLI 会自动继续执行一轮 `review-auto`。
- 因此对 Codex / Claude Code 而言，默认应把 `ingest` 理解为 `ingest -> review-auto` 的复合收口流程；如果本轮 review-auto 又自动提升了部分 claim 为 `stable`，那后续概念页、综述页渲染就能直接消费更稳定的输入。
- `ingest` 的 JSON 输出会额外附带 `post_ingest_review_auto`，纯文本输出也会单独打印一段 post-ingest auto-review 摘要，避免上层 Agent 误以为 ingest 已经完全结束。
- 在默认模板下，这条复合流程还隐含了后续页面自动收口：`ingest -> review-auto -> stable promotion -> readable concept render -> workspace overview render`。
- 其中后两步不需要上层 Agent 再单独补一条 `render-page` 命令；它们已经被纳入同一套页面重建链里。

### 更新模式
页面更新策略与页面创建策略分离，V1 固定支持：
- `append`（追加）：补充新证据或新段落，不改写旧结论。适用于新增来源只是在原有页面后面增加材料的情况。
- `merge`（合并）：把新旧信息整理到同一个页面或同一条 Claim 中。适用于新信息和旧信息方向一致，但需要去重、改写或重新组织的情况。
- `conflict-mark`（冲突标记）：保留冲突内容，并明确标记存在不同说法。适用于系统发现新旧结论可能相反，但还不能自动判断谁更可靠的情况。

### 必须进入审核队列的场景
- 截然相反的结论：例如一条 Claim 说“应该做 X”，另一条 Claim 说“不应该做 X”。
- 高度相似但是否应合并不明确的结论：例如两句话很像，但可能来自不同语境，不能直接合并。
- 替换稳定 Claim：任何会影响 `stable` Claim 的动作都需要人工确认。
- 覆盖稳定页面核心结论：不能自动把稳定页面的核心判断改掉。
- 批量删除、合并、重命名页面：这类操作影响链接、索引和历史追踪，需要审核。
- 大量 `source_refs`（来源引用）或 Claim 映射失效：说明证据链可能断裂，需要先查明原因。
- 别名冲突或 `canonical`（规范页）边界不明确：同一个别名可能指向多个页面时，必须人工判断归属。
- 将 `qa-note`（问答笔记）提升为正式概念页或综述页：问答沉淀可以轻量保存，但升级为正式知识页需要审核。
- 涉及 `private / sensitive`（私有 / 敏感）内容流向 `public / export`（公开 / 导出）区域：涉及信息边界，必须审核。

V1 当前实现说明：
- Claim 冲突 / 近重复检测采用组合策略：先用前缀分组和关键词倒排快速找候选，再用文本相似度做复核。
- `bucket`（分组）用于把看起来相近的 Claim 放到同一批里，减少全量两两比较的成本。
- `token`（检索词 / 分词结果）倒排召回用于发现“开头不同但核心词相同”的 Claim。
- `conflict base`（冲突基准文本）会先弱化否定词影响，再结合否定极性判断是否可能是相反结论。
- `claim_conflict`（声明冲突审核）表示系统认为候选 Claim 可能互相矛盾，需要进入 review。
- `alias_conflict`（别名冲突审核）表示同一个 alias 同时映射到多个 canonical 页面，需要人工指定归属或移除别名。
- 当前策略仍是启发式规则，目标是减少漏检和明显误报；它只是把风险送进审核队列，不等同于最终语义判定。

### V1审核动作 V1 Review Actions
- `merge`（合并）
- `keep_both`（两者都保留）
- `archive_one`（归档其中一个）
- `edit_then_resume`（先编辑再恢复流程）
- `assign_alias`（指定别名归属）
- `remove_alias`（移除别名）

V1 当前实现说明：
- `merge`：保留主 Claim，归档次 Claim，并自动改写其他仍为 open 的 review 候选。
- `keep_both`：解决当前 review，但保留双方 Claim。
- `archive_one`：归档指定活跃 Claim。
- `edit_then_resume`：允许人工先修改 `claims/*.json`，再从当前 review 状态恢复后续页面与索引刷新。
- `assign_alias`：用于 alias conflict review，把冲突 alias 指定给目标页面，并写入持久化 alias 覆盖层。
- `remove_alias`：用于 alias conflict review，把冲突 alias 从页面覆盖层中移除。
- 当前 alias 覆盖层已经按“基于 live page 当前 alias 集合增删”的方式实现，避免人工处理单个 alias 时误伤该页原有其他 alias。
- 当前 `assign_alias / remove_alias` 会先预演 alias 覆盖结果并重建 alias index，确认 alias 真正收敛后才写回账本，避免出现“命令成功但冲突仍存在”的假收敛。
- 当前 `assign_alias / remove_alias` 已补充“重复 ingest 后仍然保持人工裁决结果”与“过期 alias review 自动收口”的回归测试。
- 当前 `assign_alias` 的成功条件已经从“目标 alias 最终只落到某个 `page_id`”提升为“最终只收敛到目标 `canonical_id` 家族”。
- 这意味着同一个规范主题下允许 `concept` 与 `concept-summary` 等页面类型共存；只要 alias 最终只归属于同一 canonical family，就应视为成功收敛，而不是误报冲突未解。

### 自动化分级
V1 引入四级自动化边界：
- `safe_auto`（安全自动）：低风险、可重复、可回滚的动作可以直接执行。
- `auto_with_log`（自动执行并记录）：允许自动执行，但必须写入日志或变更记录。
- `require_review`（需要审核）：不能直接执行，必须先生成 review item。
- `locked`（锁定）：默认不允许自动修改，除非用户明确要求。

页面可通过 `automation_level` 声明是否允许自动修改。

### 审核单内容
Review item 不只保存动作名，还必须保存：
- 风险原因
- 受影响页面 / claims（声明）/ chunks（证据切块）
- 推荐动作
- 可选动作
- `resume_from`（恢复起点）
- 关键证据摘要

### QA回写策略 QA Writeback Policy
V1 把问答沉淀拆成三类：
- `qa-note`（问答笔记）：保存一次高质量问答，但不直接变成正式知识页。
- `overview`（综述页）：面向一个主题的高层总结页面。
- `concept-update`（概念页更新）：把问答中稳定的新结论补充到已有概念页。

默认规则：
- 高质量问答可自动沉淀为 `qa-note`。
- `qa-note` 不自动提升为正式 `concept`。
- 提升为正式概念页或综述页必须进入 review。

### 页面模板
V1 为三类页面提供固定模板：
- 概念页：定义、为什么重要、工作原理、适用场景、局限性、相关概念、来源。
- 实体页：是谁/是什么、核心信息、相关项目/概念、在本知识库中的定位、来源。
- 来源摘要页：原文概览、核心观点、提取到的概念、提取到的实体、与现有页面的联系/冲突、后续建议。

V1 当前实现说明：
- 当前概念页选择 canonical claim 时，不再只按来源数、置信度和文本长度排序，还会综合“是否像定义句”“是否能脱离上下文独立理解”“是否属于从句/元描述”这些可读性信号。
- 当前概念页展示层会优先把定义短语渲染成“概念名 + 定义短语”的形式，例如把 `一种利用 LLM 构建个人知识库的模式` 展示成 `LLM Wiki 一种利用 LLM 构建个人知识库的模式`，避免代表陈述只剩下孤立短语或半句话。
- 当前概念页中的 `Source Pages`（来源页面）与 `Source Evidence`（来源证据）已经不再只平铺内部 ID，而是优先展示适合人工阅读的入口：
  - 来源摘要页链接
  - 原始来源文件链接
  - 覆盖到的 claim / chunk 数量
  - 逐条展开的证据 chunk 链接，以及对应 `section_path`（章节路径）和行号
- `page_id / source_id / chunk_id` 等内部标识仍然保留，但会降到次级信息，避免压过真正用于阅读和下钻的页面标题、原始路径与证据位置。
- 当前来源摘要页中的 `Chunks`（证据切块）列表也会直接链接到 `chunks/<source_id>.jsonl`，方便从来源页继续下钻切块文件本体。
- 当前已存在第二层可读页体系：`concept`（人类可读概念页）与 `overview`（工作区综述页）。
- 当前这两类页面默认渲染模式都是 `llm_assisted`，但底座仍然是 deterministic：先由脚本计算 canonical claim、稳定主题、source coverage、推荐阅读路径等结构，再允许 LLM 在 grounded 约束下做可读性改写。
- `concept` 与 `overview` 页面都必须记录 `render_target / render_mode / render_status`。
- `overview` 在 `llm_assisted` 成功时，会额外生成折叠式 `Rewrite Traceability` 区块，显式展示改写句与其回绑页面，避免综述页长出新的“幻觉层”。
- 因而当前页面生成的产品方向已经明确不是“只产出 source-summary + concept-summary 的中间草稿”，而是进一步支持 Agent 协同生成正式可读的概念页与工作区综述页；它们依旧由脚本先搭好 grounded 骨架，再由 LLM 做受控改写。
- 当前默认模板也已经把这两类页面的 `command` 指向统一 Agent hook，因此对新工作区来说，“允许 LLM 辅助改写”已经不再是需要额外配置才能开启的能力，而是默认启用、按 grounded 校验自动回退的标准行为。

### 恢复机制
- 自动流程写入 review item 后暂停危险动作。
- 人工决策完成后，从 review 状态恢复后续步骤，例如刷新 Claim、重建页面、更新索引和写回账本。
- 不要求整条 ingest 全量重跑。

V1 当前实现说明：
- 当前 `review-apply` 执行动作后会即时刷新受影响的自动页面、`state/pages.jsonl`、`wiki/index.md` 与 `indexes/search_pages.jsonl`。
- 当前 `review-auto` 会优先读取 live review、live claim 与 alias/index 现状，先自动执行高把握动作，再复用既有页面重建与状态写回流程收口，而不是单独维护第二套恢复链。
- `edit_then_resume` 当前已支持“人工先改 Claim 文件，再恢复页面和索引重建”。
- 当前 `alias_conflict`（别名冲突）在 `review-apply` 后，若人工覆盖层已消除冲突，下一轮 ingest 不会重新打开同一条 open review。
- 当前 `review-list` 与 `review-apply` 在读取 review 前，会先按最新 live pages 与 alias index 刷新 alias conflict 队列；若某条 alias review 已不再对应真实冲突，会自动从 active/open 视图转入历史态。
- 当前工作区模板中的 `AGENTS.md` 与 `CLAUDE.md` 也已经同步要求上层 Agent：
  - 把 `ingest` 视作可能自动连跑 `review-auto` 的复合流程
  - 优先尝试 `automation.review_auto` 与 `automation.stable_promotion` 对应的 Agent hook
  - 除非确实需要人工判断，否则不应过早停止在“已发现 review”这一步

### Review 与状态一致性约束
为保证 review 真正能成为恢复入口，V1 明确以下一致性规则：

1. Review 解决动作必须改写账本，而不只是改一个展示文件
- `merge / archive_one / keep_both / edit_then_resume / assign_alias / remove_alias` 都必须回写状态层。

2. Review 解决后必须收口关联对象
- 相关 Claim 的 `status / duplicate_candidates / review_reason` 需要同步刷新。
- 相关自动页的 `claim_ids / review_ids / source_refs` 需要重新生成或移除。
- 相关搜索索引和 alias registry 需要同步重建或校正。

3. 已失效候选不能继续留在 open review 中
- 某个 Claim 被 merge 或 archive 后，其他 open review 对它的引用必须被重写、替换或收口。
- 某个 alias_conflict review 若在最新 alias index 中已找不到对应冲突，也必须自动退出 active/open 集合，而不是继续作为待处理项展示。

4. 人工编辑恢复必须显式走 `edit_then_resume`
- 避免 Agent 静默把磁盘上的人工改动和内存中的旧状态混用。

5. alias 类裁决必须以“真实收敛”作为成功条件
- `assign_alias` 只有在目标 alias 最终只归属于目标页面时才应返回成功。
- `remove_alias` 只有在目标 alias 最终不再归属于候选页面集时才应返回成功。
- 若预演后的 alias index 仍显示冲突或残留归属，CLI 应直接报错，而不是把 review 标记为已解决。

这部分是 V1 最重要的可维护性保障之一，因为系统不是一次性流水线，而是长期可恢复系统。

## 状态与日志 State And Logging

### 状态机
最小状态流：
`new -> normalized -> chunked -> claimed -> generated -> linked -> indexed -> linted -> done`
失败时进入：
`failed`

需要人工判断时允许进入：
- `review_required`
- `review_resolved`

状态含义：
- `new`（新建）：来源刚被发现或登记，还没有进入标准化处理。
- `normalized`（已标准化）：已经生成 normalized 文档。
- `chunked`（已切块）：已经生成 chunk，后续可以抽取 Claim。
- `claimed`（已生成声明）：已经从 chunk 中生成或更新 Claim。
- `generated`（已生成页面）：已经生成或更新相关 Wiki 页面。
- `linked`（已建立链接）：页面、Claim、Chunk、Source 之间的引用关系已经收口。
- `indexed`（已建立索引）：搜索索引和别名索引已经更新。
- `linted`（已巡检）：已经执行 lint，并得到结构化检查结果。
- `done`（已完成）：当前 ingest 或更新流程完成。
- `failed`（失败）：流程在某个阶段失败，需要查看错误日志。
- `review_required`（需要审核）：流程遇到高风险变化，已暂停危险动作并生成审核项。
- `review_resolved`（审核已解决）：人工或 Agent 已处理审核项，可以继续恢复后续步骤。

V1 当前实现说明：
- 当前 `state/ingest_state.jsonl` 已实现的核心状态以 `normalized / chunked / claimed / generated / failed / review_required` 为主。
- `linked / indexed / linted / done / review_resolved` 目前更适合作为规划状态，尚未作为独立 ingest_state 阶段完整落地。
- 页面、Claim、Review 三层当前都有独立生命周期字段，不完全依赖统一 ingest_state 表达。
- 当前来源记录本身也会表达 `generated / failed / review_required` 等来源级处理进度。

### 持久化要求
至少记录：
- 当前状态：当前对象或流程处在哪个阶段。
- 最近成功阶段：上一次已经确认完成的阶段，便于失败后从这里恢复。
- 失败阶段：具体在哪个阶段失败，便于定位问题。
- 最近错误信息：保存失败原因、异常摘要或降级说明。
- 更新时间：记录状态最后一次变更的时间。
- 重试次数：记录同一任务已经自动重试了多少次。

V1 最小持久化文件：
- `state/ingest_state.jsonl`（流程账本）：记录 ingest 每个来源或任务的阶段、失败点和恢复线索。
- `state/error_log.jsonl`（错误账本）：记录转换失败、降级处理、warning 和 error。
- `reports/lint/lint_latest.md`（最新巡检报告）：仅在实际执行 `lint` 后生成，保存最近一次 lint 的人类可读报告。

### 账本真相与展开视图
前文已经把 `state/*.jsonl` 定义为账本。这里进一步明确：哪些文件属于账本真相，哪些文件只是便于阅读、编辑、查询或展示的展开视图。

账本真相：
- `state/sources.jsonl`：来源账本，记录原始资料文件及其处理状态。
- `state/normalized.jsonl`：标准化账本，记录标准化结果、提取质量和文件路径。
- `state/chunks.jsonl`：切块账本，记录 chunk 与来源、章节和相邻 chunk 的关系。
- `state/claims.jsonl`：声明账本，记录 Claim 的状态、来源和页面反链。
- `state/reviews.jsonl`：审核账本，记录待处理和已解决的 review。
- `state/pages.jsonl`：页面账本，记录 Wiki 页面、页面类型、路径和生命周期。
- `state/ingest_state.jsonl`：流程账本，记录 ingest 阶段、失败点和恢复线索。

展开视图：
- `claims/*.json`：单条 Claim 的人工可读展开文件。
- `reviews/*.json`：单条 Review 的人工可读展开文件。
- `wiki/**/*.md`：面向人阅读和维护的 Wiki 页面。
- `indexes/search_pages.jsonl`：可重建的页面搜索索引。
- `indexes/aliases.json`：可重建或可校验的别名与规范页索引。

V1 规则：
- query 可以优先读取索引与页面，因为这样更快、更适合排序。
- 恢复流程和一致性判断必须以账本为准，因为账本保存对象身份、生命周期和跨文件关系。
- 人工编辑 Claim/Review 时，可以先修改展开文件；随后必须通过 `review-apply ... edit_then_resume` 等命令把改动纳入账本闭环。
- 若索引与账本不一致，允许重建索引；若页面与账本不一致，优先按页面账本和生命周期规则收敛。

### 重试策略 Retry Policy
- 可重试错误默认最多自动重试 3 次。
- 可重试错误指“再次执行有可能自然恢复”的问题，例如超时、临时网络失败、速率限制、文件锁冲突等。
- 不可重试错误指“重复执行也可能继续破坏状态或证据链”的问题，例如 `source_id` 冲突、大量 `chunk_id` 变化、`source_refs` 大量失效、低质量抽取、可能覆盖稳定结论。
- 非可重试错误直接转 `needs_review`（需要审核），让人先判断风险，再决定是否继续。

### 日志
- `wiki/log.md`（Wiki 变更日志）：人类可读的变更时间线，适合查看“最近知识库发生了什么”。
- `logs/*.jsonl`（结构化执行日志）：机器可读的执行日志，适合后续排查、统计和自动分析。
- Git commit（Git 提交）：工程级变更历史，适合 diff、回滚和审计。

V1 当前实现说明：
- 当前 `wiki/log.md` 已初始化，但自动追加细粒度变更时间线仍较轻量。
- 当前结构化问题与降级日志主要写入 `state/error_log.jsonl`，`logs/*.jsonl` 仍属于目录预留。

### Git工作流 Git Workflow
- 一次 `ingest`（导入处理）/ `normalize`（标准化）/ `lint fix`（巡检修复）/ `update`（更新）应形成一个语义清楚的 commit（提交）。
- 每次自动化任务前后都应检查 `git status`（当前 Git 工作区状态），确认有没有未预期的文件变化。
- Lint 有 `error`（错误）时禁止自动提交，避免把结构不一致的状态写入历史。
- 回滚优先使用 `git revert`（生成反向提交），而不是重写历史。
- 对大规模批量改动，优先生成 `change plan`（变更计划）或在临时分支执行。
- `raw/` 中的大型 PDF、图片、视频需在 V1 文档中注明是否使用 Git LFS（大文件存储）。

### 平台支持策略
V1 平台目标：
- 正式支持：`Windows 11+`、`macOS`、主流 Linux 发行版。
- 必需运行依赖：`Python 3.12+`、`git`。
- 可选增强依赖：OCR、复杂 PDF / Office 高保真转换工具。

V1 保证的边界：
- 核心流程在不安装外部办公软件的情况下可以运行。
- 缺少可选系统工具时，系统应能通过 `doctor` 给出提示，并采用降级策略而不是直接失败。
- 若某功能在 Windows 上存在明显行为差异，必须在 runtime manifest 和用户文档中明确标注。

## 巡检设计 Lint Design

### 巡检范围 Lint Scope
V1 的 lint 至少分为：
- `normalize lint`（标准化巡检）：检查 normalized 文件、提取质量、哈希和位置映射是否可靠。
- `chunk lint`（切块巡检）：检查 chunk 是否稳定、可追踪，是否破坏表格、代码块或上下文。
- `metadata lint`（元数据巡检）：检查页面、Claim、Review 等对象的必要字段是否合法。
- `wikilink lint`（Wiki 链接巡检）：检查页面之间的链接、重定向和孤儿页。
- `source_refs lint`（来源引用巡检）：检查 Claim 和页面是否能追溯到 source/chunk。
- `alias/canonical lint`（别名与规范名巡检）：检查别名冲突、重复规范页和重定向失效。
- `page quality lint`（页面质量巡检）：检查页面摘要、长度、状态和低质量内容风险。

V1 当前实现说明：
- 当前 `lint` 已经能检查工作区目录结构、状态文件是否存在、核心 ID 是否唯一，以及 Claim、Page、Review 之间的基础追踪关系。
- 当前还会检查 `canonical_id`（规范ID）是否唯一、alias registry（别名注册表）是否覆盖 live 页面、search index（搜索索引）是否覆盖 live 页面。
- 当前如果 alias registry 里存在冲突，会作为 warning 写入 lint 结果，并同步生成 `reports/lint/lint_latest.md`。
- 当前 lint 已适配 `alias_conflict` review 的结构特征，不会把“只有候选页面、没有候选 Claim”的别名冲突审核误判为缺字段。
- 更细的 `normalize / chunk / wikilink / page quality` 独立子命令属于后续细分方向，V1 先由统一 `lint` 命令覆盖主检查。

### 巡检级别 Lint Severity
- `error`（错误）：必须修复，否则不能自动提交或继续高风险写入。
- `warning`（警告）：允许继续，但必须写入报告，提醒用户后续处理。
- `info`（信息）：普通提示，用于说明检查对象、路径或当前状态。
- `suggestion`（建议）：优化建议，不影响流程继续执行。

### 关键检查项
- Normalize（标准化）：`normalized` 文件存在、`raw_hash` / `normalized_hash` 存在、抽取质量可接受、位置映射存在。
- Chunk（切块）：`chunk_id` 唯一、`section_path` 存在、代码块和表格未被破坏、overlap 设置合理。
- Metadata（元数据）：页面 `title`（标题）/ `type`（类型）/ `status`（状态）/ `canonical_id`（规范ID）合法。
- WikiLink（Wiki 链接）：检查断链、错误指向 redirect（重定向）页、孤儿页、未创建高频概念。
- Source refs（来源引用）：`source_id`、`chunk_id` 可反查，稳定页必须有来源。
- Alias / Canonical（别名 / 规范名）：检查 alias（别名）冲突、重复 canonical（规范页）、redirect（重定向）失效、疑似重复页。
- Page quality（页面质量）：检查 summary（摘要）过泛、页面过长、长期 draft（草稿）、稳定页含低置信度推论等问题。

## 测试设计 Testing

### 初始化
- 能创建 sibling 工程。
- 能复制原始资料。
- 能生成模板。
- 能自动初始化 Git 并首提。
- 能生成依赖清单、运行环境说明和 `doctor/bootstrap` 所需配置。
- 能初始化 `wiki/index.md`、`wiki/log.md`、`config/project.yml`、`config/runtime_manifest.yml`。

### 标准化
- 五类输入都至少有一条可运行路径。
- 标准化结果都有 `normalized_path`、`location_map`、`extraction_method`。
- 失败时有 `warnings`（告警信息）和 `fallback`（降级处理）标记。
- `normalizer_version`、`raw_hash`、`normalized_hash` 能驱动增量判断。
- `extraction_quality` 能正确决定是否进入 chunking。
- 在未安装可选系统工具时，核心格式转换仍有降级可运行路径。
- `.doc` / `.xls` 当前至少应能产出二进制 fallback（降级提取）文本片段或 poor（质量较差）级占位文档。
- 图片在无 `tesseract` 时应生成元数据级 normalized 文档；有 `tesseract` 时应能写入 OCR 文本。

### 追踪链路
- `page -> claim -> chunk -> source` 可达。
- `claim -> page` 可反查。
- 删除或归档页面后引用计数更新。
- review 解决后，自动页面、页面索引和反向引用关系应即时刷新。

### 检索
- 标题命中高于正文命中。
- 高权重页面类型优先于低权重类型。
- Query 默认遵循先页后声明再 chunk。
- Query normalization（查询标准化）能完成 aliases（别名）扩展、canonical（规范页）归一和基本意图识别。

V1 当前实现说明：
- 前三项当前已实现。
- aliases 扩展与 canonical 命中回传当前已实现。
- 基本意图识别当前已实现轻量版本。

### 审核
- 相反结论进入 review queue（审核队列）。
- 相似 claim 可生成待审单。
- 六种审核动作都能驱动后续恢复。
- `qa-note` 提升正式页必须经过 review。

V1 当前实现说明：
- 当前已实现相似 Claim 和相反结论两类基础 review 触发。
- 六种审核动作当前已落地并已有回归测试，其中包含 alias conflict 的 `assign_alias / remove_alias`。
- 当前已补一条保守自动审核入口 `review-auto`，用于先自动收口高把握 review，再把剩余需要人判断的项以 handoff 形式升级给上层 Agent。
- `qa-note` 提升正式页当前尚未实现具体页面工作流。

### 巡检与恢复 Lint And Recovery
- 七类 lint 都能输出结构化结果。
- `error` 会阻止自动提交，`warning` 会保留报告但允许继续。
- `ingest_state` 能从 `last_successful_stage` 继续恢复。
- 非可重试错误会正确落到 `needs_review`。

### 跨平台
- 在 Windows、macOS、Linux 上都能完成 `doctor`。
- `bootstrap` 至少能自动处理 Python 依赖安装，不依赖 shell 专属语法。
- 路径、换行、编码处理在 Windows 上不破坏 `raw -> normalized -> chunk` 主流程。

V1 当前实现说明：
- 当前 `validate_workflow.py` 已能在本地环境跑通最小主链路。
- 当前仓库已补齐 Windows 命令示例与排障文档，但真实 Windows 实机验证仍属于下一阶段工作。

### 当前已落地测试
- `tests/test_review_apply.py`（审核动作回归测试）
  - 覆盖 `merge / keep_both / edit_then_resume` 三条关键 review 恢复链路。
- `tests/test_normalizers.py`（标准化器测试）
  - 覆盖 `.doc / .xls` fallback、图片 OCR / 非 OCR 两种标准化输出。
- `tests/test_claim_extraction.py`（Claim 抽取测试）
  - 覆盖中文 claim 切分、去噪、长句拆分。
- `tests/test_review_detection.py`（审核检测测试）
  - 覆盖近重复 / 冲突候选召回与误报边界。
- `tests/test_query_alias_and_lint.py`（查询、别名与巡检测试）
  - 覆盖 alias/canonical 命中、definition/how_to/compare/timeline/evidence 六类查询行为、alias conflict review 生成、`assign_alias / remove_alias`、以及 re-ingest 后的持久化行为。
- `tests/test_e2e_workflow.py`（端到端工作流测试）
  - 覆盖 `init -> ingest -> query -> review -> lint` 主闭环 E2E。
- `scripts/validate_workflow.py`（交付级烟雾验证脚本）
  - 覆盖 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint` 交付级烟雾验证流程。

## V1落地边界 Implementation Boundary

### 已落地能力
- 统一 CLI 骨架与 8 个主命令入口。
- 工作区初始化、模板生成、Git 基线提交。
- 多格式标准化及部分降级路径。
- chunk（切块）、claim（声明）、自动 source/concept（来源 / 概念）页面生成。
- alias registry（别名注册表）、search index（搜索索引）、query `reading_pack`（查询阅读包）。
- Claim review（声明审核）与 alias conflict review（别名冲突审核）。
- `review-apply` 后的页面、索引、状态收口。
- 工作区级 lint 与 lint 报告写回。
- 覆盖主闭环的 E2E 与若干关键回归测试。

### 仍属规划或仅部分落地
- 工作区版本守卫、显式迁移入口，以及在 schema 明确后补齐的定向迁移机制。
- 更丰富的页面类型，如成熟的 entity（实体页）/ overview（综述页）/ qa-note（问答笔记）工作流。
- 细分 `normalize/chunk/wikilink/page quality` 子类 lint 子命令。
- 更复杂的动态阅读预算器与检索策略调度器。
- 更细粒度日志系统 `logs/*.jsonl` 的体系化落地。
- 真实 Windows 实机回归矩阵。

### 文档使用约定
后续所有细化设计、任务拆分和实现计划，建议都显式标注：
- `已实现`：当前代码和测试已经覆盖的能力。
- `V1 应补齐`：仍属于 V1 范围，但实现或文档还需要继续完善的能力。
- `后续规划`：不阻塞 V1 主闭环，留到后续版本推进的能力。

这样可以避免设计文档再次出现“概念层已经很细，但实现边界不够清楚”的问题。

## 前提假设 Assumptions

- 运行环境以本地个人使用为主，正式目标平台为 Windows、macOS、Linux。
- Python 版本固定为 `3.12+`。
- V1 不把 LibreOffice、Pandoc、pdftotext、tesseract 这类外部工具当成必须依赖。
- Agent 规则的权威源是 `Agent.md`，`AGENTS.md` 和 `CLAUDE.md` 只做入口适配。
- 页面标题默认采用中文优先策略；英文术语、缩写和旧译名默认进入 `aliases`。
