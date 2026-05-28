# MyAgentWiki系统详细设计 V1

## 概要 Summary

本设计将 `MyAgentWiki` 定义为一个由 Python 脚本和 Agent 协同驱动的本地 LLM Wiki 系统，服务于 Codex 和 Claude Code 两类 Agent。  
V1 的首要目标是先把 `raw -> normalized -> chunk -> claim -> wiki` 这条链路打通，其中 `raw -> normalized` 为最高优先级，并优先用 `Python 3.12+` 脚本完成文档格式转换；只有脚本无法稳定提取时，才允许 Agent 作为补充。

系统的关键能力是：
- 从用户原始知识目录同级初始化一个新的 Wiki 工程。
- 支持 `Word / Excel / PDF / Markdown / 图片` 五类输入。
- 引入独立的 `Claim` 知识声明层，建立 `page -> claim -> chunk -> source` 可追踪链路。
- 支持 Claim 到 Wiki 页面的反向引用统计与检索。
- 使用多字段 BM25 打分，并叠加页面类型权重和页面状态权重。
- 对冲突、近重复、替换稳定结论等高风险更新，进入结构化人工审核队列。

## 系统结构 System Structure

### 母仓库职责
母仓库是开源 Skill 项目本体，负责交付：
- `Agent.md`：共享核心规则源。
- `AGENTS.md`：Codex 入口文件。
- `CLAUDE.md`：Claude Code 入口文件。
- `pyproject.toml`：Python 依赖、可选依赖和 CLI 入口定义。
- Python 包与统一 CLI。
- 初始化模板工程。
- 运行环境清单与平台兼容说明。
- 项目自身知识沉淀目录 `docs/`。
- 面向用户工程的目录模板、配置模板、状态模板、审核模板。

### 用户工程职责
用户运行 `init` 后生成 sibling Wiki 工程，负责承载：
- 原始资料副本。
- 标准化中间产物。
- Chunk 与 Claim 层。
- Wiki 页面。
- 本地索引、状态、日志、审核队列。
- Git 版本历史。

## 目录设计 Directory Design

### 母仓库目录
- `Agent.md`
- `AGENTS.md`
- `CLAUDE.md`
- `README.md`
- `pyproject.toml`
- `docs/`
- `src/myagentwiki/`
- `templates/`
- `tests/`

### 初始化后的用户工程目录
- `raw/`
- `normalized/`
- `chunks/`
- `claims/`
- `wiki/`
- `indexes/`
- `state/`
- `reviews/`
- `logs/`
- `outputs/`
- `config/`
- `reports/lint/`
- `wiki/index.md`
- `wiki/log.md`
- `config/project.yml`
- `config/runtime_manifest.yml`
- `AGENTS.md`
- `CLAUDE.md`

### 运行依赖清单文件
母仓库需要额外提供：
- `pyproject.toml`：声明 Python 依赖、可选 extras、CLI 入口。
- `config/runtime_manifest.yml`：声明系统级依赖、是否必需、支持平台、检测命令、缺失时的降级策略。
- `docs/runtime-deps.md`：面向用户的依赖说明、平台安装指引和常见问题。

运行依赖分两层：
- Python 依赖：允许自动安装。
- 系统级软件依赖：优先检测，缺失时提示安装，不默认强制自动安装。

## 核心数据模型 Core Data Model

### 原始来源 Source
表示原始来源文件。
最小字段：
- `source_id`
- `source_path`
- `source_type`
- `source_hash`
- `imported_at`
- `version_group`
- `status`
- `normalized_path`
- `warnings`

V1 当前实现说明：
- 当前主键以 `source_id + source_hash + source_path` 为核心。
- 当前代码已经实现 `version_group`，用于表达“同一路径来源的多次版本演进”。
- `source_uri`、`dedupe_key` 仍属于设计保留字段，当前实现尚未作为 state 强制字段。

