# CLI 模块化设计

## 文档定位

本文档回答一个比主详细设计更聚焦的问题：

`MyAgentWiki` 当前已经具备较完整的 CLI 与知识编译主链路，也已拆出 parser、命令适配、服务、仓储和运行时转换模块；但 `src/myagentwiki/cli.py` 仍承担依赖装配、语义与结构规则、页面生成、索引和部分基础设施职责。后续如果继续在这个单文件里扩展功能，维护成本、测试成本和重构风险都会持续上升。

因此，本文档的目标不是讨论“要不要拆”，而是定义：

- 目标模块边界应该长什么样
- CLI、应用层、领域层、基础设施层之间如何依赖
- 当前功能应该如何映射到新模块
- 后续拆分时的阶段顺序、验收口径和兼容策略

本文档面向的是后续实现者。它应作为 `cli.py` 拆分、测试补齐、目录调整和代码审查时的共同基线。

若本文档与系统主流程、证据链、语义链、审核恢复链的主设计描述发生冲突，以 [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md) 为准；本文档只负责代码组织和模块边界。

## 当前实现快照

当前代码已经完成第一轮拆分，但还没有达到本文档的最终目录目标：

- `src/myagentwiki/cli_parser.py`：集中注册命令和参数
- `src/myagentwiki/cli_components/`：承接命令适配、参数转 request、结果转 `CommandResult`
- `src/myagentwiki/app_services/`：承接 init、ingest、query、review、lint、render、semantic batch、运行时转换等服务
- `src/myagentwiki/repositories/`：承接 query / ingest / review / semantic 等账本读取和持久化
- `src/myagentwiki/app_services/runtime_services.py`：承接文档转换、OCR、远程图片下载和 LLM/确定性任务接入等运行时能力
- `src/myagentwiki/cli.py`：仍负责依赖装配，并保留较多语义规则、Structure / Evidence / Knowledge / Claim 编译、页面生成和索引逻辑，尚未成为真正的薄入口

内部流程已经改为复用 `run_*_service`，不再通过调用 `command_*` 复用业务逻辑。本文后面的 `cli/ / app/ / domain/ / infra/` 目录树是长期目标，不是当前文件系统快照；继续拆分时应优先沿用现有模块，再按职责逐步调整命名和边界。

## 当前问题

### 1. 当前 `cli.py` 仍未成为薄入口

当前 `src/myagentwiki/cli.py` 已把 parser、命令适配、部分服务、仓储和运行时转换拆出，但仍包含：

- 大量依赖装配与兼容包装函数
- `raw -> normalized -> structure/evidence/knowledge/chunk/claim/page` 的核心规则与部分编排
- 语义批处理的任务收集、结果投影与页面路由
- 页面生成、检索常量、索引重建和回链辅助

这说明当前文件仍同时承担了：

- interface layer
- application layer
- domain services
- infrastructure adapters

这类结构在项目早期推进很快，但到当前阶段会开始拖累：

- 新增功能时难以判断“应该放在哪”
- 变更一处逻辑时容易误伤不相干命令
- 单元测试难以只测一层

### 2. 命令函数与业务服务的混用已经基本解决

当前命令适配层会调用 `run_init_service / run_ingest_service / run_query_service / run_review_auto_service / run_lint_service` 等服务，post-ingest 自动审核也复用 service，不再直接调用 `command_review_auto(...)`。

后续仍需守住下面这些边界：

- 不让 `argparse.Namespace` 重新变成内部调用协议
- 不让命令输出格式反向绑住 service result
- 后续增加 API、TUI、LLM 客户端或测试夹具时，统一复用 service，不复用 CLI 命令函数

### 3. 基础设施能力已开始拆分，但领域逻辑仍偏集中

MarkItDown 统一文档转换已进入 `app_services/document_conversion.py`；Markdown/图片专用标准化、旧转换器备用路径、OCR、下载重试和 LLM/确定性任务接入仍由 `app_services/runtime_services.py` 承接。多类账本读取与持久化已进入 `repositories/`，但部分文件锁、Git、索引、结构编译和页面生成能力仍留在 `cli.py`，领域层也尚未形成独立目录。

这会导致：

- 领域代码不容易读出真正的业务主线
- 基础设施替换成本高
- 很难只替换一个输入适配器而不触碰编排层

## 设计目标

本次模块化设计遵循下面几条目标。

### 1. 保持 CLI-first，不改变对外使用方式

用户和 Agent 仍然优先通过：

- `python3 -m myagentwiki ...`
- `myagentwiki ...`

执行固定流程。

也就是说，模块化重构不是要把 CLI 变成可有可无，而是让 CLI 成为稳定的薄入口。

### 2. 保持现有工作区账本和主流程不被推翻

本次设计不重写以下核心约定：

