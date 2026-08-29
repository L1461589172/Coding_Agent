# Coding Agent M6 历史任务与多轮对话实施计划

> 阶段名称：M6 — 持久化历史任务、可恢复会话与有界多轮上下文
>
> 建议周期：M5 验收后开始；M6 完成后进入 M7 最终交付
>
> 前置条件：M1–M4 已完成；M5 提供 `TaskRunViewModel`、终态 `TaskSummary`、可组合 ConversationThread、Composer intent 与版本化 recent-context
>
> 核心目标：历史任务在服务重启后仍可浏览；一次 follow-up 创建新的 Task 并归入同一 Session；模型只接收有界、完整、可解释的历史回合摘要，不复用旧 Task 的工具调用状态。

## 0. 决策摘要

M6 采用“Session 包含多个 TaskRun”的模型，而不是把一个长时间运行的 Task 改造成聊天会话：

```text
Workspace
└── Session / Conversation
    ├── TaskRun 1：user prompt → agent/tools → result + TaskSummary
    ├── TaskRun 2：follow-up → agent/tools → result + TaskSummary
    └── TaskRun N
```

关键决策：

1. 使用 SQLite 做本地单用户持久化，数据库位于 Workspace 之外；
2. Session 是历史导航和多轮上下文边界，Task 仍是调度、SSE、StopController、Trace 和 Summary 边界；
3. 同一时刻仍只允许一个全局活动 Task，M6 不引入并发 Agent；
4. follow-up 不恢复旧 Runtime，不复用旧 `Conversation`、ToolRegistry 状态、`call_id`、StopController 计数或子进程；
5. 历史上下文只使用有界 TaskRecap，不把完整事件、Diff、stdout/stderr 或旧工具结果重新送入模型；
6. 事件先持久化再通知 SSE，终态 Task 与终态事件原子收口；
7. 服务重启时不自动重跑在途任务，而是确定性标记为 `FAILED / SERVER_RESTARTED`；
8. 保留现有 `POST /api/tasks` 兼容语义：创建新 Session 和首个 Task；follow-up 使用新的 Session 子资源 API；
9. 删除会话是 P0 隐私能力；搜索、重命名、归档、分支和重新生成不是 P0；
10. M6 复用 M2 的总上下文预算和已有工具层输出上限，禁止再实现一套互相竞争的裁剪逻辑。

## 1. 范围

### 1.1 P0 交付

- SQLite schema、迁移、Repository 和事务边界；
- Session、Task、终态 Summary 与有界事件持久化；
- 服务重启后的历史浏览、SSE replay 与在途任务收敛；
- 新会话、会话列表、会话详情、follow-up 和删除 API；
- 基于 TaskRecap 的有界多轮上下文装配；
- Sidebar 历史列表、多个 TaskRun 的 Thread、New Conversation 与 Follow-up Composer；
- recent-context 从旧 task key 到 session key 的兼容迁移；
- 保留全局单活动任务约束和 M3 SSE/410/204 语义；
- 持久化安全、保留上限、删除和损坏数据库失败策略；
- 单元、集成、重启、浏览器与真实模型 smoke 验收。

### 1.2 P1（不阻塞 M6）

- 用户重命名会话；
- 标题后台生成；P0 只使用首个 Prompt 的确定性摘录；
- 历史全文搜索、归档和批量删除；
- 会话级导出；
- 更多测试框架的 Verification 分类；
- 大历史列表虚拟化和更丰富的时间分组。

### 1.3 明确不做

- 多 Workspace 同时运行、多用户、远程同步或云数据库；
- 多 Agent 并发、分支对话、消息编辑、Regenerate；
- 服务重启后继续旧进程或自动重放写操作；
- 把完整源码、Diff、命令输出、供应商响应或 API Key 存入“长期记忆”；
- 向量数据库、Embedding、语义搜索或自动长期记忆；
- 重复实现 ToolResult、事件 payload、Diff、命令输出的既有上限；
- 用 offset 做不稳定历史分页。

## 2. 领域模型与不变量

### 2.1 Session

Session 表示用户可见的一段多轮工作：

- 绑定一个规范化 Workspace fingerprint；
- 有稳定 ID、确定性标题、创建/更新时间；
- 按递增 `ordinal` 包含多个 Task；
- `updated_at` 在新增 Task 或 Task 进入终态时更新；
- 不持有 Runtime 对象、EventLog、LLM client 或子进程；
- 不维护一份可漂移的“会话总答案”。