### 标准化文档 NormalizedDocument
表示规范化后的统一文档对象。
最小字段：
- `source_id`
- `normalized_path`
- `title`
- `location_map`
- `extraction_method`
- `extraction_quality`
- `warnings`
- `raw_hash`
- `normalized_hash`
- `normalizer_version`

V1 当前实现说明：
- 当前 `content_markdown` 直接落盘到 `normalized/*.md`，不是单独内嵌在 state 记录里。
- `sections`、`artifacts` 目前未作为 state/normalized.jsonl 的强制字段持久化。

### 文档切块 Chunk
表示从 normalized 文档切分出的处理单元和证据单元。
最小字段：
- `chunk_id`
- `source_id`
- `source_path`
- `section_path`
- `chunk_index`
- `start_line`
- `end_line`
- `page_range`
- `char_count`
- `token_estimate`
- `summary`
- `text`
- `previous_chunk`
- `next_chunk`
- `overlap_from_previous`
- `hash`
- `chunker_version`

### 知识声明 Claim
表示独立知识声明，是系统的核心知识枢纽层。
最小字段：
- `claim_id`
- `text`
- `normalized_text`
- `status`
- `confidence`
- `source_ids`
- `chunk_ids`
- `page_ids`
- `conflict_group`
- `duplicate_candidates`
- `review_reason`
- `claim_type`
- `source_refs`
- `lifecycle_status`
- `superseded_by`
- `archived_at`
- `created_at`
- `updated_at`

V1 当前实现说明：
- 当前 Claim 权威源为 `claims/*.json`，`state/claims.jsonl` 作为可扫描账本存在。
- 当前已实现 Claim 历史态保留：被归档或被来源更新淘汰的 Claim 会转入历史态，而不是直接删除。
- 历史态 Claim 当前通过 `original_claim_id` 和 `claim_id__hist_<timestamp>` 方式保留演进链。

### Wiki页面 WikiPage
表示对用户可读的知识页面。
最小字段：
- `page_id`
- `title`
- `type`
- `canonical_id`
- `status`
- `automation_level`
- `review_reason`
- `summary`
- `aliases`
- `redirect_to`
- `claim_ids`
- `review_ids`
- `source_refs`
- `lifecycle_status`
- `archived_at`
- `removed`
- `created`
- `updated`

V1 当前实现说明：
- 当前已落地的自动页面类型主要是 `source-summary` 与 `concept-summary`。
- `state/pages.jsonl` 当前会保留已被自动移除页面的历史记录，移除态页面不会继续参与 query、索引和 wiki 目录。

### 审核项 ReviewItem
表示人工审核单。
最小字段：
- `review_id`
- `kind`
- `status`
- `lifecycle_status`
- `candidate_claim_ids`
- `candidate_page_ids`
- `reason`
- `recommended_action`
- `allowed_actions`
- `resume_from`
- `evidence`
- `created_at`
- `resolved_at`
- `archived_at`

V1 当前实现说明：
- 当前 Review 权威源为 `reviews/*.json`，`state/reviews.jsonl` 作为可扫描账本存在。
- 当前已实现 Review 历史态与活跃态分离；但“已解决 review”默认仍保留在 active lifecycle 中，仅 `status=resolved`。

## 初始化工作流 Initialization Workflow

`init` 的行为固定如下：
1. 接收原始知识目录路径与项目名。
2. 在原始目录同级创建新的 Wiki 工程目录。
3. 复制原始资料到工程内 `raw/`。
4. 生成全部模板目录和配置文件。
5. 写入 `AGENTS.md`、`CLAUDE.md`、`wiki/index.md`、`wiki/log.md`。
6. 初始化本地状态文件与索引占位文件。
7. 若目标目录不是 Git 仓库，则自动执行 Git 初始化并生成基线提交。

CLI 入口固定为：
- `python -m myagentwiki init`
- `python -m myagentwiki ingest`
- `python -m myagentwiki query`
- `python -m myagentwiki lint`
- `python -m myagentwiki doctor`
- `python -m myagentwiki bootstrap`
- `python -m myagentwiki review-list`
- `python -m myagentwiki review-apply`

