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
  - 覆盖 `raw/` 子目录递归扫描与 alias conflict 处理收口
