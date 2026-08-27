# Coding Agent 项目结构与功能设计文档

> 版本：v2.0（按《项目要求》可行性复核后修订）  
> 修订日期：2026-08-27  
> 目标：在 2026-09-02 24:00 前交付一个能够完成真实编程任务、过程可解释、核心 Agent 逻辑自行实现的本地 MVP。

## 1. 结论与修订摘要

原方案的技术方向（Vue 3 + FastAPI + 本地 Agent Runtime + Workspace）可行，但原范围不适合剩余工期，且对 Shell 安全边界的描述过强。因此本版作如下调整：

1. 将交付目标从“完整 Coding Agent 产品”收敛为“可稳定演示一个真实任务的 MVP”。
2. P0 只保留评分核心：原生 tool calling、自研 Agent Loop、上下文管理、工具本地执行、循环终止、错误恢复、过程展示。
3. 运行模型固定为单用户、单进程、单 Workspace、同一时刻最多一个任务；持久化、多任务并发、历史记录和取消留到 P2。
4. 前端 P0 仅实现任务输入、状态、时间线、工具调用/结果、命令输出和最终总结；文件树、代码查看器和高级 Diff 降为 P1。
5. 明确安全能力边界：文件工具可通过路径解析约束在 Workspace 内；普通本地 Shell 仅能做到工作目录、超时和危险命令拦截，不能等同于 OS 级沙箱。
6. 模型调用只使用模型厂商 API 或 OpenAI 兼容 API 的原生 tool calling，不引入任何 Agent 框架/SDK，也不依赖云端代码执行或文件工具。

## 2. 项目要求追踪

| 项目要求 | 设计响应 | 验收证据 |
|---|---|---|
| 个人独立设计并实现 coding agent | 自研 Agent Loop、工具注册与执行、上下文、终止和错误处理 | 源码、提交历史、设计说明 |
| 自主读取/写入文件、执行命令 | 六个本地工具直接访问用户授权的 Workspace | Timeline、真实文件变化、命令输出 |
| 禁止现成 Agent 框架/SDK | 仅使用 FastAPI/Vue/httpx 等通用库和模型原生 tool calling | 依赖清单、LLM 客户端源码 |
| 不依赖托管代码执行/文件工具 | 文件与 Shell 工具均在本地 Runtime 实现 | 工具源码与现场演示 |
| 自行实现关键逻辑 | Conversation、Context、Tool Dispatch、Stop、Recovery 均在仓库内 | 模块与单元测试 |
| API Key 不入库 | 仅从环境变量读取，提供无密钥的 `.env.example` | Git 搜索与配置代码 |
| 提交 Git 仓库、README.txt、视频 | 计划中设置单独交付检查点 | 最终压缩包和公开仓库 |
| 面试能解释设计决策 | 事件日志与模块边界对应 Agent 每一步决策 | 设计文档、演示脚本 |

## 3. MVP 目标与非目标

### 3.1 P0：必须完成

- 用户以 `coding-agent <workspace>` 启动本地服务。
- 用户在 Web 页面提交一个自然语言编程任务。
- Runtime 使用模型原生 tool calling 自主选择并执行工具。
- 至少实现 `list_files`、`read_file`、`search_text`、`write_file`、`replace_in_file`、`run_command`。
- 工具结果返回模型，形成 `LLM -> Tool -> Observation -> LLM` 闭环。
- 支持最大步数、连续重复调用、超时和不可恢复错误等终止条件。
- 前端通过 SSE 展示任务、工具、文件变化、命令输出与最终结果。
- 用一个含真实 Bug 和测试的样例项目完成端到端演示。

### 3.2 P1：P0 稳定后再做

- Workspace 文件树和文件查看。
- 统一 Diff 展示及文件修改统计。
- 自动发现 `pytest`、`npm test` 等验证命令。
- 更严格的上下文裁剪和摘要。
- 构建 Vue 静态资源并由 FastAPI 单端口托管。

## 4. 运行模式

```text
Browser / Vue 3
      │ REST + SSE
      ▼
FastAPI API
      │
      ├── TaskManager（单活动任务，内存状态）
      ├── EventBus（事件历史 + SSE 订阅）
      └── AgentRuntime
            ├── Conversation / Context
            ├── LLMClient（原生 tool calling）
            ├── StopController
            └── ToolRegistry
                  ├── File/Search Tools
                  └── Shell Tool
                        │
                        ▼
                  Local Workspace
```

开发时：Vue 使用 `localhost:5173`，FastAPI 使用 `localhost:8000`。最终演示优先构建前端并由 FastAPI 托管，减少启动步骤。若静态托管未完成，双进程启动仍可作为可接受降级方案。

## 5. 核心模块设计

### 5.1 CLI 与配置

`coding-agent <workspace>` 负责：

1. 将 Workspace 解析为真实绝对路径并确认存在且为目录。
2. 从环境变量读取 `CODING_AGENT_API_KEY`、`CODING_AGENT_BASE_URL`、`CODING_AGENT_MODEL`。
3. 创建单例 Workspace、TaskManager、EventBus 和 AgentRuntime。
4. 启动 Uvicorn；浏览器自动打开属于 P1。