- 工作区目录结构
- `state/*.jsonl`、`indexes/*.json`
- `normalized/`、`chunks/`、`claims/`、`wiki/`
- 证据优先主链路
- `review-apply` 作为状态恢复入口

模块化设计只改变代码组织，不先改变产品语义。

### 3. 让“命令入口”和“业务服务”彻底分层

后续每个命令都应尽量收敛到下面这个形状：

1. CLI 解析参数
2. 组装 request / options
3. 调用 application service
4. 把 service result 转成 `CommandResult`
5. 统一输出

这样命令函数不再承担具体业务实现。

### 4. 让可测试单元变小

模块拆分后，测试应能分别覆盖：

- parser / CLI 装配
- service 编排
- repository 读写
- converter / adapter
- 纯领域规则函数

这样后续修改一个模块时，不需要每次都依赖大而全的 E2E 验证。

## 分层原则

目标结构建议采用四层，而不是直接引入很重的框架。

### 1. CLI 层

职责：

- 参数解析
- 子命令注册
- 输出格式选择
- 异常转成用户可读错误

不负责：

- 主业务流程
- 账本细节
- 文档转换细节

### 2. Application 层

职责：

- 组织一次完整用例
- 调用多个 domain service / repository / adapter
- 维护命令级编排顺序
- 产出稳定的 result payload

示例：

- `InitService`
- `IngestService`
- `QueryService`
- `ReviewAutoService`
- `ReviewApplyService`
- `LintService`

### 3. Domain 层

职责：

- 纯业务规则
- 生命周期判断
- 路由规则
- 索引构建规则
- grounded 检查规则

尽量做到：

- 输入输出清晰
- 不直接依赖 CLI
- 尽量不直接做文件 IO

### 4. Infrastructure 层

职责：

- JSONL / JSON 文件读写
- 文件锁
- Git / subprocess
- 原始文档转换
- OCR / 下载 / 外部依赖 fallback
- LLM 调度器、在线客户端、CLI 客户端与确定性处理器调用

这一层提供能力给上层使用，但不决定主业务流程。

## 依赖方向

目标依赖方向固定为：

```text
CLI -> Application -> Domain
CLI -> Application -> Infrastructure
Application -> Domain
Application -> Infrastructure
Infrastructure -X-> CLI
Domain -X-> CLI
Domain -X-> argparse
```

关键约束：

- `command_*` 不允许再被内部流程直接调用
- 内部流程只允许调用 service
- service 可以调用 repository / adapter
- repository 和 adapter 不应反向依赖 service

## 目标目录结构

下面给出长期目标目录结构。当前实现使用较平的 `cli_parser.py / cli_components / app_services / repositories` 结构；这里强调的是逻辑边界，不要求为了目录名一次性搬完。

```text
src/myagentwiki/
  __init__.py
  __main__.py
  cli.py
  semantic.py
  deterministic_processor.py
  llm/
    contracts.py
    online_client.py
    cli_client.py
    router.py
    repair.py
    errors.py
    diagnostics.py

  cli/
    __init__.py
    parser.py
    result.py
    commands/
      __init__.py
      init.py
      ingest.py
      query.py
      review.py
      lint.py
      render.py
      semantic.py
      doctor.py
      bootstrap.py

  app/
    __init__.py
    services/
      __init__.py
      init_service.py
      ingest_service.py
      query_service.py
      review_service.py
      lint_service.py
      render_service.py
      semantic_service.py
      doctor_service.py
      bootstrap_service.py
    dto/
      __init__.py
      common.py
      ingest.py
      query.py
      review.py

  domain/
    __init__.py
    workspace.py
    sources.py
    normalization.py
    structure.py
    evidence.py
    knowledge.py
    claims.py
    reviews.py
    pages.py
    query.py
    lint.py
    aliases.py
    page_links.py

  infra/
    __init__.py
    fs.py
    locks.py
    git.py
    jsonl_store.py
    workspace_paths.py
    converters/
      __init__.py
      markdown.py
      pdf.py
      docx.py
      spreadsheet.py
      image.py
      binary.py
    llm/
      __init__.py
      contracts.py
      online_client.py
      cli_client.py
      router.py
    repositories/
      __init__.py
      workspace_config_repo.py
      sources_repo.py
      normalized_repo.py
      structure_repo.py
      evidence_repo.py
      knowledge_repo.py
      chunks_repo.py
      claims_repo.py
      reviews_repo.py
      pages_repo.py
      semantic_repo.py
      indexes_repo.py
```

这里不要求绝对照搬目录名，但建议保持四个顶层边界：

- `cli/`
- `app/`
- `domain/`
- `infra/`

## 模块职责划分

### `cli.py`

目标职责：

- 仅保留 `main()`
- 调用 `cli.parser.build_parser()`
- 调用命令 handler
- 调用统一 `print_result()`

