# 常见问题与排障 / Troubleshooting

本文面向第一次使用 MyAgentWiki 的用户与 Agent。

## 1. `doctor` 提示 Python 版本不满足

现象：

- `doctor` 报告 Python 低于 `3.12`

处理：

- Windows：`py -3.12 -m venv .venv`
- macOS / Linux：`python3.12 -m venv .venv`

说明：

- 当前运行基线是 `Python 3.12+`
- 这样可以兼顾 MarkItDown 及其 DOCX、XLSX、PPTX、PDF 依赖与 Windows 兼容性

## 2. `bootstrap` 安装依赖失败

现象：

- `python3 -m myagentwiki bootstrap` 返回非 0

先检查：

- `python -m pip --version`
- 网络是否可访问 Python 包源
- 是否在虚拟环境中执行

建议顺序：

1. 先运行 `python -m pip install -U pip`
2. 再运行 `python3 -m myagentwiki bootstrap --extra dev`
3. 如仍失败，直接执行 `python -m pip install -e ".[dev]"`

## 3. `ingest` 后没有生成太多内容

常见原因：

- sibling `raw/` 中资料过少
- 原始文件大多是扫描件或图片，OCR 工具未安装
- 文档提取质量为 `poor` 或 `failed`

优先检查：

- `state/error_log.jsonl`
- `state/normalized.jsonl`
- `normalized/*.md`

说明：

- 当前实现会优先保守落地中间产物，不会为了“看起来有结果”而伪造高质量文本

## 4. 图片没有 OCR 文本

现象：

- `normalized` 里只有图片尺寸、格式等元数据

原因：

- 当前环境未安装 `tesseract`
- 图片本身质量较低
- 独立 `raw/` 图片当前没有接入 LLM 图片理解
- 对 Markdown 内嵌图片，`automation.image_to_text` 被设为 `disabled`，图片理解主备线路失败，或结果为空、低置信度、没有通过业务检查

处理：

- 安装 `tesseract`
- 独立图片需要 LLM 识别时，先把图片作为 Markdown 内嵌图片纳入来源，或等待独立图片链路接入该任务
- 对 Markdown 内嵌图片，检查 `config/project.yml` 中的 `automation.image_to_text`；需要使用 LLM 时再检查 `logs/llm_requests.jsonl` 和主备线路配置
- 重新运行 `ingest`

说明：

- 独立 `raw/` 图片在 OCR 不可用或结果不足时保留元数据级 normalized 文档
- Markdown 内嵌图片会先按配置尝试图片理解；仍没有可靠文本时保留原 Markdown 正文、图片占位和告警

## 5. `.doc` 或 `.xls` 转换效果一般

说明：

- 当前实现会先调用 MarkItDown；只有失败时才采用纯 Python 保守 fallback
- 目标是先保留可读文本片段与基础容器信息
- 不保证复杂表格、版面、公式和批注高保真恢复

建议：

- 有条件时优先把老格式转换成 `.docx` / `.xlsx`

## 6. 出现 `markitdown_conversion_failed` 告警

说明：

- MarkItDown 没有成功转换该文件，系统已经尝试旧转换器或生成占位文档
- 具体错误类型记录在 `state/error_log.jsonl` 和 `state/normalized.jsonl` 的 `warnings / location_map.markitdown` 中

处理：

1. 运行 `python3 -m myagentwiki doctor`，确认 MarkItDown 及文档格式依赖完整。
2. 重新执行 `python -m pip install -e .` 修复依赖。
3. 检查原文件是否损坏、加密或使用 MarkItDown 暂不支持的老格式。

## 7. `query` 没有命中结果

先检查：

- 是否已经运行过 `ingest`
- 是否已经运行过 `lint`
- `indexes/search_pages.jsonl` 是否存在
- 查询词是否更适合用规范名、别名或更短关键词

建议：