P0 标题取第一个 Prompt 的单行、去空白、有界摘录；空值不允许进入数据库。标题是导航元数据，不进入模型上下文。

### 2.2 Task / TaskRun

每次用户提交，包括 follow-up，均创建全新的 Task：

- 每个 Task 只属于一个 Session；
- `ordinal` 在 Session 内唯一且只增不改；
- Prompt、状态、时间、result/error、TaskSummary 和事件均归属于该 Task；
- SSE cursor 和 Event ID 只在 Task 内有意义；
- Tool `call_id` 只在 Task 内有意义；
- 每个 Task 创建新的 `Conversation` 与 `StopController` 执行状态；
- 旧 Task 只读，不追加新的用户消息或工具结果。

### 2.3 TaskRecap

TaskRecap 是供后续模型理解历史的有界投影，不是第二份原始日志：

```python
class TaskRecap(BaseModel):
    task_id: str
    ordinal: int
    status: Literal["COMPLETED", "FAILED"]
    user_prompt: str
    assistant_result: str | None
    error_code: str | None
    files_changed: list[str]
    verification: VerificationSummary | None
```

规则：

- 仅从持久化 Task 与 `TaskSummary` 确定性生成；
- 字符串和列表复用其已有上限，必要的 recap 摘录有独立、小于总上下文预算的显式上限；
- 不包含 raw events、assistant 中间消息、旧工具 arguments/results、Diff、完整 stdout/stderr；
- COMPLETED 总是可进入候选历史；FAILED 仅带安全错误码和已确认的 Runtime Facts；
- `SERVER_RESTARTED` 等没有可靠模型结论的任务不得伪造 assistant_result；
- TaskRecap 可按需生成，P0 不必新增一张 recap 表；若缓存，必须有 schema/version 并能从 Task 重建。

### 2.4 核心不变量

- 全局最多一个 PENDING/RUNNING Task；
- 新 Task 行必须在返回 202 前提交；
- `session_id + ordinal` 唯一；
- `task_id + event_id` 唯一；
- terminal Task 必须有 `finished_at` 与 TaskSummary；
- terminal 事件对外可见时，GET Task 已能返回相同终态；
- 已删除 Session 的 Task/Event 不可再读取；
- 不同 Workspace fingerprint 的 Session 不可互相枚举或 follow-up；
- 数据库不可用时禁止静默退回内存模式并声称历史已保存。

## 3. 持久化位置与配置

### 3.1 数据目录

新增 `CODING_AGENT_DATA_DIR` 可选配置。默认值使用 `platformdirs.user_data_path("CodingAgent", appauthor=False)`，并明确位于 Workspace 外；该依赖应固定到 lockfile：

- Windows：`%LOCALAPPDATA%/CodingAgent/`；
- Linux/macOS：遵循平台用户数据目录；
- 测试：每个测试使用临时目录和独立数据库。

禁止：

- 默认把数据库写进被 Agent 操作的 Workspace；
- 仅按目录 basename 区分 Workspace；
- 在 API、SSE、前端或普通日志中暴露数据库绝对路径；
- 把配置中的 API Key、Authorization、LLM Base URL 或供应商原始响应写入数据库。用户主动在 Prompt 中输入的文本属于会话内容，系统无法保证自动识别全部秘密，UI 与 README 必须提醒不要提交密钥。

Workspace 使用“规范化绝对路径的稳定 SHA-256 fingerprint + 安全展示名”分区。Windows 路径先按真实 Workspace root 解析并执行 `normcase`；fingerprint 不返回 API，也不被当作秘密或身份认证；P0 仍是本地单用户应用。

### 3.2 SQLite 运行参数

