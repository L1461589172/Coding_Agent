# Coding Agent 项目结构与功能设计文档

> 版本：v2.1（补充前后端逐文件职责与实际实现状态）
>
> 修订日期：2026-08-27
>
> 目标：在 2026-09-02 24:00 前交付一个能够完成真实编程任务、过程可解释、核心 Agent 逻辑自行实现的本地 MVP。

> 阅读说明：功能设计章节描述目标；第 9 节和第 13 节描述当前代码。文件已存在或接口已定义，不代表对应 Agent 能力已经实现。

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

## 9. 前后端代码结构与实现状态

### 9.1 阅读范围与状态口径

本节按 2026-08-27 的实际源码核对，覆盖 `backend/app/` 下全部 25 个 Python 文件，以及前端 8 个源码文件和 5 个入口/工程配置文件。不列入虚拟环境、依赖目录、缓存和生成的构建产物。

- **已实现**：存在可执行逻辑；是否已接入当前默认链路会另外注明。
- **接口骨架**：仅有类型、参数 Schema、Protocol 或返回 `NOT_IMPLEMENTED` 的入口，没有对应业务执行能力。
- **待实现**：尚未编写的行为，或已有逻辑尚未接入 Runtime；不等于要求现在新增一个文件。
- 表格中的“无本阶段新增项”仅表示该辅助文件已满足当前职责，不表示整个模块或项目完成。

当前完整可观察链路是“创建任务 -> 框架说明 -> `FAILED / NOT_IMPLEMENTED`”。真实 LLM 决策、文件修改、命令执行和自动验证仍待完成。

### 9.2 前端结构与逐文件说明

```text
frontend/
├── index.html                    # HTML 页面与 Vue 挂载点
├── package.json                  # 依赖、Node 约束与开发/构建脚本
├── package-lock.json             # npm 依赖锁文件
├── tsconfig.json                 # TypeScript 严格检查
├── vite.config.ts                # Vue 插件、端口与后端代理
└── src/
    ├── main.ts                   # 创建并挂载 Vue 应用
    ├── App.vue                   # 页面布局、任务状态与事件编排
    ├── types.ts                  # Task/Event/Metadata 类型
    ├── style.css                 # 全局样式与窄屏布局
    ├── api/
    │   └── client.ts             # REST 客户端与 EventSource
    └── components/
        ├── TaskInput.vue         # 任务输入与提交
        ├── TaskStatus.vue        # 任务状态展示
        └── AgentTimeline.vue     # 通用事件时间线
```

下表文件路径相对于 `frontend/`，点击可查看源码。

