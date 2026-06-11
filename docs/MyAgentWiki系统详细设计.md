# MyAgentWiki 系统详细设计

## 文档目标（Document Purpose）

本文档是 `MyAgentWiki` 的主详细设计文档，也是当前最优先维护的单一权威版本。

它主要服务两类读者：

- 第一读者是项目作者自己，用来反向检查“系统为什么这样实现、哪些地方已经落地、哪些地方仍需继续收口”。
- 第二读者是后续协作者，用来快速建立对目录边界、数据模型、处理流程、证据链、语义链和恢复机制的整体理解。

本文档强调三件事：

1. 文档结构尽量与系统处理流程一致，方便一边读一边对照实现。
2. 英文术语只在必要时保留，并在首次出现时给出明确中文解释。
3. 除了说明“系统怎么做”，还尽量说明“为什么这样做”。

本文档中的 `MyAgentWiki` 统一指母仓库 / 产品名；若需要举用户初始化后的工作区目录示例，统一使用 `MyNotesWiki`。

## 概要（Summary）

`MyAgentWiki` 的定位不是“传统脚本流水线上补几处大模型（LLM）调用”，而是一个证据优先的语义编译器（evidence-first semantic compiler）。

它的核心任务，是把用户的原始资料持续编译成三层产物：

1. 证据层：`normalized/`、`chunks/`、`claims/`
2. 语义层：语义决策（semantic decisions）、知识角色（knowledge roles）、页面意图（page intents）
3. 展示层：`wiki/`、`indexes/`、阅读包（reading_pack）、回答交接载荷（answer-ready payload）

因此，系统主线虽然仍然可以写成 `raw -> normalized -> chunks -> claims -> wiki`，但真正的理解方式不应再是“从文件一路生成页面”，而应改成下面这条更完整的编译链：

1. `raw -> normalized -> chunks -> claims`：构建证据中间表示（evidence intermediate representation）
2. `claims -> semantic decisions`：补充结构角色、知识角色、页面意图和编译约束
3. `semantic decisions -> reviews / stable promotion / page routing`：把无法安全自动收口的部分送入审核，把高把握对象送入后续页面重建
4. `pages / indexes / reading_pack / answer-ready`：把证据和语义结果编译成面向人和面向上层 Agent 的不同视图

系统的关键能力包括：

- 从用户原始知识目录同级初始化一个新的 Wiki 工程
- 支持 `Word / Excel / PDF / Markdown / 图片` 五类输入
- 维护独立的声明层（Claim layer），并逐步向更宽泛的知识单元层（Knowledge Unit layer）演进
- 建立 `page -> claim -> chunk -> source` 的可追踪证据链
- 用多字段 BM25、页面类型权重、页面状态权重组织检索
- 用受限 LLM 处理脚本难以稳定解决的语义角色判定、页面意图判定、保守重命名和 grounded 改写
- 用审核队列、提稳流程、账本收口和回放机制保证长期可维护性

系统的核心设计哲学是：

- 确定性证据优先，按需使用语义判断（deterministic evidence first, semantic where needed）
- 脚本负责证据编译和状态落盘，LLM 负责受限语义分析和 grounded 表达
- LLM 不是事实来源，不能绕过现有证据直接制造新事实
- 所有高风险改动都必须有可追踪账本、可回读证据和明确恢复入口

## 系统定位与核心原则（System Positioning And Principles）

### 1. 证据优先，而不是页面优先

系统的主真相不应是最终页面文本，而应是证据图（evidence graph）。

原因是页面文本天然更适合给人阅读，但不适合作为长期演化中的唯一权威源：

- 页面会被重写、重排、重命名
- 页面会同时服务概念解释、综述组织、来源入口、问答沉淀等多种视图
- 页面中的可读表达可能被 LLM 改写，而证据层不应该随表达风格变化而漂移

因此，系统必须先让 `normalized / chunks / claims` 稳定下来，再决定页面怎么组织。

### 2. LLM 是受限语义分析器，不是事实写作者

LLM 在系统中的职责是：

- 判断文档结构是否可靠
- 判断 Claim 更像定义、事实、步骤、示例还是结构壳
- 判断一组稳定 Claim 更适合长成概念页、指南页、示例页、主题页、参考页还是只留在来源视图
- 在证据和页型都已确定后，做 grounded 的可读化表达

LLM 不应直接做的事包括：

- 跳过 `normalized / chunks / claims` 直接写知识页
- 把没有来源支持的句子写入权威账本
- 在没有回链对象的情况下生成“看起来很合理”的新事实
- 把审核动作、生命周期变化、规范名归属等高风险状态修改成纯自由文本结论

### 3. 语义层必须独立成账本

语义判断不能直接混入证据账本，否则系统会失去可回放性。

例如同一条 Claim：

- 它的 `claim_id`、`source_refs`、`lifecycle_status` 属于证据和生命周期真相
- 它是否更像 `definition / procedure / example / structural_shell`，则属于语义判断真相

这两类信息分层保存的好处是：

- 模型升级、提示词升级时，可以只重跑语义层
- 证据层不需要因为语义策略变动而整体重写
- query、lint、review、page rebuild 都能解释“这次为什么这么做”

### 4. 审核不是兜底补丁，而是恢复机制的一部分

审核队列（review queue）不只是“发现问题后提醒人看一眼”，它是整套编译系统中正式的暂停点和恢复入口。

原因是：

- 不是所有风险都能靠脚本或 LLM 收口
- 高风险变化如果没有暂停点，系统就会把不确定判断直接写进 live 页面和索引
- 一旦后面又要恢复，就很难知道应该从哪一层继续

因此，review item 必须携带：

- 风险原因
- 候选对象
- 关键证据
- 允许动作
- 恢复起点

这样 `review-apply` 才能成为真正的“状态恢复命令”，而不是“帮用户改一两个字段”的工具。

## 端到端处理流程（End-to-End Flow）

### 总流程图

```mermaid
flowchart TD
    A["原始资料（raw）"] --> B["标准化文档（normalized）"]
    B --> C["证据切块（chunks）"]
    C --> D["知识声明（claims）"]
    D --> E["语义决策（semantic decisions）"]
    E --> F["审核与提稳（reviews / stable promotion）"]
    F --> G["页面与索引（wiki / indexes）"]
    G --> H["阅读包（reading_pack）"]
    H --> I["回答交接（answer-ready）"]

    E --> J["语义账本（semantic ledger）"]
    D --> K["证据账本（evidence ledger）"]
    F --> L["审核账本（review ledger）"]

    F --> M["恢复入口（review-apply / edit_then_resume）"]
    M --> G
    M --> H
```

### 证据主链（Evidence Chain）

证据主链回答的是：“系统为什么能说这句话？”

这条链固定为：

`source -> normalized -> chunk -> claim -> page`

读者需要能够从页面一路回读到声明、切块、标准化文档和原始来源，而不是停留在一段被改写过的摘要上。

### 语义补充链（Semantic Supplement Chain）

语义补充链回答的是：“系统为什么把这份证据组织成这种知识结构？”

这条链固定为：

`claim / page candidate -> semantic decision -> review or page routing -> readable rendering`

它解释的是：