API Key 不得写入代码、README、日志、事件或前端响应。

### 5.2 TaskManager

任务状态：

```text
PENDING -> RUNNING -> COMPLETED
                   -> FAILED
```

MVP 同一时刻只允许一个活动任务。新任务在已有任务运行时返回 HTTP 409，避免引入并发、隔离和取消语义。任务保存在内存；服务重启后丢失是已知限制。

### 5.3 AgentRuntime

每轮执行：

```text
构建受限 Context
  -> 调用 LLM
  -> 记录 assistant message
  -> 无 tool call：完成并总结
  -> 有 tool call：校验参数并依次执行
  -> 将 Tool Result 加入 Conversation
  -> 检查停止条件
  -> 下一轮
```

模型不能直接接触文件系统或 Shell；它只能返回结构化 Tool Call。Runtime 是唯一调度者。

### 5.4 Conversation 与 Context

Conversation 保存本任务的完整逻辑消息：system、user、assistant、tool。发送模型前由 ContextBuilder 控制体积：

- 始终保留 System Prompt 和原始 Task。
- 保留最近若干轮消息。
- 单次文件读取、搜索和命令输出分别设字符上限并标记 `truncated`。
- MVP 超限时采用确定性截断；自动摘要属于 P1，避免为了“智能压缩”再引入一次不可控模型调用。

### 5.5 LLMClient

- 通过 `httpx` 调用 OpenAI 兼容的 chat completions/tool calling 接口。
- 不使用 OpenAI Agents SDK、LangChain、LlamaIndex、AutoGen、CrewAI 等 Agent 框架。
- LLMClient 只负责请求/响应转换，不负责循环、工具执行或任务状态。
- 超时、HTTP 错误、无效 JSON 和未知工具都转换为可观察错误；可恢复错误作为 Tool/Runtime Observation，超过重试阈值才失败。

### 5.6 ToolRegistry

统一维护工具名称、JSON Schema 与执行函数。调用前必须：

1. 检查工具是否注册。
2. 校验参数类型和必填项。
3. 发布 `tool_started`。
4. 执行并捕获错误。
5. 截断过大输出。
6. 发布 `tool_finished`；修改文件时追加 `file_changed`。

六个 P0 工具：

| 工具 | 主要参数 | 行为 |
|---|---|---|
| `list_files` | `path`、`max_entries` | 返回目录树，忽略 `.git`、`node_modules` 等目录 |
| `read_file` | `path`、`start_line`、`end_line` | 按行读取 UTF-8 文本并限制输出 |
| `search_text` | `query`、`path`、`max_results` | 在文本文件中搜索并返回文件、行号、片段 |
| `write_file` | `path`、`content` | 创建或整体写入文件并返回 diff 摘要 |
| `replace_in_file` | `path`、`old_text`、`new_text` | 默认要求旧文本唯一匹配，避免误改 |
| `run_command` | `command`、`timeout_seconds` | 在 Workspace 为 cwd 的本地子进程中执行 |

### 5.7 StopController

停止条件不交给模型单独决定：

- 模型返回无 Tool Call 的最终文本：`COMPLETED`。
- 达到 `MAX_STEPS`（默认 20）：`FAILED`，错误为 step limit。
- 同一工具与参数连续出现 3 次：向模型注入一次纠偏 Observation；再次重复则失败。
- 命令超时：作为 Observation 返回，Agent 可换方法；连续超时达到阈值则失败。
- LLM 或 Runtime 连续不可恢复错误达到重试阈值：`FAILED`。

“完成”不等于“测试一定通过”。最终事件必须分别说明任务状态、修改内容、执行过的验证命令和实际结果，禁止把未验证描述成已验证。

## 6. 事件与 API

### 6.1 事件信封

```json
{
  "id": "event-id",
  "task_id": "task-id",
  "type": "tool_finished",
  "timestamp": "2026-08-27T12:00:00Z",
  "step": 3,
  "payload": {}
}
```

事件类型：`task_started`、`assistant_message`、`tool_started`、`tool_finished`、`file_changed`、`command_finished`、`task_completed`、`task_failed`。

事件先写入该任务的内存历史，再通知 SSE 订阅者。浏览器断线重连时可先收到历史事件，避免演示时丢步骤。

### 6.2 REST/SSE 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/tasks` | 创建并异步启动任务 |
| `GET` | `/api/tasks/{task_id}` | 查询任务状态与最终结果 |
| `GET` | `/api/tasks/{task_id}/events` | SSE 事件流，先回放后订阅 |
| `GET` | `/api/workspace/tree` | P1：查询目录树 |
| `GET` | `/api/workspace/file?path=...` | P1：读取供 UI 展示的文件 |
| `GET` | `/health` | 健康检查 |

## 7. 安全边界与已知限制

### 7.1 文件工具边界