| 文件 | 功能简介 | 已实现的部分 | 待实现的部分 |
|---|---|---|---|
| [index.html](../frontend/index.html) | 页面入口 | 中文语言标记、viewport、标题、`#app` 挂载点及模块入口 | 无本阶段新增项 |
| [package.json](../frontend/package.json) | 依赖与命令定义 | Vue/Vite/TypeScript 依赖，`dev`、`typecheck`、`build`、`preview` 脚本 | 若引入前端组件单测，再增加测试依赖与脚本；目前无 `test` 脚本 |
| [package-lock.json](../frontend/package-lock.json) | 锁定依赖解析结果 | 保存 npm 依赖版本与完整性信息，供 `npm ci` 使用 | 无业务逻辑；依赖变更时由 npm 更新，不手改 |
| [tsconfig.json](../frontend/tsconfig.json) | 类型检查配置 | strict、Bundler 模块解析、DOM 类型及 Vue/TS 文件检查范围 | 无本阶段新增项 |
| [vite.config.ts](../frontend/vite.config.ts) | 开发与预览服务配置 | Vue 插件、固定 5173 端口、`/api` 和 `/health` 代理；支持 `CODING_AGENT_BACKEND_URL` | 前后端单端口交付需后端静态托管配合；当前构建预览仍依赖独立后端 |
| [src/main.ts](../frontend/src/main.ts) | Vue 启动入口 | 引入根组件和样式，创建应用并挂载 | 当前单页不需要路由/全局状态插件；无本阶段新增项 |
| [src/App.vue](../frontend/src/App.vue) | 工作台与状态编排 | 获取工作区元数据、创建/查询任务、订阅事件、按 ID 去重、终态关闭事件流并查询结果；防重复提交、错误/断线提示、手动重连及卸载清理 | 真实 Tool/Shell/Diff 交互、文件树/代码查看；页面刷新后恢复当前任务尚未实现 |
| [src/types.ts](../frontend/src/types.ts) | 前后端数据契约 | TaskStatus、Task、EventType、AgentEvent、Metadata；与现有 API 字段对应 | 工具/命令/文件变化的结构化 payload 类型；当前 payload 仍是通用字典，类型声明不是运行时校验 |
| [src/style.css](../frontend/src/style.css) | 页面样式 | 暗色布局、状态/事件卡片、按钮与焦点样式；800px 以下切换窄屏布局 | 后续专用工具卡片、终端输出及 Diff 样式；主题切换不在本阶段 |
| [src/api/client.ts](../frontend/src/api/client.ts) | HTTP 与 SSE 接入 | 元数据/创建/查询请求、10 秒请求超时、HTTP 错误提示；EventSource、游标、基础事件检查与关闭函数 | 完整响应/事件 payload 校验，长期断线与服务重启后的恢复策略；当前没有自动重试创建任务 |
| [src/components/TaskInput.vue](../frontend/src/components/TaskInput.vue) | 输入组件 | 多行输入、8000 字符上限、去除首尾空白、空内容禁用、向 App 发出提交事件；禁用状态由 App 传入 | 用户取消/重试控件尚未实现；不得将禁用输入理解为后端取消能力 |
| [src/components/TaskStatus.vue](../frontend/src/components/TaskStatus.vue) | 状态组件 | 展示四种状态、任务 ID 前缀和初始就绪提示 | 真实步骤数、工具调用数、修改文件数、耗时和测试统计 |
| [src/components/AgentTimeline.vue](../frontend/src/components/AgentTimeline.vue) | 时间线组件 | 接收事件列表、空状态、类型名称、时间与通用文本/JSON 展示；使用文本插值，不执行事件中的 HTML | 专用 Tool Call、Terminal、Changes、Diff 展示；存在事件名称映射不代表后端已生成对应真实事件 |

职责约束：组件只负责展示/发出交互事件，`App.vue` 管理当前页面状态，`api/client.ts` 负责网络请求。前端不调用模型、不访问本地文件系统，也不执行 Shell。目前没有独立 `pages/`、`stores/`、`router/` 目录，也没有 Pinia。

### 9.3 后端结构与逐文件说明

```text
backend/app/
├── __init__.py                   # 包说明与版本
├── cli.py                        # coding-agent 命令入口
├── main.py                       # 应用组装、生命周期与安全中间件
├── api/
│   ├── __init__.py               # API 包标识
│   └── routes.py                 # 元数据、任务与 SSE 接口
├── core/
│   ├── __init__.py               # 基础设施包标识
│   ├── config.py                 # Settings 配置
│   └── events.py                 # 每任务 EventLog
├── models/
│   ├── __init__.py               # 数据模型包标识
│   ├── task.py                   # 任务/请求/错误模型
│   └── event.py                  # 事件模型与 SSE 编码
├── services/
│   ├── __init__.py               # 应用服务包标识
│   └── tasks.py                  # TaskManager
├── agent/
│   ├── __init__.py               # Agent 包标识
│   ├── runtime.py                # 运行接口与占位 Runtime
│   ├── llm.py                    # 模型客户端协议
│   ├── context.py                # 对话与最近完整轮次选择
│   └── stop.py                   # 独立停止策略
└── tools/
    ├── __init__.py               # 工具包标识
    ├── base.py                   # 工具参数、定义与结果契约
    ├── registry.py               # 工具注册和参数校验分发
    ├── workspace.py              # 路径守卫
    ├── files.py                  # 四个文件工具骨架
    ├── search.py                 # 文本搜索工具骨架
    └── shell.py                  # 命令执行工具骨架
```

下表文件路径相对于 `backend/app/`。

#### 入口、API、基础设施与数据模型

