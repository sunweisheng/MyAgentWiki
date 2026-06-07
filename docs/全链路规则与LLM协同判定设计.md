# 全链路规则与 LLM 协同判定设计

## 1. 设计目标

本设计解决的问题不是“再补几条概念页标题规则”，而是把 `normalized -> chunks -> claims -> wiki` 全链路里的“语义判断职责”重新分层，让系统同时发挥脚本代码与 LLM 的优势。

如果把项目方向放到“尚未发布、允许根本调整”的前提下，这份设计还应进一步明确：

- MyAgentWiki 不是“传统脚本流水线上补几处 LLM hook”，而是一个 **evidence-first semantic compiler**。
- `normalized/chunks/claims` 不只是中间文件，而是编译过程中的不同 IR（中间表示）。
- `wiki` 页面不应被视为唯一主产物；它只是 evidence graph 之上的一种 presentation layer。
- LLM 不只是“灰区修补器”，而是编译器中的受限语义分析器，但仍必须被规则、schema、缓存和 grounded 校验约束。

因此，下面的方案不应理解为“在现有 deterministic pipeline 上外挂一层补丁”，而应理解为：把现有项目重构成“脚本掌管证据编译，LLM 掌管受限语义分析，最终共同生成知识视图”的新架构。

- 脚本负责可重复、可缓存、可审计、可回滚的证据编译流水线。
- LLM 负责脚本难以稳定覆盖的语义分类、页型判定、保守重命名与 grounded 改写。
- 人工只处理高风险且不可约的歧义。

本设计的重点场景是：

- 避免章节标题、步骤标题、问句标题、建议句、示例名、总结段误生成 `concept` 页。
- 让“这是不是概念页”成为全局机制问题，而不是只在 `wiki` 末端补救。
- 让大量 LLM 判定以批量方式执行，避免高频小调用重复携带静态上下文。

## 2. 设计原则

### 2.1 Deterministic First, Semantic Where Needed

- 能用脚本稳定解决的问题，不交给 LLM。
- 只有在“字符串规则不足以可靠判断语义角色”时，才进入 LLM 灰区判定。
- LLM 不是事实来源，只是结构化裁决器与 grounded 改写器。

### 2.1.1 Evidence First, Not Page First

- 系统的主真相应是 evidence graph，而不是最终页面文本。
- `normalized/chunk/claim` 层的结构化证据应先稳定，再决定页面怎么长出来。
- 页面只是视图，未来允许同一批证据编译出多种页面类型，而不是所有东西都往 `concept` 和 `source-summary` 里挤。

### 2.2 先判页型，再命名，再渲染

当前机制偏向“先生成候选标题，再看标题质量”。
新机制改为：

1. 先判断一组内容属于什么语义角色。
2. 只有被判定为 `concept` 的候选，才进入命名与落页流程。
3. 只有页面类型明确后，才允许可读化改写。

### 2.3 Batch Over Singleton

- 默认优先批量调用 LLM，而不是针对每条 Claim / 每个概念页单独调用。
- 批量调用以“同一任务类型、同一阶段、同一上下文模板”为单位组织。
- 批量输出必须使用严格 JSON schema，避免自由文本污染状态层。

### 2.4 Grounded Output Only

- LLM 只能在已有 `normalized/chunk/claim/page/review` 证据上做分类、选择、重命名、汇总。
- LLM 返回的新标题、新页型、新摘要，必须能回链到输入项。
- 无法 grounded 的结果必须回退到脚本默认行为或拒绝写入。

### 2.5 Stability Over Cleverness

- 宁可漏掉一部分“可能是概念”的边缘候选，也不要放进大量明显不是概念的页面。
- 引入 LLM 后，仍要优先保证 `canonical_id` 稳定、增量 ingest 可重放、测试可断言。

### 2.6 Separate Ledgers For Separate Truths