目标状态下，`cli.py` 应尽量接近一个很薄的装配入口。

### `cli/parser.py`

职责：

- 子命令注册
- 公共参数复用
- 把 handler 绑定到各命令适配函数

建议补一个轻量公共注册工具，减少现在 `query` 和 `answer-query` 这类高度相似参数定义的重复。

### `cli/result.py`

职责：

- `CommandResult`
- 输出序列化
- JSON / text 模式转换

好处是命令输出契约集中管理，不再散在主文件里。

### `cli/commands/*.py`

职责：

- 把 `argparse.Namespace` 转成更稳定的 request object
- 调用对应 service
- 把 service result 映射成 `CommandResult`

要求：

- 不做真实业务实现
- 不直接写账本
- 不直接做文档转换

### `app/services/*.py`

职责：

- 每个文件对应一类用例编排
- 负责“按什么顺序调用哪些模块”
- 汇总 summary、warnings、产出 payload

示例：

- `ingest_service.py`
  - 扫描 raw
  - 去重 / 版本更新
  - 标准化
  - 结构化
  - 知识抽取
  - claim 草拟
  - review 刷新
  - page rebuild
  - post-ingest automation

- `review_service.py`
  - review list
  - review auto
  - review apply
  - alias conflict 收口

### `domain/*.py`

职责：

- 尽量放纯规则和纯计算
- 不直接做 IO
- 输入数据结构后返回新数据结构或检查结果

示例：

- `claims.py`
  - claim text 归一化
  - claim type / lifecycle 规则
  - duplicate / similarity bucket 规则

- `pages.py`
  - page route
  - render target 规则
  - grounded 检查

- `query.py`
  - BM25 打分
  - intent 识别
  - reading_pack 组织

### `infra/repositories/*.py`

职责：

- 每类账本文件一个 repository
- 屏蔽 `load_jsonl / write_jsonl / replace_jsonl_record` 等低层细节
- 统一 live / historical 记录装载与写回

建议优先抽的 repository：

- `claims_repo.py`
- `reviews_repo.py`
- `pages_repo.py`
- `semantic_repo.py`
- `indexes_repo.py`

因为这几类对象最常被多个命令共享。

### `infra/converters/*.py`

职责：

- 各类文件转 Markdown
- 平台 fallback
- OCR 辅助
- 图片嵌入资源处理

原则：

- 每种文档类型的适配单独成模块
- ingest service 只关心“我要拿到 normalized markdown”，不关心 DOCX/PDF/XLSX 的解析细节

## 按命令的设计映射

### `init`

建议拆分为：

- `cli/commands/init.py`
- `app/services/init_service.py`
- `domain/workspace.py`
- `infra/git.py`
- `infra/repositories/workspace_config_repo.py`

其中：

- 目录规则、路径约束、sibling `raw/` 约定放在 domain
- 模板渲染、文件写入、Git 基线放在 infra
- 初始化流程编排放在 app service

### `ingest`

这是最值得优先拆的命令。

建议拆成以下子模块：

- `app/services/ingest_service.py`
- `domain/sources.py`
- `domain/normalization.py`
- `domain/structure.py`
- `domain/evidence.py`
- `domain/knowledge.py`
- `domain/claims.py`
- `domain/reviews.py`
- `domain/pages.py`
- `infra/converters/*`
- `infra/repositories/*`

`ingest_service.py` 不应继续持有所有实现细节，而应只做总编排。

### `query` 和 `answer-query`

建议共用同一个 query service。

结构上可为：

- `app/services/query_service.py`
- `domain/query.py`
- `domain/aliases.py`
- `domain/page_links.py`
- `infra/repositories/pages_repo.py`
- `infra/repositories/claims_repo.py`
- `infra/repositories/indexes_repo.py`

其中：

- `query`
  - 返回普通阅读结果
- `answer-query`
  - 只是对同一 reading pack 做不同格式投影

这样可以避免两个命令长期平行复制参数和主逻辑。

### `review-list / review-auto / review-apply`

建议合并成统一 `review_service.py`，内部再分：

- `list_reviews(...)`
- `auto_resolve_reviews(...)`
- `apply_review_action(...)`

同时把“自动审核策略”和“命令入口”彻底拆开，避免 post-ingest 继续直接调用命令函数。

### `lint`

建议拆为：

- `app/services/lint_service.py`
- `domain/lint.py`
- `infra/repositories/*`

其中 domain 负责：

- 检查项定义
- 一致性规则
- 检查结果结构

service 负责：

- 装载工作区对象
- 调用各类检查
- 汇总报告
- 写出 `reports/lint/lint_latest.md`

### `doctor / bootstrap`

这两个命令相对独立，可以最早拆。

原因：

- 依赖外部最少
- 对工作区状态无侵入
- 拆出来能先验证新的 CLI 分层方式

## 关键数据边界

