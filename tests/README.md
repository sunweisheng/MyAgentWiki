# 测试目录说明

本目录用于存放：

- CLI 行为测试
- 标准化层测试
- 路径与跨平台兼容测试
- 状态恢复与 lint 规则测试

当前已落地：

- `test_review_apply.py`
  - review 的 `merge / keep_both / edit_then_resume` 回归测试
- `test_normalizers.py`
  - `.doc / .xls` 老格式 fallback 与图片 OCR / 非 OCR 标准化测试
- `test_claim_extraction.py`
  - 中文 claim 切分、去噪、长句拆分测试
- `test_review_detection.py`
  - 近重复 / 冲突候选召回与误报边界测试
- `test_query_alias_and_lint.py`
  - query alias/canonical 扩展、alias index 初始化、lint 报告写回测试
- `test_e2e_workflow.py`
  - `init -> ingest -> query -> review -> lint` 主闭环 E2E 测试
  - 覆盖 sibling `raw/` 子目录递归扫描与 alias conflict 处理收口
- `test_user_workspace_lab.py`
  - 用户工程测试实验场回归测试
  - 覆盖 `tests/fixtures/user_project_lab/` 定义与 `scripts/run_user_workspace_lab.py` 本地运行入口
  - 覆盖基线主链路、原始资料更新 / 新增、Markdown 表格与本地图片混排、页面关联扩展读取

## 用户工程实验场

仓库内新增两层结构：

- `tests/fixtures/user_project_lab/`
  - 只提交测试定义，如样本 manifest 和实验场说明
- `tests/runtime/`
  - 只保留本地运行结果，通过 `.gitignore` 排除，不提交到 Git

推荐运行方式：

```bash
python3 scripts/run_user_workspace_lab.py --clean --scenario baseline
python3 scripts/run_user_workspace_lab.py --clean --scenario update_raw
```

默认会在本地生成完整：

- `raw/`
- `assets/`
- `workspace/`
- `reports/`

这样可以直接人工检查派生数据、页面结果、查询输出和 lint 报告，同时避免把重复运行产生的大量测试数据写进 Git 历史。