- 只接受相对路径；拒绝绝对路径、空字节和越界路径。
- 拼接 Workspace 后执行规范化/真实路径解析，再确认结果仍位于根目录内。
- 新文件先校验其最近存在父目录的真实路径，避免符号链接逃逸。
- 默认忽略或拒绝 `.git`、`.env`、密钥文件和依赖缓存目录。
- 所有写操作记录目标路径、前后 diff 摘要和结果。

### 7.2 Shell 边界

`cwd=workspace` 不是安全沙箱。MVP 通过命令超时、输出限制、危险命令模式拒绝和前端可见日志降低风险，但无法阻止一个获准进程主动访问 Workspace 外文件。演示只在专用样例 Workspace 内运行，不以管理员权限启动。

如果未来需要把“只能访问 Workspace”升级为强保证，必须增加容器、受限用户、Windows Sandbox/Job Object 或其他 OS 级隔离；这不属于本次 P0。

### 7.3 Prompt Injection 与凭据

仓库文件和命令输出都视为不可信数据。System Prompt 明确禁止把文件中的指令当作系统指令；日志层对 API Key 做脱敏；工具结果不返回进程环境变量。

## 8. 前端 MVP

单页界面包含：

- Task 输入框与 Run 按钮。
- 当前 Workspace 名称和任务状态。
- 按事件顺序展示的 Agent Timeline。
- Tool 卡片：工具名、参数摘要、成功/失败、耗时。
- Shell 卡片：命令、stdout/stderr、exit code、是否超时。
- File Change 卡片：路径和简化 diff。
- 最终结果卡片：完成状态、改动、验证及错误。

运行中禁止重复提交。SSE 断开时显示连接状态，但不自动创建新任务。

## 9. 工程结构

```text
coding-agent/
├── backend/
│   └── app/
│       ├── api/                 # FastAPI 路由
│       ├── agent/               # Runtime、Conversation、Stop
│       ├── core/                # 配置和事件总线
│       ├── models/              # Task/Event 数据模型
│       ├── services/            # TaskManager
│       ├── tools/               # Workspace 与六个本地工具
│       ├── cli.py
│       └── main.py
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── App.vue
│   │   ├── main.ts
│   │   └── types.ts
│   ├── package.json
│   └── vite.config.ts
├── tests/                       # 后端核心单元测试
├── demo_workspace/              # 可重复演示的 Bug 项目（实施阶段创建）
├── docs/
│   ├── Coding Agent 项目结构与功能设计文档.md
│   ├── Coding Agent 实施计划.md
│   └── 项目要求.pdf
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md                    # 开发说明
└── README.txt                   # 1000 汉字以内的正式提交说明
```

## 10. 关键决策及理由

1. **单任务串行**：演示目标关注 Agent 自主闭环，不值得在最后一周承担并发隔离风险。
2. **内存状态**：任务持久化不是要求；内存模型更容易保证事件顺序并快速调试。
3. **SSE 而非 WebSocket**：服务端只需单向推送事件，SSE 实现更少、浏览器原生支持重连。
4. **精确替换优先**：`replace_in_file` 要求唯一命中，比让模型整文件重写更容易审计和生成 diff。
5. **确定性停止器**：模型负责决策，但 Runtime 必须能制止无限循环、重复动作和卡死命令。
6. **真实披露 Shell 边界**：本地进程不是沙箱；演示安全与生产安全不能混为一谈。

## 11. 验收标准

### 11.1 核心单元测试

- 路径穿越和符号链接逃逸被拒绝。
- 文件读取行范围、输出截断正确。
- `replace_in_file` 对零匹配和多匹配报错。
- Shell 超时能终止并返回结构化结果。
- 重复 Tool Call 和最大步骤能停止循环。
- LLM 错误不会泄露 API Key。

### 11.2 端到端验收

在 `demo_workspace` 中准备一个失败测试。输入修复任务后，必须观察到：

1. Agent 自主列目录、搜索并读取源码/测试。
2. Agent 修改真实文件并产生 `file_changed` 事件。
3. Agent 执行测试；若首次失败，能根据输出继续修改。
4. 最终测试通过，Timeline 和最终总结与真实结果一致。
5. 全程未调用任何现成 Agent 框架或托管代码执行工具。

### 11.3 提交前检查

- 公开 Git 仓库保留真实、连续提交历史。
- `README.txt` 不超过 1000 汉字并包含仓库地址、运行方式和特色功能。
- 2 分钟内 MP4 展示真实任务闭环，文件不超过 200 MB。
- 仓库、README.txt、视频和 Git 历史中不存在 API Key。
- 截止后不再向公开仓库推送提交。

## 12. 最终 Demo 路径

```text
启动 coding-agent demo_workspace
  -> 页面提交“修复 divide 除零行为并确保测试通过”
  -> Agent 查看目录和测试
  -> Agent 读取/搜索实现
  -> Agent 局部修改源码
  -> Agent 运行 pytest
  -> 根据真实结果继续或结束
  -> 页面展示 Timeline、Diff 摘要、命令结果和最终总结
```

这个范围既满足题目对“编程智能体”的定义，也把时间投入集中在评委会追问的部分：Agent 为什么这样运行、每一步由谁决定、工具如何落地、错误怎样反馈、循环为何会停止。
