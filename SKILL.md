---
name: myagentwiki
description: Use this skill when working inside a MyAgentWiki workspace, or when the user wants to initialize, ingest, query, lint, review, or maintain a local LLM Wiki driven by Codex or Claude Code. It provides the CLI-first workflow, traceability rules, review handling rules, and reading strategy for wiki pages, claims, knowledge units, evidence blocks, chunks, and sources.
---

# MyAgentWiki Skill

本 Skill 用于让 Agent 在 `MyAgentWiki` 仓库或用户工作区里，按统一规则执行知识库初始化、资料导入、检索、审核和状态恢复。

## 什么时候使用 / When To Use

出现以下情况时应使用本 Skill：

- 用户要初始化新的 MyAgentWiki 知识库工作区
- 用户要执行 `doctor / bootstrap / ingest / query / lint`
- 用户要处理 `review-list / review-apply`
- 用户要追踪 `page -> claim -> knowledge_unit -> evidence_block -> source` 主证据链，或需要按需回读匹配 chunk 补上下文
- 用户要在 Codex 或 Claude Code 中把原始知识目录整理成可维护的本地 Wiki

## 核心规则 / Core Rules

先读根目录的 [Agent.md](Agent.md)。

额外要求：

- 固定流程优先走 CLI，不直接批量改写 `state/*.jsonl`
- 用户明确说“用调试模式运行……”时，为对应工作区业务命令添加 `--debug`，并用 `debug-list / debug-show` 查看步骤、数据流、快照和 LLM 请求；不要给 `init / doctor / bootstrap` 添加该参数
- `raw/` 视为原始资料区，不自动改写
- 已实现的 LLM 任务默认由调度器先请求在线客户端，在线配置缺失或请求失败时自动改用 Codex CLI 客户端
- 两条线路都失败时当前命令应失败，不返回空结果，也不调用确定性处理器掩盖错误；已完成阶段按现有状态恢复机制保留
- 在线模型配置只保存在 MyAgentWiki Skill 根目录的 `.env`，不应提交到 Git；用户工作区不保存这份配置，缺失时允许直接尝试 CLI 备用线路
- 完全离线执行时，应在任务配置或本地测试环境中显式选择 `deterministic`
- 若用户当前点名的目录里已经存在顶层 `raw/`，默认就把这个顶层 `raw/` 当作唯一资料源；不要再主动把同目录下的 `Clippings/`、其他顶层目录或零散文件并入同一次初始化/导入，除非用户明确要求合并
- 若用户已明确给出 `raw/` 路径，初始化或导入前的默认检查范围也应限制在该 `raw/` 内；不要为了确认导入范围先读取它的父目录、其他兄弟目录或整库内容，除非用户明确要求扩大发现范围
- 若用户还没有明确给出 `raw/` 路径，也不要主动探测附近已有工作区、兄弟目录或父目录来替用户猜测来源；默认只围绕用户当前点名的目录继续，必须改目录结构时先明确说明假设
- 需要证据、来源、冲突判断时，必须回读 `reading_pack`
- 人工修改 claim 后，使用 `review-apply ... edit_then_resume` 恢复流程
- 历史态 claim / review / page 保留追踪链，不直接删除

## 标准工作流 / Standard Flow

1. 先执行 `python3 -m myagentwiki doctor`
2. 再执行 `python3 -m myagentwiki bootstrap`
3. 初始化工作区时执行 `python3 -m myagentwiki init --source-dir ... --project-name ...`
4. 更新资料后执行 `python3 -m myagentwiki ingest --target-dir ...`
5. 用 `python3 -m myagentwiki lint --target-dir ...` 检查一致性
6. 用 `python3 -m myagentwiki query "问题" --target-dir ...` 做首轮检索
7. 如果有冲突或别名问题，执行 `review-list` 与 `review-apply`

## 查询与阅读 / Query And Reading

- 先读候选页面、命中字段、排序解释
- 再看 `reading_pack.claims`
- 需要证据时继续读 `reading_pack.claims` 里的 `knowledge_unit_ids / evidence_block_ids / source_refs`，并按需读取 `reading_pack.matched_chunks` 与 `reading_pack.timeline_sources` 补足上下文
- 涉及 alias / canonical 命中时，优先阅读规范页面
- 若目标是把结果直接交给上层回答器，优先使用 `answer-query` 或 `query --answer-ready`
- 若 `reading_pack.answer_guardrails.can_answer_from_summary_only` 为 `false`，不要只停在摘要层
- 回答前优先按 `reading_pack.answer_handoff.recommended_read_order` 消费上下文
- 若 `reading_pack.answer_guardrails.risk_flags` 非空，回答里应带上不确定性或待确认提示

## 参考文件 / References

按需再读这些文件：

- [README.md](README.md)：项目介绍、安装与使用说明
- [MyAgentWiki系统详细设计.md](docs/MyAgentWiki系统详细设计.md)：详细设计与当前实现边界
- [docs/runtime-deps.md](docs/runtime-deps.md)：依赖与跨平台说明
- [docs/troubleshooting.md](docs/troubleshooting.md)：常见故障排查
- [docs/调试模式与全链路追踪设计.md](docs/调试模式与全链路追踪设计.md)：调试目录、记录格式、查看命令与安全边界