连接初始化必须设置并测试：

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA busy_timeout = <bounded milliseconds>
```

要求：

- schema migration 在应用开始接受请求前完成；
- 使用参数化 SQL；
- Repository 封装连接和事务，不把 SQL 散落在 routes/runtime；
- 当前异步 Web 路径不得直接长时间执行阻塞数据库操作；使用明确的异步适配层或 `asyncio.to_thread`；
- shutdown 先停止接收新任务、等待/取消在途 Task 收口，再关闭连接；
- 数据库损坏、版本过新或迁移失败时启动失败并给出安全错误，不创建空库覆盖旧库。

## 4. Schema 与迁移

建议初版 schema：

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE workspaces (
  id TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_opened_at TEXT NOT NULL
);

CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_task_id TEXT,
  task_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  prompt TEXT NOT NULL,
  status TEXT NOT NULL,
  mode TEXT NOT NULL,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  result TEXT,
  error_json TEXT,
  trace_json TEXT,
  summary_json TEXT,
  first_event_id INTEGER,
  last_event_id INTEGER,
  UNIQUE(session_id, ordinal)
);

CREATE TABLE events (
  task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  event_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  step INTEGER,
  payload_json TEXT NOT NULL,
  payload_chars INTEGER NOT NULL,
  PRIMARY KEY(task_id, event_id)
);
```

补充索引至少覆盖：

- Session 列表：`workspace_id, updated_at DESC, id DESC`；
- Session Task：`session_id, ordinal`；
- 启动收敛：`tasks(status)`；
- Event replay 已由复合主键覆盖。

`error_json`、`trace_json`、`summary_json` 和 `payload_json` 读取后必须继续经过 Pydantic 严格验证；数据库不是可信输入。`trace_json` 是 M5 有界 ExecutionTrace 的持久快照，不是 raw log。迁移不得依赖 ORM 自动猜测。每个 migration 有顺序、事务策略、前向版本拒绝和测试 fixture。

## 5. Repository 与服务边界

### 5.1 协议

建议拆分：

```python
class SessionRepository(Protocol):
    async def create_with_task(...): ...
    async def get(...): ...
    async def list_page(...): ...
    async def append_task(...): ...
    async def delete(...): ...

class TaskRepository(Protocol):
    async def get(...): ...
    async def transition_to_running(...): ...
    async def append_event(...): ...
    async def finish_with_event(...): ...
    async def list_session_tasks(...): ...
    async def reconcile_interrupted(...): ...
```

具体方法可以合并到一个 `HistoryRepository`，但事务意图必须清楚。Routes 只做验证和 HTTP 映射；TaskManager 管理单活动任务与执行；AgentRuntime 只消费已装配的历史上下文，不直接查数据库。

### 5.2 TaskManager 改造

当前 `self.tasks` / `self.logs` 不能继续作为历史事实来源。M6 改为：

- Repository 是 Task/Session/持久事件的事实源；
- TaskManager 只保存当前活动 Task 的锁、后台 asyncio Task、live subscribers 和必要的短期 EventLog；
- 已终态 Task 从内存淘汰不影响 GET、历史列表或 replay；
- `max_tasks=100` 不再代表全部历史容量，改成独立的持久化保留策略；
- 全局 busy 判断同时检查进程内 active 状态和数据库 PENDING/RUNNING 状态。

测试仍可提供 in-memory repository，但 production 默认必须使用 SQLite；禁止测试替身泄漏成自动降级路径。

## 6. 事件持久化、SSE 与终态原子性

### 6.1 发布顺序

每个结构化事件只构造、校验和执行既有 payload 裁剪一次：

```text
Runtime raw fact
→ 既有 EventLog payload bound
→ Repository 同事务 append event + 更新有界 trace_json（唯一 task_id + event_id）
→ 更新 live EventLog / Condition
→ SSE subscriber 可见
```

M6 不对 event payload 再裁剪一次，也不持久化未受限 raw payload。TraceRecorder 仍消费同一个原始结构化事实，但其有界 snapshot 与对应事件在同一事务提交，防止重启后 Summary 事实落后。Repository append 失败时不得先向 SSE 声称事件成功；Task 必须安全失败并进入一致的终态收口。

### 6.2 终态事务

成功、失败、shutdown 和启动收敛使用同一语义：

```text
BEGIN
  更新 Task terminal fields + TaskSummary
  追加唯一 terminal event
  更新 Session updated_at / last_task_id
COMMIT
→ 唤醒 SSE subscriber
```

唯一约束使重试不会追加两个 terminal 事件。若事务提交结果未知，按 task/event 唯一键重新读取后判断，不盲目重复写。

### 6.3 Replay 与 410

- 活动 Task：数据库历史与 live EventLog 合并时按 event_id 去重；
- 终态/重启后 Task：直接从数据库流式或分页 replay；
- `after` / `Last-Event-ID` 沿用 M3 校验；
- cursor 等于最新事件且 Task 已终态返回 204；
- cursor 小于最早保留事件返回 410，并返回安全的 earliest/latest 元数据；
- cursor 大于最新已知事件仍返回 400；
- 已删除或不属于当前 Workspace 的 Task 返回 404。