| 文件 | 功能简介 | 已实现的部分 | 待实现的部分 |
|---|---|---|---|
| [cli.py](../backend/app/cli.py) | 命令行入口 | 解析必填 Workspace 和 `--port`；读取配置、创建应用；固定本机地址、单 worker 启动 Uvicorn | 自动打开浏览器属于 P1；目前无多 worker、远程监听或自动重载选项 |
| [main.py](../backend/app/main.py) | 应用工厂与依赖组装 | `create_app` 创建 Workspace/Registry，在 lifespan 内创建并关闭 TaskManager；注入测试 Runner；Host/Origin/CORS 限制、健康检查、根路径提示 | 真实模型客户端的创建/释放、Vue 静态产物托管；现有中间件不等于身份认证或系统沙箱 |
| [api/routes.py](../backend/app/api/routes.py) | HTTP API 层 | 元数据、任务创建/查询、SSE；409/404/503 错误；游标检查、历史续传与终态 204 | 文件树/文件读取 API；不在本阶段的取消/历史/重试接口尚不存在 |
| [core/config.py](../backend/app/core/config.py) | 集中配置 | 环境变量读取、工作区参数优先、正整数/端口校验、Origin 列表；密钥排除在 repr 外 | 模型配置可用性验证；`max_steps` 已读取但未传入真实 Loop；不会自动加载 `.env` |
| [core/events.py](../backend/app/core/events.py) | 事件存储和订阅 | 每任务内存 EventLog、递增 ID、Condition 通知、回放与等待、默认 15 秒心跳、终态拒绝追加 | 单事件/任务历史体积限制和敏感内容处理；持久化不在本阶段 |
| [models/task.py](../backend/app/models/task.py) | 任务数据模型 | TaskCreate 输入长度/空白/额外字段检查；四种状态、UUID、时间、结果、结构化错误与 scaffold 模式 | 真实步骤、验证结果、修改文件清单等字段；没有 CANCELLED 状态 |
| [models/event.py](../backend/app/models/event.py) | 事件信封与编码 | 8 种事件名称、终态集合、时间/step/payload 字段；`as_sse()` 生成 ID 与单行 JSON | 各事件 payload 的专用模型、真实工具事件数据；SSE 编码位于此文件而非 events.py |
| [services/tasks.py](../backend/app/services/tasks.py) | 任务生命周期 | 预留单活动任务、创建后台协程、查询副本、默认 100 任务上限；结果/异常转换、终态事件、释放活动占用和关闭清理（含尚未调度的任务） | 真实 TaskRunner 接入；当前完成分支只由测试 Runner 验证，不代表默认 Agent 能完成任务 |

#### Agent 与工具模块