- 确定性证据账本与 LLM 语义判定账本应分离，不要把所有 mutable 语义字段直接塞回 deterministic 状态文件。
- `normalized/chunks/claims/pages` 保存“当前编译产物”。
- `semantic_decisions` 保存“为什么得到这些编译决策”。
- 这样模型升级、prompt 升级、阈值升级时，系统可以重跑语义层，而不污染证据层真相。

## 3. 当前机制问题总结

从当前实现看，问题并不只在 `concept title quality`：

- `normalized -> chunks` 阶段保留了大量结构标题，这本身没有问题，但后续把它们当主题候选时缺少语义闸门。
- `claims` 阶段会从句子与章节上下文中抽取可用 Claim，但“这条 Claim 更像概念、步骤、总结还是建议”没有被显式建模。
- `wiki` 阶段的概念页生成目前过于依赖 `section_path` 与代表 Claim 的局部可读性。
- LLM 目前主要用于：
  - review-auto 自动裁决
  - stable promotion
  - readable concept rewrite
  - overview rewrite
  - 灰区概念标题 accept/reject/rename

真正缺失的是：

- 一个跨阶段的“语义角色判定框架”
- 一个可缓存、可批量的 LLM 分类层
- 一个把脚本与 LLM 明确分工的统一设计

## 4. 总体方案：Semantic Gate Framework

建议把项目整体重构为统一的 **Semantic Compiler Framework**。

`Semantic Gate Framework` 可以作为其中的关键子模块，但如果从项目方向上根本调整，更准确的描述应是：

- `raw -> normalized -> chunks -> claims` 负责构建 evidence IR
- `semantic analysis` 负责给 IR 赋予角色、意图和编译约束
- `wiki rendering` 负责把 evidence graph 编译成不同页面视图

也就是说，语义判定不再只是“下一阶段前的闸门”，而是编译器中的正式 pass。

### 4.1 框架职责

Semantic Gate Framework 负责 4 类事：

1. 判定结构角色
2. 判定内容角色
3. 判定页面角色
4. 提供受限的重命名与收口建议

### 4.1.1 更根本的职责升级

如果按未发布项目来重构，建议把职责从“闸门”升级为“多阶段语义分析 pass”：

1. document analysis pass
2. chunk policy pass
3. claim role pass
4. page intent pass
5. overview synthesis pass

这样整个系统的语言会更统一，也更接近真正可维护的编译器设计。

### 4.2 统一输出风格

所有语义闸门都采用：

- 脚本先初筛
- 灰区候选再打包送 LLM
- LLM 返回有限枚举和少量结构化字段
- 脚本校验、缓存、落盘、收口

## 5. 全链路职责分层

### 5.0 先增加一层总视角：三套产物而不是一条线

如果方向允许根本调整，建议整个系统从“一条线性流水线”改成“三套产物协同”：

1. Evidence Products
- `normalized/`
- `chunks/`
- `claims/`

2. Semantic Products
- `semantic decisions`
- `role labels`
- `page intents`
- `semantic caches`

3. Presentation Products
- `wiki/`
- `indexes/`
- `reading packs`
- `answer-ready payloads`

这样会比“所有信息都挤在 state 和 page records 里”更清楚，也更利于后期扩展页面类型。

## 5.1 Raw -> Normalized

### 脚本负责

- 文件扫描
- 格式识别
- OCR / fallback / 文本提取
- Markdown 正规化
- 标题层级恢复
- `location_map`、哈希、提取元数据落盘

### LLM 只处理灰区

这一层不要让 LLM 直接“改写全文”，而是只做 **文档结构判定**：

- 文档更像什么类型：
  - `article`
  - `note`
  - `faq`
  - `tutorial`
  - `spec`
  - `chat_log`
  - `reference`
  - `timeline`
- 结构是否可靠：
  - `clean`
  - `mostly_clean`
  - `noisy`
  - `ocr_broken`
- 后续 chunking 建议：
  - `heading_first`
  - `paragraph_first`
  - `qa_pair`
  - `table_row`
  - `chat_turn`
  - `timeline_event`

