# Coding Agent 基础框架修改说明

> 修改日期：2026-08-27  
> 版本：0.1.0 / M0  
> 范围：依据已修订设计搭建基础工程与验证链路；未实现完整编程智能体。

> 文档性质：M0 历史交付记录，2026-08-27 按当前代码补充状态导航。下文“M0 当时未实现”“35 passed”和浏览器验证均保留阶段原意；当前状态见 [文档导航](README.md)。

## 1. 本次结果

本文件保留 M0 历史交付记录，其中“工具未实现”等表述指 M0 时点。此后 M1 已实现全部六个本地工具、D001 已修复，M2 已接入 LLM HTTP 客户端、上下文预算和基础 Agent Loop；当前全量 234 passed。工具契约见 [M1 工具系统完成说明](Coding%20Agent%20M1%20工具系统完成说明.md)，当前 M2 契约与验证见 [M2 上下文预算与 Agent Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md)。

已从仅有文档的仓库搭建出可运行的 FastAPI 后端和 Vue 3 前端。用户可以指定 Workspace 启动服务、在页面提交任务、查看服务端 SSE 事件和最终结果。

**默认结果是 `FAILED / NOT_IMPLEMENTED`，不是任务成功。** 当前没有调用任何模型、读取/修改用户代码或执行用户命令；这是为了在 M0 验证基础链路，不用模拟成功代替真实 Agent 能力。

本次未提交或推送 Git，未创建公开仓库、视频或最终提交压缩包。原始《项目要求.pdf》和已有 IDE 配置未修改。

## 2. M0 当时已实现与预留的边界

| 模块 | M0 当时实现 | M0 当时规划的后续工作 |
|---|---|---|
| CLI / Settings | 工作区参数、环境变量、端口校验、本机单 worker 启动 | 真实模型配置有效性检查、浏览器自动打开 |
| Workspace | 真实路径解析、相对路径限制、越界/符号链接逃逸与常见敏感路径拒绝 | 写入时竞争条件、完整路径别名策略、读写工具接入 |
| TaskManager | 单活动任务、202 创建、409 冲突、状态与结果、关闭服务时清理任务 | 真实 Runtime 接入；持久化/取消不在 M0 |
| EventLog | 内存历史、递增游标、SSE 回放/订阅、心跳、终态关闭 | 工具载荷的长度限制及历史容量控制 |
| 六个工具 | Pydantic 参数协议、统一结果、注册和调度、参数错误转换 | 实际目录搜索、文件读写、Diff、Shell 执行 |
| LLMClient | 可替换客户端 Protocol、ModelReply、ToolCall | HTTP 客户端、响应解析、超时/重试与供应商适配 |
| Conversation | 保存完整交互轮次、校验调用/结果配对、保留最近轮次 | 字符/token 预算、输出截断与摘要 |
| StopController | 最大步数、同参数重复 3 次提醒/4 次停止的独立策略 | 在真实 Loop 中执行策略，补超时/连续错误处理 |
| AgentRuntime | 明确的未实现说明和可测试的运行接口 | LLM -> Tool -> Observation 完整循环 |
| Vue 页面 | 任务输入、状态、工具清单、事件时间线、最终结果、断线提示 | 专用 Tool/Shell/Diff 卡片、文件树与代码查看 |
| 测试 | 后端自动化测试、类型/构建检查、浏览器 smoke | 真实模型、真实编程任务和跨平台验收 |

## 3. 文件与职责清单

本节保留 M0 交付时的简要清单。前后端逐文件功能、已实现与待实现部分，统一维护在[项目结构与功能设计文档](Coding%20Agent%20项目结构与功能设计文档.md)第 9 节，包含当前源码树、调用关系、接口对照和测试文件。

### 3.1 根目录与工程配置

- `.gitignore`：忽略密钥配置、虚拟环境、依赖目录、缓存、构建产物与 QA 截图；没有删除这些目录中的用户内容。
- `.env.example`：只描述环境变量，不包含密钥；项目不自动加载 `.env`。
- `pyproject.toml`：Python 包、CLI 入口、运行/开发依赖、pytest 与 Ruff 配置。
- `constraints.txt`：记录本次验证的 Python 依赖快照，用于约束重装结果；不包含机器绝对路径或可编辑安装路径。
- `README.md`：替换原简短介绍，补齐安装、启动、配置、验证、工程结构和真实能力边界。
- `demo_workspace/README.md`：占位工作区；尚未放入真实 Bug 和失败测试。

### 3.2 后端

