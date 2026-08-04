# 运行依赖说明

## 必需依赖

- Python `3.12+`
- `git`
- `markitdown[docx,pdf,pptx,xls,xlsx,outlook]>=0.1.6,<0.2.0`
- 项目声明的其他 Python 包，包括 MarkItDown 文档格式依赖、`pillow`、`openai`、`json-repair>=0.61.7,<1` 与 `jsonschema>=4.23,<5`

这些 Python 包由 `pip install -e .` 或 `pip install -e ".[dev]"` 统一安装。`json-repair` 用于修复 Function Calling 参数中的常见 JSON 语法问题，`jsonschema` 使用合同中的同一份 Schema 做正式校验；即使当前工作区显式使用确定性处理器，`doctor` 仍会按 `config/runtime_manifest.yml` 检查完整项目依赖。

## 可选增强依赖

这个工具不是当前文档转换主流程的前提条件，只用于增强图片文字提取：

- `tesseract`
  - 用途：图片 OCR 增强
  - 缺失时：独立 `raw/` 图片保留元数据占位；Markdown 内嵌图片按配置尝试 LLM 图片理解，失败后保守降级

## 当前转换器现状

- Markdown / 纯文本
  - 保留 MyAgentWiki 专用标准化，负责远程图片下载、附件回链和换行整理

- 统一文档转换
  - PDF、DOCX、XLS/XLSX、CSV、PPTX、HTML、JSON/XML、ZIP、EPUB、IPYNB、Outlook MSG 等格式默认使用 MarkItDown
  - 调用范围限制为本地文件 `convert_local()`，MarkItDown 插件默认关闭
  - 当前只安装文档相关 extras，不安装 Azure、音频转写或 YouTube 依赖
  - 转换成功时记录 `extraction_method=markitdown`、转换器版本和行号范围
  - 后续 `ingest` 会核对标准化器版本和 MarkItDown 版本；版本变化时自动重新处理旧结果，不要求手工重建工作区

- 转换失败
  - MarkItDown 抛错或返回空内容时，现有 PDF、Word、Excel 转换器作为备用路径
  - `warnings` 会记录 `markitdown_conversion_failed:<错误类型>`，不会把备用结果伪装成 MarkItDown 成功
  - 不支持的格式会生成 `poor` 或 `failed` 占位文档，并进入错误记录

- 图片
  - 已支持元数据级标准化
  - 当前检测到 `tesseract` 时，会尝试本地 OCR 并把结果写入 normalized 文档
  - 独立 `raw/` 图片当前不调用图片理解；OCR 没有可靠文本时只保留尺寸、格式、文件信息等元数据级占位文档
  - Markdown 内嵌图片会携带工作区上下文；OCR 不可用、失败、为空或信号较弱时，按 `automation.image_to_text` 配置尝试图片理解
  - 内嵌图片仍没有可靠文本或单图片处理失败时，保留 Markdown 正文、图片占位和告警
  - 复杂版面、高保真位置框和更细的视觉结构理解仍待后续增强

- 老格式 `.doc` / `.xls`
  - 默认先尝试 MarkItDown
  - 转换失败时使用现有纯 Python 保守 fallback，提取可见文本片段和基础二进制元数据
  - 暂不保证版面、表格结构、批注、公式等高保真恢复，后续再增强

## 平台说明

目标平台：

- Windows 11+
- macOS
- 主流 Linux 发行版

当前原则：

- 核心流程不依赖外部办公软件才能运行
- 可选系统工具缺失时，`doctor` 需要明确提示并说明降级策略
- `bootstrap` 与文档示例应避免依赖 shell 专属语法，保证 Windows 可直接照做

## 当前推荐启动方式

Windows:

- `py -3.12 -m venv .venv`
- `.venv\\Scripts\\python -m pip install -U pip`
- `.venv\\Scripts\\python -m pip install -e ".[dev]"`
- `.venv\\Scripts\\python -m myagentwiki doctor`

macOS / Linux:

- `python3.12 -m venv .venv`
- `.venv/bin/python -m pip install -U pip`
- `.venv/bin/python -m pip install -e ".[dev]"`
- `.venv/bin/python -m myagentwiki doctor`

完成项目安装后，才可以使用 `python -m myagentwiki bootstrap --extra dev` 安装或修复依赖；`bootstrap --dry-run` 可先查看将要执行的安装命令。

## 工作流验证脚本

仓库当前已提供：

- [scripts/validate_workflow.py](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/scripts/validate_workflow.py)

用途：

- 用最小样例跑通 `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
- 验证 sibling `raw/` 的递归扫描子目录能力
- 为 Windows / macOS / Linux 提供统一的 CLI 烟雾测试入口

说明：

- 当前脚本本身是跨平台的
- 但本仓库当前轮开发是在非 Windows 环境完成，因此 Windows 侧属于“脚本与命令路径已适配、待真实机器补充实跑确认”