### 6.4 启动收敛

应用启动且 migration 成功后，在开放 API 前扫描当前 Workspace 的 PENDING/RUNNING Task：

- 标记为 FAILED；
- `error.code = SERVER_RESTARTED`，错误消息固定且不包含内部路径；
- 设置 `finished_at`；
- 从已持久化 `trace_json` 生成 partial TaskSummary；不得扫描可能被裁剪或淘汰的事件来冒充完整 Trace；
- 追加下一 event_id 的 `task_failed`；
- 更新 Session；
- 不恢复旧 LLM 请求、工具调用、命令进程或写操作。

收敛本身必须幂等：第二次启动不会再次改写已经 terminal 的 Task。

## 7. API 契约

### 7.1 兼容现有 API

`POST /api/tasks {prompt}`：

- 创建新 Session 和 ordinal=1 的首个 Task；
- 仍返回 202 与 Task DTO；
- Task DTO 新增正式 `session_id` 和 `ordinal`；
- 继续执行 trim、1–8000 字符、Origin、全局 busy、mode 与未配置检查；
- 现有客户端无需先调用 Session API。

`GET /api/tasks/{task_id}` 与 `/events` 保持兼容，只把事实源改为 Repository。

### 7.2 新 API

```text
GET    /api/sessions?limit=20&before=<opaque_cursor>
GET    /api/sessions/{session_id}
GET    /api/sessions/{session_id}/tasks?limit=20&before_ordinal=<n>
POST   /api/sessions/{session_id}/tasks
DELETE /api/sessions/{session_id}
```

`POST /api/sessions/{id}/tasks {prompt}`：

- Session 必须属于当前 Workspace；
- 事务内分配下一个 ordinal 并更新 task_count；
- 全局已有活动 Task 时返回 409；
- 被删除/跨 Workspace 的 Session 返回 404；
- 返回 202 Task；
- 创建失败不得留下 task_count 漂移或空 Task。

Session 列表 DTO 只返回导航所需字段：

```typescript
interface SessionListItem {
  id: string
  title: string
  created_at: string
  updated_at: string
  task_count: number
  last_task_id: string | null
  last_task_status: TaskStatus | null
}
```

Session 详情不内嵌无限 Task/Event；Task 使用游标分页。列表使用基于 `(updated_at, id)` 的不透明游标，不用 offset。游标损坏返回 400。

### 7.3 删除

删除是隐私与磁盘上限的必要能力：

- 删除活动 Task 所属 Session 返回 409；
- 用户确认后事务级 cascade 删除 Session/Tasks/Events；
- 成功返回 204；重复删除返回 404；
- 删除后清理匹配的 recent-context 和前端缓存；
- live subscriber 若目标在删除前已结束，后续读取返回 404；
- 普通日志不输出 Prompt/result/数据库路径。

## 8. 多轮上下文装配

### 8.1 输入来源

follow-up Task 的模型输入由以下部分组成：

```text
system prompt
→ 选中的历史完整 TaskRecap 回合（旧 → 新）
→ 当前 follow-up prompt
→ 当前 Task 产生的 assistant/tool rounds
→ 既有 Tool Schema
```

SessionContextBuilder 从 Repository 读取当前 Task 之前的 terminal Task，生成 TaskRecap，再交给 `Conversation`。AgentRuntime 不直接查询 Session，以便测试和职责隔离。

### 8.2 预算算法

必须复用 M2 的 `ContextBudget`、`measure_model_input` 和最终预算校验：

1. 先证明 system + 当前 prompt + Tool Schema 能放入总预算；放不下沿用现有 `ContextBudgetError`；
2. 从最近历史 Task 开始选择完整 recap 回合；
3. 每个历史 Task 的 user/assistant（或 user/failed fact）必须整体保留或整体丢弃，禁止半个回合；
4. 选择完成后恢复为旧到新顺序；
5. 当前 Task 内最新完整工具回合继续按 M2 规则保留；
6. 发送 LLM 前再次以真实序列化消息和 Tool Schema 做总预算校验；
7. 老历史放不下时静默淘汰最老完整 recap，并在 Debug/测试事实中可观察 `included_history_tasks` / `omitted_history_tasks` 计数；
8. 不用字符预算与 token 预算相加，继续采用 M2 的“双上限都满足”语义。