```text
backend/app/
├── __init__.py                 # 包与版本
├── cli.py                      # coding-agent 命令入口
├── main.py                     # 应用工厂、lifespan、Host/Origin 限制
├── api/
│   └── routes.py               # 元数据、任务、SSE 路由
├── core/
│   ├── config.py               # 环境配置；API Key 不参与 repr
│   └── events.py               # 每任务 EventLog 与 SSE 回放/订阅
├── models/
│   ├── task.py                 # TaskCreate / Task / TaskStatus / TaskError
│   └── event.py                # AgentEvent 与终态事件定义
├── services/
│   └── tasks.py                # 单活动任务管理、后台协程与关闭清理
├── agent/
│   ├── runtime.py              # TaskRunner 协议与关闭的 AgentRuntime
│   ├── llm.py                  # LLMClient / ModelReply / ToolCall
│   ├── context.py              # 完整轮次 Conversation
│   └── stop.py                 # 步数与重复动作策略
└── tools/
    ├── base.py                 # ToolSpec / ToolArgs / ToolResult
    ├── registry.py             # 工具注册、参数校验和结果规范化
    ├── workspace.py            # 工作区路径守卫
    ├── files.py                # 四个文件工具协议；执行未实现
    ├── search.py               # search_text 协议；执行未实现
    └── shell.py                # run_command 协议；没有 subprocess 调用
```

各包均包含 `__init__.py`，不依赖只有目录而无法导入的空壳结构。

### 3.3 前端

- `frontend/package.json`、`package-lock.json`：Vue/Vite/TypeScript 依赖、脚本与锁文件。
- `frontend/index.html`、`tsconfig.json`、`vite.config.ts`：HTML 入口、严格类型配置、REST/SSE 同源代理。
- `frontend/src/main.ts`、`App.vue`、`style.css`：入口、页面状态编排与响应式样式。
- `frontend/src/types.ts`：任务、事件、元数据类型。
- `frontend/src/api/client.ts`：HTTP 客户端、超时、错误提示、EventSource。
- `frontend/src/components/TaskInput.vue`：输入校验、重复提交限制。
- `frontend/src/components/TaskStatus.vue`：任务状态显示。
- `frontend/src/components/AgentTimeline.vue`：事件顺序展示，使用文本插值而非执行 HTML。

没有引入路由、Pinia 或完整 IDE 组件；当前单页状态可在 App 内维护。尚未把构建后的前端嵌入 Python 包。

### 3.4 测试与检查脚本

- `tests/conftest.py`：临时 Workspace 和隔离的 FastAPI TestClient。
- `tests/test_api.py`：健康检查、元数据、无效输入、状态、SSE、Host/Origin、冲突、异常脱敏和容量上限。
- `tests/test_workspace.py`：合法路径、越界、绝对路径、常见敏感路径、符号链接逃逸。
- `tests/test_agent_contracts.py`：配置、Context 配对、Stop 策略、工具协议与关闭状态。
- `tests/test_events.py`：实时订阅/回放衔接、心跳、断开与终态约束。
- `tests/test_task_manager.py`：尚未调度即关闭的边界、注入测试 Runner 的完成路径。
- `scripts/smoke_browser.cjs`：可选 Playwright 检查，依赖本地 Edge 和已启动的两个服务；不参与 Agent 本身运行。

### 3.5 文档同步

- 设计文档新增第 13 节“基础框架实现状态”，不把目标设计描述成已完成实现。
- 实施计划勾选 M0 框架/安装项，以及已实现的 TaskManager、SSE 项；M1 工具执行、M2 Loop 和 M3 完整 UI 仍未完成。
- 本文是本次代码修改的对应说明；正式提交用 `README.txt` 仍留在 M5。

## 4. M0 当时接口契约

以下为 M0 记录。当前 `/api/meta` 另含 `tool_statuses`，六工具均为 ready；任务仍保持 scaffold/agent_ready=false。最新接口状态以设计文档第 6/9 节为准。

| 请求 | 正常结果 | 关键边界 |
|---|---|---|
| `GET /health` | 200，`status=ok`、`mode=scaffold`、`agent_ready=false` | 表示服务健康，不表示 Agent 已就绪 |
| `GET /api/meta` | 200，工作区名称、模式与六个工具名称 | 不返回完整配置或 API Key |
| `POST /api/tasks` | 202，返回 `PENDING` Task | 空白/过长输入 422；活动任务 409；累计 100 任务后 503 |
| `GET /api/tasks/{id}` | 200，当前任务状态、结果或错误 | 不存在时 404 |
| `GET /api/tasks/{id}/events` | 200，SSE，先回放后等待 | 支持 `Last-Event-ID` 和 `after`；无效游标 400 |
| 同上，终态已全部读取 | 204 | 告诉 EventSource 停止自动重连 |
| `GET /` | 200，后端与前端启动提示 | 不托管 Vue 静态产物 |

文件树、文件读取、取消、重试、历史列表等接口尚未实现；访问不存在的路由会得到 404。

SSE 事件 ID 是每任务递增的数字字符串，不是全局 UUID。每条 SSE 数据使用单行 JSON，前端按 ID 去重；重连不会再次创建任务。

默认链路：