1. 先试短查询词
2. 再试“什么是 X”“X 的来源证据”这类意图更明确的问法
3. 查看 `indexes/aliases.json` 是否已有对应 alias / canonical
4. 如果你已经命中到正确页面，但还想一次拿到更完整的 Claim / Chunk / 来源路径，改用 `--reading-depth deep`

## 8. 出现 alias conflict review

现象：

- `review-list` 中看到 `kind=alias_conflict`

说明：

- 这表示同一个 alias 当前映射到了多个规范页面

可用动作：

- `assign_alias`
- `remove_alias`
- `keep_both`
- `edit_then_resume`

建议：

- 如果 alias 应只属于某个页面，优先使用 `assign_alias`
- 如果 alias 本身不应存在，使用 `remove_alias`

## 8. review 处理后又感觉状态不一致

先做这几步：

1. 重新运行 `review-list`
2. 再运行 `lint --target-dir ...`
3. 必要时重新运行 `ingest --target-dir ...`

说明：

- 当前实现的权威账本是 `state/*.jsonl`
- 单文件 `claims/*.json` 与 `reviews/*.json` 是便于人工查看与编辑的展开形式

如果你看到的是这类现象：

- 刚处理完一轮 review，`lint` 里的 warning 数量虽然下降了，但又冒出新的 `page_semantic_consistency`
- 某组内容刚从 `concept` 改到 `guide / duty / example / reference / timeline`，下一轮又像是被系统拉回旧页型
- 没有新增 source 文件，但重新跑一次 `ingest` 后页面家族仍发生了变化

优先这样判断：

1. 先看 `state/claims.jsonl` 里对应 claim 的 `knowledge_role`、`page_intent_hints`、`concept_candidate_score` 是否刚被改写
2. 再看 `state/pages.jsonl` 里同一组内容是否还残留旧的自动页面记录，或是否已正确切换到新的 `guide/duty/example/topic/reference/timeline`
3. 最后再跑一次 `lint --target-dir ...`，确认剩下的是“知识语义仍待选择”，还是“页面记录没有正确收口”

怎么理解：

- 如果 `knowledge_role` 已经变成 `procedure / example`，而 `page_semantic_consistency` 还在抱怨某个 live `concept` 页，通常说明你面对的是“页面路由或页面生命周期收口没有完全收口”，而不只是内容本身有歧义
- 如果同一组内容同时挂着多个 live 自动页，应优先把它理解为页面生命周期没有完全收口，而不是预期中的长期并行结构
- 如果不再需要的自动页面已经退场，只剩 `guide / example / reference` 之类的新页型，但 `lint` 仍提示 warning，那么更可能是这组 claim 本身确实处在语义灰区，需要继续调整 claim 状态、角色或页面归属
- 如果没有新 source，但 claim 的语义字段变了，重新跑 `ingest` 后页面变化是正常的；当前系统会把这种“语义账本变化”也视作上游变化，而不是简单跳过
- 如果看到 `claim_semantic_risk_flags_reviewed`，表示语义决策账本中的某些 claim 带有 `ambiguous` 风险标记；这不是 ingest 失败，而是在提醒对应语义判断仍需复核。确定性处理器不再因单个中文关键词自动写入旧的 `ambiguous_case_keyword / ambiguous_reference_keyword / ambiguous_timeline_keyword / ambiguous_howto_keyword`
- 如果看到 `semantic_page_intent_brakes_reviewed`，通常表示某个 specialized page intent 因组级证据不足被降级；优先检查 `state/pages.jsonl` 的 `page_route.route_reason` 和对应 `state/semantic_decisions.jsonl`，不要直接手改 wiki 页面

建议：

- 先把它当成“收口链是否统一”的问题，而不是急着手工改多份页面或索引文件
- 优先重跑 `ingest` 或 `review-auto` 让统一链路收敛
- 只有在确认剩下的是知识语义选择问题时，才继续改 claim 的角色、状态或页面归属

## 9. Windows 下命令路径不一样