### 环境自检与初始化
V1 增加两个环境命令：

- `doctor`
  - 检查 Python 版本是否满足 `3.12+`。
  - 检查必需 Python 包是否已安装。
  - 检查 `git` 是否可用。
  - 检查可选系统工具是否存在，例如 OCR、Office/PDF 转换工具。
  - 输出结构化环境报告，区分 `required`、`optional`、`missing`。

- `bootstrap`
  - 安装或修复 Python 依赖。
  - 生成运行环境报告。
  - 不默认静默安装系统级软件，只提示缺失项和平台安装建议。

## 标识与命名 Identity And Naming

### 原始来源ID规则 Source ID Rules
- `source_id` 不能只依赖文件名，必须由内容哈希、来源类型、导入时间片段等稳定特征生成。
- 同内容但不同文件名默认视为同一来源，写入同一 `dedupe_key`。
- 同一 `source_uri` 内容更新时，不覆盖旧来源，默认在同一 `version_group` 下生成新版本。
- 重复 ingest 同一来源时，默认跳过已完成版本；若 `raw_hash` 或 `normalized_hash` 变化，则进入增量更新流程。

V1 当前实现说明：
- 当前 `source_id` 基于 `raw/` 下相对路径和 `source_hash` 生成，避免子目录同名文件冲突。
- 当前“同一路径文件内容更新”采用原位演进：复用原 `source_id`，清理旧证据链后重建 normalized / chunk / claim / page，而不是新增一个并行活跃 source。
- `version_group` 当前已记录路径级演进关系。
- `dedupe_key`、`source_uri` 仍属于设计保留语义，当前未作为运行中主字段落地。

### 规范名治理 Canonical Naming
- 每个 `concept` / `entity` / `overview` 页面必须有稳定的 `canonical_id`。
- `title` 是显示名，可调整；`canonical_id` 是长期主键，不应随重命名变化。
- 页面标题默认采用中文优先策略；英文术语、缩写、旧译名进入 `aliases`。
- 旧标题页默认不删除，改为 `type: redirect` 并写 `redirect_to` 指向规范页。

### 别名注册表 Alias Registry
- V1 维护全局别名表，例如 `indexes/aliases.yml` 或等价结构化索引。
- Alias registry 作为检索扩展、页面去重、自动加链接和别名冲突巡检的统一数据源。
- AI 或脚本在新建页面前，必须先查询 alias registry 和现有页面 frontmatter。
- 如果同一 alias 可能对应多个 `canonical_id`，不自动合并，转入 `needs_review`。

## 标准化层 Normalization Layer

### 总体原则
- `raw -> normalized` 为 V1 第一优先级。
- 优先纯 Python 实现。
- 外部办公软件不是前提依赖。
- Agent 只做 Python 失败后的补充解析。

### 统一转换架构
标准化层采用“统一抽象 + 多转换器”设计：
- `BaseConverter`
- `MarkdownConverter`
- `PdfConverter`
- `WordConverter`
- `ExcelConverter`
- `ImageConverter`

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
- 记录 `page_range` 与页级 location map。
- 无法提取的页面写入 warnings。
兜底：
- 复杂排版页可标记待 Agent 辅助。

### Word 文档 Word
行为：
- 提取标题、段落、列表、表格、图片占位。
- 保持块顺序和章节结构。
- 输出 Markdown 和段落级映射。
兜底：
- 对复杂嵌套对象保留结构 warning，不强行完美恢复。

V1 当前实现说明：
- `.docx` 当前已实现两条路径：`python-docx` 主路径 + `zip+xml` 纯 Python fallback。
- `.doc` 当前已实现纯 Python 二进制保守 fallback，优先提取可见文本片段和基础容器元数据，不保证高保真结构恢复。