- 为什么这个 chunk 没有被当成主题候选
- 为什么这条 Claim 被判断为步骤、示例或结构壳
- 为什么一组稳定 Claim 会被路由成 `concept / guide / topic / reference`
- 为什么某个可读页面允许 LLM 改写，另一个只保留 deterministic 骨架

### 证据链与语义链如何串起来

为了避免“证据链”和“LLM 语义补充工作链条”各写各的，系统要求这两条链在对象层显式相连：

1. `claim` 保留 `source_refs`
2. `semantic decision` 保留 `item_ids`、`task_type`、`input_fingerprint`
3. `page` 或 `review` 能通过 `semantic_decision_id` 或等价关系回查到语义判断来源
4. `reading_pack` 和 `answer-ready` 只能消费已回链的 page / claim / chunk / source，而不是消费脱离证据链的自由文本

这意味着上层回答器读到的每一层摘要，都应有回退路径：

- 回到页面摘要
- 回到关键 Claim
- 回到匹配 Chunk
- 回到来源摘要或原始来源入口

### 权威源与写入责任矩阵

| 对象 | 主要作用 | 权威源 | 默认写入者 | 能否重建 |
| --- | --- | --- | --- | --- |
| Source | 记录原始来源及处理状态 | `state/sources.jsonl` | CLI | 不能随意重建 |
| NormalizedDocument | 统一文档表示 | `normalized/*.md` + `state/normalized.jsonl` | CLI | 可由 `raw` 重新生成 |
| Chunk | 证据单元 | `state/chunks.jsonl` | CLI | 可由 `normalized` 重新生成 |
| Claim | 知识声明层 | `claims/*.json` + `state/claims.jsonl` | CLI，必要时人工编辑后走恢复 | 可重建，但需保留历史态 |
| SemanticDecision | 语义判断与解释链 | `state/semantic_decisions.jsonl` 或 `semantic/*.jsonl` | CLI / Agent hook | 可按输入重跑 |
| ReviewItem | 风险暂停点与恢复入口 | `reviews/*.json` + `state/reviews.jsonl` | CLI | 不能静默丢失 |
| WikiPage | 面向人阅读的视图 | `wiki/**/*.md` + `state/pages.jsonl` | CLI / grounded rewrite | 可重建，但需遵守生命周期 |
| Search Index | 排序与快速检索 | `indexes/search_pages.jsonl` | CLI | 可重建 |
| Alias Registry | 别名扩展与规范名治理 | `indexes/aliases.json` + 覆盖层 | CLI / review-apply | 可重建，但人工覆盖需保留 |
| Reading Pack | 查询交接上下文 | `query` 输出 | CLI | 可按 query 重算 |
| Answer-Ready Payload | 回答器消费层 | `answer-query` 或 `query --answer-ready` 输出 | CLI | 可按 query 重算 |

## 母仓库与用户工作区边界（Repository And Workspace Boundary）

### 母仓库负责什么

母仓库负责交付产品代码、模板、规则、测试和文档，包括：

- `Agent.md`：共享 Agent 核心规则源，约束不同 Agent 的共同工作边界
- `AGENTS.md`：面向 Codex 的入口规则文件
- `CLAUDE.md`：面向 Claude Code 的入口规则文件
- `SKILL.md`：Skill 主入口，说明什么时候应使用 MyAgentWiki
- `agents/openai.yaml`：OpenAI Skill 元数据，用于 Skill 展示和接入配置
- `pyproject.toml`：Python 项目配置文件，用于声明依赖、构建方式和 CLI 入口
- `src/myagentwiki/`：项目核心源码目录，包含 CLI、主流程和核心实现
- `templates/`：工作区初始化模板目录
- `tests/`：自动化测试目录
- `scripts/`：辅助脚本与交付级验证脚本目录
- `docs/`：项目文档目录，包含详细设计、运行说明、排障文档和资料沉淀

它负责的是“如何编译”和“如何约束 Agent”，而不是承载用户知识资产本体。

### 用户工作区负责什么

用户运行 `init` 后生成的工作区负责承载：

- sibling `raw/` 原始资料目录引用
- `normalized / chunks / claims` 证据层产物
- `semantic/` 或等价语义账本目录
- `wiki / indexes` 展示层产物
- `state / reviews / reports / logs` 状态与控制层
- 本地 Git 历史

### 为什么这条边界很重要

这条边界直接决定升级策略：

- 母仓库升级时，不应直接覆盖用户工作区里的 `state/`、`claims/`、`reviews/`、`wiki/`
- 用户工作区内容更新时，也不应反向改写母仓库文档和模板
- 模板演进应优先通过“新工作区生成 + 老工作区渐进迁移”吸收
- Agent 不应跳过 CLI 直接批量手改账本来模拟迁移

迁移、版本守卫、兼容性规划、显式迁移动作等内容属于单独的实施专题，主文档只保留必要边界说明，不在这里展开全部细节。

## 目录设计（Directory Design）

### 母仓库目录

- `Agent.md`：共享 Agent 核心规则
- `AGENTS.md`：Codex 入口规则
- `CLAUDE.md`：Claude Code 入口规则
- `SKILL.md`：Skill 主入口
- `agents/openai.yaml`：OpenAI Skill 元数据
- `README.md`：项目总说明
- `pyproject.toml`：Python 项目配置与依赖声明
- `docs/`：详细设计、运行说明、排障文档、项目资料
- `src/myagentwiki/`：CLI 与核心实现
- `templates/`：工作区模板
- `tests/`：自动化测试
- `scripts/`：验证脚本与辅助工具

### 初始化后的用户工作区目录

若需要举例，统一使用 `MyNotesWiki/` 表示工作区，使用其同级 `raw/` 表示原始资料目录。

- `../raw/`：与工作区平级的原始资料目录
- `../assets/`：与工作区平级的下载型派生素材目录
- `normalized/`：标准化文档层
- `chunks/`：证据切块层
- `claims/`：声明展开文件
- `semantic/`：语义分析结果、批量缓存和中间产物
- `wiki/`：知识页面
- `indexes/`：搜索索引、别名索引、阅读索引等
- `state/`：结构化账本
- `reviews/`：审核展开文件
- `logs/`：结构化执行日志目录
- `outputs/`：导出或临时输出目录
- `config/`：工作区配置
- `reports/lint/`：巡检报告目录

### 工作区分层与写入边界

#### 1. 原始资料层

- `raw/`：位于工作区外部并与工作区平级，保存用户自己维护的原始资料及其目录结构；Agent 不自动修改该层内容

#### 2. 下载素材层

- `assets/`：位于工作区外部并与工作区平级，保存标准化阶段下载得到的远程图片等派生素材；不属于独立导入源，也不写回 `raw/`

#### 3. 证据编译层

- `normalized/`：标准化文档目录，保存统一格式的文档中间表示
- `chunks/`：证据切块目录，保存可检索、可引用、可回链的证据单元
- `claims/`：声明展开目录，保存单条 Claim 的人工可读展开文件

这三层不是“临时文件夹”，而是系统主真相的一部分。

#### 4. 语义分析层

- `semantic/`：语义分析结果、批量缓存和中间产物目录
- `state/semantic_*.jsonl`：语义决策账本文件，用于记录结构化语义判断历史

保存文档结构判定、Claim 角色判定、页面意图判定、批处理缓存和语义决策历史。

#### 5. 知识呈现层

