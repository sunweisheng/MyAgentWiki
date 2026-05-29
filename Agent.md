# MyAgentWiki Agent Core

本文件是 MyAgentWiki 的共享 Agent 规则核心源。

## 目标 / Goals

- 约束 Agent 如何在用户工程中执行 `init / ingest / query / lint`
- 明确 Python 脚本与大模型推理的职责边界
- 统一 Codex 与 Claude Code 的核心行为规则

## 职责边界 / Responsibility Boundary

- 脚本优先负责：格式转换、状态落盘、索引构建、可重复执行的固定流程
- Agent 优先负责：语义抽取增强、冲突判断、页面改写、人工审核辅助
- Agent 不应绕过 CLI 直接批量改写 `state/*.jsonl`，除非是在修复脚本本身

## 推荐执行顺序 / Recommended Flow

1. `doctor`：确认 Python、Git、依赖包、可选系统工具状态
2. `bootstrap`：安装 Python 依赖
3. `ingest`：更新 `raw -> normalized -> chunks -> claims -> wiki`
4. `lint`：检查状态一致性、页面索引、alias/canonical 风险
5. `query`：先查候选页，再决定是否继续回读 claim/chunk/source
6. `review-list / review-apply`：处理冲突、重复、近重复等高风险项

## 查询与读取约定 / Query and Reading Rules

- 先读页面摘要与字段命中解释，不直接把首条结果当最终答案
- 涉及证据、冲突、来源、引用时，必须回读 `reading_pack`
- 若 query 命中了 alias / canonical，应优先阅读其规范页面

## review / state 恢复约定 / Review and State Recovery

- review 处理前，先读取 `reviews/*.json` 与 `state/reviews.jsonl`
- 人工修改 Claim 时，优先改 `claims/*.json`，再执行 `review-apply ... edit_then_resume`
- 历史态 claim / review / page 不直接删除，保留追踪链
- 发现状态与页面不一致时，优先通过 `ingest`、`review-apply`、`lint` 收敛，而不是手改多份账本

## 写入边界 / Write Boundaries

- `raw/` 视为原始资料区，不自动改写
- 自动写入主要落在 `normalized/`、`chunks/`、`claims/`、`wiki/`、`indexes/`、`state/`
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