### Excel 表格 Excel
行为：
- 读取 workbook、sheet、表头、数据区域。
- 每个 sheet 转为 Markdown 表格和结构化块。
- 保留 sheet 名、行列坐标、公式存在标记。
兜底：
- 对复杂合并单元格和不规则布局写 warnings。

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
- 当前尚未接入 Agent 视觉理解自动续跑，只保留降级说明与 warnings。

### 提取方式 Extraction Method
每个 normalized 产物必须标记一种方法：
- `python_only`
- `python_only+tesseract`
- `python_plus_agent`
- `agent_only_fallback`

V1 当前实现说明：
- 当前实际已落地方法主要为 `python_only` 与 `python_only+tesseract`。
- `python_plus_agent`、`agent_only_fallback` 仍属于后续扩展保留值。

### 提取质量 Extraction Quality
每个 normalized 产物必须带质量等级：
- `good`
- `partial`
- `poor`
- `failed`

分流规则：
- `good`：正常进入 chunking。
- `partial`：进入 chunking，但保留 warnings。
- `poor`：仅允许生成 draft 级中间产物，不允许直接参与稳定结论写入。
- `failed`：写入 error log，不进入 ingest 主流程。

### 跨平台实现约束
为支持 Windows、macOS、Linux，V1 实现必须遵守：
- 路径处理统一使用 `pathlib`，不写死 `/`。
- 文件编码默认按 UTF-8 处理，并兼容 Windows 常见换行差异。
- 子进程调用不依赖 `bash`、`zsh` 或 POSIX 专属语法。
- Git、工具检测、文件扫描通过 Python 标准库和可移植命令实现。
- 文档转换优先纯 Python 库，避免一开始就绑定平台特有软件。

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
- 提取核心检索意图，例如 `compare`、`definition`、`timeline`、`how_to`。
- 输出结构化查询对象，供 BM25 检索和页面选择使用。

V1 当前实现说明：
- 当前已实现的是多字段 BM25 检索与页面权重、状态权重叠加。
- `query_normalizer`、alias 扩展、canonical 归一、意图识别当前尚未独立落地。

## 切块设计 Chunking Design

### 切分规则
默认切分策略：
- 先按 Markdown 标题切。
- 超长块再按段落切。
- 过短块与相邻块合并。
- 保留少量 overlap。
- 代码块、表格、引用块尽量整体保留。

### 默认参数
- `target_tokens: 1000`
- `max_tokens: 1600`
- `min_tokens: 200`
- `overlap_tokens: 0`（当前实现）

V1 当前实现说明：
- 当前 chunk 参数已在代码中固化为 `target=1000 / max=1600 / min=200`。
- 当前 `overlap_from_previous` 字段已经存在，但默认仍为 `0`，尚未启用真正的 overlap 切块策略。

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
- Claim 是独立文件，不依附于单个页面。
- Wiki 页面不直接把“结论”只绑到 source，而是先绑到 claim。
- 同一 claim 可被多个页面复用。
- Claim 必须支持正向和反向引用。

### 文件与索引
- `claims/` 中保存 claim 主文件。
- `indexes/claims.jsonl` 或等价索引保存反查加速数据。
- 权威源是 claim 文件本身，索引只是派生物。

V1 当前实现说明：
- 当前尚未单独落地 `indexes/claims.jsonl`。
- 当前 Claim 反查主要依赖 `state/claims.jsonl`、Claim 单文件以及页面索引聚合结果。

### 状态
V1 允许：
- `draft`
- `stable`
- `disputed`
- `needs_review`
- `archived`

V1 当前实现说明：
- 当前规则抽取出来的 Claim 主要落在 `draft` / `needs_review`。
- `stable`、`disputed` 目前仍属于后续人工或 Agent 深化治理状态，尚未在自动流程中完整使用。
- 生命周期维度当前独立使用 `lifecycle_status` 表达 `active / superseded / archived`。

### 声明类型 Claim Type
V1 建议支持：
- `definition`
- `fact`
- `comparison`
- `causal`
- `procedure`
- `evaluation`
- `warning`

## 检索设计 Retrieval Design

