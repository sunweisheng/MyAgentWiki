# MyAgentWiki CLAUDE Entry

本文件是面向 Claude Code 的入口规则文件。

共享核心规则请参考：

- `Agent.md`

## Claude Code 适配层 / Claude Code Adapter

- 优先使用 `python -m myagentwiki ...` 或 `myagentwiki ...` 执行固定流程
- 在 review / state 恢复场景里，先读当前工作区的 `state/*.jsonl` 与 `reviews/*.json`
- 不直接跳过 CLI 去批量改写账本文件

## 用户工程初始化约定 / Workspace Initialization

- `init` 后默认生成 `AGENTS.md`、`CLAUDE.md`、`config/project.yml`、`indexes/aliases.json`
- 新工作区应默认带 Git 基线提交
- `raw/` 应放在工作区外部并与工作区平级；若已存在则复用，不存在则创建空目录
- `raw/` 允许包含子目录，Agent 不应假定原始资料是扁平结构

## review / state 恢复约定 / Review and State Recovery

- `merge / archive_one / keep_both / edit_then_resume` 统一通过 `review-apply`
- 人工改 claim 后恢复流程，使用 `edit_then_resume`
- 需要解释查询结果时，优先使用 `query` 的 `reading_pack`
- 若目标是给上层回答器准备输入，优先使用 `answer-query` 或 `query --answer-ready`
- 若 `reading_pack.answer_guardrails.can_answer_from_summary_only` 为 `false`，不要只根据页面摘要直接作答
- 回答前优先遵循 `reading_pack.answer_handoff.recommended_read_order`
- 若 `reading_pack.answer_guardrails.risk_flags` 非空，回答中必须显式表达不确定性或待确认点

## 当前状态 / Current Status

- 本入口文件只补 Claude Code 适配层，不重复定义共享核心规则
- 权威规则源仍然是 `Agent.md`

Claude Code 适配层后续可继续补充：

- 命令调用约定
- 更细的状态恢复脚手架