禁止：

- 为历史再复制一套 tokenizer 或粗略 `len/4` 口径；
- 裁剪当前 Prompt 来迁就旧历史；
- 把工具输出上限当作多轮总预算；
- 把旧 raw ToolResult 放回模型；
- 用模型生成不受验证的“记忆摘要”替代确定性 TaskRecap。

### 8.3 失败与过期历史

- 已完成 Task：带 prompt、result 和有界 Runtime Facts；
- 已失败 Task：带 prompt、终态错误码和已确认文件/验证事实，不伪造模型结论；
- 事件已按保留策略淘汰：TaskRecap 仍来自 Task/TaskSummary，因此不影响后续上下文；
- TaskSummary 缺失或版本无法解析：该历史 Task 不进入模型，并记录安全告警；不得因此让当前请求读入 raw event 兜底；
- 当前 follow-up 自己的错误不会改写已有历史。

### 8.4 Workspace 是最终事实源

历史 recap 只能帮助理解意图，不能证明文件当前仍保持旧状态。System prompt 应明确：文件系统是当前事实源；涉及代码内容时继续用既有工具读取。这样既避免历史源码长期记忆，也避免用户在 Agent 外修改文件后使用过期内容。

## 9. 前端状态与 UX

### 9.1 状态拆分

App 层维护三个相互独立的概念：

- `selectedSessionId`：用户正在浏览的会话；
- `selectedSessionRuns`：分页加载并由 M5 `buildTaskRun` 生成的 TaskRun；
- `activeTask`：全局唯一在途 Task 和持续 SSE watcher，即使用户浏览旧会话也不能丢失。

禁止用一个 `task` ref 同时承担历史选择、全局 busy 和 live SSE。切换会话不会取消 Agent；运行中的 Session 在 Sidebar 显示明确状态，用户可返回。

### 9.2 Sidebar

- 顶部保留 Workspace 和 Agent Ready；
- `新建会话` 创建新 Session 的首个 Task；
- 历史按更新时间倒序游标加载；
- 显示标题、相对/绝对可访问时间和末 Task 状态；
- 选中、运行、失败不能只靠颜色；
- 有 loading、empty、error、load more 和 deleted 状态；
- P0 不做伪搜索或伪文件夹。

### 9.3 ConversationThread

- 直接复用 M5 的 `TaskRunSection`、Activity Formatter、File/Command 附件和 TaskSummary；
- 按 ordinal 旧到新渲染；
- 每个 TaskRun 有清晰的 Prompt、状态、时间和边界；
- 旧 Task events 延迟加载，先显示 Prompt/result/Summary；展开活动时再取事件，避免首屏无限请求；
- Event 410 显示“部分活动已过期”，但终态 Summary 仍可用；
- 长会话使用 Task 分页/“加载更早任务”，不一次加载全部。

### 9.4 Composer

- 没有选中 Session：发出 `new_task` / 新会话意图；
- 选中 terminal Session：发出 `follow_up`；
- 任一全局 Task 在途：Composer 禁用并说明正在执行哪个会话；
- follow-up 成功后追加新的 TaskRun，不清空旧 Thread；
- 409、404、422、503 使用现有安全错误映射；404 表示会话已删除/不可用时回到历史空状态；
- 仍保留 8000 字符、trim 和防重复提交。

### 9.5 URL 与恢复

P0 不必引入 Router，可使用 `?session=<id>` 配合 History API 实现刷新与前进/后退。若决定引入 Vue Router，必须同步处理开发/生产 fallback，不能只在 dev server 可用。

recent-context 迁移：

1. 优先读取 M6 `{version: 2, sessionId, taskId?}`；
2. 若只有 M5 `{taskId}` 或旧 `coding-agent:last-task-id`，GET Task 后读取正式 `session_id` 并写回 v2；
3. 旧后端返回的 Task 没有 `session_id` 时保持 M5 单 Task 降级，不制造 Session；
4. 404 或损坏数据只清除 localStorage 引用；
5. 后端历史是事实源，localStorage 只是最近选择，不保存会话内容。

## 10. 保留、隐私与资源上限

### 10.1 默认上限

所有值应配置化并在文档写出默认值；实施前通过 fixture 校准。至少包含：