### 默认查询顺序
- 先检索 `wiki pages`
- 再下钻 `claims`
- 最后按需回读 `chunks`

V1 当前实现说明：
- 当前 query 已实现这种读取顺序，并能返回 `reading_pack`，包含匹配 claims、chunks、source summary 和邻接 chunk 线索。

### 多字段 BM25
至少对这些字段分别打分：
- `title`
- `aliases`
- `summary`
- `headings`
- `body`
- `claim_text`
- `source_refs`

总分公式固定为：
`final_score = Σ(field_weight * bm25(field)) * page_type_weight * page_status_weight`

V1 当前实现说明：
- 当前 query 优先读取 `indexes/search_pages.jsonl`。
- 当前页面索引支持按 `page_signature` 增量复用，未变化页面可直接复用既有索引记录。

### 查询读取规则 Query Reading Rules
- 查询时先读 `index`、frontmatter、`summary`、`aliases`、`headings`。
- 命中相关页面后，再读取相关 section、claim、chunk。
- 判断型、冲突型、对比型问题不能只读孤立 chunk。
- 命中 chunk 时必须同时附带页面摘要、`section_path`、`previous_chunk`、`next_chunk`。
- 涉及证据、冲突或引用时，必须回读 claim 对应的 chunk/source。

### 查询标准化与扩展 Query Normalization And Expansion
- 搜索时必须同时查 `title`、`summary`、`aliases`、`body`。
- alias 精确命中、canonical 命中、redirect 指向规范页时，应参与加权。
- 中英混合查询默认启用 aliases 扩展和 canonical 归一化。

### 默认权重
字段权重：
- `title: 5.0`
- `aliases: 4.0`
- `summary: 3.0`
- `headings: 2.5`
- `body: 1.0`
- `claim_text: 2.0`
- `source_refs: 0.5`

页面类型权重：
- `overview: 1.25`
- `concept: 1.15`
- `concept-summary: 1.15`
- `entity: 1.10`
- `source-summary: 1.00`
- `qa: 0.95`
- `draft: 0.70`

页面状态权重：
- `stable: 1.10`
- `draft: 0.80`
- `disputed: 0.90`
- `outdated: 0.60`
- `needs_review: 0.75`

### Codex / Claude Code 读取策略 Reading Strategy
V1 不实现复杂动态预算器，但规则文件中必须明确轻量阅读策略：
- 先读索引和候选页摘要，再决定是否下钻正文。
- 不默认大批量读取 raw。
- 长页面如频繁只读局部，应建议拆页。

## 更新与审核 Update And Review

### 自动写入默认策略
默认采用“常规自动写入 + 全程留痕”。

### 更新模式
页面更新策略与页面创建策略分离，V1 固定支持：
- `append`：补充新证据，不改旧结论。
- `merge`：融合新旧信息。
- `conflict-mark`：保留冲突，不直接覆盖。

### 必须进入审核队列的场景
- 截然相反的结论。
- 高度相似但是否应合并不明确的结论。
- 替换稳定 claim。
- 覆盖稳定页面核心结论。
- 批量删除、合并、重命名页面。
- 大量 source_refs 或 claim 映射失效。
- 别名冲突或 canonical 边界不明确。
- 将 `qa-note` 提升为正式概念页或综述页。
- 涉及 private / sensitive 内容流向 public / export 区域。

### V1审核动作 V1 Review Actions
- `merge`
- `keep_both`
- `archive_one`
- `edit_then_resume`

V1 当前实现说明：
- `merge`：保留主 Claim，归档次 Claim，并自动改写其他仍为 open 的 review 候选。
- `keep_both`：解决当前 review，但保留双方 Claim。
- `archive_one`：归档指定活跃 Claim。
- `edit_then_resume`：允许人工先修改 `claims/*.json`，再从当前 review 状态恢复后续页面与索引刷新。

### 自动化分级
V1 引入四级自动化边界：
- `safe_auto`
- `auto_with_log`
- `require_review`
- `locked`

