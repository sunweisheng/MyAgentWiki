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
