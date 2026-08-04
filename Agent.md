# MyAgentWiki Agent Core

本文件是 MyAgentWiki 的共享 Agent 规则核心源。

## 目标 / Goals

- 约束 Agent 如何在用户工程中执行 `init / ingest / query / lint`
- 明确 Python 脚本与大模型推理的职责边界
- 统一 Codex 场景下的核心行为规则

## 职责边界 / Responsibility Boundary

- 脚本优先负责：格式转换、状态落盘、索引构建、可重复执行的固定流程
- Agent 优先负责：语义抽取增强、冲突判断、页面改写、人工审核辅助
- Agent 不应绕过 CLI 直接批量改写 `state/*.jsonl`，除非是在修复脚本本身
- 需要 LLM 的任务统一经 LLM 调度器执行在线主线路和 CLI 备用线路；两条线路都失败时保留已完成阶段并让当前命令失败，不写入伪结果
- 确定性处理器只用于显式 `deterministic` 模式，不作为 LLM 请求失败后的静默替代

## 推荐执行顺序 / Recommended Flow

1. `doctor`：确认 Python、Git、依赖包、可选系统工具状态
2. `bootstrap`：安装 Python 依赖
3. `ingest`：更新 `source -> normalized -> structure_block -> evidence_block -> knowledge_unit -> claim / metadata -> page` 主证据链，并同步维护 chunk 检索容器
4. `lint`：检查状态一致性、页面索引、alias/canonical 风险
5. `query`：先查候选页，再决定是否继续回读 claim、knowledge_unit、evidence_block、chunk 和 source
6. `review-list / review-apply`：处理冲突、重复、近重复等高风险项

## 长时间任务执行约定 / Long-Running Task Rules

- 对 `ingest`、批量 `review-apply`、大范围 `lint`、重建索引、脚本迁移等可能持续较久的任务，Agent 应默认把脚本视为“正在正常处理”，不要因为短时间内看不到新输出就急于中断
- 只要脚本仍在运行且没有明确失败信号，Agent 不应主动打断；应优先等待阶段性输出、观察资源消耗变化，或仅向用户汇报当前仍在处理中
- 只有在出现明确证据时才考虑中止或改道，例如：进程已报错退出、连续较长时间完全无输出且无资源变化、用户明确要求停止、或继续运行会明显扩大数据不一致风险
- 若任务执行时间较长，Agent 应定期向用户报告进度，而不是通过频繁打断脚本来确认状态；默认每隔 60 秒同步一次，除非用户另有要求，或脚本刚输出了更有价值的阶段性结果
- 进度汇报应尽量使用外部可观察信息，例如已完成的阶段、最近一条日志、当前仍在运行的命令、下一步预计动作；在无法确认内部进度时，应明确说明“仍在处理，暂未看到新的阶段输出”
- 若任务可能修改 `normalized/`、`structure_blocks/`、`evidence_blocks/`、`knowledge_units/`、`chunks/`、`claims/`、`wiki/`、`indexes/`、`state/` 等衍生数据，Agent 应尽量避免在中间状态强制中止，以降低账本与索引不一致的风险

## 查询与读取约定 / Query and Reading Rules

- 先读页面摘要与字段命中解释，不直接把首条结果当最终答案
- 涉及证据、冲突、来源、引用时，必须回读 `reading_pack`
- 若 query 命中了 alias / canonical，应优先阅读其规范页面
- 若目标是给上层回答器准备输入，优先使用 `answer-query` 或 `query --answer-ready`
- 若 `reading_pack.answer_guardrails.can_answer_from_summary_only` 为 `false`，Agent 不应只根据页面摘要直接作答
- 回答前优先遵循 `reading_pack.answer_handoff.recommended_read_order`
- 若 `reading_pack.answer_guardrails.risk_flags` 非空，回答中必须显式表达不确定性或待确认点

## review / state 恢复约定 / Review and State Recovery

- review 处理前，先读取 `reviews/*.json` 与 `state/reviews.jsonl`
- 人工修改 Claim 时，优先改 `claims/*.json`，再执行 `review-apply ... edit_then_resume`
- 历史态 claim / review / page 不直接删除，保留追踪链
- 发现状态与页面不一致时，优先通过 `ingest`、`review-apply`、`lint` 收敛，而不是手改多份账本

## 写入边界 / Write Boundaries

- `raw/` 视为工作区外部且与工作区平级的原始资料区，不自动改写
- 若用户当前点名的目录里已经存在顶层 `raw/`，Agent 应把这个顶层 `raw/` 视为唯一默认资料源；不要再主动把同目录下的 `Clippings/`、其他顶层目录或零散文件并入同一次初始化/导入，除非用户明确要求合并这些来源
- `assets/` 视为与工作区平级的派生附件目录，不属于独立导入源；只有当 `normalized metadata` 明确回链到 `asset_path` 时，Agent 才按需读取对应附件
- 当用户已明确提供 `raw/` 路径，或当前工作区已经记录 sibling `raw/` 路径时，Agent 的默认文件检查范围也应限制在该 `raw/` 内；不要为了“确认导入范围”先枚举它的父目录、其他兄弟目录或整库内容
- 当用户还没有明确给出 `raw/` 路径时，Agent 也不要主动探测附近已有工作区、兄弟目录或父目录来替用户猜测来源；默认只基于用户当前点名的目录或当前工作区已有配置继续，并在需要改目录结构时先明确说明假设
- 自动写入主要落在 `normalized/`、`structure_blocks/`、`evidence_blocks/`、`knowledge_units/`、`chunks/`、`claims/`、`wiki/`、`indexes/`、`state/`
- 若需要修改工作区模板或状态规则，应优先改仓库源码和模板，再重新生成或重跑

## 当前已落地规则 / Current V1 Rules

- query 已支持 alias 扩展、canonical 命中回传、BM25 多字段打分
- concept page 聚合与 claim review 检测共用更稳的文本归一化思路
- lint 已覆盖结构检查、ID 唯一性、traceability、page/canonical/alias/index 基本一致性

## 后续可继续扩展 / Future Additions

- 页面更新策略
- Claim 与 source_refs 规则
- 更细的 Agent 读写预算控制
- 更完整的 Skill 调用约定
