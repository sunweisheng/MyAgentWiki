# 运行依赖说明

## 必需依赖

- Python `3.12+`
- `git`

## 可选增强依赖

这些工具不是 V1 主流程的前提条件，但可以提升特定格式的处理质量：

- `tesseract`
  - 用途：图片 OCR 增强
  - 缺失时：使用 Agent 视觉理解或保守降级

- `libreoffice`
  - 用途：Office 文档高保真转换
  - 缺失时：使用纯 Python 提取路径

- `pandoc`
  - 用途：富文本和多格式文档转换
  - 缺失时：走格式专用 Python 转换器

- `pdftotext`
  - 用途：PDF 文本提取增强
  - 缺失时：走纯 Python PDF 解析

## 当前 V1 转换器现状

- Markdown / 纯文本
  - 已支持，走纯 Python 标准化

- PDF
  - 已支持两条路径：`pypdf` 主路径 + 低依赖 fallback
  - 缺少 `pypdf` 时，至少会保留页数、可提取文本片段或占位信息
  - 复杂排版和扫描件当前仍可能降级为 `partial`

- Excel `.xlsx` / `.csv`
  - 已支持两条路径：`openpyxl` 主路径 + `zip+xml` 纯 Python fallback
  - 即使缺少 `openpyxl`，也能保守输出为 Markdown 表格和 sheet 结构

- Word `.docx`
  - 已支持两条路径：`python-docx` 主路径 + `zip+xml` 纯 Python fallback
  - 即使缺少 `python-docx`，也能保守提取标题、段落、表格主结构
  - 复杂样式、批注、图片锚点等高保真信息后续再增强

- 图片
  - 已支持元数据级标准化
  - 当前检测到 `tesseract` 时，会尝试本地 OCR 并把结果写入 normalized 文档
  - 无 OCR 或 OCR 失败时，会保留尺寸、格式、文件信息等元数据级占位文档
  - 更强的视觉理解和版面理解后续再增强

- 老格式 `.doc` / `.xls`
  - 当前已支持纯 Python 保守 fallback
  - 会优先提取可见文本片段、基础二进制元数据，并明确写出 `warnings`
  - 暂不保证版面、表格结构、批注、公式等高保真恢复，后续再增强

## 平台说明

V1 目标平台：

- Windows 11+
- macOS
- 主流 Linux 发行版

V1 原则：

- 核心流程不依赖外部办公软件才能运行
- 可选系统工具缺失时，`doctor` 需要明确提示并说明降级策略
- `bootstrap` 与文档示例应避免依赖 shell 专属语法，保证 Windows 可直接照做

## 当前推荐启动方式

Windows:

- `py -3.12 -m venv .venv`
- `.venv\\Scripts\\python -m pip install -U pip`
- `.venv\\Scripts\\python -m myagentwiki bootstrap --extra dev`

macOS / Linux:

- `python3.12 -m venv .venv`
- `.venv/bin/python -m pip install -U pip`
- `.venv/bin/python -m myagentwiki bootstrap --extra dev`

## 工作流验证脚本

仓库当前已提供：

- [scripts/validate_workflow.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/scripts/validate_workflow.py)

用途：

- 用最小样例跑通 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
- 验证递归扫描 `raw/` 子目录
- 为 Windows / macOS / Linux 提供统一的 CLI 烟雾测试入口

说明：

- 当前脚本本身是跨平台的
- 但本仓库当前轮开发是在非 Windows 环境完成，因此 Windows 侧属于“脚本与命令路径已适配、待真实机器补充实跑确认”