### 设计意图

这一步不直接产出概念，只提供后续切块和 Claim 抽取的语义提示。

### 建议增加的根本调整

如果彻底重构，`normalized` 不应只被视作“清洗后的 Markdown 文件”，还应被视作文档 IR。

这意味着：

- 允许 `normalized` 层携带轻量结构语义
- 允许对不同文档类型走不同后续策略
- 允许 query / answer-ready 直接回读 normalized IR，而不总是强依赖 page 文本

### 建议新增字段

`state/normalized.jsonl` 可增加：

- `document_kind`
- `structure_quality`
- `chunk_strategy_hint`
- `semantic_gate_status`
- `semantic_gate_source` (`rule` / `llm` / `fallback`)

## 5.2 Normalized -> Chunks

### 脚本负责

- 按规则切块
- 行号、页码、上下文链路落盘
- 生成 `section_path`
- 控制 chunk 大小和稳定性

### LLM 只处理灰区

建议不要让 LLM 自由切块，而是只在灰区文档上做 **chunk policy review**：

- 当前文档更适合哪种切块策略
- 哪些标题更像结构壳，不应单独视作主题节点
- 哪些表格、FAQ、问答、聊天记录需要特殊切法

### 设计意图

很多坏概念页并不是出在“LLM 不会命名”，而是更早的阶段把“结构壳标题”保留成了后续主题线索。

因此这一层要开始显式地区分：

- `structural heading`
- `topical heading`
- `procedural heading`
- `conclusion heading`
- `example heading`

### 建议新增字段

对 section 或 chunk 增加轻量标签：

- `section_kind`
- `chunk_kind`
- `topicworthiness_hint`

其中 `chunk_kind` 可枚举为：

- `conceptual`
- `procedural`
- `example`
- `summary`
- `meta`
- `reference`
- `mixed`

脚本可先按规则给初值，LLM 只修正灰区。

### 这里还应再往前一步

如果允许重构，建议把“section”从纯字符串路径提升为显式对象：

- `section_id`
- `section_title`
- `section_kind`
- `section_parent_id`
- `section_source_span`

这样后续很多语义任务就不必反复从 `section_path` 字符串里猜结构。

## 5.3 Chunks -> Claims

### 脚本负责

- Claim 候选抽取
- 噪声过滤
- 子句切分
- `claim_type`
- `confidence`
- `source_refs`
- `source_ids`

### 这一层是全局语义治理的关键层

建议新增 **Claim Semantic Review**，但不要对每条 claim 都单独调用 LLM。

### 脚本初筛后，需要 LLM 判断的不是“这句话对不对”，而是：

- 这条 Claim 是否适合进入知识声明层
- 这条 Claim 的语义角色更像：
  - `definition`
  - `fact`
  - `procedure`
  - `example`
  - `conclusion`
  - `opinion`
  - `meta`
  - `structural_shell`
- 这条 Claim 是否具备“概念沉淀潜力”
- 如果它只是结构壳或总结壳，是否应降级为 supporting context

### 关键改法

当前 `claim_type` 更偏“句子性质”，建议增加一组正交字段，专门描述其知识角色：

- `knowledge_role`
- `page_intent_hints`
- `concept_candidate_score`

例如：

- `knowledge_role=definition`
- `page_intent_hints=["concept"]`

或者：

- `knowledge_role=procedure`
- `page_intent_hints=["guide"]`

或者：

- `knowledge_role=conclusion`
- `page_intent_hints=["overview", "source-summary"]`

### 设计意图

如果在 Claim 层就知道“这条东西更像 procedure/example/conclusion”，后面就不该再去生成 concept page。

### 这里值得更彻底一点

如果从根本调整项目方向，可以考虑让 `Claim` 从“句子声明”升级为“Knowledge Unit”：

- 文本句子仍可保留为表现形式
- 但底层模型不再默认所有 unit 都是适合落页的“知识声明”
- 某些 unit 本质上是：
  - structural marker
  - example snippet
  - procedural step
  - conclusion fragment
  - evidence observation