页面可通过 `automation_level` 声明是否允许自动修改。

### 审核单内容
Review item 不只保存动作名，还必须保存：
- 风险原因
- 受影响页面 / claims / chunks
- 推荐动作
- 可选动作
- `resume_from`
- 关键证据摘要

### QA回写策略 QA Writeback Policy
V1 把问答沉淀拆成三类：
- `qa-note`
- `overview`
- `concept-update`

默认规则：
- 高质量问答可自动沉淀为 `qa-note`。
- `qa-note` 不自动提升为正式 `concept`。
- 提升为正式概念页或综述页必须进入 review。

### 页面模板
V1 为三类页面提供固定模板：
- 概念页：定义、为什么重要、工作原理、适用场景、局限性、相关概念、来源。
- 实体页：是谁/是什么、核心信息、相关项目/概念、在本知识库中的定位、来源。
- 来源摘要页：原文概览、核心观点、提取到的概念、提取到的实体、与现有页面的联系/冲突、后续建议。

### 恢复机制
- 自动流程写入 review item 后暂停危险动作。
- 人工决策完成后，从 review 状态恢复后续步骤。
- 不要求整条 ingest 全量重跑。

V1 当前实现说明：
- 当前 `review-apply` 执行动作后会即时刷新受影响的自动页面、`state/pages.jsonl`、`wiki/index.md` 与 `indexes/search_pages.jsonl`。
- `edit_then_resume` 当前已支持“人工先改 Claim 文件，再恢复页面和索引重建”。

## 状态与日志 State And Logging

### 状态机
最小状态流：
`new -> normalized -> chunked -> claimed -> generated -> linked -> indexed -> linted -> done`
失败时进入：
`failed`

需要人工判断时允许进入：
- `review_required`
- `review_resolved`

V1 当前实现说明：
- 当前 `state/ingest_state.jsonl` 已实现的核心状态以 `normalized / chunked / claimed / generated / failed / review_required` 为主。
- `linked / indexed / linted / done / review_resolved` 目前更适合作为规划状态，尚未作为独立 ingest_state 阶段完整落地。
- 页面、Claim、Review 三层当前都有独立生命周期字段，不完全依赖统一 ingest_state 表达。
- 当前来源记录本身也会表达 `generated / failed / review_required` 等来源级处理进度。

### 持久化要求
至少记录：
- 当前状态
- 最近成功阶段
- 失败阶段
- 最近错误信息
- 更新时间
- 重试次数

V1 最小持久化文件：
- `state/ingest_state.jsonl`
- `state/error_log.jsonl`
- `reports/lint/lint_latest.md`

### 重试策略 Retry Policy
- 可重试错误默认最多自动重试 3 次。
- 可重试错误包括超时、临时网络失败、速率限制、文件锁冲突等。
- 不可重试错误包括 `source_id` 冲突、大量 `chunk_id` 变化、`source_refs` 大量失效、低质量抽取、可能覆盖稳定结论。
- 非可重试错误直接转 `needs_review`。

### 日志
- `wiki/log.md`：人类可读变更时间线
- `logs/*.jsonl`：结构化执行日志
- Git commit：工程级变更历史

V1 当前实现说明：
- 当前 `wiki/log.md` 已初始化，但自动追加细粒度变更时间线仍较轻量。
- 当前结构化问题与降级日志主要写入 `state/error_log.jsonl`，`logs/*.jsonl` 仍属于目录预留。

### Git工作流 Git Workflow
- 一次 `ingest` / `normalize` / `lint fix` / `update` 应形成一个语义清楚的 commit。
- 每次自动化任务前后都应检查 `git status`。
- Lint 有 `error` 时禁止自动提交。
- 回滚优先使用 `git revert`，不重写历史。
- 对大规模批量改动，优先生成 change plan 或在临时分支执行。
- `raw/` 中的大型 PDF、图片、视频需在 V1 文档中注明是否使用 Git LFS。

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
- `normalize lint`
- `chunk lint`
- `metadata lint`
- `wikilink lint`
- `source_refs lint`
- `alias/canonical lint`
- `page quality lint`

