# Coding Agent 项目结构与功能设计文档

> 版本：v2.7（M2 上下文总预算、结果裁剪与 Agent Loop）
>
> 修订日期：2026-08-27
>
> 目标：在 2026-09-02 24:00 前交付一个能够完成真实编程任务、过程可解释、核心 Agent 逻辑自行实现的本地 MVP。

> 阅读说明：当前为 M2 Agent Loop 接入后的工作区。目标架构不等于当前行为；第 9/13 节描述实际代码。M1 六工具、M2 HTTP、上下文预算与基础循环已实现，全量 234 passed；工具事件和连续错误恢复仍待完成。文档索引和验证口径见 [docs/README](README.md)。

## 1. 结论与修订摘要

原方案的技术方向（Vue 3 + FastAPI + 本地 Agent Runtime + Workspace）可行，但原范围不适合剩余工期，且对 Shell 安全边界的描述过强。因此本版作如下调整：

1. 将交付目标从“完整 Coding Agent 产品”收敛为“可稳定演示一个真实任务的 MVP”。
2. P0 只保留评分核心：原生 tool calling、自研 Agent Loop、上下文管理、工具本地执行、循环终止、错误恢复、过程展示。
3. 运行模型固定为单用户、单进程、单 Workspace、同一时刻最多一个任务；持久化、多任务并发、历史记录和取消留到 P2。
4. 前端 P0 仅实现任务输入、状态、时间线、工具调用/结果、命令输出和最终总结；文件树、代码查看器和高级 Diff 降为 P1。
5. 明确安全能力边界：文件工具可通过路径解析约束在 Workspace 内；普通本地 Shell 仅能做到工作目录、超时和危险命令拦截，不能等同于 OS 级沙箱。
6. 模型调用只使用模型厂商 API 或 OpenAI 兼容 API 的原生 tool calling，不引入任何 Agent 框架/SDK，也不依赖云端代码执行或文件工具。

## 2. 项目要求追踪

| 项目要求 | 设计响应 | 当前证据与缺口 |
|---|---|---|
| 个人独立设计并实现 coding agent | 自研 Loop、工具、上下文与停止策略 | 本地工具、上下文预算与基础 Agent Loop 已实现；真实供应商验收待完成 |
| 自主读取/写入文件、执行命令 | 六个本地工具供 Runtime 调度 | 独立工具可执行；模型自主调用与 Timeline 工具事件未接入 |
| 禁止现成 Agent 框架/SDK | 使用通用 Web/HTTP 库和原生 tool calling | 依赖中未引入 Agent 框架；LLMClient 已使用 httpx 自行适配 Chat Completions |
| 不依赖托管代码执行/文件工具 | 工具在本地 Workspace/进程执行 | tools 源码与真实工具测试已有；不是 OS 沙箱 |
| 自行实现关键逻辑 | 本地管理 Conversation、Tool Dispatch、Stop、Recovery | 轮次配对、总预算、工具分发、Stop 与基础循环已实现；Recovery 尚未实现 |
| API Key 不入库 | 环境变量读取、公开配置白名单 | Settings repr 隐藏密钥、通用错误不透出；完整历史/材料密钥扫描仍需交付前执行 |
| 提交 Git 仓库、README.txt、视频 | 独立交付检查点 | 已有本地提交；最终 README.txt、视频、压缩包未生成，未核对远程公开状态 |
| 面试能解释设计决策 | 模块与事件对应实际步骤 | 架构/工具说明已有；真实模型决策链路仍待实现和演示 |

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
- 高级交互式 Diff Viewer；工具返回的文本 Diff 已在 M1 实现，基础文件变化卡片仍属于 M3。
- 自动发现 `pytest`、`npm test` 等验证命令。
- 更精细的上下文选择和自动摘要；基本字符/token 总预算与确定性 ToolResult 裁剪已实现。
- 构建 Vue 静态资源并由 FastAPI 单端口托管。

## 4. 运行模式

下图同时是当前配置完整时的调用关系；配置不完整时 Runtime 安全降级为 scaffold。实际页面链路见第 9.4 节。

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

Conversation 保存本任务的完整逻辑消息：system、user、assistant、tool。发送模型前由 `Conversation.build_context()` 控制体积：