这样后续页型判定会自然得多。

## 5.4 Claims -> Wiki

### 脚本负责

- Claim 相似性聚类
- canonical 收口
- 页面依赖重建
- 页面账本维护
- 页面与 Claim / Review 互链
- grounded 校验

### LLM 负责灰区页型判定

这是本设计最核心的改动。

建议把当前的 `review_concept_candidate` 扩展为更高层的 **page intent review**。

它回答的不是：

- “这个标题能不能当概念名？”

而是：

- “这组 Claim 应该生成哪种页面？”

### 建议页面意图枚举

- `concept`
- `guide`
- `example`
- `section`
- `conclusion`
- `overview_material`
- `entity`
- `reject`

### 这里也建议调整

如果项目还没发布，不建议继续让非 concept 内容长期“借住”在 `source-summary`。

更彻底的方向是把页面类型体系做成正式 taxonomy，而不是临时回收站：

- `source-summary`
- `concept`
- `entity`
- `guide`
- `example`
- `topic`
- `overview`
- `timeline`
- `reference`

这样系统将来不会长期依赖“先塞进 source-summary，未来再说”的折中策略。

### 只有 `concept` 才允许继续生成 concept page

其他结果的处理方式：

- `guide`：进入 guide 候选池
- `example`：进入 example 候选池
- `section`：作为结构节点保留，不直接落独立知识页
- `conclusion`：进入 overview/topic 候选池
- `overview_material`：作为综述候选，不落 concept
- `reject`：彻底拒绝进入概念页流程

### 对 concept 的进一步处理

若判定为 `concept`，再让 LLM 返回：

- `canonical_title`
- `aliases`
- `reason`
- `confidence`

但返回值必须受限：

- 不能自由发明事实
- 不能返回开放文本段落
- 只能返回 schema 允许的短字段

## 6. 批量化 LLM 设计

### 6.0 需要再补一个调度层

如果大量任务都要批量执行，建议不要把批量逻辑散落在各命令里，而是新增 **Semantic Batch Scheduler**。

它负责：

- 发现待判定项
- 按任务类型分桶
- 做 token-aware shard
- 复用静态上下文模板
- 写回统一的 semantic decision ledger
- 处理失败重试与局部失效

如果没有这个调度层，文档里的 batch 设计容易停留在概念层，而不是系统能力。

## 6.1 为什么必须批量

如果仍按“每个候选打一枪”的模式做：

- 静态上下文重复发送，浪费 token
- ingest 时间会急剧变慢
- 成本高
- 调用抖动会更明显

因此，批量化必须是主设计，不是优化项。

## 6.2 建议的批量单元

### A. Document Structure Batch

单位：一批 `normalized` 文档

输入：每个文档只传必要摘要：

- `source_id`
- 标题
- 前几级 heading
- 抽样段落
- 提取质量
- 基础统计

输出：

- `document_kind`
- `structure_quality`
- `chunk_strategy_hint`

### B. Claim Candidate Batch

单位：同一来源或同一批来源下的一组 Claim 候选

输入：

- `claim_id`
- `section_label`
- `claim_text`
- `claim_type`
- `confidence`
- 简短邻接上下文

输出：

- `knowledge_role`
- `page_intent_hints`
- `concept_candidate_score`
- `decision` (`keep` / `downgrade` / `reject`)

### C. Page Intent Batch

单位：一组 concept page 候选 bucket

输入：

- `bucket_key`
- `preferred_section_label`
- `canonical_claim`
- top supporting claims
- source_count
- claim_count
- role histogram

输出：

- `page_intent`
- `canonical_title`
- `aliases`
- `decision_reason`
- `confidence`

### D. Review Auto Batch

当前已有 review-auto 思路，后续可以继续沿用：

- 同类 review 项按 batch 送入 hook
- 只要求返回有限动作

## 6.3 批量执行策略