- 每 Workspace 最大 Session 数；
- 每 Session 最大 Task 数；
- 历史最大保存天数；
- 每 Task 最大持久事件数和字符数；
- Session/Task 列表 page size 与硬上限；
- TaskRecap 单字段、单 Task 和总历史预算；
- SQLite 文件大小告警阈值。

自动保留策略只删除 terminal 且非活动 Session，按最旧更新时间处理，并在事务中 cascade。P0 若不启用自动删除，也必须提供显式删除和磁盘增长文档；不能保留无界数据。

### 10.2 敏感数据

Prompt、result、文件名和命令摘要可能包含项目敏感信息。历史功能会按设计保存这些受限会话内容，因此要求：

- README 明确本地保存范围、默认路径类别、删除方式和保留策略；
- 数据库文件使用当前用户权限创建；
- 日志只记录 ID、状态、安全错误码和计数；
- 配置/请求头中的 API Key、Authorization 和供应商 raw response 在写库前不可进入 DTO；
- 测试使用只放在模型配置/Authorization 中、从未写进 Prompt 的 canary secret；扫描数据库文本、日志和导出事件必须找不到；
- UI 与 README 明确提示：用户若主动把秘密写入 Prompt、代码、文件名或命令，它可能随会话被本地保存，应删除对应 Session 并轮换已泄露密钥；
- 删除是逻辑立即不可读；SQLite 页/WAL 的物理擦除能力必须如实说明，若需要强擦除列为后续安全增强。

## 11. 错误模型

建议新增安全错误码：

- `HISTORY_STORAGE_UNAVAILABLE`：存储不可用；
- `HISTORY_SCHEMA_UNSUPPORTED`：数据库版本不可兼容；
- `HISTORY_DATA_INVALID`：持久数据验证失败；
- `SERVER_RESTARTED`：任务因服务重启终止；
- `SESSION_TASK_LIMIT`：会话 Task 达到上限；
- `SESSION_CONTEXT_INVALID`：历史 Summary 无法安全装配，但当前任务是否可继续按策略明确；
- `SESSION_NOT_FOUND` 对外仍映射 404，避免泄露跨 Workspace 存在性。

数据库错误消息不得回显 SQL、绝对路径或 payload。可恢复的单条损坏记录与数据库整体不可用要区分；不得悄悄跳过关键 Task 状态后继续声称一致。

## 12. 实施阶段

### Phase 0：契约、威胁模型与迁移演练

- 冻结 Session/TaskRecap/API/schema/上限；
- 确认默认数据目录和 Workspace fingerprint；
- 写出启动收敛、删除、备份与数据库损坏行为；
- 先建立 repository contract、migration 和 restart fixtures；
- 确认 M5 兼容点已经落地，若未落地只补接口，不并行重写 UI。

### Phase 1：SQLite Repository

- 数据目录、连接初始化、migration runner；
- workspaces/sessions/tasks/events schema 与索引；
- 参数化 CRUD、游标分页、事务和严格 DTO 反序列化；
- temporary SQLite 与 in-memory repository 契约测试；
- 关闭连接和迁移失败测试。

### Phase 2：持久 Task/Event 生命周期

- TaskManager 改为 repository 事实源 + active runtime state；
- create/running/event/terminal 的提交顺序；
- durable replay、410/204、唯一事件与重试；
- shutdown 和 startup reconciliation；
- 从内存淘汰终态 Task 后仍可完整读取。

### Phase 3：Session API 与兼容层

- 扩展 Task DTO 的 `session_id` / `ordinal`；
- 保持 `POST /api/tasks` 创建新 Session；
- Session list/detail/task page/follow-up/delete；
- Origin、busy、Workspace 隔离、分页游标和容量错误；
- OpenAPI 与前端严格 parser 更新。

### Phase 4：SessionContextBuilder

- TaskRecap 确定性构建；
- newest-first 选择、完整回合保留、old-to-new 输出；
- 接入现有 Conversation 和总预算最终校验；
- completed/failed/restarted/summary-invalid/超长历史覆盖；
- 证明没有旧 ToolResult、Diff 或 call_id 进入新 Task Runtime。

### Phase 5：历史与多 TaskRun UX