| 文件 | 功能简介 | 已实现的部分 | 待实现的部分 |
|---|---|---|---|
| [agent/runtime.py](../backend/app/agent/runtime.py) | Agent 执行入口 | TaskRunner 协议、Workspace/Registry 引用、框架说明事件；抛出 RuntimeNotReady，由 TaskManager 转为 NOT_IMPLEMENTED | 完整 Agent Loop：构建上下文、调用模型、执行工具、回填结果、验证和判断结束；当前不调用 Registry.execute |
| [agent/llm.py](../backend/app/agent/llm.py) | 模型适配接口 | **接口骨架**：ToolCall、ModelReply 和 LLMClient 的 `complete`/`close` 协议 | 具体 HTTP 客户端、鉴权、响应解析、超时、重试和关闭；没有任何真实模型请求 |
| [agent/context.py](../backend/app/agent/context.py) | 对话管理 | 保存 system/user 和完整交互轮次；校验调用 ID 与结果配对；深拷贝；默认选择最近 8 轮并保留初始任务 | 接入 Runtime、字符/token 预算、单次结果截断和摘要；不是完整 ContextManager，尚无单独 context_builder.py |
| [agent/stop.py](../backend/app/agent/stop.py) | 确定性停止规则 | 独立方法检查最大步数；按规范化名称/参数识别连续重复，第三次返回 warn、第四次返回 stop | Runtime 调用这些方法、插入纠偏 Observation、执行终止动作；超时/连续错误限制尚未实现 |
| [tools/base.py](../backend/app/tools/base.py) | 通用工具契约 | 严格参数模型、禁止额外字段、ToolResult、异步 handler 类型、ToolSpec 与函数 Schema 生成 | 统一结果大小限制和实际截断；`truncated` 字段存在不代表已实现截断逻辑 |
| [tools/registry.py](../backend/app/tools/registry.py) | 工具注册/分发 | 六工具注册、重复名称拒绝、Schema 输出、参数校验、await handler；转换 UNKNOWN_TOOL/INVALID_ARGUMENTS/TOOL_ERROR，不回显原始异常 | 注册真实 handler、接入 Runtime、工具事件/耗时/输出限制；当前不会自动调用 Workspace.resolve |
| [tools/workspace.py](../backend/app/tools/workspace.py) | 工作区路径约束 | 根目录存在性检查；拒绝绝对路径、上级遍历、空字节、Windows 驱动器/数据流路径和常见敏感路径；真实路径与符号链接逃逸检查 | 所有真实文件操作接入守卫；处理检查后路径变化等竞争条件；不隔离 Shell 进程 |
| [tools/files.py](../backend/app/tools/files.py) | 文件工具集合 | **接口骨架**：list_files/read_file/write_file/replace_in_file 的参数、基础大小/数量限制和注册定义；共用占位 handler | 目录遍历、分行读取、编码/文件大小检查、写入、唯一匹配替换及 Diff；当前不访问文件内容 |
| [tools/search.py](../backend/app/tools/search.py) | 文本搜索工具 | **接口骨架**：query/path/max_results 参数限制、搜索工具注册、未实现结果 | 真正遍历文本、过滤文件、返回路径/行号/片段、控制扫描范围和截断 |
| [tools/shell.py](../backend/app/tools/shell.py) | 本地命令工具 | **接口骨架**：command/timeout_seconds 参数限制与未实现结果 | 子进程创建、cwd、环境变量隔离、命令策略、超时、输出捕获/限制、退出码与进程树清理；当前没有 subprocess 调用 |

#### Python 包标识文件

这些文件不是待填充的业务模块，除根包提供版本号外，当前均只负责包标识/职责说明。

| 文件 | 功能简介与已实现部分 | 待实现部分 |
|---|---|---|
| [__init__.py](../backend/app/__init__.py) | 根包说明与 `__version__ = "0.1.0"`，供应用元数据使用 | 无本阶段新增项；发布时维护版本 |
| [api/__init__.py](../backend/app/api/__init__.py) | API 包与边界说明 | 无本阶段新增项 |
| [core/__init__.py](../backend/app/core/__init__.py) | 配置/事件基础设施包说明 | 无本阶段新增项 |
| [models/__init__.py](../backend/app/models/__init__.py) | 数据模型包说明 | 无本阶段新增项 |
| [services/__init__.py](../backend/app/services/__init__.py) | 应用服务包说明 | 无本阶段新增项 |
| [agent/__init__.py](../backend/app/agent/__init__.py) | Agent 自研逻辑包说明 | 无本阶段新增项 |
| [tools/__init__.py](../backend/app/tools/__init__.py) | 工具协议包说明，标记 M0 执行关闭 | 无独立业务实现；工具接入后同步说明 |

### 9.4 当前前后端调用关系

```text
TaskInput.vue --submit--> App.vue
                             │
                             ▼
                    api/client.ts（createTask）
                             │ POST /api/tasks
                             ▼
                    api/routes.py
                             │
                             ▼
                    services/tasks.py（TaskManager）
                             │ run(task, events)
                             ▼
                    agent/runtime.py（占位 Runtime）
                             │ 说明消息 + RuntimeNotReady
                             ▼
                    TaskManager 标记 FAILED / NOT_IMPLEMENTED

TaskManager / Runtime -> core/events.py（EventLog）
                                │ models/event.py 编码
                                ▼
                         api/routes.py（SSE）
                                │
                                ▼
                    api/client.ts -> App.vue
                                      ├── TaskStatus.vue
                                      ├── AgentTimeline.vue
                                      └── 最终结果区域（仍位于 App.vue）
```

