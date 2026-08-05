# MyAgentWiki LLM 主备线路与 Function Calling 设计

## 1. 目标

MyAgentWiki 的真实模型请求统一由 `myagentwiki.llm.router` 调度：

1. `online_client` 是在线主线路，每个请求首次执行后最多重试两次。
2. `cli_client` 是 Codex CLI 备用线路，只执行一次。
3. 主线路遇到不可重试错误时直接进入备用线路；可重试错误三次仍失败后进入备用线路。
4. 主备线路都失败时抛出 `LLMRouteError`，不使用确定性处理结果掩盖错误；直接依赖结果的调用点让当前命令失败。

确定性处理独立放在 `deterministic_processor` 中，只能由任务显式选择。调度器本身在主备都失败时始终抛出错误；当前 Markdown 内嵌图片调用点会按单附件边界捕获该错误，保留正文、图片占位和告警，其他直接依赖 LLM 结果的调用点让错误继续返回命令层。

## 2. 模块职责

```text
src/myagentwiki/llm/
├── contracts.py
├── online_client.py
├── cli_client.py
├── router.py
├── repair.py
├── errors.py
└── diagnostics.py
```

- `contracts`：保存每个任务的函数名、说明、参数 Schema、上下文说明和业务检查。
- `online_client`：通过 OpenAI SDK 发送非流式 Function Calling 请求。
- `cli_client`：通过 Codex CLI 和 `--output-schema` 返回同名函数结果包。
- `router`：读取配置、执行重试、切换备用线路并返回已校验参数。
- `repair`：按“JSON 修复、Schema 校验、业务检查”的顺序处理函数参数。
- `errors`：保存可重试错误、不可重试错误和主备线路最终错误。
- `diagnostics`：向工作区 `logs/llm_requests.jsonl` 写入脱敏请求记录。

## 3. Function Calling 合同

当前纳入十个任务：

- 语义分析：`document_analysis`、`claim_candidate_quality`、`claim_role`、`page_intent`
- 自动处理：`review_auto_decision`、`claim_stable_promotion`、`review_concept_candidate`
- 页面改写：`render_readable_concept_page`、`render_workspace_overview_page`
- 图片理解：`describe_image`，当前由 Markdown 内嵌图片在 OCR 不足时调用；独立 `raw/` 图片标准化暂未接入该任务

每个任务只允许调用一个指定函数。所有对象 Schema 都设置 `additionalProperties: false`。在线线路强制指定该函数并关闭并行调用；CLI 线路返回 `function_name` 和 `arguments_json`，随后进入同一套修复与检查。

请求上下文只解释任务目标、证据边界、参数含义和信息不足时的处理方式，不再要求模型输出普通 JSON 文本。程序已知的任务名、请求 ID 和合同版本不要求模型重复填写。

## 4. 错误与重试

可重试错误包括连接失败、超时、HTTP 408/409/429、5xx，以及空响应、函数调用错误、JSON 无法修复、Schema 不符和业务检查失败。

在线配置缺失或无效、TLS 配置错误，以及其他 4xx 不在线重试，直接进入 CLI。两次在线重试前分别等待 `1 秒 + 随机量` 和 `2 秒 + 随机量`。不同请求之间不设置等待。

OpenAI SDK 和 HTTP transport 的内部重试都关闭。客户端只在当前逻辑请求内使用，请求结束后关闭，不保存全局单例。

## 5. 配置与兼容

工作区 `config/project.yml` 使用统一 `llm` 配置。语义任务声明策略、任务名、超时、最低置信度、批次和版本；自动处理任务声明策略、任务名、超时和最低置信度；页面改写任务声明模式、任务名和超时。任务配置不再保存 Python command，也不能自行选择在线或 CLI 线路。

新工作区中，已经实现合同的增强任务默认启用主备线路。缺少在线配置时直接使用 Codex CLI；两条线路都不可用时，直接依赖结果的流程失败，Markdown 内嵌图片按前述单附件规则降级。确定性模式必须显式配置为 `deterministic`。

项目配置示例：

```yaml
llm:
  contract_version: "v2"
  routing:
    primary: "online"
    fallback: "cli"
  retry:
    online_max_retries: 2
    backoff_seconds: [1.0, 2.0]
    jitter_max_seconds: 0.25
    http_statuses: [408, 409, 429]
    http_status_min: 500
  context:
    document_max_chars: 24000
    image_max_bytes: 20971520
    image_mime_types: ["image/png", "image/jpeg", "image/webp", "image/gif"]
  cli:
    executable: "codex"
    timeout_seconds: 120
    model: ""
```