- Sidebar 游标历史；
- selectedSession 与 activeTask 状态拆分；
- ConversationThread 多 TaskRun、懒加载事件和加载更早任务；
- New Conversation / Follow-up Composer；
- URL query、前进后退、recent-context v2 与旧 key 迁移；
- 删除确认、404、重启失败、空/错/加载状态。

### Phase 6：保留、安全与资源关闭

- 会话/任务/事件/磁盘上限；
- cascade 删除和 active-session 保护；
- WAL/checkpoint/连接关闭、后台 watcher 与 SSE subscriber 释放；
- canary secret、日志和数据库内容扫描；
- 故障注入：写库失败、commit 结果未知、损坏 JSON、迁移失败、磁盘满。

### Phase 7：回归与文档收口

- 后端 pytest/Ruff；前端 Vitest/typecheck/build；browser smoke；
- M1–M5 回归，特别是 M2 预算、M3 SSE、M4 真实模型 3/3、M5 Activity/Summary；
- 历史重启、多轮 follow-up、删除和事件过期 E2E；
- 经用户授权后执行有限真实模型多轮 smoke；
- 更新 README、架构图、API、配置、保留/隐私、故障恢复说明；
- 确认 M7 交付清单不再包含 M6 未完成实现。

## 13. 测试矩阵

### 13.1 Repository / Migration

- 空库初始化、连续迁移、重复启动幂等；
- 数据库版本高于程序时安全拒绝；
- foreign key/cascade/unique/index；
- Session 列表 cursor 在相同 updated_at 下稳定；
- 并发 append_task 只有唯一 ordinal；
- 数据 JSON 损坏的安全错误；
- 连接/事务在异常和 shutdown 后关闭；
- Workspace basename 相同但路径不同不会串历史。

### 13.2 Task / Event 一致性

- create 返回后 Task 已可 GET；
- RUNNING/terminal 与事件发布顺序；
- append event 失败不会先到 SSE；
- terminal event 重试不重复；
- 重启后 completed/failed replay；
- PENDING/RUNNING 启动后精确变为一次 SERVER_RESTARTED；
- cursor 的 200/204/400/410/404；
- 内存淘汰后历史仍存在；
- delete cascade 后所有读取均 404。

### 13.3 多轮上下文

- 单 Session 多 Task 顺序；
- 最近完整 recap 优先，输出恢复旧到新；
- 不保留半个历史回合；
- system + 当前 Prompt + Tool Schema 始终优先；
- 字符和 token 任一超限都会淘汰旧历史；
- 最终真实序列化输入通过现有 M2 校验；
- failed/restarted Task 不伪造 assistant 文本；
- summary 无效时不回退 raw events；
- 旧 call_id、StopController 步数和 ToolResult 不进入新 Task；
- Workspace 外部修改后 Agent 仍重新读取文件。

### 13.4 API

- 旧 `POST /api/tasks` 仍为 202 并返回 session_id；
- follow-up 202、全局 busy 409、Session 上限、422、503；
- Session list/task list cursor；
- 跨 Workspace 统一 404；
- delete active 409、terminal 204、重复 404；
- Origin、内容类型、Prompt 8000 字符与错误脱敏；
- Schema/OpenAPI 与前端 parser 一致。

### 13.5 Frontend / Browser

- 历史空态、分页、选中、运行/失败标记；
- 多 TaskRun 同 call_id/event id 不串卡片；
- 运行任务时浏览旧 Session，SSE watcher 仍更新 activeTask；
- follow-up 追加而不是替换 Thread；
- refresh、URL、back/forward、旧 localStorage 迁移；
- deleted/404、410 partial activities、SERVER_RESTARTED；
- 390px、键盘、focus、live region、reduced motion；
- 长 Session 不一次加载全部 events。

### 13.6 真实模型验收

先通过 Fake LLM 确定性断言真实请求消息，再经用户授权运行一组最小 smoke：

1. 新会话完成一个小型、可复位的代码任务并验证；
2. 同一会话 follow-up 使用代词/承接表达，要求检查或小幅调整前一结果；
3. 验证模型理解前一任务意图，但仍通过工具读取当前文件；
4. 重启服务后浏览两轮历史；
5. 再发一轮只读 follow-up，确认持久 Session 可继续；
6. 独立运行测试并保存脱敏报告。

真实调用不用于证明预算算法；预算、消息顺序和敏感字段必须由可断言 fixture 证明。

## 14. M6 退出标准