连接不是实现能力的证明：`main.py` 已创建 Registry 并交给 Runtime，但占位 Runtime 没有使用它执行工具；LLMClient、Conversation、StopController 也尚未被默认 Runtime 调用。

设计中的 EventBus 对应当前 `core/events.py` 的每任务 EventLog；不存在单独的 `event_bus.py`。Tool Call、Terminal、Diff 与最终结果目前也没有独立 Vue 文件，不能按目标功能名称推断它们已存在。

### 9.5 API 与页面功能对照

| 接口/能力 | 后端文件 | 前端使用位置 | 当前状态 |
|---|---|---|---|
| `GET /health` | `main.py` | 未由页面自动调用；可手动检查 | 已实现服务健康信息，agent_ready=false |
| `GET /api/meta` | `api/routes.py` | client.getMetadata -> App 工作区与工具清单 | 已实现，只返回工作区名称与工具名称，不是文件树 |
| `POST /api/tasks` | `api/routes.py`、`services/tasks.py` | TaskInput -> App -> client.createTask | 已实现任务创建，默认运行后返回未实现状态 |
| `GET /api/tasks/{id}` | `api/routes.py` | client.getTask -> App 状态/最终结果 | 已实现内存查询 |
| `GET /api/tasks/{id}/events` | `api/routes.py`、`core/events.py` | client.watchTask -> App -> Timeline | 已实现回放/实时订阅；默认流程只有启动、说明、失败三个事件 |
| `GET /api/workspace/tree` | 尚无路由 | 尚无文件树组件 | 待实现（P1），当前返回 404 |
| `GET /api/workspace/file?path=...` | 尚无路由 | 尚无 Code Viewer | 待实现（P1），当前返回 404 |
| Tool/Shell/File Change 专用结果 | 仅在 models/event.py 定义事件名称 | Timeline 能展示通用 JSON | 实际事件产生和专用展示待实现，不是已完成的工具功能 |

`GET /` 的后端响应只是启动说明；`frontend/dist/` 即使已经构建，也不会自动由 FastAPI 托管。页面重连保留的是当前页面内的 task_id/事件游标，整页刷新后的任务恢复尚未实现。

### 9.6 工程配置与验证文件

| 文件 | 功能/已实现部分 | 待实现或维护说明 |
|---|---|---|
| [pyproject.toml](../pyproject.toml) | Python 打包、coding-agent 入口、运行/开发依赖、pytest/Ruff 配置 | 真实功能所需依赖在对应阶段补充；不引入 Agent SDK |
| [constraints.txt](../constraints.txt) | Python 已验证依赖快照 | 依赖升级后重新验证并维护 |
| [.env.example](../.env.example) | 环境变量模板，不含真实密钥 | 不会自动加载；当前模型字段只是预留 |
| [.gitignore](../.gitignore) | 忽略环境、依赖、缓存、密钥配置和 QA 产物 | 不提供运行时安全隔离 |
| [tests/conftest.py](../tests/conftest.py) | 临时 Workspace 与隔离的 API 测试客户端 | 后续测试 fixture 扩展 |
| [tests/test_api.py](../tests/test_api.py) | 请求校验、状态、SSE 回放、Host/Origin、409/503、异常不透出、关闭行为 | 真实工具/API 集成和长期断线恢复验收 |
| [tests/test_workspace.py](../tests/test_workspace.py) | 相对路径、越界、敏感路径、符号链接逃逸测试 | 真正文件读写时的安全性与跨平台边界 |
| [tests/test_agent_contracts.py](../tests/test_agent_contracts.py) | 配置、Context 配对、Stop 独立策略、工具 Schema 与未实现结果 | 真实 LLM 适配、工具执行、预算/终止的完整 Loop 测试 |
| [tests/test_events.py](../tests/test_events.py) | 实时订阅/历史回放、心跳、读者断开、终态禁止追加 | 大载荷、多订阅者和历史体积限制测试 |
| [tests/test_task_manager.py](../tests/test_task_manager.py) | 创建后立即关闭、注入测试 Runner 的成功分支 | 默认真实 Runtime 完成任务的测试 |
| [scripts/smoke_browser.cjs](../scripts/smoke_browser.cjs) | 用 Playwright/Edge 检查框架提交、三事件、未实现结果与窄屏布局 | 非 Vue 组件单测，也不是 Agent 修复代码的 E2E；工具卡片和复杂断线场景待补 |
| [demo_workspace/README.md](../demo_workspace/README.md) | 可指定的工作区占位说明 | 真实 Bug 源码、失败测试与重复演示数据尚未创建 |

