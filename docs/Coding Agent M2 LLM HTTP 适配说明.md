# Coding Agent M2 LLM HTTP 适配说明

日期：2026-08-28。范围：记录 M2 第一项——OpenAI-compatible Chat Completions HTTP 适配、响应校验、超时/有限重试和资源关闭。此后上下文预算与 Agent Loop 已实现，见 [后续说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md)；本文 221 项验证数字保留该阶段原意。

## 1. 实现结果

`OpenAICompatibleLLMClient` 使用项目已有的 `httpx` 依赖调用 `{base_url}/chat/completions`，只负责把消息与工具定义发送给模型并转换为 `ModelReply`。调用方传入 `ToolRegistry.schemas()`；客户端原样发送这组六工具 Schema，不重新维护另一份工具参数定义，也不执行工具。

请求固定包含 `model`、`messages` 和 `stream=false`；有工具时增加原始 `tools` 与 `tool_choice=auto`。鉴权使用后端进程中的 Bearer API Key，密钥不会写入 repr、错误消息、响应事件或测试夹具输出。

## 2. 响应校验

客户端把模型输出视为不可信数据。当前接受单个 Chat Completion choice，并校验：

- `message.role` 必须为 `assistant`，正文必须是字符串或 null；没有正文也没有工具调用时拒绝。`length`、`content_filter` 以及 finish reason 与 tool call 不一致均作为显式错误，不能误报为正常完成。
- `tool_calls` 仅接受 `type=function`；调用 ID 和函数名必须为非空、无首尾空白的字符串。
- 同一响应中的调用 ID 必须唯一，工具名必须存在于本次请求发送的 Schema 中。
- `function.arguments` 必须是可解析为 JSON object 的字符串；数组、标量和无效 JSON 均拒绝。
- 参数的字段、类型与额外字段仍由现有 `ToolRegistry.execute()` 使用对应 Pydantic `ToolArgs` 做最终严格校验，HTTP 客户端不复制这套规则。

非 JSON、空 choices、多 choices、错误角色、畸形 tool call、未知工具和空响应统一转换为不含原始响应正文的 `LLMError`。主要错误码包括 `LLM_INVALID_RESPONSE`、`LLM_RESPONSE_TRUNCATED`、`LLM_RESPONSE_BLOCKED`、`LLM_UNKNOWN_TOOL`、`LLM_INVALID_TOOLS`、`LLM_AUTH_ERROR`、`LLM_RATE_LIMIT`、`LLM_TIMEOUT`、`LLM_NETWORK_ERROR`、`LLM_SERVICE_ERROR` 和 `LLM_CLOSED`。

## 3. 超时与重试

默认总/read/write/pool 超时为 60 秒，连接超时为 10 秒，最多重试 2 次（总请求最多 3 次）。仅以下瞬时故障重试：

- `httpx.TimeoutException` 和其他 `httpx.TransportError`；
- HTTP 408、409、425、429、500、502、503、504。

401/403、其他 4xx、成功 HTTP 中的无效模型响应、未知工具和参数 JSON 错误不会重试。退避默认从 0.25 秒指数增长；合法 `Retry-After` 会被采用，但单次等待上限为 5 秒。协程取消直接向上传播，不被当作网络失败重试。

`LLMError` 暴露稳定 `code`、`retryable`、`status_code` 和 `attempts`，便于后续 Runtime 决定是否形成 Observation 或终止；它不包含供应商响应正文、请求 URL、请求头或底层异常文本。

## 4. 配置与关闭

`Settings` 新增并校验：

| 环境变量 | 默认值 | 约束 |
|---|---:|---|
| `CODING_AGENT_LLM_TIMEOUT_SECONDS` | 60 | 正数 |
| `CODING_AGENT_LLM_CONNECT_TIMEOUT_SECONDS` | 10 | 正数 |
| `CODING_AGENT_LLM_MAX_RETRIES` | 2 | 0–10 |

`OpenAICompatibleLLMClient.from_settings()` 复用现有 API Key、Base URL、模型名及上述策略。Base URL 必须是无内嵌凭据、query 或 fragment 的 HTTP(S) 地址；既可传 `/v1` 根，也可传完整 `/chat/completions` 地址。

客户端支持异步上下文管理和显式 `close()`。关闭幂等；内部创建的 `httpx.AsyncClient` 由适配器关闭。测试或上层注入的客户端默认视为外部资源，不擅自关闭；显式 `owns_client=true` 时由适配器负责关闭。关闭后的调用固定返回 `LLM_CLOSED`。

## 5. 修改与验证

| 文件 | 修改内容 |
|---|---|
| [agent/llm.py](../backend/app/agent/llm.py) | HTTP 请求、严格转换、安全错误、重试、关闭及 Settings 工厂 |
| [core/config.py](../backend/app/core/config.py) | 模型超时/连接超时/重试环境配置与边界校验 |
| [test_llm_client.py](../tests/test_llm_client.py) | 请求、Schema 复用、响应错误、重试、取消、脱敏和资源所有权测试 |
| [test_agent_contracts.py](../tests/test_agent_contracts.py) | 新配置的默认/环境读取与边界回归 |

本轮不调用真实模型，使用 `httpx.MockTransport` 做确定性协议测试。LLM 客户端及 Agent 契约针对性验证为 31 passed；全量为 **221 passed, 1 warning**。Ruff lint、41 个 Python 文件格式检查和 `pip check` 通过。warning 仍是既有 Starlette TestClient/httpx 弃用提示；本轮没有升级依赖，也没有重跑前端构建或浏览器 smoke。

## 6. 后续状态与尚未完成

- 默认 `AgentRuntime` 现已在模型配置完整时创建并调用该客户端；配置不完整时仍保持 scaffold/`NOT_IMPLEMENTED` 安全降级。
- Conversation 上下文总预算、工具结果回填和 StopController 基础策略现已接入；连续 Runtime 错误策略和工具事件仍属于后续 M2/M3。
- 尚未对任何真实供应商或 OpenAI-compatible 网关做联网验收；不同供应商的非标准字段兼容性需要在 M4 真实模型阶段验证。
- 当前只支持非流式 Chat Completions 原生 function tool calling；Responses API、旧 `function_call`、自定义工具和流式增量解析不在本阶段范围。

协议字段依据 [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat)；异步客户端关闭与超时行为依据 [HTTPX Async Support](https://www.python-httpx.org/async/) 和 [HTTPX Timeouts](https://www.python-httpx.org/advanced/timeouts/)。
