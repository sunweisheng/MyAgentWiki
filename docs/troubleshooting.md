# 常见问题与排障 / Troubleshooting

本文面向第一次使用 MyAgentWiki 的用户与 Agent。

## 1. `doctor` 提示 Python 版本不满足

现象：

- `doctor` 报告 Python 低于 `3.12`

处理：

- Windows：`py -3.12 -m venv .venv`
- macOS / Linux：`python3.12 -m venv .venv`

说明：

- 当前 V1 基线是 `Python 3.12+`
- 这样可以兼顾 `.docx` / `.xlsx` / `pypdf` 依赖稳定性与 Windows 兼容性

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

- V1 会优先保守落地中间产物，不会为了“看起来有结果”而伪造高质量文本

## 4. 图片没有 OCR 文本

现象：

- `normalized` 里只有图片尺寸、格式等元数据

原因：

- 当前环境未安装 `tesseract`
- 图片本身质量较低

处理：

- 安装 `tesseract`
- 重新运行 `ingest`

说明：

- 没有 OCR 时系统仍会保留图片占位 normalized 文档
- 后续可由 Agent 补充视觉理解

## 5. `.doc` 或 `.xls` 转换效果一般

说明：

- 当前 V1 对 `.doc` / `.xls` 采用纯 Python 保守 fallback
- 目标是先保留可读文本片段与基础容器信息
- 不保证复杂表格、版面、公式和批注高保真恢复

建议：

- 有条件时优先把老格式转换成 `.docx` / `.xlsx`
- 或安装 `libreoffice` 作为后续增强路径

## 6. `query` 没有命中结果

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

## 7. 出现 alias conflict review

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

- V1 的权威账本是 `state/*.jsonl`
- 单文件 `claims/*.json` 与 `reviews/*.json` 是便于人工查看与编辑的展开形式

如果你看到的是这类现象：

- 刚处理完一轮 review，`lint` 里的 warning 数量虽然下降了，但又冒出新的 `page_semantic_consistency`
- 某组内容刚从 `concept` 改到 `guide / example / reference / timeline`，下一轮又像是被系统拉回旧页型
- 没有新增 source 文件，但重新跑一次 `ingest` 后页面家族仍发生了变化

优先这样判断：

1. 先看 `state/claims.jsonl` 里对应 claim 的 `knowledge_role`、`page_intent_hints`、`concept_candidate_score` 是否刚被改写
2. 再看 `state/pages.jsonl` 里同一组内容是否还残留旧的自动页面记录，或是否已正确切换到新的 `guide/example/topic/reference/timeline`
3. 最后再跑一次 `lint --target-dir ...`，确认剩下的是“知识语义仍待选择”，还是“页面记录没有正确收口”

怎么理解：

- 如果 `knowledge_role` 已经变成 `procedure / example`，而 `page_semantic_consistency` 还在抱怨某个 live `concept` 页，通常说明你面对的是“页面路由或页面生命周期收口没有完全收口”，而不只是内容本身有歧义
- 如果同一组内容同时挂着多个 live 自动页，应优先把它理解为页面生命周期没有完全收口，而不是预期中的长期并行结构
- 如果不再需要的自动页面已经退场，只剩 `guide / example / reference` 之类的新页型，但 `lint` 仍提示 warning，那么更可能是这组 claim 本身确实处在语义灰区，需要继续调整 claim 状态、角色或页面归属
- 如果没有新 source，但 claim 的语义字段变了，重新跑 `ingest` 后页面变化是正常的；当前系统会把这种“语义账本变化”也视作上游变化，而不是简单跳过
- 如果看到 `claim_semantic_risk_flags_reviewed`，通常表示某些 claim 命中了 `ambiguous_case_keyword / ambiguous_reference_keyword / ambiguous_timeline_keyword / ambiguous_howto_keyword` 等保守风险标记；这不是 ingest 失败，而是在提醒“局部中文关键词不足以自动决定语义角色”
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