模块化后，建议尽量把下面几类对象的载荷边界固定下来。

### Request / Options

每个 service 最好接收显式 request object，而不是原始 `argparse.Namespace`。

例如：

- `InitRequest`
- `IngestRequest`
- `QueryRequest`
- `ReviewAutoRequest`

这样可以避免 `argparse` 直接污染内部代码。

### Result / Summary

每个 service 最好返回显式 result object 或稳定 dict，而不是直接拼 UI 文案。

例如：

- `IngestResult`
- `QueryResult`
- `LintResult`

`CommandResult.message` 只是 CLI 表达层，不应成为业务层唯一产出。

### Repository record normalization

repository 层应负责：

- live / historical 默认字段补齐
- schema version guard
- 统一 ID 键
- 写回顺序稳定化

这样 service 就不需要每次自己补 lifecycle defaults。

## 推荐的第一批拆分顺序

不建议一口气大拆。建议按下面顺序推进。

### Phase A: 先把 CLI 入口变薄

目标：

- 抽出 `cli/result.py`
- 抽出 `cli/parser.py`
- 抽出 `cli/commands/doctor.py`
- 抽出 `cli/commands/bootstrap.py`

验收：

- 外部命令行行为不变
- `src/myagentwiki/cli.py` 只保留 main 装配

### Phase B: 先拆最独立的 service

目标：

- 拆 `doctor_service.py`
- 拆 `bootstrap_service.py`
- 拆 `init_service.py`

验收：

- `init` 不再在命令函数里直接写全部细节
- `argparse.Namespace` 不再进入核心业务逻辑

### Phase C: 抽 repository 层

目标：

- 优先抽 `claims_repo / reviews_repo / pages_repo / semantic_repo / indexes_repo`

验收：

- `load_jsonl / write_jsonl / replace_jsonl_record` 不再被高层广泛直接调用

### Phase D: 拆 `review` 和 `query`

原因：

- 两者共享大量状态账本
- 两者都已经有较明确的输出契约
- 拆出来收益高，风险比 ingest 低

### Phase E: 最后拆 `ingest`

原因：

- ingest 涉及链路最长
- 文档转换、结构化、claim、review、page rebuild 都在这里交汇
- 等 repository、review、query 边界先稳定后，再拆 ingest 风险最低

## 不建议做的事

### 1. 不建议一次性迁移到大型框架

例如：

- 不必为了分层强行引入复杂 DI 框架
- 不必先上 event bus
- 不必先引入 ORM 风格抽象

当前项目更适合“轻量模块化 + 显式函数边界 + 少量 dataclass”。

### 2. 不建议先改工作区账本格式

如果在拆模块的同时修改：

- JSONL schema
- 文件命名
- 工作区目录结构

会把“代码组织重构”和“产品语义迁移”叠在一起，风险太大。

### 3. 不建议继续新增内部 `command_*` 复用

从本文档起，新的内部流程如果需要复用逻辑，应优先新增 service，而不是继续调用命令函数。

## 测试策略

模块化后，建议测试分三层。

### 1. 单元测试

覆盖：

- 纯规则函数
- repository 读写行为
- converter fallback

### 2. service 测试

覆盖：

- `init_service`
- `review_service`
- `query_service`
- `lint_service`

重点检查编排与 summary 是否稳定。

### 3. E2E 测试

继续保留现有：

- `doctor -> bootstrap --dry-run -> init -> ingest -> query -> lint`
- `review-list / review-auto / review-apply`
- user workspace lab

模块化不是减少 E2E，而是让更多问题在更早层被发现。

## 验收标准

当下面这些条件成立时，可以认为模块化设计真正落地，而不是只做了“文件搬家”：

1. `src/myagentwiki/cli.py` 不再承载真实业务实现。
2. 内部流程不再调用 `command_*`。
3. 高层业务逻辑不再直接操作底层 JSONL 写回细节。
4. 文档转换与 OCR 逻辑不再和 ingest 编排混在同一个文件里。
5. `query` 和 `answer-query` 共用同一 service 主逻辑。
6. `review-list / review-auto / review-apply` 共用同一 review service 主逻辑。
7. 新增命令时，能够自然判断它属于 `cli / app / domain / infra` 哪一层。

## 与后续工作的关系

后续若要继续推进重构，建议以本文档为“代码组织基线”，再配合：

- [MyAgentWiki系统详细设计.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/MyAgentWiki系统详细设计.md)
  - 看系统主流程和对象关系
- [全链路重构实现计划.md](/Users/sunweisheng/Documents/GitHub/MyAgentWiki/docs/全链路重构实现计划.md)
  - 看功能演进与阶段性实现顺序

也就是说：

- 主详细设计回答“系统应该做什么”
- 本文档回答“代码应该怎么组织”
- 重构实现计划回答“我们准备先做哪一步”