- `wiki/`：知识页面目录，保存面向人阅读的页面视图
- `indexes/`：索引目录，保存搜索索引、别名索引和阅读辅助索引

这层面向人阅读，也服务 query、reading_pack 和 answer-ready。

#### 6. 状态与控制层

- `state/`：结构化账本目录，保存对象身份、生命周期、跨文件关系和恢复线索
- `reviews/`：审核展开目录，保存单条 review 的人工可读展开文件
- `reports/`：报告目录，主要承载 lint 等流程生成的人类可读报告
- `logs/`：日志目录，承载更细粒度的结构化执行日志

这一层负责保存账本真相、审核单、巡检报告和执行痕迹。

## 核心对象与数据模型（Core Objects And Data Model）

### 数据模型总则

对象设计围绕三类真相分层：

1. 证据真相（Evidence Truth）
2. 语义真相（Semantic Truth）
3. 展示真相（Presentation Truth）

这样做的原因，是为了避免把所有“会变化的语义判断”都塞回 Claim 或 Page 本体，导致系统难以解释、难以回放、难以局部重编译。

### Source（原始来源）

表示原始来源文件。

最小字段：

- `source_id`：来源唯一标识
- `source_path`：来源文件路径
- `source_type`：来源类型，例如 Markdown、PDF、Word、图片
- `source_hash`：来源内容哈希，用来判断内容是否变化
- `imported_at`：导入时间
- `version_group`：版本分组，用来串起同一来源的多次演进
- `status`：当前处理状态
- `normalized_path`：对应标准化文档路径
- `warnings`：处理过程中的告警信息

设计原因：

- `source_id` 用来稳定标识来源身份，而不是依赖文件名
- `source_hash` 用来判断内容是否变化
- `version_group` 用来表达“同一路径来源的演进关系”
- `warnings` 用来保留降级提取、局部失败和风险提示

当前实现：

- 系统会为每个原始文件生成 `source_id`
- 当前 `source_id` 基于 `raw/` 下相对路径和 `source_hash` 生成，避免子目录同名冲突
- 同一路径文件内容更新时，当前实现采用原位演进：复用 `source_id`，重建下游证据链

### NormalizedDocument（标准化文档）

表示规范化后的统一文档对象。

最小字段：

- `source_id`：对应的来源 ID
- `normalized_path`：标准化文档路径
- `title`：文档标题
- `location_map`：位置映射，用来回链原文位置
- `extraction_method`：提取方式
- `extraction_quality`：提取质量
- `warnings`：提取过程中的告警信息
- `raw_hash`：原始内容哈希
- `normalized_hash`：标准化结果哈希
- `normalizer_version`：标准化器版本
- `document_kind`：文档类型
- `structure_quality`：结构质量
- `chunk_strategy_hint`：建议切块策略

设计原因：

- `normalized_path` 让正文保留在可直接打开的 Markdown 文件里，而不是挤进账本
- `location_map` 让后续 chunk、claim、页面和引用能回到原位置
- `document_kind / structure_quality / chunk_strategy_hint` 让后续流程知道这份文档该怎么切、怎么读、该有多保守

### Chunk（证据切块）

表示从标准化文档切分出的处理单元和证据单元。

最小字段：

- `chunk_id`：切块唯一标识
- `source_id`：所属来源 ID
- `source_path`：所属来源路径
- `section_path`：章节路径
- `chunk_index`：切块序号
- `start_line`：起始行号
- `end_line`：结束行号
- `page_range`：页码范围
- `char_count`：字符数
- `token_estimate`：Token 估算数
- `summary`：切块摘要
- `text`：切块正文
- `previous_chunk`：前一切块 ID
- `next_chunk`：后一切块 ID
- `overlap_from_previous`：与前一切块的重叠内容
- `hash`：切块内容哈希
- `chunker_version`：切块器版本
- `chunk_kind`：切块角色
- `topicworthiness_hint`：主题承载潜力提示

设计原因：

- Chunk 同时承担检索、摘要、Claim 抽取、溯源、增量更新和语义分析输入的职责
- `previous_chunk / next_chunk` 用来补足上下文，而不是直接复制 overlap 文本
- `chunk_kind / topicworthiness_hint` 让后续流程区分结构壳、主题段、步骤段、总结段等不同角色

### Claim（知识声明）

表示独立知识声明，是系统当前最核心的知识枢纽层。

最小字段：

- `claim_id`：声明唯一标识
- `text`：声明原文
- `normalized_text`：归一化后的声明文本
- `status`：声明状态
- `source_ids`：关联来源 ID 列表
- `chunk_ids`：关联切块 ID 列表
- `page_ids`：关联页面 ID 列表
- `conflict_group`：冲突分组标识
- `duplicate_candidates`：重复候选列表
- `review_reason`：进入审核的原因
- `claim_type`：声明类型
- `knowledge_role`：知识角色
- `page_intent_hints`：页面意图提示
- `concept_candidate_score`：概念页候选分
- `source_refs`：来源引用指针
- `lifecycle_status`：生命周期状态
- `superseded_by`：被哪些后续声明替代
- `archived_at`：归档时间
- `created_at`：创建时间
- `updated_at`：更新时间

设计原因：

- Claim 把“知识结论”从“页面文本”中独立出来
- 同一条 Claim 可以被多个页面复用
- `source_refs` 比 `source_ids` 更重要，因为它回答“来自来源里的哪里”
- `knowledge_role` 和 `page_intent_hints` 不是为了立刻生成页面，而是为了让后续语义和页面路由有共同语言

当前实现：

- 每条 Claim 会展开保存为 `claims/*.json`
- `state/claims.jsonl` 保存快扫总账
- Claim 合并、归档或被新版本替代时，不会直接消失，而是留下历史态

### SemanticDecision（语义决策）

表示系统对某批输入做出的结构化语义判断。

最小字段：

- `decision_id`：语义决策唯一标识
- `task_type`：任务类型，例如文档分析、Claim 角色判定、页面意图判定
- `item_type`：目标对象类型
- `item_ids`：目标对象 ID 列表
- `decision`：决策结果
- `confidence`：决策置信度
- `reason_code`：原因代码
- `prompt_version`：提示词版本
- `model_key`：模型标识
- `schema_version`：返回结构版本
- `input_fingerprint`：输入指纹，用来支持缓存与失效
- `created_at`：创建时间
- `superseded_by`：被后续决策替代的标记

设计原因：

- 语义层需要有独立账本，否则无法解释“为什么这个对象被这样组织”
- `prompt_version / model_key / schema_version` 用来支持升级、失效和回放
- `input_fingerprint` 用来支持缓存和局部重跑

### ReviewItem（审核项）

表示人工审核单。

最小字段：

- `review_id`：审核项唯一标识
- `kind`：审核类型
- `status`：审核状态
- `lifecycle_status`：生命周期状态
- `candidate_claim_ids`：候选声明 ID 列表
- `candidate_page_ids`：候选页面 ID 列表
- `reason`：触发审核的原因
- `recommended_action`：推荐动作
- `allowed_actions`：允许执行的动作列表
- `resume_from`：恢复起点
- `evidence`：关键证据摘要
- `created_at`：创建时间
- `resolved_at`：解决时间
- `archived_at`：归档时间

设计原因：