- 默认按任务类型分桶，不混任务
- 每桶按 token 预算切 shard
- 优先按来源或主题局部聚合，避免跨领域污染
- 支持 `--semantic-batch-size` 或配置项控制

### 建议默认粒度

- `document_structure_batch`: 10-20 文档
- `claim_candidate_batch`: 20-60 claims
- `page_intent_batch`: 10-30 concept groups

## 6.4 批量缓存

建议新增 `state/semantic_decisions.jsonl` 或等价缓存账本。

最小字段：

- `decision_id`
- `task_type`
- `input_fingerprint`
- `input_ids`
- `model_key`
- `decision_payload`
- `confidence`
- `created_at`
- `invalidated_by`

### 作用

- 相同输入不重复调用
- 版本升级时可按 `model_key` 或规则版本失效
- 让语义判定也具备可追踪历史

### 这里建议再加两个维度

- `prompt_version`
- `schema_version`

这样未来即使模型不变，prompt 或输出结构变化也能安全失效缓存。

## 7. 规则初筛与 LLM 灰区的边界

## 7.1 脚本强规则直接处理

以下场景直接由脚本拦截，不进入 LLM：

- 明显编号步骤
- 明显“总结/结论/后记/示例”
- 纯短壳词
- 问句模板壳
- 文件名、格式名、字段说明壳
- 占位文本、环境提示、错误提示

这样可以把大部分低价值调用挡在门外。

## 7.2 进入 LLM 灰区的条件

只有下面这些候选才值得调用 LLM：

- 看起来既可能是概念，也可能是 guide/example/opinion
- 标题与 Claim 不一致，但 Claim 中疑似存在可提炼术语
- 多条 Claim 聚合后出现稳定主题，但脚本无法确定页型
- 单来源长文中反复出现的主题节点，脚本无法判断是章节还是概念

### 这里建议增加 `abstain`

当前文档里隐含的是“脚本分不清就让 LLM 判”。
更稳的设计应是：

- 脚本能直接过就过
- 脚本能直接拒就拒
- LLM 只能在灰区给 `accept / reject / rename / retype / abstain`

`abstain` 很重要，因为它能显式表达：

- 证据不足
- 批次上下文不足
- 多页型都说得通
- 需要人工或更大范围 batch

没有 `abstain`，LLM 很容易被迫给出过度自信的错误裁决。

## 7.3 规则收口

LLM 返回后，脚本仍要做最终收口：

- 枚举值校验
- 标题合法性校验
- generic/question/shell 再过滤
- grounded 校验
- canonical 稳定化

只有全部通过，才允许写入页面账本。

## 8. 对现有页面类型的影响

## 8.1 Concept

生成门槛显著提高：

- 不再因为“多条 Claim + 可读标题”就自动生成
- 必须通过 `page_intent=concept`

## 8.2 Source Summary

如果做根本重构，`source-summary` 不应继续承担“非 concept 内容的总兜底页”。

更合理的定位是：

- 作为单来源入口页
- 负责来源摘要、证据导航、可沉淀主题索引
- 不负责长期承载所有 guide/example/conclusion 正文

也就是说，`source-summary` 应是“来源视图”，不是“杂项回收站”。

## 8.3 Overview

建议把 overview 的输入从“多个 concept 页”扩展为：

- 已确认的 `concept` 页
- 被判为 `overview_material` 的 conclusion/theme groups

这样 overview 不会错过那些本来不该成为 concept、但确实适合汇总的内容。

## 9. 建议新增的数据字段

为了让脚本与 LLM 协同不只停留在运行期，而是真正进入账本层，建议逐步增加以下字段。

但如果从根本调整方向，建议把“字段新增”与“账本分层”一起设计，而不是简单往原有账本里追加。

## 9.1 Normalized

- `document_kind`
- `structure_quality`
- `chunk_strategy_hint`
- `semantic_gate_status`

## 9.2 Chunk

- `section_kind`
- `chunk_kind`
- `topicworthiness_hint`

