# Coding Agent M2 上下文预算与 Agent Loop 说明

日期：2026-08-28。范围：完成 M2 的上下文字符/token 总预算、模型侧 ToolResult 裁剪，以及 Conversation、ToolRegistry、StopController、LLMClient 的 Agent Loop 集成。工具专用事件、连续超时/LLM 错误恢复和关闭时文件写入语义仍属于后续任务。

## 1. 上下文总预算

`ContextBudget` 默认限制：80,000 字符、估算 20,000 token、单个模型侧工具结果最多 12,000 字符。总量统计包含 system、原始用户任务、历史 assistant/tool 消息以及本次实际发送的 `ToolRegistry.schemas()`；工具 Schema 不是免费上下文。

项目不新增 tokenizer 依赖。当前估算器对每个非 ASCII 字符计 1 token，对 ASCII 字符按每 4 个计 1 token，并对紧凑 JSON 序列化后的完整模型输入计量。这不是供应商账单 token 的精确值，而是确定性、可测试的本地保护线；字符和估算 token 两个上限必须同时满足。真实模型阶段可按所选模型替换估算器，但不得取消字符硬上限。

`Conversation.build_context()` 的选择规则：

1. 始终保留 system 和原始任务；二者连同工具 Schema 已超预算时显式失败。
2. 只按完整轮次选择最近历史，assistant tool calls 和按序 tool results 不会被拆散。
3. 从最新轮次向前装入；更老轮次放不下时停止，不保留“旧但不保留新”的反直觉上下文。
4. 最新完整轮次即使把工具结果缩到最小安全信封仍放不下时，以 `CONTEXT_BUDGET_EXCEEDED` 终止，不向模型发送孤立或不一致消息。

## 2. ToolResult 裁剪整合

文件、搜索和命令工具原有的行数、字节数、扫描量、stdout/stderr 等上限完全不变。新的裁剪只发生在构建下一次模型请求时，不修改 `ToolRegistry`、不修改工具返回，也不把已有工具预算复制到 Runtime。

超过模型侧单结果预算时，tool message 的 `content` 被替换为合法 JSON 信封，包含：

- `context_truncated=true`；
- 原始字符数；
- 原始 `ok`、`error_code` 和工具自身 `truncated` 状态；
- 在剩余预算内尽可能长的原始 JSON 前缀预览。

Conversation 内仍保留原始有界 ToolResult；同一轮有多个结果且总量不足时，会用二分方式进一步收紧共同的结果预览上限，始终保持全部调用 ID 与结果配对。

配置变量：

| 环境变量 | 默认值 | 约束 |
|---|---:|---|
| `CODING_AGENT_CONTEXT_MAX_CHARACTERS` | 80000 | 正整数 |
| `CODING_AGENT_CONTEXT_MAX_TOKENS` | 20000 | 正整数，当前为估算 token |
| `CODING_AGENT_TOOL_RESULT_MAX_CHARACTERS` | 12000 | 至少 256 |
| `CODING_AGENT_CONTEXT_RECENT_ROUNDS` | 8 | 正整数 |

## 3. Agent Loop

模型配置完整时，默认 Runtime 执行：

```text
受预算约束的 Conversation + 原有工具 Schema
  -> LLMClient.complete
  -> 校验 ModelReply / 发布 assistant_message
  -> 无 tool call：返回最终文本
  -> 有 tool call：StopController 检查
  -> ToolRegistry.execute
  -> ToolResult JSON 按原 call id、原顺序回填
  -> Conversation.append_round
  -> 下一轮
```

assistant 消息使用 OpenAI 原生 function tool call 结构；参数以稳定紧凑 JSON 字符串保存。每个 tool message 使用模型给出的 `tool_call_id`，并严格按本轮调用顺序追加。并行 tool calls 会顺序执行，避免本地写操作与命令产生未定义并发；结果仍在同一完整轮次内一起回填。

工具参数错误、未知工具、路径错误、命令非零等 `ToolResult` 都作为 Observation 返回模型，模型可以在下一轮修正，而不是立刻把任务变成通用异常。Fake LLM 已验证错误参数后的恢复路径。

## 4. 确定性停止

- `max_steps` 现在按 LLM 决策轮计数；到达上限返回 `AGENT_STEP_LIMIT`。
- 相同工具名与规范化参数连续第三次出现时不再执行工具，而是按该调用 ID 回填 `REPEATED_TOOL_CALL` 纠偏 Observation。
- 再次重复（第四次）返回结构化 `REPEATED_TOOL_CALL` 任务失败。
- 同一模型响应中的调用 ID 为空或重复、无工具调用且最终文本为空，返回 `INVALID_MODEL_REPLY`。
- 客户端的安全 `LLMError` 和上下文预算错误会转换为稳定任务错误，不回显底层响应或异常。

连续命令超时、连续 LLM 错误的跨轮恢复阈值仍未实现；本阶段没有把“客户端内部 HTTP 重试”误写成 Agent 级恢复。

## 5. 应用组装与资源

仅当 `CODING_AGENT_API_KEY`、`CODING_AGENT_BASE_URL`、`CODING_AGENT_MODEL` 三项均非空时，默认应用创建 LLM 客户端并报告 `mode=agent`、`agent_ready=true`。配置不完整时保持 `mode=scaffold`，提交任务以 `NOT_IMPLEMENTED` 失败且不执行任何工具。注入测试 Runner 时不额外创建无用 HTTP 客户端。

应用关闭顺序是先取消/等待活动任务，再关闭 Runtime 拥有的 LLM 客户端；已有 `run_command` 取消与进程树回收语义保持不变。

## 6. 修改与验证

| 文件 | 修改内容 |
|---|---|
| [agent/context.py](../backend/app/agent/context.py) | 双预算估算、工具 Schema 计量、完整轮次选择、模型侧结果裁剪 |
| [agent/runtime.py](../backend/app/agent/runtime.py) | 自研 Agent Loop、调用 ID 回填、停止规则与安全错误 |
| [core/config.py](../backend/app/core/config.py) | 上下文/结果/轮次配置与模型配置就绪判断 |
| [main.py](../backend/app/main.py) | 按配置组装 Runtime/LLM，动态 mode/agent_ready，关闭资源 |
| [services/tasks.py](../backend/app/services/tasks.py) | agent 模式任务与结构化 Runtime 错误 |
| [api/routes.py](../backend/app/api/routes.py) | 返回实际 mode 与 agent_ready |
| [test_context_budget.py](../tests/test_context_budget.py) | 字符/token、Schema、完整轮次、结果裁剪和超限测试 |
| [test_agent_runtime.py](../tests/test_agent_runtime.py) | Fake LLM 闭环、并行 ID、错误恢复、停止策略、应用组装 |

新增 13 项确定性测试；受影响组件/API 针对性验证 30 passed。当前全量 **234 passed, 1 warning**，Ruff lint 与 43 个 Python 文件格式检查通过，`pip check` 通过。测试不调用真实模型；真实工具闭环确实完成“读取错误实现 → 唯一替换 → 执行 pytest → 最终回复”。warning 仍是既有 Starlette TestClient/httpx 弃用提示。

## 7. 尚未完成

- `tool_started`、`tool_finished`、`file_changed`、`command_finished` 真实事件及事件/历史体积限制。
- 连续 LLM/Runtime 错误和连续命令超时的跨轮恢复策略。
- 关闭时已经开始的文件写入语义与更完整的取消验收。
- 真实供应商联网测试、真实 Demo 连续成功率和前端专用工具卡片。