- 审核项不是备注，而是“暂停点 + 决策容器 + 恢复入口”
- `allowed_actions` 用来明确系统支持哪些收口方式
- `resume_from` 用来避免人工处理后还得整条链全量重跑

### WikiPage（知识页面）

表示面向人阅读的页面视图。

最小字段：

- `page_id`：页面唯一标识
- `title`：页面标题
- `type`：页面类型
- `canonical_id`：规范 ID
- `status`：页面状态
- `automation_level`：自动化等级
- `review_reason`：进入审核的原因
- `page_intent`：页面意图
- `summary`：页面摘要
- `aliases`：别名列表
- `redirect_to`：重定向目标
- `claim_ids`：关联声明 ID 列表
- `review_ids`：关联审核项 ID 列表
- `source_refs`：来源引用指针
- `lifecycle_status`：生命周期状态
- `archived_at`：归档时间
- `removed`：是否已移除
- `created`：创建时间
- `updated`：更新时间

设计原因：

- 页面是展示层，不是事实层
- `canonical_id` 负责长期身份稳定，`title` 负责人类可读显示
- `page_intent` 决定为什么成页，`type` 决定以什么模板呈现

当前实现：

- 当前设计不再要求保留 `concept-summary` 等早期页型兼容
- 页型体系直接以正式页面族谱为准，由 `concept / guide / example / topic / reference / timeline / overview / source-summary / qa-note` 等页型承担主流程
- query、migrate 与兼容清理应围绕正式页型和明确迁移动作设计，而不是长期维持早期页型并存

### 状态、生命周期与自动化等级

为了避免混淆，系统把几个常见概念拆开：

- `status`：当前业务状态，例如 `draft / stable / disputed / needs_review`
- `lifecycle_status`：是否仍参与 live 主流程，例如 `active / superseded / archived / removed`
- `automation_level`：系统默认能自动改到什么程度，例如 `safe_auto / auto_with_log / require_review / locked`

这几组字段必须分开理解，否则后续 review、page rebuild、query 和 lint 都会误判。

### 账本、展开视图与权威源规则

系统中的文件大致分三类：

#### 1. 账本真相

- `state/sources.jsonl`：来源账本
- `state/normalized.jsonl`：标准化账本
- `state/chunks.jsonl`：切块账本
- `state/claims.jsonl`：声明账本
- `state/reviews.jsonl`：审核账本
- `state/pages.jsonl`：页面账本
- `state/ingest_state.jsonl`：流程状态账本
- `state/semantic_decisions.jsonl` 或 `semantic/*.jsonl`：语义决策账本

这类文件负责保存对象身份、生命周期、跨文件关系和恢复线索。

#### 2. 展开视图

- `claims/*.json`：单条 Claim 的展开视图
- `reviews/*.json`：单条 Review 的展开视图
- `wiki/**/*.md`：面向人阅读的知识页面

这类文件更适合人工阅读、编辑和点查。

#### 3. 派生索引

- `indexes/search_pages.jsonl`：页面搜索索引
- `indexes/aliases.json`：别名与规范页索引

这类文件服务检索和快速定位，原则上可重建。

统一规则：

- 对象身份以 ID 为准，不以标题或正文为准
- 展示层不能静默覆盖权威字段
- 当页面、索引、展开文件和账本不一致时，应优先依据账本和生命周期规则判断 live 集合

## 初始化与环境（Initialization And Environment）

### 初始化流程

`init` 的行为固定如下：

1. 接收原始知识目录路径与项目名
2. 在原始目录同级创建新的 Wiki 工程目录
3. 若同级 `raw/` 已存在则直接复用；若不存在则创建空的 `raw/`
4. 生成模板目录和配置文件
5. 写入 `AGENTS.md`、`CLAUDE.md`、`wiki/index.md`、`wiki/log.md`
6. 初始化状态文件和索引占位文件
7. 若目标目录不是 Git 仓库，则自动执行 Git 初始化并生成基线提交

### CLI 入口

- `python3 -m myagentwiki doctor`：环境体检命令，用来检查当前机器是否满足运行条件
- `python3 -m myagentwiki bootstrap`：环境自举命令，用来安装或修复 Python 依赖
- `python3 -m myagentwiki init`：初始化工作区命令，用来创建新的 Wiki 工程骨架
- `python3 -m myagentwiki ingest`：导入与编译命令，用来把原始资料推进到证据层、语义层和展示层
- `python3 -m myagentwiki query`：查询命令，用来检索页面并返回阅读包
- `python3 -m myagentwiki answer-query`：回答交接命令，用来生成更适合上层回答器直接消费的 answer-ready 输出
- `python3 -m myagentwiki lint`：巡检命令，用来检查证据层、语义层和展示层的一致性
- `python3 -m myagentwiki review-list`：审核列表命令，用来查看当前待处理的审核项
- `python3 -m myagentwiki review-auto`：保守自动审核命令，用来先自动收口高把握审核项
- `python3 -m myagentwiki review-apply`：审核应用命令，用来落地审核动作并恢复后续流程

### 为什么初始化必须把骨架一次搭全

初始化时就把证据层、语义层、展示层和状态层边界搭好，有两个直接好处：

- 后续实现扩展时，不需要为了补目录结构再做破坏性迁移
- 上层 Agent 从第一天起就知道哪些目录可以读、哪些目录不能直接手改

### 环境命令

#### `doctor`

负责环境体检：

- 检查 Python 版本是否满足 `3.12+`
- 检查必需 Python 包是否已安装
- 检查 `git` 是否可用
- 检查可选系统工具是否存在
- 输出结构化环境报告

#### `bootstrap`

负责环境自举：

- 安装或修复 Python 依赖
- 生成运行环境报告
- 不默认静默安装系统级软件，只提示缺失项与平台建议

### 工作区输出约定

主命令的 JSON 输出应统一带 `workspace_summary`，至少包含：

- `workspace_dir`：工作区绝对路径
- `workspace_name`：工作区目录名
- `entry_page_path`：入口页路径，通常是 `wiki/index.md`
- `wiki_log_path`：Wiki 日志页路径
- `lint_report_path`：最近一次 lint 报告路径
- `lint_report_exists`：最近一次 lint 报告是否实际存在

如果命令直接涉及外部原始资料目录，还应额外附带 `raw_dir`。

这样做的原因，是为了避免 UI 或上层 Agent 只记住目录名，忘记真实工作区路径。

## 标准化层（Normalization Layer）

### 这一层在系统中的角色

标准化层是 document IR（文档中间表示）的起点。

它不只是把文件转成 Markdown，而是负责：

- 把异构原始资料转换成统一、可继续处理的结构
- 尽可能保留标题层级、位置映射、页码信息、表格结构和回链线索
- 为后续切块和文档结构判定提供稳定输入

### 总体原则

- `raw -> normalized` 是整套编译链的第一优先级
- 优先纯 Python 实现
- 外部办公软件不是主路径前提
- LLM 不直接替代标准化器，只在结构灰区上提供受限判断

### 统一转换架构

标准化层采用“统一抽象 + 多转换器”设计：