- [ ] 历史 Session/Task/Summary/有界 Events 在正常服务重启后仍可读取；
- [ ] 在途任务重启后只收敛一次为 `SERVER_RESTARTED`，不会自动重放；
- [ ] 现有 `POST /api/tasks`、GET Task、SSE replay 保持兼容；
- [ ] follow-up 创建同 Session 的新 Task 和新 Runtime 状态；
- [ ] Session 列表和 Task 列表使用稳定游标分页；
- [ ] ConversationThread 复用 M5 TaskRun/Activity/Summary，没有第二套格式化实现；
- [ ] 历史上下文使用完整、有界 TaskRecap，并通过 M2 最终总预算校验；
- [ ] 旧 raw ToolResult、Diff、stdout/stderr、call_id、StopController 状态不进入新 Task；
- [ ] 全局单活动 Task 约束在新会话和 follow-up 两条入口都成立；
- [ ] 删除 terminal Session 后 API/UI 不可再读取，活动 Session 不可删除；
- [ ] 数据库位于 Workspace 外，连接、WAL、SSE watcher 和后台任务可关闭；
- [ ] 配置/请求头中的 API Key 与供应商原始响应不进入数据库/日志/事件；会话正文的本地持久化边界已明确告知用户；
- [ ] migration、restart、故障注入、backend、frontend、browser 测试通过；
- [ ] 经授权的真实模型多轮 smoke 通过，且 M4 独立三轮回归仍为 3/3；
- [ ] README 与 docs 说明存储位置类别、保留、删除、重启和备份/损坏行为；
- [ ] M7 最终交付不存在被推迟的 M6 P0 实现。

## 15. 风险与止损

| 风险 | 预防与止损 |
|---|---|
| 把历史列表误当成持久化 | 以进程重启测试为第一验收，不接受 localStorage-only |
| SQLite 阻塞 async loop | Repository 异步边界、短事务、busy timeout 和并发测试 |
| SSE 已通知但数据库未提交 | persist-before-notify；终态事务提交后再唤醒 |
| 重启重复执行写操作 | 绝不自动恢复 Runtime；统一 SERVER_RESTARTED 收敛 |
| 多轮历史挤爆上下文 | 只选完整 TaskRecap；最近优先；复用 M2 最终预算校验 |
| 历史内容过期误导 Agent | Workspace 是事实源；代码任务继续 read/search |
| 与工具输出裁剪重复 | 事件只持久化既有受限 payload；recap 不含 raw ToolResult |
| M5/M6 UI 重写 | 复用 TaskRunSection、Composer intent、Sidebar 数据接口和 recent-context migration |
| 数据库无限增长 | 显式 Session/Task/Event/天数/磁盘上限与删除能力 |
| 删除不彻底的错误承诺 | 明确逻辑删除可见性与 SQLite 物理页限制，不夸大安全擦除 |
| 数据库损坏后静默丢历史 | 启动失败并保留原文件；不自动新建覆盖或回退内存 |
| 截止期挤压可靠性 | 先砍搜索、重命名、动画、虚拟化；不砍迁移、预算、重启收敛、删除和资源关闭 |

## 16. 建议提交划分

```text
docs: freeze m6 session persistence and context contracts
feat(history): add sqlite migrations and repository contracts
feat(history): persist task lifecycle and bounded events
fix(history): reconcile interrupted tasks on startup
feat(api): add session history follow-up and delete endpoints
feat(agent): inject bounded session recaps into conversation
feat(ui): add session history and multi-run conversation thread
fix(ui): preserve active watcher during history navigation
test: add migration restart retention and context regressions
docs: document local history privacy recovery and operations
```

每个提交必须保持 schema 可迁移和既有测试可运行。涉及 schema 的提交要包含 migration、repository 测试和版本说明；不能只改 Pydantic model 而不提供旧数据库路径。

## 17. M6 与 M7 的边界

M6 负责“历史与多轮能力本身可用且可靠”，包括本地持久化、重启行为、隐私删除、资源上限和真实多轮 smoke。M7 只负责最终交付收口：全量复验、README.txt、录屏、密钥/仓库扫描、交付清单和最终提交。

以下内容不得留到 M7：schema/migration、Session API、follow-up 上下文、重启收敛、删除、资源关闭、M6 自动化测试。M7 发现这些缺口时应退回 M6 修复，而不是在交付阶段临时拼接。