- 始终保留 System Prompt 和原始 Task。
- 保留最近若干轮消息。
- 工具层继续负责各自读取/搜索/命令上限；模型侧另对 ToolResult 做带状态与预览的 JSON 裁剪。
- MVP 超限时采用确定性截断；自动摘要属于 P1，避免为了“智能压缩”再引入一次不可控模型调用。

当前总预算同时限制紧凑 JSON 的字符数和确定性估算 token，并计入本次发送的工具 Schema。只选择最近完整轮次；system/原始任务或最新完整轮次无法容纳时显式失败，不发送孤立 tool result。实现细节见 [M2 Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md)。

### 5.5 LLMClient

- 通过 `httpx` 调用 OpenAI 兼容的 chat completions/tool calling 接口。
- 不使用 OpenAI Agents SDK、LangChain、LlamaIndex、AutoGen、CrewAI 等 Agent 框架。
- LLMClient 只负责请求/响应转换，不负责循环、工具执行或任务状态。
- 超时、HTTP 错误、无效 JSON 和未知工具都转换为可观察错误；可恢复错误作为 Tool/Runtime Observation，超过重试阈值才失败。

当前已实现客户端层能力，并已由 Agent Loop 调用：Bearer 鉴权、`/chat/completions` 非流式请求、既有工具 Schema 原样透传、严格 tool call 转换、安全错误、可配置超时/有限重试和幂等关闭。客户端错误会转换为结构化任务失败；跨轮连续错误恢复仍待实现。详见 [M2 HTTP 说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md) 与 [Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md)。

### 5.6 ToolRegistry

当前 ToolRegistry 维护名称、Schema、handler，执行严格参数校验并返回工具结果，不发布事件，也不统一统计所有工具的耗时。M2 接入时的目标流程是：

1. 检查工具是否注册。
2. 校验参数类型和必填项。
3. 由 Runtime/调度层发布 `tool_started`。
4. 执行并捕获错误。
5. 各工具已有读取/输出预算；Runtime 再控制整体上下文与事件体积。
6. Runtime/调度层发布 `tool_finished`，成功变更时追加 `file_changed`，命令执行追加 `command_finished`；这些事件目前尚未接入。

六个 P0 工具：

| 工具 | 主要参数 | 行为 |
|---|---|---|
| `list_files` | `path`、`max_entries` | 递归返回路径/类型的扁平列表，忽略 `.git`、`node_modules` 等目录 |
| `read_file` | `path`、`start_line`、`end_line` | 按行读取 UTF-8 文本并限制输出 |
| `search_text` | `query`、`path`、`max_results` | 在文本文件中搜索并返回文件、行号、片段 |
| `write_file` | `path`、`content` | 创建或整体写入文件并返回 diff 摘要 |
| `replace_in_file` | `path`、`old_text`、`new_text` | 必须唯一匹配，重叠匹配也计入多处；不提供强制全局替换选项 |
| `run_command` | `command`、`timeout_seconds` | 在 Workspace 根目录执行白名单 argv；不解释 Shell 运算符 |

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
  "id": "1",
  "task_id": "task-id",
  "type": "tool_finished",
  "timestamp": "2026-08-27T12:00:00Z",
  "step": 3,
  "payload": {}
}
```

事件类型：`task_started`、`assistant_message`、`tool_started`、`tool_finished`、`file_changed`、`command_finished`、`task_completed`、`task_failed`。

示例用于展示信封，不表示当前默认 Runtime 已发出 tool_finished。id 为任务内递增数字字符串；当前 Agent Loop 会发出 task_started、assistant_message、task_completed 或 task_failed，但工具级事件仍待实现，step 目前默认为 0。

事件先写入该任务的内存历史，再通知 SSE 订阅者。浏览器断线重连时可先收到历史事件，避免演示时丢步骤。

### 6.2 REST/SSE 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/tasks` | 创建并异步启动任务 |
| `GET` | `/api/tasks/{task_id}` | 查询任务状态与最终结果 |
| `GET` | `/api/tasks/{task_id}/events` | SSE 事件流，先回放后订阅 |
| `GET` | `/api/meta` | 已实现：工作区名称、六工具名称/状态及实际 agent/scaffold 模式 |
| `GET` | `/api/workspace/tree` | P1 规划，尚无路由，当前 404 |
| `GET` | `/api/workspace/file?path=...` | P1 规划，尚无路由，当前 404 |
| `GET` | `/health` | 健康检查 |