根目录 [README.md](../README.md) 负责环境配置和运行说明；[基础框架修改说明](Coding%20Agent%20基础框架修改说明.md) 保存 M0 的交付与验证记录；[实施计划](Coding%20Agent%20实施计划.md) 负责里程碑和待办。正式提交用 `README.txt` 尚未创建，不将它列为已存在的源码文件。

### 9.7 剩余实现工作与落点

| 阶段 | 前端待实现 | 后端待实现 | 主要落点 |
|---|---|---|---|
| M1：本地工具 | 暂不扩展展示，先确定结构化输出字段 | 六个工具真实执行、路径校验接入、Diff、Shell 超时/输出限制 | `tools/files.py`、`search.py`、`shell.py`、`workspace.py`、`registry.py` |
| M2：Agent 闭环 | 准备接收真实工具事件 | LLM 具体适配、循环、结果回填、上下文预算、Stop 与恢复机制、事件载荷限制 | `agent/llm.py`、`runtime.py`、`context.py`、`stop.py`、`core/events.py` |
| M3：执行过程展示 | 专用 Tool/Shell/File Change 卡片、统计和连接恢复验收 | 真实中间事件与结构化结果，保持 API/前端类型一致 | `App.vue`、`types.ts`、`api/client.ts`、`components/`；`models/event.py`、`models/task.py` |
| P1：Workspace / 静态托管 | 文件树、Code Viewer、Diff Viewer | 文件查询 API、前端静态产物托管 | 未来扩展 `components/`、`api/routes.py`、`main.py`；新增文件名尚未确定 |
| M4：真实 Demo | 展示真实改动及测试结果 | 对真实项目完成探索、修改和验证 | `demo_workspace/` 及新增端到端测试 |

多用户、并行任务、长期记忆和数据库持久化不因本表列出待办而自动纳入本轮范围。后续新增或完成文件时，应同时更新本节“已实现/待实现”列与实施计划，避免仅以存在同名文件判断功能完成。

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

## 13. 基础框架实现状态（2026-08-27）

功能设计章节描述目标，不代表全部完成；第 9 节与本节描述当前实现。M0 已创建可启动的后端和前端，以及后续功能的模块接口；真实编程能力仍按实施计划推进。

- 启动：`coding-agent <workspace>` 已可用，固定监听 `127.0.0.1`、单 worker；Vue 独立启动于 5173。
- API：实现 `/health`、`/api/meta`、创建/查询任务、任务 SSE；文件树和文件读取 API 尚未实现。
- 状态：默认 Runtime 明确以 `FAILED / NOT_IMPLEMENTED` 结束，不产生伪造的文件修改、命令结果或成功总结。
- 工具：六种工具的 Schema、参数校验和注册入口已创建，执行函数均关闭，等待 M1 实现。
- LLM：只建立客户端协议与模型返回结构，未实现模型供应商适配器或外部请求。
- 上下文与终止：完整轮次裁剪和重复/步数策略有单元测试；尚未接入完整 Loop，也没有 token 预算或命令超时控制。
- EventBus 在代码中以每任务 `EventLog` 实现。事件 `id` 是任务内递增数字字符串，用于 `Last-Event-ID` / `after` 续传；终态已读完返回 204。
- TaskManager 保留至多 100 个内存任务，超过上限返回 503。现阶段每个框架任务只有三个小事件；真实工具接入前还必须增加事件载荷/历史体积限制。
- 安全：先实现路径越界与常见敏感路径校验、Host/Origin 限制、配置与异常详情不透出；这些不是强沙箱，也不是完备的敏感内容扫描。
- 逐文件职责、实现状态和后续落点见第 9 节；环境与运行方式见根目录 README.md；M0 交付验证记录见《Coding Agent 基础框架修改说明》。