常用命令写法：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\python -m myagentwiki doctor
.venv\Scripts\python -m myagentwiki bootstrap --extra dev
```

说明：

- CLI 内部尽量使用 Python 标准库与跨平台子进程调用
- 不依赖 `bash`、`zsh` 或 POSIX 专属语法

## 10. 如何确认一套流程真的能跑通

推荐：

- 运行 [scripts/validate_workflow.py](../scripts/validate_workflow.py)
- 再运行测试目录中的 E2E 回归

当前边界：

- 我们可以在仓库里提供跨平台脚本与 Windows 验证清单
- 但当前仓库内无法直接在真实 Windows 环境上执行验证

## 11. `Workspace schema guard failed`

现象：

- `query`、`ingest`、`lint`、`review-apply` 等写链路或读链路命令直接报 schema guard

处理：

- 确认工作区来自当前版本的 `init` 模板
- 按错误提示补齐或迁移 `config/project.yml`，不要直接跳过检查改写账本

## 12. `llm_request_failed`

含义：

- 在线主线路和 Codex CLI 备用线路都没有得到通过合同检查的结果
- 当前命令会返回非零状态，不写空决策，也不会自动切换到确定性处理器
- 已经完成并落盘的前序阶段仍然保留，可以修复线路后按现有状态恢复机制重跑

优先检查：

1. 查看 `logs/llm_requests.jsonl` 中对应 `request_id` 的线路、尝试次数、错误类型和 HTTP 状态。该日志不包含 API Key、完整正文、图片内容或完整原始输出。
2. 如在线线路报配置错误，检查工作区私有的 `.env`；不要输出或提交其中的 API Key。
3. 如在线线路报 403、404 等不可重试错误，它只会请求一次并立即切到 CLI，这属于预期行为。
4. 如在线线路报 429、5xx、超时或结果合同错误，它最多执行三次，然后切到 CLI。
5. 检查 `codex` 是否可执行、是否已登录；必要时核对 `MYAGENTWIKI_CODEX_BIN`、`MYAGENTWIKI_CODEX_MODEL`、`MYAGENTWIKI_CODEX_TIMEOUT_SECONDS`。

可用调试命令：

```bash
python3 scripts/debug_llm_routing.py contract --task claim_role
python3 scripts/debug_llm_routing.py simulate --scenario http_404_to_cli
python3 scripts/debug_llm_routing.py live --workspace /path/to/workspace --task claim_role --payload-file /path/to/payload.json
```

需要完全离线运行时，应在对应任务配置中显式使用 `deterministic`。不要把它当成线路失败后的自动降级。

## 13. `llm_configuration_migration_required`

这表示旧工作区仍在任务下配置 Python `command`。当前版本不执行任务级命令，也不会猜测自定义集成的意图。按错误中的一一对应建议删除旧字段，选择 `llm_assisted` 或 `deterministic`，再重跑原命令。

## 14. 如何查看一次命令的完整运行过程

在需要排查的工作区业务命令上添加 `--debug`：

```bash
python3 -m myagentwiki ingest --target-dir /path/to/workspace --debug
python3 -m myagentwiki query "问题" --target-dir /path/to/workspace --debug
```

命令结果里的 `debug_run.report_path` 指向本次报告。也可以继续查看：

```bash
python3 -m myagentwiki debug-list --target-dir /path/to/workspace
python3 -m myagentwiki debug-show --target-dir /path/to/workspace --run-id latest
python3 -m myagentwiki debug-show --target-dir /path/to/workspace --run-id latest --step-id <step_id> --json
python3 -m myagentwiki debug-show --target-dir /path/to/workspace --run-id latest --request-id <request_id> --json
```

`logs/debug/<run_id>/` 会保存步骤、数据关系、完整文本与 JSON 快照、每次 LLM 尝试和脚本统计报告。它可能包含原始资料内容，不应提交或直接对外发送。默认保留 7 天；下次调试运行或查看命令启动时会清理已到期记录。