- `BaseConverter`：基础转换器接口，约束所有转换器的共同输入输出行为
- `MarkdownConverter`：Markdown 转换器，负责处理 Markdown 和纯文本材料
- `PdfConverter`：PDF 转换器，负责处理 PDF 文档
- `WordConverter`：Word 转换器，负责处理 `.docx / .doc` 文档
- `ExcelConverter`：Excel 转换器，负责处理 `.xlsx / .xls / .csv` 表格
- `ImageConverter`：图片转换器，负责处理图片元数据和 OCR 文本

所有转换器输出统一 `NormalizedDocument`。

### Markdown

行为：

- 保留标题层级、列表、代码块、表格、链接
- 清理 BOM、空白噪声、非法换行
- 记录行号映射
- 发现远程图片时先下载到 sibling `assets/`，再继续标准化

当前实现补充：

- 远程图片默认落到 `assets/<source_id>/`
- 下载结果通过 `location_map.images[*]` 回链 `asset_path / asset_hash / content_type / download_mode`
- 下载失败不会让整份 Markdown 退出主流程，而是保留正文并写入 `warnings`

### PDF

行为：

- 提取页级文本
- 按页或逻辑段生成 Markdown
- 记录 `page_range` 和页级 `location_map`
- 对无法提取的页面写入 `warnings`

设计原因：

PDF 往往结构噪声更高，所以必须先保住页级回链，后续才谈得上时间线、引用和证据路径。

### Word

行为：

- 提取标题、段落、列表、表格、图片占位
- 保持块顺序和章节结构
- 输出 Markdown 和段落级映射

当前实现：

- `.docx` 已有 `python-docx` 主路径和 `zip+xml` 纯 Python 回退
- `.doc` 当前采用纯 Python 二进制保守回退

### Excel

行为：

- 读取 workbook、sheet、表头、数据区域
- 每个 sheet 转为 Markdown 表格和结构化块
- 保留 sheet 名、行列坐标、公式存在标记

当前实现：

- `.xlsx` / `.csv` 已有稳定 Python 路径
- `.xls` 当前采用纯 Python 二进制保守回退

### 图片

行为：

- 先提取元数据、EXIF、尺寸、文件名语义
- 若本地 OCR 可用则提取 OCR 文本
- 若 OCR 不可用或结果不足，则保留降级说明和待补充标记

当前实现：

- 已实现“元数据保底 + `tesseract` 可用时本地 OCR 增强”
- 当前尚未接入自动的 Agent 视觉理解续跑

### 提取方式与提取质量

每个标准化对象都必须记录：

- `extraction_method`：提取方式
- `extraction_quality`：提取质量

建议的提取方式：

- `python_only`：纯 Python 提取
- `python_only+tesseract`：Python 提取加本地 OCR 增强
- `python_plus_agent`：Python 先提取，Agent 再补充理解
- `agent_only_fallback`：仅在极端兜底场景下使用 Agent

建议的质量等级：

- `good`：质量良好，可正常进入下游流程
- `partial`：部分可用，可继续处理但要保留告警
- `poor`：质量较差，只适合保守进入草稿层
- `failed`：提取失败，应退出主流程并留痕

这样做的原因，是为了让下游流程知道“该继续正常处理、保守处理，还是暂停”。

### 查询标准化

查询标准化（query normalization）与来源标准化分离。

最小职责：

- 去掉无意义口头词
- 识别中英混写术语
- 根据 alias registry 扩展同义词
- 提取基本检索意图，例如 `compare / definition / timeline / how_to / evidence`

当前实现：

- 已实现多字段 BM25 检索与页面权重叠加
- 已实现第一版 query normalization、alias 精确扩展和 canonical 目标回传
- 已实现轻量意图识别

## 切块层（Chunking Layer）

### 这一层在系统中的角色

切块层不是单纯“把文档切小”，而是把文档中间表示进一步编译成证据单元（evidence units）。

它同时承担：

- 检索单元
- 摘要单元
- Claim 抽取单元
- 溯源单元
- 增量更新单元
- 语义分析输入单元

### 默认切分规则

- 先按 Markdown 标题切
- 超长块再按段落切
- 过短块与相邻块合并
- 代码块、表格、引用块尽量整体保留
- 预留 overlap 字段，但当前默认不复制重叠文本

### 允许被文档分析覆盖的策略

若文档分析已给出 `chunk_strategy_hint`，可覆盖默认策略，例如：

- FAQ 文档优先按问答对切
- timeline 文档优先按事件切
- table-heavy 文档优先按表格行组切
- chat log 优先按轮次切

### 默认参数

- `target_tokens: 1000`：目标切块长度
- `max_tokens: 1600`：单块最大长度上限
- `min_tokens: 200`：单块最小长度下限
- `overlap_tokens: 0`：当前默认不复制重叠文本

### 为什么当前不启用 overlap

当前阶段更重视证据去重、引用稳定和可追踪性。

如果直接复制重叠文本，会带来几个问题：

- Claim 抽取时容易把同一句话当成两份证据
- review 可能出现重复候选
- `source_refs` 统计容易失真

因此当前采用 `previous_chunk / next_chunk` 来补上下文，而不是复制 overlap 正文。

### 质量约束

- `chunk_id` 必须稳定
- 不能破坏代码块、表格、引用块
- 若 chunk 规则变化导致大规模 `chunk_id` 变更，应进入审慎收口，而不是静默覆盖旧引用

## 声明层（Claim Layer）

### 这一层在系统中的角色

当前对外术语仍保留 Claim，但更准确的理解方式是：

它是“知识单元层”的第一版实现，而不是默认等于“可以直接长成页面的结论”。

它的职责是：

- 从 chunk 中抽取可追踪的知识单元
- 把页面组织与知识结论解耦
- 为后续语义分析、检索、审核和页面路由提供共同对象

### 设计原则

- Claim 不依附于某一页
- 同一条 Claim 可以被多个页面复用
- Claim 必须能正向回到来源，也能被页面反向引用
- 并非所有 Claim 都适合作为正式页面的核心结论

### Claim 状态

建议支持：

- `draft`：草稿状态
- `stable`：稳定状态
- `disputed`：争议状态
- `needs_review`：待审核状态
- `archived`：归档状态

当前实现：

- 规则抽取出来的 Claim 主要落在 `draft / needs_review`
- `stable` 已进入受控自动流程，通过 `review-auto` 中的提稳子步骤按可追踪性、冲突状态与文本完整度收口
- `disputed` 仍更多依赖后续人工或 Agent 深化治理

### Claim 类型与知识角色

`claim_type` 回答“这句话像哪类句子”，例如：

- `definition`：定义类句子
- `fact`：事实类句子
- `comparison`：对比类句子
- `causal`：因果类句子
- `procedure`：步骤类句子
- `evaluation`：评价类句子
- `warning`：风险提示类句子

`knowledge_role` 回答“它在知识系统里扮演什么角色”，例如：

- `definition`：定义角色
- `fact`：事实角色
- `procedure`：步骤角色
- `example`：示例角色
- `conclusion`：结论角色
- `opinion`：观点角色
- `meta`：元说明角色
- `structural_shell`：结构壳角色

为什么要拆两层：

- 同样是定义类句子，可能既是页面核心，也可能只是来源里的局部说明
- 只有把“句型”和“系统角色”拆开，后续 page intent 才能稳定做路由

### 当前抽取策略的重点

当前规则抽取采用：