没有 `/api/tools/execute` 或任务取消/重试/历史列表接口。SSE 使用 `Last-Event-ID`（优先）或 `after`；范围外游标返回 400，终态已读完返回 204。当前前端走 REST/SSE，不直接调用 Python 工具。

## 7. 安全边界与已知限制

### 7.1 文件工具边界

- 只接受相对路径；拒绝绝对路径、空字节和越界路径。
- 拼接 Workspace 后执行规范化/真实路径解析，再确认结果仍位于根目录内。
- 新文件先校验其最近存在父目录的真实路径，避免符号链接逃逸。
- 默认忽略或拒绝 `.git`、`.env`、密钥文件和依赖缓存目录。
- 成功写入返回目标路径、Diff、哈希和结果；失败返回结构化错误。没有持久化审计日志，也尚未发布 file_changed 事件。

### 7.2 Shell 边界

`cwd=workspace` 不是安全沙箱。当前通过命令超时、输出限制和 argv 白名单降低风险，但无法阻止一个获准进程主动访问 Workspace 外文件。真实工具执行日志接入前端属于 M2/M3 待办，尚不能依赖网页观察工具执行。演示只在专用样例 Workspace 内运行，不以管理员权限启动。

M1 已实现 argv 白名单、精简环境、超时、输出预算，以及 Windows Job Object / POSIX 进程组清理。Job Object 在此仅管理进程生命周期，**不隔离文件或网络**。如果未来需要把“只能访问 Workspace”升级为强保证，必须另行设计容器、受限账户或 Windows Sandbox 等 OS 级隔离；这不属于本次 P0。

### 7.3 Prompt Injection 与凭据

目标要求：仓库文件和命令输出作为不可信数据，不得升级为系统指令；Runtime/System Prompt 和展示/日志层需处理注入与凭据泄漏风险。

当前仅有 Settings repr 隐藏密钥、公开元数据白名单、通用异常文案和命令环境裁剪。**尚无真实 System Prompt、内容级脱敏管道或日志脱敏实现**。工具不会主动附带整个环境字典，但获准脚本仍可能把环境或自行读取的凭据打印到 stdout/stderr；普通源码/Diff 也可能包含敏感内容。

## 8. 前端 MVP

目标单页界面包含：

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

本节基于 2026-08-28 M2 Loop 接入后的实际源码核对；不列入虚拟环境、依赖目录、缓存和生成的构建产物。

- **已实现**：存在可执行逻辑；是否已接入当前默认链路会另外注明。
- **接口骨架**：仅有类型、参数 Schema、Protocol 或返回 `NOT_IMPLEMENTED` 的入口，没有对应业务执行能力。
- **待实现**：尚未编写的行为，或已有逻辑尚未接入 Runtime；不等于要求现在新增一个文件。
- 表格中的“无本阶段新增项”仅表示该辅助文件已满足当前职责，不表示整个模块或项目完成。

模型配置完整时，网页任务已由 LLM 自主决策并执行基础 Agent Loop；配置不完整时仍以 `FAILED / NOT_IMPLEMENTED` 安全结束。当前 assistant 与终态事件可观察，但专用工具/文件/命令事件尚未发布，因此页面端到端展示仍未完成。D001 字节码缓存问题已修复并持续回归。

