# MyAgentWiki AGENTS Entry

本文件是面向 Codex 的入口规则文件。

共享核心规则请参考：

- `Agent.md`

## Codex 适配层 / Codex Adapter

- 优先使用 `python3 -m myagentwiki ...` 或 `myagentwiki ...` 执行固定流程
- 在 review / state 恢复场景里，先读当前工作区的 `state/*.jsonl` 与 `reviews/*.json`
- 不直接跳过 CLI 去批量改写账本文件
- 用户通常只需要表达目标，不需要主动描述 `reading_pack`、`state/*.jsonl`、`review-apply` 这类内部结构
- 已实现的增强任务默认由 LLM 调度器先请求在线客户端，在线配置缺失或请求失败时自动改用 Codex CLI 客户端；两条线路都失败时当前命令失败，不用确定性结果掩盖错误
- 在线模型配置只保存在当前工作区的 `.env`，不应提交到 Git；没有该文件时允许直接尝试 CLI 备用线路
- 完全不请求 LLM 时，必须在任务配置或本地测试环境中显式选择 `deterministic`
- 查询时，Agent 应自动完成“先看候选页面，再按需回读证据，有风险就明确提示不确定性”的流程
- 审核时，Agent 应先整理问题、风险和建议，再用白话向用户解释可选处理方式
- 遇到长时间运行的脚本时，Codex 不要因为暂时没有新输出就随意中断；优先等待脚本继续推进，并以阶段性进度汇报代替打断
- 若脚本仍在运行，默认每隔 60 秒向用户简短同步一次现状即可；只有看到明确失败、明显卡死，或用户要求停止时，才考虑中止
- 涉及 `normalized/`、`structure_blocks/`、`evidence_blocks/`、`knowledge_units/`、`chunks/`、`claims/`、`wiki/`、`indexes/`、`state/` 的生成或收敛流程时，更要避免中途强制打断，以降低数据不一致风险

## 用户工程初始化约定 / Workspace Initialization

- `init` 后默认生成 `AGENTS.md`、`config/project.yml`、`indexes/aliases.json`
- 新工作区应默认带 Git 基线提交
- `raw/` 应放在工作区外部并与工作区平级；若已存在则复用，不存在则创建空目录
- `raw/` 允许包含子目录，Agent 不应假定原始资料是扁平结构
- 若用户当前点名的目录里已经存在顶层 `raw/`，默认就把这个顶层 `raw/` 当作唯一资料源；不要再主动把同目录下的 `Clippings/`、其他顶层目录或零散文件并入同一次初始化/导入，除非用户明确要求合并
- `assets/` 应保留为与工作区平级的 sibling 派生附件目录，不属于独立导入源；只有当 `normalized metadata` 明确回链到 `asset_path` 时，Agent 才按需读取对应附件
- 若用户已明确给出 `raw/` 路径，初始化前的检查默认只看该 `raw/` 本身；不要为了确认范围先读取其父目录、其他兄弟目录或整库内容，除非用户明确要求扩大发现范围
- 若用户还没明确给出 `raw/` 路径，也不要主动去探测附近已有工作区、兄弟目录或父目录来替用户猜测来源；默认只围绕用户当前点名的目录继续，必须改目录结构时先明确说明假设

## review / state 恢复约定 / Review and State Recovery

- `merge / archive_one / keep_both / edit_then_resume` 统一通过 `review-apply`
- 若目标是让 Agent 先自动处理高把握审核项，再把剩余需要人判断的部分整理成可继续对话的输入，优先使用 `review-auto`
- 对用户解释时优先用白话：
  - `merge` = 把两条看作同一件事，合并成一条更清楚的结论
  - `keep_both` = 两条都保留，因为它们虽然相似但不应强行合并
  - `archive_one` = 保留更准确的一条，把另一条归档
  - `edit_then_resume` = 用户先手工修改 claim，Agent 再继续把审核流程收口
- 人工改 claim 后恢复流程，使用 `edit_then_resume`
- 需要解释查询结果时，优先使用 `query` 的 `reading_pack`
- 若目标是给上层回答器准备输入，优先使用 `answer-query` 或 `query --answer-ready`
- 若目标是给上层 Agent 准备“审核自动处理 + 剩余人工判断”的输入，优先使用 `review-auto --format prompt|messages|chatml`
- 若 `reading_pack.answer_guardrails.can_answer_from_summary_only` 为 `false`，不要只根据页面摘要直接作答
- 回答前优先遵循 `reading_pack.answer_handoff.recommended_read_order`
- 若 `reading_pack.answer_guardrails.risk_flags` 非空，回答中必须显式表达不确定性或待确认点
- 若 `review-auto` 的 `agent_brief.should_ask_user` 为 `true`，应只追问 `escalation_handoff` 中列出的审核项，并用白话解释 `choice_options`

## 当前状态 / Current Status

- 本入口文件只补 Codex 适配层，不重复定义共享核心规则
- 权威规则源仍然是 `Agent.md`

Codex 适配层后续可继续补充：

- 命令调用约定
- 更细的状态恢复脚手架