在线地址、模型、API Key、API 风格和 TLS 校验保存在 MyAgentWiki Skill 根目录且不入库的 `.env`，不放在用户工作区。系统环境变量优先于 `.env`，适合 CI 或临时覆盖。

## 6. 返回处理与诊断

函数结果固定按以下顺序处理：

1. 检查调用数量和函数名。
2. 使用 `json_repair.loads` 解析参数。
3. 使用函数合同的 JSON Schema 校验参数。
4. 检查输入 ID、允许动作、证据关系等业务约束。
5. 通过后交给现有业务流程。

诊断日志只记录请求 ID、任务、函数名、最终线路与状态、各线路尝试次数和耗时、错误分类、HTTP 状态、是否修复、函数 Schema 版本和提示版本，不记录 API Key、图片内容、完整正文或完整模型输出。

缓存指纹同时记录路由版本、在线模型和 API 风格、CLI 模型、函数名、函数 Schema 版本、提示版本和总合同版本。切换线路配置或升级合同时，不应复用旧判断。

## 7. 上下文边界

- `document_analysis` 默认传入最多 24,000 字符正文；超长正文保留开头和结尾，并标记 `content_truncated=true`。
- 页面改写只传入允许引用的 claim 或 page，返回 ID 必须属于输入集合。
- 自动审核只传入当前 review 允许的动作，模型不得返回集合外动作。
- 在线图片按真实 MIME 和二进制内容生成 data URL；CLI 图片使用绝对路径和 `-i` 参数。
- 提示只说明函数用途、字段含义、证据边界和信息不足时的处理方式，不包含“只返回 JSON”或普通 JSON 示例。

## 8. 调试与验证

`scripts/debug_llm_routing.py` 提供三个入口：

```bash
python3 scripts/debug_llm_routing.py contract --task claim_role
python3 scripts/debug_llm_routing.py simulate --scenario all
python3 scripts/debug_llm_routing.py live --workspace /path/to/workspace --task claim_role --payload-file /path/to/payload.json
```

- `contract`：离线查看函数名、版本和 Schema。
- `simulate`：用固定客户端覆盖首次成功、重试成功、403/404、429/5xx、修复失败、函数名错误、Schema/业务检查失败、CLI 成功和主备失败。
- `live`：显式执行一次真实主备请求；成功时输出通过检查的函数参数，失败时输出请求 ID 和脱敏尝试记录，不输出凭据或完整请求上下文。

用户工作区实验场默认设置 `MYAGENTWIKI_LLM_MODE=deterministic`，不依赖个人 API 或 Codex 登录。只有显式传入 `--live-llm-check` 才执行真实线路检查。

## 9. 旧配置迁移

旧任务级 `command` 不再执行。配置加载器遇到旧格式时返回 `llm_configuration_migration_required`，并按旧模块给出一一对应建议：

| 旧模块 | 配置修改 |
| --- | --- |
| `myagentwiki.agent_online_hook` | 删除 `command`，任务设为 `llm_assisted`；在线提供方继续放在 MyAgentWiki Skill 根目录的 `.env`，由调度器作为主线路读取 |
| `myagentwiki.agent_cli_hook` | 删除 `command`，任务设为 `llm_assisted`；CLI 由调度器自动作为备用线路使用 |
| `myagentwiki.agent_hook` | 删除 `command`；保留旧本地行为时设为 `deterministic`，采用主备线路时设为 `llm_assisted` |

未知自定义命令不能自动迁移，必须人工确认它应改为 `llm_assisted`、`deterministic`，还是另行接入正式客户端接口。旧协议模块不保留转发入口。

## 10. 实现验收边界

- 两种在线 API 风格必须强制唯一函数、关闭并行调用、`stream=false`，SDK 和 HTTP transport 内部重试均为零。
- 在线每个逻辑请求最多三次，CLI 最多一次；不同请求之间不额外等待，也不存在全局 OpenAI 客户端。
- 合法 JSON 保持语义不变，常见语法问题可修复；修复不能补造缺失字段、错误 ID、证据关系或业务决策。
- 十个已实现任务可通过在线与 CLI 两条线路；`qa_note / concept_update` 的配置检查明确指出尚无合同。
- 主备都失败时，语义批处理、审核和页面生成等直接调用线路的流程失败；失败批次不写伪结果，已经完成的阶段按现有状态恢复机制保留。Markdown 内嵌图片是当前例外：单张图片失败会降级为占位和告警，不会单独终止整份 Markdown；独立 `raw/` 图片当前不调用该合同。
