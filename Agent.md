# MyAgentWiki Agent Core

本文件是 MyAgentWiki 的共享 Agent 规则核心源。

目标：

- 约束 Agent 如何在用户工程中执行 `init / ingest / query / lint`
- 明确 Python 脚本与大模型推理的职责边界
- 统一 Codex 与 Claude Code 的核心行为规则

后续会补充：

- 页面更新策略
- Claim 与 source_refs 规则
- review 队列处理规则
- 读取策略与写入边界