M1 六工具既可独立通过注册表调用，也已由 Runtime 调度。只读语义见 [只读阶段说明](Coding%20Agent%20M1%20只读工具实现说明.md)，写入/命令见 [M1 工具系统完成说明](Coding%20Agent%20M1%20工具系统完成说明.md)，循环见 [M2 Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md)。

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
| [src/App.vue](../frontend/src/App.vue) | 工作台与状态编排 | 获取工作区元数据并展示工具可用状态、创建/查询任务、订阅事件、按 ID 去重、终态关闭事件流并查询结果；防重复提交、错误/断线提示、手动重连及卸载清理 | 真实 Tool/Shell/Diff 交互、文件树/代码查看；页面刷新后恢复当前任务尚未实现 |
| [src/types.ts](../frontend/src/types.ts) | 前后端数据契约 | TaskStatus、Task、EventType、AgentEvent、Metadata（含 tool_statuses）；与现有 API 字段对应 | 工具/命令/文件变化的结构化 payload 类型；当前 payload 仍是通用字典，类型声明不是运行时校验 |
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
│   ├── runtime.py                # Agent Loop、工具分发与终止控制
│   ├── llm.py                    # 模型协议与 OpenAI-compatible HTTP 适配
│   ├── context.py                # 对话与最近完整轮次选择
│   └── stop.py                   # 独立停止策略
└── tools/
    ├── __init__.py               # 工具包标识
    ├── base.py                   # 工具参数、定义与结果契约
    ├── registry.py               # 工具注册和参数校验分发
    ├── workspace.py              # 路径守卫
    ├── read_only.py              # 有界遍历、读取和资源策略
    ├── files.py                  # 列表、读取、写入、唯一替换
    ├── writes.py                 # 快照、原子提交、哈希和单段统一 Diff
    ├── search.py                 # UTF-8 字面文本搜索
    ├── command_policy.py         # 命令白名单、程序定位和子进程环境
    ├── command_worker.py         # 收到许可后启动目标命令的隔离启动器
    ├── windows_job.py            # Windows Job Object 进程树生命周期
    └── shell.py                  # 监督执行、双流输出、超时和取消清理