## 9.3 Claim

- `knowledge_role`
- `page_intent_hints`
- `concept_candidate_score`
- `semantic_decision_source`

## 9.4 Page

- `page_intent`
- `generation_gate`
- `title_origin` (`rule` / `llm_rename` / `section_label` / `claim_phrase`)
- `semantic_decision_id`

## 9.5 Semantic Decision Ledger

如果要长期演进，这一层不应只是缓存，而应成为正式账本：

- `task_type`
- `item_type`
- `item_ids`
- `decision`
- `confidence`
- `reason_code`
- `prompt_version`
- `model_key`
- `schema_version`
- `input_fingerprint`
- `created_at`
- `superseded_by`

这能让“语义决策历史”与“证据历史”并列存在。

这些字段不要求一步到位，但它们体现了系统的长期方向：

- 状态层不只记录“生成了什么”
- 还记录“为什么允许它被生成”

## 10. Hook 接口设计建议

建议复用现有 hook 思路，但把任务从单点标题修补升级成批量语义判定。

### 10.0 这里建议调整成两层模型

如果方向允许变更，hook 不应只是“命令式外挂”。
建议拆成两层：

1. Semantic Analyzer Interface
- 面向结构化批量输入
- 只负责分类、裁决、重命名

2. Grounded Rewrite Interface
- 面向已经通过页型判定的内容
- 只负责可读化表达

这样分类模型与改写模型可以分开配置、分开缓存、分开测试。

### 建议新增任务

- `review_document_structure_batch`
- `review_claim_candidates_batch`
- `review_page_intent_batch`

### 建议统一返回模式

所有任务返回：

- `task`
- `results`

其中 `results` 每项必须带：

- `item_id`
- `decision`
- `confidence`
- `reason`

如果是 page intent review，则额外允许：

- `page_intent`
- `canonical_title`
- `aliases`

### 重要限制

- 不允许 hook 返回长段自由解释
- 不允许返回 schema 外字段直接影响账本
- 不允许生成未在输入证据中可解释的新事实

### 还应补一条

- 不同任务可以使用不同模型档位，但必须由统一调度层决定，而不是由调用方临时散配。

否则后面模型策略会在项目里四处分叉。

## 11. Lint 与收敛机制

Lint 不应只停留在“报 warning”，而应成为语义治理的收口工具。

建议新增以下检查：

- `concept_page_intent_consistency`
- `claim_role_page_type_consistency`
- `section_heading_promoted_as_concept`
- `conclusion_material_promoted_as_concept`
- `example_material_promoted_as_concept`

### 中长期目标

对于高置信错误页型，lint 不只是报错，还能为后续 `ingest/rebuild` 提供回收信号：

- `should_archive`
- `should_retype`
- `should_merge_back_to_source_summary`

## 12. 实施顺序建议

### 12.0 若允许根本转向，顺序也应调整

当前文档的实施顺序偏向“先挡新坏页，再慢慢补层次”。
如果项目尚未发布，更推荐先把架构骨架搭正，再做局部修补。

因此建议新的优先级如下：

1. 先定义 evidence ledger / semantic ledger / presentation ledger 的边界
2. 再定义统一 semantic batch scheduler
3. 再接 claim role 与 page intent 两个最高价值 pass
4. 再回头补 chunk/document 层标签
5. 最后才是具体页面类型扩展与 lint 回收

下面保留一个更面向落地的阶段划分。

## 第一阶段：先挡住新坏页

目标：

- 不再让明显的流程页、章节页、总结页、示例页进入 concept page

实施：

- 增加脚本强规则
- 增加 `page_intent` 灰区判定
- `concept` 之外一律不生成 concept page

## 第二阶段：把 Claim 层语义角色显式化

目标：

- 让后续页面生成不再只依赖标题与 section label

实施：

- 增加 `knowledge_role`
- 增加 `page_intent_hints`
- 批量化 claim semantic review

## 第三阶段：把 normalized/chunks 的结构标签接入