- 整句优先
- 子句只作补充候选
- 明显依赖前文的从句、元描述、对话前缀、孤立纯日期标题、结构噪声主动降权或过滤

这样做的原因，是为了避免“像文本但不是知识声明”的碎片误入 Claim 层。

## 语义分析层（Semantic Analysis Layer）

### 为什么这一层必须独立写清楚

这是当前文档最容易被误读的部分。

如果只写“系统会调用 LLM 做一些判断”，读者很难知道：

- 到底哪些判断属于脚本，哪些属于 LLM
- 为什么某些页面会生成，另一些不会
- 为什么 concept page 的问题，其实往往要从 claim role 和 page intent 往前解决

因此这里把语义层拆成正式的语义分析阶段（semantic analysis passes）。

### 语义分析阶段

建议统一为以下几类：

1. 文档分析（document analysis pass）
2. 切块策略评审（chunk policy pass）
3. Claim 角色判定（claim role pass）
4. 页面意图判定（page intent pass）
5. grounded 改写（grounded rewrite pass）
6. 概览页综合（overview synthesis pass）

### 每一类阶段分别做什么

#### 文档分析

目标：

- 判断文档更像 `article / note / faq / tutorial / spec / chat_log / reference / timeline`
- 判断结构质量，例如 `clean / mostly_clean / noisy / ocr_broken`
- 给出 `chunk_strategy_hint`

原因：

很多后面的问题，其实是文档结构一开始就没有被区分。

#### Claim 角色判定

目标：

- 给 Claim 补 `knowledge_role`
- 补 `page_intent_hints`
- 给出 `concept_candidate_score`

原因：

如果不在这里先做角色判定，页面生成阶段就只能反复从局部文本猜语义，越写越补丁化。

#### 页面意图判定

目标：

- 判断对象是否值得成页
- 判断更适合成什么页
- 在灰区候选上允许 `accept / reject / rename / reroute`

原因：

“先生成标题再看标题好不好”是不稳定的，正确顺序应该是“先判页型，再命名，再渲染”。

#### grounded 改写

目标：

- 在页型、证据和结构骨架已经确定之后，做可读化表达

原因：

这样可以让 LLM 的自由度只落在表达层，而不是事实层和结构层。

### 语义层的统一输入输出约束

统一流程应为：

1. 脚本先做初筛
2. 灰区候选打包送入 LLM
3. LLM 返回严格 JSON schema
4. 脚本做 schema 校验、grounded 校验、账本写回和缓存收口

这条约束也适用于短句 / 短 claim：

- 不能继续把 `<12`、`<14`、`<16` 这类长度阈值当成主要语义判断
- 脚本层只应继续拦截纯链接、路径、speaker 前缀、纯日期、表格线等明显垃圾
- 对“短但可能有意义”的候选，应进入独立的质量灰区批处理，由 LLM 返回 `standalone / fragment / title_shell / noise` 这类受限标签
- 只有在质量判定明确放行时，短 claim 才应继续进入 `safe_auto`

### 批处理与缓存

默认优先使用批调度器（batch scheduler），而不是单条高频调用。

原因：

- 同一任务类型能共享静态上下文
- 便于控制预算、重试和缓存
- 更适合后续回放和调试

语义账本至少应记录：

- `task_type`：任务类型
- `item_ids`：目标对象 ID 列表
- `model_key`：模型标识
- `prompt_version`：提示词版本
- `schema_version`：结构版本
- `input_fingerprint`：输入指纹

## 审核、提稳与恢复（Review, Stable Promotion And Recovery）

### 更新为什么应被视为增量重编译

`ingest` 不应被理解为“再跑一次脚本”，而应被理解为增量重编译（incremental recompilation）。

它的目标是：

- 只重编译受影响的证据层
- 只重算受影响的语义层
- 只重建受影响的展示层

### 默认复合流程

在当前方向下，默认链路应理解为：

`ingest -> review-auto -> stable promotion -> page rebuild -> query-ready artifacts`

也就是说，`ingest` 结束并不总意味着“所有后续收口都已完成”，但默认模板会继续把高把握自动步骤串起来。
其中 `stable promotion` 是否发生，取决于 hook 判定是否返回 `decision=promote`；`page rebuild` 是否进一步产出可读 `concept / overview`，还取决于 stable claim 数量、页型路由结果与页面生成条件。

### 必须进入审核队列的场景

- 截然相反的结论
- 高度相似但是否应合并不明确的结论
- 替换稳定 Claim
- 覆盖稳定页面核心结论
- 批量删除、合并、重命名页面
- 大量 `source_refs` 或 Claim 映射失效
- 别名冲突或规范名边界不明确
- 问答沉淀要升级为正式页面
- 私有 / 敏感内容要流向公开 / 导出区域

### 审核动作

统一支持：

- `merge`：合并
- `keep_both`：两者都保留
- `archive_one`：归档其中一个
- `edit_then_resume`：先编辑再恢复流程
- `assign_alias`：指定别名归属
- `remove_alias`：移除别名

### 为什么 `edit_then_resume` 很关键

这是人工编辑与自动恢复之间的正式桥梁。

如果没有这一步，系统很容易出现：

- 磁盘上的人工改动已经发生
- 内存或账本里的旧状态还没刷新
- 后续页面和索引用旧状态继续生成

所以人工改 Claim 后，必须通过 `review-apply ... edit_then_resume` 把改动重新纳入闭环。

### 自动审核与提稳

当前已经存在保守自动审核路径 `review-auto`：

- 先读取 live review、live claim、live page 和 alias index
- 自动收口部分高把握场景
- 把剩余需要人判断的项整理成 handoff

当前可自动收口的典型场景包括：

- 明显片段化、被更完整陈述包含的 conflict claim
- 互补但并非重复的两条 Claim
- 部分低风险 alias 场景；噪声 alias 若仍存在归属歧义或会影响用户可见 review 流程，则优先升级为人工判断项

同时，系统还支持受控的 `stable promotion`：

- 默认 `safe_auto` 只要求 claim 仍可追踪、没有开放 review / duplicate / conflict，且文本本身不是明显碎片或噪声；单一来源也可以被提升为 `stable`
- 对短 claim，`safe_auto` 不再直接依赖固定字符数门槛，而应优先读取短句质量语义结论；没有明确放行时继续保守停留在 `draft/needs_review`
- 多来源支撑仍然是强正向信号，但不再作为默认提稳门槛
- 只有在 hook 返回 `decision=promote` 且置信度达标时，才提升为 `stable`
- 未达标时保持原状，不做“顺手提稳”

### 恢复机制

恢复应满足：

- 自动流程写入 review item 后暂停危险动作
- 审核动作应用后，从 review 指向的恢复点继续
- 不要求整条 ingest 全量重跑

当前 `review-apply` 已会刷新：

- 受影响页面本体
- `state/pages.jsonl`：页面账本
- `wiki/index.md`：Wiki 首页
- `indexes/search_pages.jsonl`：页面搜索索引

## 页面与展示层（Pages And Presentation Layer）

### 页面不是唯一中心产物

页面只是展示层的一种主要视图，不是系统唯一主产物。

这点很重要，因为：

- 有些问题更适合通过来源视图回答
- 有些问题更适合通过阅读包回答
- 有些问题只需要 Claim 和 Chunk，不需要先长成正式页面

