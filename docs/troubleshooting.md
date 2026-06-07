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

常见原因：

- `config/project.yml` 里的 `workspace.schema_version` 缺失
- 工作区是旧版本或未显式标注版本的老工作区
- 工作区版本高于当前 CLI 已知 schema registry

建议顺序：

1. 先运行 `python3 -m myagentwiki compat-report --target-dir ...`
2. 如果只想看完整迁移计划，再运行 `python3 -m myagentwiki migrate --target-dir ...`
3. 若 schema path 提示需要确认，再使用 `python3 -m myagentwiki migrate-schema-confirm --confirm ...`
4. 若确实要执行迁移，再使用 `python3 -m myagentwiki migrate --apply --target-dir ...`

说明：

- 当前 CLI 不会在 schema guard 失败时静默继续写入
- 这不是“命令坏了”，而是为了避免在未知或过旧工作区上直接改账本

## 12. `compat-report` / `migrate` 里看到 `schema_transition_not_registered`

含义：

- 目标 schema 版本是已知的
- 但当前 transition graph 里还没有从现有版本到目标版本的已注册路径

建议：

- 先不要手工改 `state/*.jsonl`
- 回到当前 CLI 已支持的 schema 目标，或等待后续版本补正式 transition

## 13. `compat-report` / `migrate` 里看到 `inspect_target_workspace_schema_version`

含义：

- 你指定的 `--to-schema-version` 根本不在当前已知 schema registry 中

建议：

- 先确认目标版本名是否写对
- 如果这是未来准备中的版本，不要把它当成当前 CLI 已支持的可规划目标

说明：

- 当前系统会区分“目标版本未知”和“目标版本已知但 path 未注册”这两种灰区

## 14. 迁移后想撤回

做法：

- 先查看最近一次迁移是否已经生成 backup snapshot
- 然后运行 `python3 -m myagentwiki migrate --rollback --target-dir ...`

说明：

- 当前 rollback 主要恢复关键状态文件、配置与迁移前备份内容
- 它是最小恢复骨架，不等于通用跨版本回滚系统