```

下表文件路径相对于 `backend/app/`。

#### 入口、API、基础设施与数据模型

| 文件 | 功能简介 | 已实现的部分 | 待实现的部分 |
|---|---|---|---|
| [cli.py](../backend/app/cli.py) | 命令行入口 | 解析必填 Workspace 和 `--port`；读取配置、创建应用；固定本机地址、单 worker 启动 Uvicorn | 自动打开浏览器属于 P1；目前无多 worker、远程监听或自动重载选项 |
| [main.py](../backend/app/main.py) | 应用工厂与依赖组装 | 创建 Workspace/Registry；配置完整时创建 LLM/AgentRuntime；动态 mode/ready；先关闭任务再关闭模型；注入测试 Runner 时不创建无用客户端 | Vue 静态产物托管；现有中间件不等于身份认证或系统沙箱 |
| [api/routes.py](../backend/app/api/routes.py) | HTTP API 层 | 元数据、任务创建/查询、SSE；409/404/503 错误；游标检查、历史续传与终态 204 | 文件树/文件读取 API；不在本阶段的取消/历史/重试接口尚不存在 |
| [core/config.py](../backend/app/core/config.py) | 集中配置 | 模型请求/连接/重试、字符/token/结果/轮次预算、max_steps、工作区/端口/Origin；三项模型配置就绪判断；密钥不进 repr | 部分模型配置当前按 scaffold 降级而非报错；不会自动加载 `.env` |
| [core/events.py](../backend/app/core/events.py) | 事件存储和订阅 | 每任务内存 EventLog、递增 ID、Condition 通知、回放与等待、默认 15 秒心跳、终态拒绝追加 | 单事件/任务历史体积限制和敏感内容处理；持久化不在本阶段 |
| [models/task.py](../backend/app/models/task.py) | 任务数据模型 | TaskCreate 输入长度/空白/额外字段检查；四种状态、UUID、时间、结果、结构化错误与 scaffold 模式 | 真实步骤、验证结果、修改文件清单等字段；没有 CANCELLED 状态 |
| [models/event.py](../backend/app/models/event.py) | 事件信封与编码 | 8 种事件名称、终态集合、时间/step/payload 字段；`as_sse()` 生成 ID 与单行 JSON | 各事件 payload 的专用模型、真实工具事件数据；SSE 编码位于此文件而非 events.py |
| [services/tasks.py](../backend/app/services/tasks.py) | 任务生命周期 | 单活动任务、后台协程、默认 100 任务上限；agent/scaffold mode；Runtime 结构化错误、终态事件与关闭清理 | 持久化、用户取消和重试接口不在当前范围 |

#### Agent 与工具模块

| 文件 | 功能简介 | 已实现的部分 | 待实现的部分 |
|---|---|---|---|
| [agent/runtime.py](../backend/app/agent/runtime.py) | Agent 执行入口 | 自研 LLM→Tool→Observation 循环；Schema 复用、调用 ID/顺序回填、参数错误恢复、步数/重复停止、安全错误和资源关闭 | 连续错误/命令超时恢复；工具专用事件；关闭中写入语义 |
| [agent/llm.py](../backend/app/agent/llm.py) | 模型适配接口 | LLMClient 协议与 OpenAI-compatible 实现；鉴权、Schema 原样透传、严格响应/tool call 校验、安全错误、超时/有限重试、取消传播、资源所有权与幂等关闭；已接入 Runtime | 真实供应商兼容性验收；流式、Responses API 与旧 function_call 不在当前范围 |
| [agent/context.py](../backend/app/agent/context.py) | 对话管理 | 保存/校验完整轮次；字符与估算 token 总预算；计入工具 Schema；最近轮次选择；模型侧 ToolResult 合法 JSON 裁剪；已接入 Runtime | 精确供应商 tokenizer 与自动摘要不在当前 P0 |
| [agent/stop.py](../backend/app/agent/stop.py) | 确定性停止规则 | 最大决策轮与规范化重复识别已接入 Runtime；第三次回填纠偏 Observation，第四次结构化失败 | 连续命令超时与 LLM/Runtime 错误限制尚未实现 |
| [tools/base.py](../backend/app/tools/base.py) | 通用工具契约 | 严格参数模型、ToolResult、异步 handler、ToolSpec/Schema 和 implemented 状态；六个工具使用统一成功/错误/截断信封 | output 目前仍是通用字典；后续增加工具事件的专用 payload 类型 |
| [tools/registry.py](../backend/app/tools/registry.py) | 工具注册/分发 | 必须绑定 Workspace；六个真实 handler、Schema、严格参数校验和统一安全错误；已由 Runtime 调用并回填 Observation | 工具事件与全工具耗时统计；命令耗时已由 shell.py 返回 |
| [tools/workspace.py](../backend/app/tools/workspace.py) | 工作区路径约束 | 根目录身份、真实路径及敏感/链接/Windows 歧义检查；文件读写和命令入口均使用；同一 Workspace 写操作锁、内部临时文件名过滤 | 不能消除所有检查后路径变化的竞争，也不隔离进程；不同 Workspace 对象不共享写锁 |
| [tools/read_only.py](../backend/app/tools/read_only.py) | 共享只读基础设施 | ReadLimits、WalkState、受限且排序的深度优先遍历、协作式扫描时限、UTF-8/BOM 与普通文件检查、文件大小上限和打开后身份核验 | OS 级强隔离不在当前范围；固定忽略规则尚不解析 .gitignore |
| [tools/files.py](../backend/app/tools/files.py) | 文件工具集合 | list_files/read_file 与写入/唯一替换的参数和线程 handler；替换检查包含重叠匹配，零次或多次均拒绝；调用 writes 完成变更 | Runtime 接入、file_changed 事件；多文件事务不在 MVP 范围 |
| [tools/writes.py](../backend/app/tools/writes.py) | 文本变更基础设施 | 有界快照、写前冲突检查、同目录临时文件/fsync、原子替换/无覆盖创建、失败清理；BOM 保留、前后 SHA-256、受限单段统一 Diff | 不是跨进程 compare-and-swap；不保留所有 ACL/扩展属性，不提供回滚历史或多文件事务 |
| [tools/search.py](../backend/app/tools/search.py) | 文本搜索工具 | 文件/目录范围内区分大小写的字面搜索；路径、行列号、片段；文件数/字节/输出上限与跳过统计，线程中执行 | Runtime 接入；正则表达式、非 UTF-8 编码和索引不在当前实现范围 |
| [tools/shell.py](../backend/app/tools/shell.py) | 本地命令工具 | CommandLimits、固定 cwd、双流有界捕获、退出状态、超时/输出预算/取消、子进程清理；每命令创建并清理独立字节码前缀，修复 D001 | Runtime 与 command_finished 事件接入；没有交互终端、后台服务或流式 UI |
| [tools/command_policy.py](../backend/app/tools/command_policy.py) | 命令策略 | 受限 argv、开发命令白名单、可信 PATH、环境白名单及固定 ComSpec；固定禁写 Python 字节码，配合 shell 的新缓存前缀 | 不分析脚本内容或插件行为，不能限制获准程序的文件/网络访问 |
| [tools/command_worker.py](../backend/app/tools/command_worker.py) | 受控启动器 | Python -I 启动，等待父进程许可后才运行目标 argv；stdin 禁用、转发退出状态；目标程序继承 Job/进程组 | 不是独立用户接口，不应从不可信工作区替换本项目的运行时代码 |
| [tools/windows_job.py](../backend/app/tools/windows_job.py) | Windows 进程树管理 | ctypes 封装 Job 创建、kill-on-close、分配、终止和句柄关闭；未获分配许可不启动用户命令 | 仅管理生命周期，不提供文件/网络沙箱；POSIX 路径由 shell.py 的进程组实现 |

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
| [tools/__init__.py](../backend/app/tools/__init__.py) | 工具包说明：六个本地工具已实现，非 OS 安全沙箱 | 无独立业务实现 |

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
                    agent/runtime.py
                      │ 配置完整：Context 预算 -> LLM -> Stop -> Registry
                      │            -> 按 call id 回填 -> 下一轮/最终文本
                      │ 配置不全：RuntimeNotReady
                      ▼
                    TaskManager 标记 COMPLETED / 结构化 FAILED

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

`main.py` 只在 API Key、Base URL、模型名齐全时创建 LLM 客户端并报告 agent ready；配置不全不会误执行工具。当前 Runtime 已使用 Conversation、LLMClient、StopController 和 Registry.execute，但尚未把每次工具调用发布为专用事件。

设计中的 EventBus 对应当前 `core/events.py` 的每任务 EventLog；不存在单独的 `event_bus.py`。Tool Call、Terminal、Diff 与最终结果目前也没有独立 Vue 文件，不能按目标功能名称推断它们已存在。

### 9.5 API 与页面功能对照

| 接口/能力 | 后端文件 | 前端使用位置 | 当前状态 |
|---|---|---|---|
| `GET /health` | `main.py` | 未由页面自动调用；可手动检查 | 已实现服务健康信息及实际 agent/scaffold mode |
| `GET /api/meta` | `api/routes.py` | client.getMetadata -> App 工作区与工具清单 | 已实现工作区/工具名称、tool_statuses 与实际 agent_ready |
| `POST /api/tasks` | `api/routes.py`、`services/tasks.py` | TaskInput -> App -> client.createTask | agent 模式运行真实 Loop；scaffold 模式返回 NOT_IMPLEMENTED |
| `GET /api/tasks/{id}` | `api/routes.py` | client.getTask -> App 状态/最终结果 | 已实现内存查询 |
| `GET /api/tasks/{id}/events` | `api/routes.py`、`core/events.py` | client.watchTask -> App -> Timeline | 已实现回放/实时订阅；Agent 已发布逐轮 assistant 与终态，工具专用事件待接入 |
| `GET /api/workspace/tree` | 尚无路由 | 尚无文件树组件 | 待实现（P1），当前返回 404 |
| `GET /api/workspace/file?path=...` | 尚无路由 | 尚无 Code Viewer | 待实现（P1），当前返回 404 |
| Tool/Shell/File Change 专用事件 | 工具结果已实现；models/event.py 定义事件名称，Runtime 尚未发布 | Timeline 能展示通用 JSON | 工具层能力已存在，事件接入和专用展示待实现 |

`GET /` 的后端响应只是启动说明；`frontend/dist/` 即使已经构建，也不会自动由 FastAPI 托管。页面重连保留的是当前页面内的 task_id/事件游标，整页刷新后的任务恢复尚未实现。

### 9.6 工程配置与验证文件

| 文件 | 功能/已实现部分 | 待实现或维护说明 |
|---|---|---|
| [pyproject.toml](../pyproject.toml) | Python 打包、coding-agent 入口、运行/开发依赖、pytest/Ruff 配置 | 真实功能所需依赖在对应阶段补充；不引入 Agent SDK |
| [constraints.txt](../constraints.txt) | Python 已验证依赖快照 | 依赖升级后重新验证并维护 |
| [.env.example](../.env.example) | 基础环境变量示例，不含真实密钥 | 不会自动加载；完整模型策略变量见根 README |
| [.gitignore](../.gitignore) | 忽略环境、依赖、缓存、密钥配置和 QA 产物 | 不提供运行时安全隔离 |
| [tests/conftest.py](../tests/conftest.py) | 临时 Workspace 与隔离的 API 测试客户端 | 后续测试 fixture 扩展 |
| [tests/test_api.py](../tests/test_api.py) | 请求校验、状态、SSE 回放、Host/Origin、409/503、异常不透出、关闭行为 | 真实工具/API 集成和长期断线恢复验收 |
| [tests/test_workspace.py](../tests/test_workspace.py) | 相对路径、越界、敏感路径、Windows 别名、符号链接/junction/硬链接、根目录替换测试 | 持续补充文件系统边界与跨平台验收 |
| [tests/test_read_only_tools.py](../tests/test_read_only_tools.py) | 三个工具真实读取、过滤、UTF-8/CRLF、预算/截断、错误码、线程执行、工作区隔离及不修改内容 | 真实 Agent Loop 端到端测试不在此文件范围 |
| [tests/test_write_tools.py](../tests/test_write_tools.py) | 创建/覆盖/不变、BOM/CRLF、唯一与重叠匹配、路径守卫、大小/Diff 限制、失败清理与并发变更检查 | 跨平台文件系统/ACL 与恶意并发环境仍需独立验收 |
| [tests/test_shell_tools.py](../tests/test_shell_tools.py) | 白名单、环境裁剪、双流输出、超时/取消、子进程清理、Job 分配失败、Node/npm 及无模型修复流程 | POSIX 实机验收、Runtime 与模型端到端测试 |
| [tests/test_command_bytecode.py](../tests/test_command_bytecode.py) | D001 的 22 项回归：固定时间戳/等长修改/真实旧缓存，两种写工具和三种 pytest 入口；继承、重复调用、目录清理与异常、显式 compileall | 后续命令策略变更持续回归；不覆盖脚本主动修改环境或自定义加载器 |
| [tests/test_agent_contracts.py](../tests/test_agent_contracts.py) | 配置（含模型与预算环境变量）、Context 配对、Stop 独立策略、工具 Schema 与实际分发 | — |
| [tests/test_llm_client.py](../tests/test_llm_client.py) | HTTP 请求/鉴权、六工具 Schema 复用、响应/tool call 校验、超时/HTTP 重试、取消、错误脱敏与关闭所有权 | 真实供应商联网兼容性验收不在确定性单测范围 |
| [tests/test_context_budget.py](../tests/test_context_budget.py) | 字符/估算 token、工具 Schema 计量、完整轮次选择、ToolResult JSON 裁剪和显式超限 | 精确供应商 tokenizer 不在当前确定性估算范围 |
| [tests/test_agent_runtime.py](../tests/test_agent_runtime.py) | Fake LLM 真实读/改/pytest/final；并行 ID、参数恢复、裁剪、步数/重复停止、应用组装/关闭 | 真实供应商与工具专用事件验收仍待完成 |
| [tests/test_events.py](../tests/test_events.py) | 实时订阅/历史回放、心跳、读者断开、终态禁止追加 | 大载荷、多订阅者和历史体积限制测试 |
| [tests/test_task_manager.py](../tests/test_task_manager.py) | 创建后立即关闭、注入测试 Runner 的成功分支 | 默认 Runtime 完成/结构化失败另由 test_agent_runtime 覆盖 |
| [scripts/smoke_browser.cjs](../scripts/smoke_browser.cjs) | 用 Playwright/Edge 检查框架提交、三事件、未实现结果与窄屏布局 | 非 Vue 组件单测，也不是 Agent 修复代码的 E2E；工具卡片和复杂断线场景待补 |
| [scripts/test.ps1](../scripts/test.ps1) | 使用仓库虚拟环境与独立随机临时/缓存目录运行 pytest，转发退出码 | 不自动删除历史临时目录；不支持 PowerShell 的平台使用等价 Python 命令 |
| [demo_workspace/README.md](../demo_workspace/README.md) | 可指定的工作区占位说明 | 真实 Bug 源码、失败测试与重复演示数据尚未创建 |

根目录 [README.md](../README.md) 负责环境配置和运行说明；[基础框架修改说明](Coding%20Agent%20基础框架修改说明.md) 保存 M0 的交付与验证记录；[实施计划](Coding%20Agent%20实施计划.md) 负责里程碑和待办。正式提交用 `README.txt` 尚未创建，不将它列为已存在的源码文件。

### 9.7 剩余实现工作与落点

| 阶段 | 前端待实现 | 后端待实现 | 主要落点 |
|---|---|---|---|
| M1：已实现，D001 已修复 | 六工具就绪标签已有；真实结果卡片属于 M3 | 六工具、资源限制及独立字节码缓存已有；持续维护回归，POSIX 实机验收待完成 | `tools/command_policy.py`、`shell.py`、`tests/test_command_bytecode.py` |
| M2：Agent 闭环 | 准备接收真实工具事件 | HTTP/基础循环/结果回填/上下文预算/步数重复 Stop 已完成；连续错误恢复、取消写入语义、事件载荷限制待补 | `runtime.py`、`stop.py`、`core/events.py` |
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

下面是目标验收清单。工具层、LLM 客户端错误转换、Loop 级停止和错误 Observation 已有自动化测试；连续恢复与真实供应商验收尚未实现，组件通过不代表完整 Agent 验收通过。

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

以下为规划示例。当前 demo_workspace 只有占位 README，没有 divide 实现、失败测试或真实模型演示记录；单元测试临时创建的样例不是最终 Demo。

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

## 13. 当前实现状态（2026-08-28，M2 基础 Agent Loop 已接入）

功能设计章节描述目标，不代表全部完成；第 9 节与本节描述当前实现。基础 Agent 编程闭环已有 Fake LLM 确定性证据，真实模型、工具事件和 Demo 仍按实施计划推进。

- 启动：`coding-agent <workspace>` 已可用，固定监听 `127.0.0.1`、单 worker；Vue 独立启动于 5173。
- API：实现 `/health`、`/api/meta`、创建/查询任务、任务 SSE；文件树和文件读取 API 尚未实现。
- 状态：三项模型配置完整时进入 agent 模式并执行真实 Loop；配置不全时明确以 `FAILED / NOT_IMPLEMENTED` 结束且不操作工作区。
- 工具：六种协议均已注册并绑定工作区，Runtime 通过原有 Schema/Registry 调用；结果按调用 ID 和顺序回填模型。
- 只读边界：UTF-8 普通文件、固定忽略规则、拒绝链接、资源预算及截断元数据已实现；不是并发对抗环境下的强沙箱。
- LLM：已实现 OpenAI-compatible Chat Completions 客户端并由 Runtime 调用；严格响应/tool call 校验、有限重试与资源关闭已有测试，真实供应商联网验收尚未进行。
- 写入与命令：UTF-8 原子写入、唯一替换、Diff/哈希、精简环境、命令白名单、超时/输出预算/回收已实现；不代表命令内脚本被沙箱隔离。
- 最新复验：M2 累计新增 40 项后全量 234 passed，Ruff（43 文件）和 pip check 通过；上下文/Runtime 新增 13 项，受影响组件/API 针对性 30 passed。D001 三轮 194 和 HTTP 阶段 221 等历史保留原意；未运行真实模型任务。
- D001：每命令新建 PYTHONPYCACHEPREFIX 并固定禁写字节码，普通 Python 子进程继承；不删除工作区已有缓存，命令结束后清理本次目录。该策略增加冷导入开销，也不是对主动覆盖环境或 sys.modules 热重载的保证。
- 上下文与终止：字符/估算 token 双总预算计入工具 Schema；最近完整轮次和模型侧结果裁剪已接入。决策轮上限、第三次重复纠偏/第四次停止已生效；连续超时/错误恢复待补。
- EventBus 在代码中以每任务 `EventLog` 实现。事件 `id` 是任务内递增数字字符串，用于 `Last-Event-ID` / `after` 续传；终态已读完返回 204。
- TaskManager 保留至多 100 个内存任务，超过上限返回 503。Agent 任务会产生逐轮 assistant 事件，但真实工具事件和事件载荷/历史体积限制仍待增加。
- 安全：先实现路径越界与常见敏感路径校验、Host/Origin 限制、配置与异常详情不透出；这些不是强沙箱，也不是完备的敏感内容扫描。
- CLI 帮助已反映本地 Agent；TaskManager 的 NOT_IMPLEMENTED 现在只表示模型三项配置不完整，不再表示 Loop 或工具未实现。
- 最新验证、文档导航和独立 pytest 临时/缓存运行方式见 [docs/README](README.md)；D001 修复与三类缓存/权限区别见 [修复说明](Coding%20Agent%20D001%20修复说明.md)。前端构建和浏览器验证本次未重跑，历史记录不替代最新验收。