### 推荐页面族谱

建议长期采用更清楚的页面族谱：

- `concept`：概念页
- `entity`：实体页
- `guide`：指南页
- `example`：示例页
- `topic`：主题页
- `overview`：综述页
- `reference`：参考页
- `timeline`：时间线页
- `qa-note`：问答笔记页
- `source-summary`：来源摘要页或来源入口页

其中 `source-summary` 的正式角色应收缩为“来源入口页 / 来源视图”，而不是杂项内容回收站。

### 模板为什么要跟 page intent 对齐

页面模板不应只按“旧页型名字”区分，而应按 page intent 选择模板族。

例如：

- 概念页：定义、核心机制、边界条件、相关概念、来源
- 指南页：目标、前置条件、步骤、变体、注意事项、来源
- 示例页：场景、输入、过程、结果、可迁移点、来源
- 主题页 / 综述页：问题空间、关键子主题、证据入口、相关页面、来源
- 参考页：术语表、规则表、参数清单、来源
- 来源摘要页：原文概览、核心观点、可下钻证据、与现有页面的联系 / 冲突、后续建议

### grounded 改写的边界

当前页面生成方向已经明确为：

- 先由脚本搭 grounded 骨架
- 再由 LLM 做受控改写

这样做的原因，是为了同时保留：

- 可追踪性
- 可读性
- 对表达层升级的空间

当前可读页体系中，`concept` 与 `overview` 是最先被打磨的两类页面。

## 检索、阅读包与回答交接（Retrieval, Reading Pack And Answer Handoff）

### 检索层在系统中的角色

检索不只是“查页面”，而是 evidence graph 和 presentation layer 的统一读取接口。

它需要同时支持三类读取路径：

- 页面优先（presentation-first）
- 证据优先（evidence-first）
- 混合路径（hybrid）

### 默认查询顺序

默认顺序是：

1. 先检索页面
2. 再下钻 Claim
3. 最后按需回读 Chunk

但对于 `evidence / timeline / how_to / review-risk` 等意图，应允许直接提升 evidence-first 路径。

### 多字段 BM25

至少对以下字段分别打分：

- `title`：页面标题
- `aliases`：页面别名
- `summary`：页面摘要
- `headings`：页面标题层级
- `body`：页面正文
- `claim_text`：关联声明文本
- `source_refs`：来源引用

总分公式：

`final_score = Σ(field_weight * bm25(field)) * page_type_weight * page_status_weight`

设计原因：

- 标题、别名、摘要、正文的重要性不同
- 页面类型和页面状态本身也携带回答可靠性信息
- evidence 类问题不应永远由同一类旧页型兜底

### 当前默认权重

字段权重：

- `title: 5.0`：标题权重最高，最能代表主题命中
- `aliases: 4.0`：别名权重较高，适合处理中英文别名和旧称
- `summary: 3.0`：摘要权重较高，代表页面核心内容
- `headings: 2.5`：标题层级权重中高，适合定位局部主题
- `body: 1.0`：正文基础权重
- `claim_text: 2.0`：声明文本权重高于普通正文
- `source_refs: 0.5`：来源引用权重较低，主要服务证据类查询

页面类型权重：

- `overview: 1.25`：综述页默认优先级最高
- `concept: 1.15`：概念页优先级较高
- `entity: 1.10`：实体页优先级较高
- `topic: 1.08`：主题页略高于中性页
- `guide: 1.05`：指南页略高于中性页
- `reference: 1.00`：参考页中性权重
- `timeline: 1.00`：时间线页中性权重
- `source-summary: 0.98`：来源页常规查询略后排，但证据查询可被意图加权提升
- `example: 0.95`：示例页略后排
- `qa: 0.95`：问答页略后排
- `draft: 0.70`：草稿页明显后排

页面状态权重：

- `stable: 1.10`：稳定页适度加权
- `draft: 0.80`：草稿页后排
- `disputed: 0.90`：争议页略后排
- `outdated: 0.60`：过期页明显后排
- `needs_review: 0.75`：待审核页后排

### 阅读包为什么是标准输入，而不是附属输出

阅读包（reading_pack）不只是“检索结果附带的上下文”，而是上层回答器的正式输入契约。

原因是：

- query 排序和 query 阅读路径是两回事
- 页面摘要能帮助快速定位，但很多问题不能停在摘要层
- 如果上层回答器没有标准交接层，就会各自重新猜“先读什么、后读什么”

因此 `reading_pack` 至少要回答：

- 当前问题属于什么意图
- 当前最优命中页是什么
- 还需要继续读哪些 Claim / Chunk / Source
- 哪些风险意味着不能直接作答

### Query 输出契约

最小输出应包含：

- 查询文本与标准化查询
- 查询意图
- alias 命中与 canonical 命中线索
- 候选页面列表
- 每个页面的排序解释与命中字段
- `reading_pack`：阅读包，即查询之后给上层 Agent 的结构化阅读上下文

`reading_pack` 最小包含：

- `query_intent`：查询意图
- 匹配 `claims`：命中的声明列表
- 匹配 `chunks`：命中的证据切块列表
- 相关来源摘要
- `section_path`：章节路径
- `previous_chunk`：前一切块
- `next_chunk`：后一切块

当前实现补充：

- `query` 已显式返回 `contract_version: query_answer_handoff/v1`
- 支持 `reading_depth`
- `deep` 模式会返回更厚的 `reading_pack` 和 `source_trail`

### Query -> Answer Handoff Contract

这层契约回答的是：“回答器在真正生成答案前，应该如何消费这次检索结果？”

建议结构包括：

- `query`：查询对象，保存原问题、标准化查询和意图
- `page_context`：页面上下文，保存当前最优命中页信息
- `retrieval_context`：检索上下文，保存排序解释、阅读焦点和风险入口
- `evidence_context`：证据上下文，保存可继续下钻的 Claim、Chunk、Source
- `answer_guardrails`：回答边界，约束回答器不能随意越界发挥
- `answer_handoff`：回答交接信息，定义推荐读序和降级动作

其中最关键的是两块：

#### `answer_guardrails`

它显式定义回答边界，例如：

- 是否允许只看摘要
- 是否必须读 Claim
- 是否必须读 Chunk
- 是否必须读来源
- 是否应该显式引用来源
- 是否应该表达不确定性

#### `answer_handoff`

它显式定义消费顺序，例如：

- 推荐读序
- 必读证据路径
- 风险出现时的降级动作

这两块的意义，是把“回答前的阅读纪律”固化下来，而不是交给每个上层 Agent 临场猜测。

### Answer-Ready Output Layer

在 `reading_pack` 之上，当前系统又增加了一层面向回答器的回答交接载荷（answer-ready payload）。

入口包括：

- `python3 -m myagentwiki query "..." --answer-ready`：保留 query 调用方式，同时直接产出回答交接层
- `python3 -m myagentwiki answer-query "..."`：直接生成更适合回答器消费的 answer-ready 输出

它的目标不是直接替回答器写最终答案，而是把最适合回答阶段直接消费的内容再压一层，减少重复解析工作。

最小结构应包含：

- `workspace_summary`：工作区路径摘要
- `selected_result`：当前回答锚点结果
- `alternatives`：备选结果
- `agent_brief`：给上层 Agent 的紧凑工作指令
- `answer_context`：压缩后的回答上下文
- `agent_summary`：给上层 Agent 直接阅读的摘要说明