目标：

- 从更早阶段就减少结构壳污染

实施：

- 增加 `document_kind`
- 增加 `chunk_strategy_hint`
- 增加 `section_kind/chunk_kind`

## 第四阶段：让 lint 和 rebuild 具备回收旧坏页能力

目标：

- 新机制不仅防新增，也能逐步收敛历史错误页

实施：

- lint 新增页型一致性检查
- rebuild 根据高置信错误页型执行归档或不续命

## 第五阶段：页面类型从“临时回收”升级为正式 taxonomy

目标：

- 不再让 `source-summary` 长期承担 guide/example/conclusion 的宿主职责

实施：

- 增加正式页面类型
- 定义不同页面类型的 render contract
- 让 query/readability/overview 直接利用页型信息

## 13. 测试策略建议

要让这套机制可长期维护，测试必须覆盖“脚本规则 + LLM 批量判定 + 收口”三层。

### 单元测试

- 标题强规则
- page intent 映射
- generic/question/example/conclusion 拦截
- schema 校验与 fallback

### 集成测试

- 一篇 FAQ 文档不会生成大量 concept 页
- 一篇教程文档主要沉淀到 source-summary / guide，而不是 concept
- 真正的术语页仍能生成 concept
- 批量结果部分失败时，未失败项仍可正常写入

### 回归测试

- 历史上已经验证正确的 `BM25 / MCP / Chunking / RAG` 等概念页不能被误杀
- alias / canonical / query 排序不能被破坏

## 14. 最终结论

这不是“概念页标题机制”的局部修补，而是 MyAgentWiki 全局语义判定架构应该进入的下一阶段：

- `normalized/chunks` 负责保留结构与证据
- `claims` 负责形成可追踪声明
- `semantic gates` 负责做脚本难以胜任的语义角色分类
- `wiki` 负责在页型明确的前提下落盘与可读化

最重要的转变是：

- 从“标题像不像概念名”
- 变成“这组证据在知识系统里应该扮演什么角色”

而实现路径不是“更多自由 LLM 生成”，而是：

- 规则初筛
- LLM 灰区批量判定
- 规则收口
- grounded 落盘

这套设计既符合 MyAgentWiki 一贯的 `deterministic first` 哲学，也真正发挥了 LLM 在语义判定上的优势。

## 15. 面向未发布项目的进一步方向声明

既然项目尚未正式发布，建议明确一个很重要的工程原则：

- 允许推翻当前实现中的局部折中
- 允许替换当前不够准确的内部概念
- 允许重新划分页面类型、状态账本和语义账本

但同时也建议保留一条约束：

- 对外尽量复用已经有解释力的核心名词，避免无必要的命名震荡

### 15.1 哪些东西可以大胆调整

- `Semantic Gate` 可以升级为 `Semantic Compiler` 总体架构
- `Claim` 可以逐步演进为更宽泛的 `Knowledge Unit`
- `source-summary` 可以从“杂项回收页”收缩为“来源入口页”
- `concept / overview / guide / example / topic / reference` 的页面 taxonomy 可以重新设计
- `state/*.jsonl` 与 `semantic_decisions.jsonl` 的边界可以重新划分

### 15.2 哪些东西值得尽量保留

- `raw -> normalized -> chunks -> claims -> wiki` 这条用户能理解的主链路表达
- `page -> claim -> chunk -> source` 这条可追踪证据链
- `grounded-first`
- `scripts own deterministic pipeline, LLM own semantic judgment`

### 15.3 推荐的对外叙事

如果后续要统一 README、系统设计文档和实现方向，推荐把项目定位表述为：

`MyAgentWiki 是一个 evidence-first 的本地知识编译系统。`

它通过脚本构建稳定证据层，通过受限 LLM 语义分析构建知识角色层，再把这些产物编译成可查询、可阅读、可追踪的 Wiki 视图。

这句话会比“一个带 Agent hook 的脚本流水线”更准确，也更能指导后续架构选择。