```text
POST /api/tasks -> 202 / PENDING
  -> RUNNING + task_started
  -> assistant_message（说明能力尚未实现）
  -> FAILED + task_failed（NOT_IMPLEMENTED）
  -> SSE 关闭，前端查询并展示最终结果
```

`task_completed` 路径仅通过注入的测试 Runner 验证；默认应用不会模拟真实任务完成。终态事件由 TaskManager 管理，未来 Runtime 应发布中间事件并返回结果或抛出错误。

## 5. 安装与运行入口

完整说明见 [根目录 README](../README.md)，当前测试方式及缓存问题见 [文档导航](README.md)。下面保留仍适用的最短 Windows 启动路径；无需因阅读本历史记录而重复创建已有虚拟环境或安装依赖。

```powershell
# 仓库根目录
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
.\.venv\Scripts\coding-agent.exe demo_workspace
```

第二个终端：

```powershell
cd frontend
npm.cmd ci --ignore-scripts
npm.cmd run dev
```

访问 `http://127.0.0.1:5173`。当前无需 API Key。停止两个终端中的服务分别使用 `Ctrl+C`。

后端在应用 lifespan 中创建 TaskManager，并在退出时清理任务，避免模块导入时立即启动 Runtime。Vite 代理 `/api` 和 `/health`，前端无需持有服务器文件路径或模型凭据。

## 6. M0 历史验证记录

验证环境：Windows、Python 3.12.4、Node.js 22.21.1、npm 10.9.4。主要解析版本包括 FastAPI 0.141.1、Uvicorn 0.52.4、Pydantic 2.13.4、Vite 7.3.6；其他版本见锁文件/约束文件。

| 验证 | 结果 |
|---|---|
| Python 可编辑安装与 `coding-agent --help` | 通过，CLI 入口有效 |
| `python -m pip check` | 通过，无依赖冲突 |
| `python -m pytest -q` | **35 passed**，测试不消耗模型 API |
| Ruff lint 与格式检查 | 通过 |
| Vue TypeScript 检查与 Vite 生产构建 | 通过，产物生成于 `frontend/dist/` |
| 真实本地 HTTP `/health` | 200，返回 `scaffold` 与 `agent_ready=false` |
| Edge 浏览器 smoke | 通过：元数据、任务提交、3 个事件、NOT_IMPLEMENTED、再次提交按钮恢复 |
| 桌面 1365px / 窄屏 390px 截图检查 | 通过，无横向溢出；页面脚本无未捕获异常 |

测试有一条第三方兼容性提示：当前 Starlette TestClient 提示未来应迁移到 `httpx2`。这不是测试失败；本次保留已通过验证的依赖快照，没有为消除提示引入额外 HTTP 库。后续升级 Starlette/测试客户端时需重跑 API/SSE 测试。

浏览器 QA 截图位于 `output/qa/`，构建产物、依赖目录和截图均被 Git 忽略。符号链接测试在本次 Windows 环境中通过；其他账号若无创建符号链接权限会跳过该项，需要在具备权限的环境补测。

没有做的验证：真实 LLM、真实工具读写、Shell 子进程/超时、Bug 修复成功率、Linux/macOS、公网或多用户安全。不能从本次测试推断这些能力已实现。

## 7. M0 当时规划的后续实现顺序

本节是历史计划，不是当前待办。文件和命令工具已实现，D001 已修复；下一步按 [实施计划](Coding%20Agent%20实施计划.md) 接入 M2，避免重新搭建已有工具。

1. **M1 文件工具**：复用 Workspace 校验，实现文本读写、唯一替换、搜索范围限制和 Diff；补文件大小/编码/输出截断测试。
2. **M1 Shell**：在专用工作区实现命令授权策略、超时、输出限制、敏感环境隔离和进程树清理。`cwd` 不能提供强隔离。
3. **M2 模型适配**：实现 LLMClient，不引入 Agent 框架；模型输出是数据，由自研 Runtime 校验并调度工具。
4. **M2 Loop**：接上 Conversation、工具结果回填、StopController、错误重试、总执行预算和事件载荷上限。
5. **M3 UI**：将当前通用事件卡片升级为真实工具、Shell 和文件变化卡片；补断线恢复、状态查询与事件回放的一致性验收。
6. **M4 Demo**：引入初始失败的真实测试，验证文件确实修改、测试确实由 Agent 执行；不得以固定脚本伪装自主决策。

当前路径守卫不能阻止已经获准的任意本地进程访问 Workspace 外部；也不保证并发修改符号链接时的安全。Host/Origin 限制只减少误暴露风险，不是身份认证。不要对公网开放或以管理员权限运行未来的执行功能。

## 8. 实现参考

通用框架生命周期与构建配置参照 [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)、[Vue 快速开始](https://vuejs.org/guide/quick-start.html) 和 [Vite 入门](https://vite.dev/guide/)。Agent 的任务、事件、工具协议、上下文和停止策略在本仓库自行实现，未使用现成 Agent SDK。