当前支持四种渲染格式：

- `summary`：人类可读摘要格式
- `prompt`：单段提示词格式
- `messages`：聊天 API 直接可消费的消息数组格式
- `chatml`：ChatML 文本格式

### 查询读取纪律

统一规则：

- 先读索引、页面元数据、摘要、别名、标题层级
- 命中页面后，再进入相关 Claim 和 Chunk
- 涉及证据、冲突、时间线、引用时，必须回读 Claim 对应的 Chunk 和 Source
- 即使在 `deep` 模式下，也优先扩充结构化证据路径，而不是让 LLM 直接重新总结

## 状态、一致性与日志（State, Consistency And Logging）

### 状态层在系统中的角色

状态层不只是记录 ingest 走到哪一步，而是同时承载：

- 证据账本
- 语义账本
- 展示层 live 集合与恢复入口

因此它必须支持：

- 只重跑语义分析
- 只重建页面
- 只重建索引
- 从 review 恢复，而不是全量重来

### 最小状态流

建议的主流程状态：

`new -> normalized -> chunked -> claimed -> generated -> linked -> indexed -> linted -> done`

失败时进入：

- `failed`：流程失败状态

需要人工判断时允许进入：

- `review_required`：需要审核状态
- `review_resolved`：审核已解决状态

语义层还应有一组独立概念状态：

- `semantic_pending`：等待进入语义处理
- `semantic_batched`：已经进入语义批处理
- `semantic_decided`：已经得到语义决策
- `semantic_abstained`：语义层明确放弃判断
- `semantic_superseded`：旧语义决策已被新决策替代

### 一致性规则

#### 1. 审核动作必须改写账本

`merge / archive_one / keep_both / edit_then_resume / assign_alias / remove_alias` 都必须回写状态层，而不只是改展示文件。

#### 2. 审核解决后必须收口关联对象

至少要同步刷新：

- Claim 的状态、重复候选、审核原因
- 页面的关联 Claim、关联 Review、来源引用
- 索引和 alias registry

#### 3. 已失效候选不能继续留在 open review 中

否则系统会不断对同一个已解决问题重复追问。

#### 4. alias 裁决必须以“真实收敛”为成功条件

不是命令返回成功就算结束，而是 alias index 真的已经收敛。

### 持久化要求

至少记录：

- 当前状态
- 最近成功阶段
- 失败阶段
- 最近错误信息
- 更新时间
- 重试次数

### 日志层

- `wiki/log.md`：给人看的变更时间线
- `state/error_log.jsonl`：结构化错误与降级记录
- `logs/*.jsonl`：更细粒度的机器日志目录
- Git 提交：工程级变更历史

## 巡检与测试（Lint And Testing）

### Lint 为什么是编译验证阶段

Lint 不只是质量检查，更像编译验证阶段（compiler verification pass）。

它至少验证三件事：

1. 证据层是否自洽
2. 语义层是否可解释、可回放、可回链
3. 展示层是否与前两层一致

### Lint 范围

至少包括：

- 标准化巡检
- 切块巡检
- 元数据巡检
- Wiki 链接巡检
- 来源引用巡检
- 别名与规范名巡检
- 页面质量巡检
- 语义决策巡检
- 页面意图一致性巡检

当前实现：

- 已能检查工作区目录结构、状态文件、核心 ID 唯一性、Claim / Page / Review 基础追踪关系
- 已能检查 `canonical_id` 唯一性、alias registry 覆盖情况、search index 覆盖情况
- 已新增概念页标题质量 warning，用来显式暴露“结构词标题、过短标题、问句壳标题”等问题

### 测试设计重点

在当前架构下，测试不应只覆盖“命令能不能跑通”，还必须覆盖：

- evidence IR 是否稳定
- semantic pass 是否可批量、可缓存、可回放
- presentation layer 是否正确消费 semantic decisions

重点测试面包括：

- 初始化与 Git 基线
- 五类输入标准化与降级路径
- `page -> claim -> chunk -> source` 追踪链
- query 权重与意图路由
- 语义批处理与语义账本
- review 六种动作与恢复闭环
- lint 报告与非可重试错误分流
- Windows、macOS、Linux 的基础兼容约束

当前仓库已落地的代表性测试包括：

- `tests/test_review_apply.py`：审核动作与恢复链回归测试
- `tests/test_normalizers.py`：标准化器与降级路径测试
- `tests/test_claim_extraction.py`：Claim 抽取测试
- `tests/test_review_detection.py`：审核候选检测测试
- `tests/test_query_alias_and_lint.py`：查询、别名与 lint 测试
- `tests/test_e2e_workflow.py`：端到端主闭环测试
- `scripts/validate_workflow.py`：交付级工作流烟雾验证脚本

## 当前实现边界与后续收口重点（Current Boundary And Next Focus）

### 当前已经比较明确或已落地的部分

- 统一 CLI 骨架与主命令入口
- 工作区初始化、模板生成、Git 基线提交
- 多格式标准化及部分降级路径
- Chunk、Claim、早期自动页生成，以及较新的可读 `concept / overview` 页面基础
- alias registry、search index、`reading_pack`
- Claim review 与 alias conflict review
- `review-apply` 之后的页面、索引、状态收口
- lint 与 lint 报告
- 覆盖主闭环的端到端和关键回归测试

### 当前仍在继续重构和收口的部分

- `semantic/` 目录与正式 `semantic_decisions` 账本的全面收口
- document analysis / claim role / page intent 三类批量语义分析阶段
- `abstain / prompt_version / schema_version` 等语义协议
- 页面族谱继续收敛为 `concept / guide / example / topic / timeline / reference / overview / source-summary`
- `source-summary` 从默认回收页收缩为来源入口视图
- Claim 向更宽泛 Knowledge Unit 的抽象演进
- 更细粒度的日志系统
- 更完整的跨平台实机验证矩阵

### 主文档不再承担的内容

为保持主线清晰，以下内容不再在本文档中展开所有历史细节：

- 版本迁移与兼容动作的完整专题设计
- 早期多份设计稿中的重复叙述
- 过于细碎的版本阶段命名

这些内容应放在专题文档或实施计划文档中维护，并从主文档链接过去。

## 阅读与维护约定（Reading And Maintenance Convention）

后续继续细化本文档时，建议统一使用三种标记语气，而不是再引入新的版本章节：

- `当前实现`：代码和测试已经覆盖，或已有明确行为边界
- `设计目标`：架构上已经确定，但可能仍在继续收口
- `后续扩展`：不阻塞主闭环，可放到后续阶段推进

这样做的好处是：

- 文档结构不会被版本命名打断
- 读者能更快区分“已经这样做了”和“准备这样做”
- 实现说明可以更多解释原因，而不是反复切换版本标签

## 前提假设（Assumptions）

- 运行环境以本地个人使用为主
- 正式目标平台为 Windows、macOS、Linux
- Python 版本固定为 `3.12+`
- 外部办公软件和 OCR 工具属于可选增强能力，不是主路径前提
- `Agent.md` 是 Agent 规则的共享权威源，`AGENTS.md` 与 `CLAUDE.md` 只做入口适配