V1 当前实现说明：
- 当前 `lint` 已落地的是工作区结构检查、state 文件存在性检查、`chunk_id/claim_id/review_id/page_id` 唯一性检查、Claim 溯源检查、页面记录与页面文件一致性检查，以及历史态 page/claim/review 的基本一致性检查。
- 其余 lint 分类仍属于后续细分方向，当前尚未拆成独立子命令。

### 巡检级别 Lint Severity
- `error`：必须修复，否则不能提交。
- `warning`：允许提交，但必须写入报告。
- `info`：提示。
- `suggestion`：优化建议。

### 关键检查项
- Normalize：`normalized` 文件存在、`raw_hash` / `normalized_hash` 存在、抽取质量可接受、位置映射存在。
- Chunk：`chunk_id` 唯一、`section_path` 存在、代码块和表格未被破坏、overlap 合理。
- Metadata：页面 `title` / `type` / `status` / `canonical_id` 合法。
- WikiLink：断链、错误指向 redirect 页、孤儿页、未创建高频概念。
- Source refs：`source_id`、`chunk_id` 可反查，稳定页必须有来源。
- Alias / Canonical：alias 冲突、重复 canonical、redirect 失效、疑似重复页。
- Page quality：summary 过泛、页面过长、长期 draft、稳定页含低置信度推论。

## 测试设计 Testing

### 初始化
- 能创建 sibling 工程。
- 能复制原始资料。
- 能生成模板。
- 能自动初始化 Git 并首提。
- 能生成依赖清单、运行环境说明和 `doctor/bootstrap` 所需配置。
- 能初始化 `wiki/index.md`、`wiki/log.md`、`config/project.yml`、`config/runtime_manifest.yml`、`reports/lint/lint_latest.md`。

### 标准化
- 五类输入都至少有一条可运行路径。
- 标准化结果都有 `normalized_path`、`location_map`、`extraction_method`。
- 失败时有 warnings 和 fallback 标记。
- `normalizer_version`、`raw_hash`、`normalized_hash` 能驱动增量判断。
- `extraction_quality` 能正确决定是否进入 chunking。
- 在未安装可选系统工具时，核心格式转换仍有降级可运行路径。
- `.doc` / `.xls` 当前至少应能产出二进制 fallback 文本片段或 poor 级占位文档。
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
- Query normalization 能完成 aliases 扩展、canonical 归一和基本意图识别。

V1 当前实现说明：
- 前三项当前已实现。
- aliases 扩展、canonical 归一和基本意图识别当前尚未独立实现。

### 审核
- 相反结论进入 review queue。
- 相似 claim 可生成待审单。
- 四种审核动作都能驱动后续恢复。
- `qa-note` 提升正式页必须经过 review。

V1 当前实现说明：
- 当前已实现相似 Claim 和相反结论两类基础 review 触发。
- 四种审核动作当前已落地并已有回归测试。
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

### 当前已落地测试
- `tests/test_review_apply.py`
  - 覆盖 `merge / keep_both / edit_then_resume` 三条关键 review 恢复链路。
- `tests/test_normalizers.py`
  - 覆盖 `.doc / .xls` fallback、图片 OCR / 非 OCR 两种标准化输出。
- `tests/test_claim_extraction.py`
  - 覆盖中文 claim 切分、去噪、长句拆分。

## 前提假设 Assumptions

- 运行环境以本地个人使用为主，正式目标平台为 Windows、macOS、Linux。
- Python 版本固定为 `3.12+`。
- V1 不把 LibreOffice、Pandoc、pdftotext、tesseract 这类外部工具当成必须依赖。
- Agent 规则的权威源是 `Agent.md`，`AGENTS.md` 和 `CLAUDE.md` 只做入口适配。
- 页面标题默认采用中文优先策略；英文术语、缩写和旧译名默认进入 `aliases`。
