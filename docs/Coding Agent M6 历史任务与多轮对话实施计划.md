# Coding Agent M6 历史任务与多轮对话实施计划

> 阶段名称：M6 — 持久化历史任务、可恢复会话与有界多轮上下文
>
> 建议周期：M5 验收后开始；M6 完成后进入 M7 最终交付
>
> 前置条件：M1–M4 已完成；M5 提供 `TaskRunViewModel`、终态 `TaskSummary`、可组合 ConversationThread、Composer intent 与版本化 recent-context
>
> 核心目标：历史任务在服务重启后仍可浏览；一次 follow-up 创建新的 Task 并归入同一 Session；模型只接收有界、完整、可解释的历史回合摘要，不复用旧 Task 的工具调用状态。

> 2026-08-29 完成状态：Phase 0–7 的 P0 实现已完成。后端全量 `281 passed, 1 warning`，M6 定向 30 passed，Ruff、前端 20 项 Vitest、严格类型、生产构建与 M6 browser smoke 通过。经用户授权的真实模型多轮/重启 smoke 为 3/3 COMPLETED：同 Session ordinal 1→2→3，重启恢复、follow-up 重读当前文件/运行 pytest、测试未改和模型密钥不落历史等 8 项检查全部通过。正式交付候选仍由 M7 再做一次冻结复验。

当前 format v1 冻结上限为 200 Session、每 Session 100 Task、单 Task 512 个/256000 字符的受限事件、单事件 payload 12000 字符、单 JSON 读取 2 MiB；TaskRecap 契约的 prompt/result 上限分别为 4000/8000 字符。单次启动最多自动隔离 10 个损坏 Task，超过后停止启动并保留 quarantine 现场，避免把大面积损坏误报为空历史。

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

1. 使用项目根目录 `/.coding-agent/history/` 下的版本化 JSON 文件做本地单用户持久化；目录受 Git 忽略和 Workspace 工具路径守卫保护；
2. Session 是历史导航和多轮上下文边界，Task 仍是调度、SSE、StopController、Trace 和 Summary 边界；
3. 同一时刻仍只允许一个全局活动 Task，M6 不引入并发 Agent；
4. follow-up 不恢复旧 Runtime，不复用旧 `Conversation`、ToolRegistry 状态、`call_id`、StopController 计数或子进程；
5. 历史上下文只使用有界 TaskRecap，不把完整事件、Diff、stdout/stderr 或旧工具结果重新送入模型；
6. 每个 Task 的状态、Trace、Summary 和有界 Events 保存在同一个 JSON 快照中，以同目录临时文件 + `fsync` + `os.replace` 原子更新，成功后再通知 SSE；
7. 服务重启时不自动重跑在途任务，而是确定性标记为 `FAILED / SERVER_RESTARTED`；
8. 保留现有 `POST /api/tasks` 兼容语义：创建新 Session 和首个 Task；follow-up 使用新的 Session 子资源 API；
9. 删除会话是 P0 隐私能力；搜索、重命名、归档、分支和重新生成不是 P0；
10. M6 复用 M2 的总上下文预算和已有工具层输出上限，禁止再实现一套互相竞争的裁剪逻辑。

## 1. 范围

### 1.1 P0 交付

- JSON format version、目录布局、迁移、Repository、原子替换和进程锁边界；
- Session、Task、终态 Summary 与有界事件持久化；
- 服务重启后的历史浏览、SSE replay 与在途任务收敛；
- 新会话、会话列表、会话详情、follow-up 和删除 API；
- 基于 TaskRecap 的有界多轮上下文装配；
- Sidebar 历史列表、多个 TaskRun 的 Thread、New Conversation 与 Follow-up Composer；
- recent-context 从旧 task key 到 session key 的兼容迁移；
- 保留全局单活动任务约束和 M3 SSE/410/204 语义；
- 持久化安全、保留上限、删除、备份和损坏 JSON 的隔离/恢复策略；
- 单元、集成、重启、浏览器与真实模型 smoke 验收。

### 1.2 P1（不阻塞 M6）

- 用户重命名会话；
- 标题后台生成；创建时暂用首个 Prompt 的确定性摘录，首轮完成后改用其终态结果首句摘要；
- 历史全文搜索、归档和批量删除；
- 会话级导出；
- 更多测试框架的 Verification 分类；
- 大历史列表虚拟化和更丰富的时间分组。

### 1.3 明确不做

- 多 Workspace 同时运行、多用户、远程同步或数据库；
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

Session 创建时标题取第一个 Prompt 的单行有界摘录；首轮完成后，从已有 Agent 终态结果提取首个有效文本行作为摘要标题，不额外调用模型。首轮失败或结果为空时保留 Prompt 摘录。标题去 Markdown、去多余空白并限制为 80 字符；旧历史在启动重建投影时自动更新。标题是导航元数据，不进入模型上下文。

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
- TaskRecap 可按需生成，P0 不单独持久化 recap；若未来缓存，必须有 `format_version` 并能从 Task JSON 重建。

### 2.4 核心不变量

- 全局最多一个 PENDING/RUNNING Task；
- 新 Task JSON 快照必须在返回 202 前原子落盘；
- `session_id + ordinal` 唯一；
- `task_id + event_id` 唯一；
- terminal Task 必须有 `finished_at` 与 TaskSummary；
- terminal 事件对外可见时，GET Task 已能返回相同终态；
- 已删除 Session 的 Task/Event 不可再读取；
- 不同 Workspace fingerprint 的 Session 不可互相枚举或 follow-up；
- 历史目录不可写、格式版本不兼容或关键 JSON 损坏时禁止静默退回内存模式并声称历史已保存。

## 3. 持久化位置与配置

### 3.1 数据目录

默认数据根目录固定为项目根目录下：

```text
<coding-agent-root>/.coding-agent/history/
```

项目根目录不能依赖进程当前工作目录推断；实现中从已安装/源码包位置解析应用根，测试则显式注入临时根目录。新增 `CODING_AGENT_HISTORY_DIR` 仅作为高级覆盖项，必须是绝对路径；默认行为仍满足“保存在 Coding Agent 项目目录下”。

安全要求：

- 根目录 `.gitignore` 加入 `/.coding-agent/`；
- `Workspace.BLOCKED` 加入 `.coding-agent`，即使 Agent 的 Workspace 就是项目根，也不能通过六工具读取、修改或搜索历史；
- 启动时拒绝历史目录是符号链接、junction/reparse point、普通文件或解析后逃逸项目根的默认路径；
- 目录和文件使用当前用户权限创建，不向 API、SSE 或普通日志暴露绝对路径；
- 不按 Workspace basename 隔离历史，使用规范化绝对路径的稳定 SHA-256 fingerprint；Windows 路径先解析真实 root 并执行 `normcase`；
- fingerprint 只用于本地分区，不返回 API，也不被当作秘密或身份认证；
- 配置中的 API Key、Authorization、LLM Base URL 和供应商原始响应禁止进入历史 JSON；用户主动在 Prompt 中输入的文本属于会话内容，UI 与 README 必须提醒不要提交秘密。

测试为每个用例注入新的临时 `history_dir`，不得读写开发者真实 `.coding-agent/history/`。

### 3.2 目录布局

P0 使用以下布局：

```text
.coding-agent/
└── history/
    ├── history.lock
    ├── CURRENT                     # 当前格式目录名，例如 v1
    ├── v1/
    │   ├── format.json             # 格式、创建时间、应用兼容版本
    │   └── workspaces/
    │       └── <workspace_fingerprint>/
    │           ├── workspace.json
    │           ├── index.json      # 可重建的 Session 列表投影
    │           ├── sessions/
    │           │   └── <session_id>/
    │           │       ├── session.json
    │           │       └── tasks/
    │           │           └── <ordinal>-<task_id>.json
    │           └── trash/          # 删除后待清理，不参与任何读取
    ├── backups/                    # 格式迁移前的有界备份
    └── quarantine/                 # 损坏文件隔离及安全诊断元数据
```

ID 必须通过严格 UUID/允许字符校验后才能参与路径拼接；不得把 API 参数原样当文件名。Task 文件名中的 ordinal 使用固定宽度十进制，排序仍以 JSON 内严格校验后的数字为准。

### 3.3 单写入者与资源关闭

- 应用启动时打开 `history.lock` 并获取非阻塞跨进程独占锁；Windows 使用 `msvcrt`，POSIX 使用 `fcntl` 的小型适配层；
- 同一历史目录已被另一个进程使用时启动失败，不允许两个进程同时写；
- 进程内所有 Repository 写操作再经过一个 async lock 串行化；
- JSON 编解码和磁盘 `fsync` 通过明确的线程边界执行，避免阻塞 event loop；
- shutdown 先停止接收新任务，收敛活动 Task，完成最后一次原子写，再释放文件锁和后台 watcher；
- 崩溃遗留的临时文件在下次启动时验证后清理，不把临时文件当正式历史。

## 4. JSON 格式、原子性与迁移

### 4.1 文件格式

每个 JSON 文件都包含：

```json
{
  "format_version": 1,
  "kind": "task",
  "revision": 7,
  "data": {}
}
```

要求：

- UTF-8、无 BOM、确定性 key 顺序、末尾换行；
- 时间统一为带时区 UTC ISO 8601；
- 所有读取继续经过 Pydantic 严格验证，禁止额外字段；
- 单个 Session/Task/Event 字符串和数组沿用既有显式上限；
- Task JSON 同时保存 Task fields、`trace`、`summary`、`events[]`、`first_event_id` 和 `last_event_id`；
- `events[]` 保存的只是经过既有 EventLog payload bound 后的事件，不保存 raw payload；
- `trace` 是 M5 有界 ExecutionTrace，不是第二份原始日志；
- `index.json`、`workspace.json` 和 `session.json` 是可从 Task 文件重建的投影，不是不可替代的唯一事实源。

### 4.2 原子写入

所有可变 JSON 使用项目既有原子文件思想，但由 HistoryRepository 独立实现，不调用 Agent 的 `write_file` 工具：

```text
构建并严格校验完整新对象
→ 序列化到同目录唯一临时文件
→ flush + fsync 临时文件
→ os.replace(temp, target)
→ POSIX 尽力 fsync 父目录
→ 更新内存 revision
```

同一个 Task 的事件、Trace、状态、result/error 和 Summary 位于同一 JSON 文件，因此一次 `os.replace` 就是该 Task 的提交边界。Task JSON 原子落盘后才更新 Session/index 投影并通知 SSE。若投影更新失败，Task 事实仍有效，启动时可重建投影；不得反过来用较新的 index 覆盖 Task。

在既有事件上限（最多 512 条、约 256 KB payload history）下，每个事件重写一个 Task JSON 的成本可控，也换来了比多文件 JSON/JSONL 更清楚的崩溃一致性。若未来上限显著增长，再通过新 format version 引入分片，M6 P0 不预先复杂化。

### 4.3 创建、终态与删除顺序

- 新 Session：先在同一父目录构建完整临时 Session 目录，写入 session + ordinal 1 Task，验证后原子重命名为正式 session_id，再更新 index；
- follow-up：原子写入新 Task 文件，再原子更新 session.json；若第二步失败，启动重建会发现合法孤立 Task 并补回 Session；
- 普通事件：在内存副本追加有界 Event、更新 Trace/revision，原子替换 Task JSON，成功后通知 SSE；
- terminal：一次原子替换同时提交 terminal fields、finished_at、TaskSummary 和唯一 terminal event，再更新 Session/index；
- 删除：在锁内先识别 current、retained backups 和 quarantine 中可识别的同一 Session 数据，把它们逐一原子移动到同一 `trash/<deletion_id>/` 批次；全部移动成功后才更新 index 并返回 204，失败时尽力回滚且返回安全错误；后台物理清理该批次，重启时继续清理已提交批次；
- 任一步失败都不得先向客户端声称成功。

### 4.4 格式迁移与备份

- `CURRENT` 指向当前版本目录，内容只允许 `v<positive-int>`；
- 应用版本低于历史格式时安全拒绝启动，不修改任何文件；
- 升级时先获取独占锁，把旧版本复制到 `backups/<timestamp>-vN/`，然后迁移到新的 sibling 临时目录；
- 新目录全量严格校验通过后，原子替换 `CURRENT`；旧版本保留为回退依据；
- 迁移失败删除/隔离未完成的新目录，保持旧 CURRENT 不变；
- 备份数量和总字节有显式上限，只在确认没有活动任务时清理最旧备份；
- P0 至少实现 v1 初始化、v1 幂等打开、未来版本拒绝和一套合成 v0→v1 fixture，证明框架不是只写版本号。

### 4.5 损坏恢复

- `index.json` / `session.json` 损坏：保留原文件到 quarantine，从严格有效的 Task JSON 重建并原子替换；
- 单个 Task JSON 损坏：隔离该文件，把 Session 标记为 `history_incomplete`，不把残缺内容送入模型；其他 Session 仍可用；
- `format.json`、CURRENT、目录边界或大量 Task 同时损坏：启动失败并保留现场，禁止创建空历史覆盖；
- quarantine 记录文件名、错误码、时间和哈希，不复制 Prompt/result 到普通日志；
- 恢复命令/文档必须先备份，不提供会递归删除整个 `.coding-agent` 的默认操作。

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

具体方法可以合并到一个 `JsonHistoryRepository`，但原子提交意图必须清楚。Routes 只做验证和 HTTP 映射；TaskManager 管理单活动任务与执行；AgentRuntime 只消费已装配的历史上下文，不直接读文件。

建议代码落点：

```text
backend/app/history/
├── models.py        # format envelope、Session、持久 Task 的严格模型
├── paths.py         # 项目根、ID/fingerprint、链接与边界校验
├── atomic.py        # 临时文件、fsync、os.replace
├── lock.py          # msvcrt/fcntl 单写入者锁
├── migrations.py    # CURRENT、备份、版本迁移与回退
└── repository.py    # JsonHistoryRepository 与投影重建
```

不要让 `routes.py` 自行打开 JSON，也不要复用面向 Agent Workspace 的文件工具写历史；这两条路径的权限、错误模型和原子性不同。

### 5.2 TaskManager 改造

当前 `self.tasks` / `self.logs` 不能继续作为历史事实来源。M6 改为：

- Repository 与严格校验后的 Task JSON 是 Task/Session/持久事件的事实源；
- TaskManager 只保存当前活动 Task 的锁、后台 asyncio Task、live subscribers 和必要的短期 EventLog；
- 已终态 Task 从内存淘汰不影响 GET、历史列表或 replay；
- `max_tasks=100` 不再代表全部历史容量，改成独立的持久化保留策略；
- 全局 busy 判断同时检查进程内 active 状态和历史中 PENDING/RUNNING 状态。

测试仍可提供 in-memory repository，但 production 默认必须使用 `JsonHistoryRepository`；禁止测试替身泄漏成自动降级路径。

## 6. 事件持久化、SSE 与终态原子性

### 6.1 发布顺序

每个结构化事件只构造、校验和执行既有 payload 裁剪一次：

```text
Runtime raw fact
→ 既有 EventLog payload bound
→ 在内存副本追加 event + 更新有界 trace
→ 原子替换完整 Task JSON（唯一 task_id + event_id）
→ 更新 live EventLog / Condition
→ SSE subscriber 可见
```

M6 不对 event payload 再裁剪一次，也不持久化未受限 raw payload。TraceRecorder 仍消费同一个原始结构化事实；Trace snapshot 和对应 Event 在同一个 Task JSON replacement 中提交，防止重启后 Summary 事实落后。原子替换失败时不得先向 SSE 声称事件成功；Task 必须安全失败并进入一致的终态收口。

### 6.2 终态提交

成功、失败、shutdown 和启动收敛使用同一语义：

```text
读取并验证当前 Task revision
→ 在副本中更新 terminal fields + TaskSummary + 唯一 terminal event
→ revision + 1
→ 原子替换 Task JSON
→ 更新可重建的 Session/index 投影
→ 唤醒 SSE subscriber
```

terminal event ID、Task terminal status 和 revision 的严格校验使重试不会追加两个终态。若 `os.replace` 结果未知，重新读取正式 Task JSON 判断 revision/terminal event，不盲目重复写；残留临时文件永远不优先于正式文件。

### 6.3 Replay 与 410

- 活动 Task：Task JSON 历史与 live EventLog 合并时按 event_id 去重；
- 终态/重启后 Task：从严格校验后的 Task JSON replay；
- `after` / `Last-Event-ID` 沿用 M3 校验；
- cursor 等于最新事件且 Task 已终态返回 204；
- cursor 小于最早保留事件返回 410，并返回安全的 earliest/latest 元数据；
- cursor 大于最新已知事件仍返回 400；
- 已删除或不属于当前 Workspace 的 Task 返回 404。

### 6.4 启动收敛

应用启动且格式初始化/迁移、投影重建成功后，在开放 API 前扫描当前 Workspace 的 PENDING/RUNNING Task JSON：

- 标记为 FAILED；
- `error.code = SERVER_RESTARTED`，错误消息固定且不包含内部路径；
- 设置 `finished_at`；
- 从同一 Task JSON 中已持久化的 `trace` 生成 partial TaskSummary；不得扫描可能被裁剪或淘汰的 events 来冒充完整 Trace；
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
- 在 Repository 写锁内从严格校验后的 Tasks 分配下一个 ordinal；Task 原子落盘后再更新 task_count 投影；
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
- 用户确认后把 current、retained backups/quarantine 中可识别的同 Session 数据移动到一个已验证 trash 批次并从索引移除；后台再递归清理该批次；
- 成功返回 204；重复删除返回 404；
- 删除后清理匹配的 recent-context 和前端缓存；
- live subscriber 若目标在删除前已结束，后续读取返回 404；
- 普通日志不输出 Prompt/result/历史目录绝对路径。

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
- `.coding-agent/history`、backups、trash 和 quarantine 的总字节告警/硬上限。

自动保留策略只删除 terminal 且非活动 Session，按最旧更新时间原子移动到 trash 后清理。P0 若不启用自动删除，也必须提供显式删除和磁盘增长文档；不能保留无界数据。

### 10.2 敏感数据

Prompt、result、文件名和命令摘要可能包含项目敏感信息。历史功能会按设计保存这些受限会话内容，因此要求：

- README 明确本地保存范围、默认路径类别、删除方式和保留策略；
- 历史目录和 JSON 文件使用当前用户权限创建；
- 日志只记录 ID、状态、安全错误码和计数；
- 配置/请求头中的 API Key、Authorization 和供应商 raw response 在写历史前不可进入 DTO；
- 测试使用只放在模型配置/Authorization 中、从未写进 Prompt 的 canary secret；扫描历史 JSON、日志和导出事件必须找不到；
- UI 与 README 明确提示：用户若主动把秘密写入 Prompt、代码、文件名或命令，它可能随会话被本地保存，应删除对应 Session 并轮换已泄露密钥；
- 删除后 API 立即不可读，并随后删除 trash 中的普通文件；retained backups/quarantine 中可识别的同一 Session 也必须清除。文件系统快照、外部同步盘或磁盘恢复仍可能保留副本，不能承诺安全擦除。

## 11. 错误模型

建议新增安全错误码：

- `HISTORY_STORAGE_UNAVAILABLE`：存储不可用；
- `HISTORY_FORMAT_UNSUPPORTED`：JSON 格式版本不可兼容；
- `HISTORY_DATA_INVALID`：持久数据验证失败；
- `SERVER_RESTARTED`：任务因服务重启终止；
- `SESSION_TASK_LIMIT`：会话 Task 达到上限；
- `SESSION_CONTEXT_INVALID`：历史 Summary 无法安全装配，但当前任务是否可继续按策略明确；
- `SESSION_NOT_FOUND` 对外仍映射 404，避免泄露跨 Workspace 存在性。

历史错误消息不得回显绝对路径、Prompt/result 或 payload。可恢复的单条 Task 损坏与格式根/CURRENT 整体不可用要区分；不得悄悄跳过关键 Task 状态后继续声称一致。

## 12. 实施阶段

### Phase 0：契约、威胁模型与迁移演练（已完成）

- 冻结 Session/TaskRecap/API/JSON format/上限；
- 确认默认 `.coding-agent/history`、工具路径阻止和 Workspace fingerprint；
- 写出启动收敛、删除、备份与损坏 JSON 的隔离/恢复行为；
- 先建立 repository contract、format migration、atomic replace 和 restart fixtures；
- 确认 M5 兼容点已经落地，若未落地只补接口，不并行重写 UI。

### Phase 1：JSON HistoryRepository（已完成）

- `.coding-agent` 目录、Git ignore、Workspace.BLOCKED 和跨进程 history.lock；
- CURRENT、format.json、Workspace/Session/Task JSON 与可重建 index；
- 严格路径/DTO 校验、游标分页、原子替换、trash/quarantine；
- temporary JSON repository 与 in-memory repository 契约测试；
- 文件锁释放、临时文件清理、格式迁移/回退失败测试。

### Phase 2：持久 Task/Event 生命周期（已完成）

- TaskManager 改为 repository 事实源 + active runtime state；
- create/running/event/terminal 的提交顺序；
- durable replay、410/204、唯一事件与重试；
- shutdown 和 startup reconciliation；
- 从内存淘汰终态 Task 后仍可完整读取。

### Phase 3：Session API 与兼容层（已完成）

- 扩展 Task DTO 的 `session_id` / `ordinal`；
- 保持 `POST /api/tasks` 创建新 Session；
- Session list/detail/task page/follow-up/delete；
- Origin、busy、Workspace 隔离、分页游标和容量错误；
- OpenAPI 与前端严格 parser 更新。

### Phase 4：SessionContextBuilder（已完成）

- TaskRecap 确定性构建；
- newest-first 选择、完整回合保留、old-to-new 输出；
- 接入现有 Conversation 和总预算最终校验；
- completed/failed/restarted/summary-invalid/超长历史覆盖；
- 证明没有旧 ToolResult、Diff 或 call_id 进入新 Task Runtime。

### Phase 5：历史与多 TaskRun UX（已完成）

- Sidebar 游标历史；
- selectedSession 与 activeTask 状态拆分；
- ConversationThread 多 TaskRun、懒加载事件和加载更早任务；
- New Conversation / Follow-up Composer；
- URL query、前进后退、recent-context v2 与旧 key 迁移；
- 删除确认、404、重启失败、空/错/加载状态。

### Phase 6：保留、安全与资源关闭（已完成）

- 会话/任务/事件/磁盘上限；
- 原子移动到 trash、异步清理和 active-session 保护；
- 文件锁/临时文件/后台清理器/watcher/SSE subscriber 释放；
- canary secret、日志和历史 JSON 内容扫描；
- 故障注入：临时写失败、`fsync`/`os.replace` 失败、替换结果未知、损坏 JSON、迁移失败、磁盘满。

### Phase 7：回归与文档收口（已完成；M7 将做最终候选复验）

- 后端 pytest/Ruff；前端 Vitest/typecheck/build；browser smoke；
- M1–M5 回归，特别是 M2 预算、M3 SSE、M4 真实模型 3/3、M5 Activity/Summary；
- 历史重启、多轮 follow-up、删除和事件过期 E2E；
- 经用户授权后执行有限真实模型多轮 smoke；
- 更新 README、架构图、API、配置、保留/隐私、故障恢复说明；
- 确认 M7 交付清单不再包含 M6 未完成实现。

## 13. 测试矩阵

### 13.1 Repository / Format Migration

- 空目录初始化、连续迁移、重复启动幂等；
- JSON format version 高于程序时安全拒绝且不改文件；
- CURRENT 切换、备份上限、index/session 投影重建；
- 同目录临时文件、`fsync`、`os.replace` 和残留临时文件清理；
- `os.replace` 前失败时旧 JSON 保持可读，替换结果未知时按正式文件 revision 判定；
- 两个进程争用同一 history.lock 时第二个安全失败；
- `.coding-agent` 的大小写变体通过 Workspace 六工具读取/搜索/写入均返回 `PATH_NOT_ALLOWED`；
- 默认 history root 是 symlink/junction/reparse point 或逃逸项目根时拒绝启动；
- Session 列表 cursor 在相同 updated_at 下稳定；
- 并发 append_task 只有唯一 ordinal；
- index/session/task/format 各层损坏的重建、隔离或安全失败；
- 文件句柄/锁在异常和 shutdown 后关闭；
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
- Session 原子移入 trash 后所有读取均 404，重启会继续安全清理。

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

- [x] 历史 Session/Task/Summary/有界 Events 在正常服务重启后仍可读取；
- [x] 在途任务重启后只收敛一次为 `SERVER_RESTARTED`，不会自动重放；
- [x] 现有 `POST /api/tasks`、GET Task、SSE replay 保持兼容；
- [x] follow-up 创建同 Session 的新 Task 和新 Runtime 状态；
- [x] Session 列表和 Task 列表使用稳定游标分页；
- [x] ConversationThread 复用 M5 TaskRun/Activity/Summary，没有第二套格式化实现；
- [x] 历史上下文使用完整、有界 TaskRecap，并通过 M2 最终总预算校验；
- [x] 旧 raw ToolResult、Diff、stdout/stderr、call_id、StopController 状态不进入新 Task；
- [x] 全局单活动 Task 约束在新会话和 follow-up 两条入口都成立；
- [x] 删除 terminal Session 后 API/UI 不可再读取，活动 Session 不可删除；
- [x] 历史位于项目 `/.coding-agent/history/`，被 Git 忽略且被六工具路径守卫阻止；文件锁、临时文件、SSE watcher 和后台任务可关闭；
- [x] Task 状态、Trace、Summary 与有界 Events 通过单 Task JSON 原子替换保持一致，索引可重建；
- [x] 配置/请求头中的 API Key 与供应商原始响应不进入历史 JSON/日志/事件；会话正文的本地持久化边界已明确告知用户；
- [x] format migration、restart、故障注入、backend、frontend、browser 测试通过；
- [x] 经授权的真实模型多轮 smoke 通过，且 M4 独立三轮回归仍为 3/3；
- [x] README 与 docs 说明存储位置类别、保留、删除、重启和备份/损坏行为；
- [x] M7 最终交付不存在被推迟的 M6 P0 实现。

## 15. 风险与止损

| 风险 | 预防与止损 |
|---|---|
| 把历史列表误当成持久化 | 以进程重启测试为第一验收，不接受 localStorage-only |
| JSON 重写阻塞 async loop | Task JSON 有界；线程化 I/O、单写锁和延迟/压力测试 |
| SSE 已通知但文件未提交 | atomic replace before notify；终态 Task JSON 成功后再唤醒 |
| 重启重复执行写操作 | 绝不自动恢复 Runtime；统一 SERVER_RESTARTED 收敛 |
| 多轮历史挤爆上下文 | 只选完整 TaskRecap；最近优先；复用 M2 最终预算校验 |
| 历史内容过期误导 Agent | Workspace 是事实源；代码任务继续 read/search |
| 与工具输出裁剪重复 | 事件只持久化既有受限 payload；recap 不含 raw ToolResult |
| M5/M6 UI 重写 | 复用 TaskRunSection、Composer intent、Sidebar 数据接口和 recent-context migration |
| JSON 目录无限增长 | 显式 Session/Task/Event/天数/备份/trash/总字节上限与删除能力 |
| 删除不彻底的错误承诺 | 原子移出可见历史后清理；明确备份/文件系统恢复边界，不夸大安全擦除 |
| 单个 JSON 损坏扩散 | 每 Task 独立文件、严格校验、quarantine；关键格式损坏时保留现场并拒绝启动 |
| Agent 修改自己的历史 | `/.coding-agent/` 同时加入 Git ignore 与 Workspace.BLOCKED，并拒绝链接/reparse point |
| 截止期挤压可靠性 | 先砍搜索、重命名、动画、虚拟化；不砍迁移、预算、重启收敛、删除和资源关闭 |

## 16. 建议提交划分

```text
docs: freeze m6 session persistence and context contracts
feat(history): add versioned json repository and atomic file contracts
feat(history): persist task lifecycle and bounded events
fix(history): reconcile interrupted tasks on startup
feat(api): add session history follow-up and delete endpoints
feat(agent): inject bounded session recaps into conversation
feat(ui): add session history and multi-run conversation thread
fix(ui): preserve active watcher during history navigation
test: add format migration restart retention and context regressions
docs: document local history privacy recovery and operations
```

每个提交必须保持 JSON format 可迁移和既有测试可运行。涉及 format 的提交要包含 migrator、repository fixture、备份/回退测试和版本说明；不能只改 Pydantic model 而不提供旧历史路径。

## 17. M6 与 M7 的边界

M6 负责“历史与多轮能力本身可用且可靠”，包括本地持久化、重启行为、隐私删除、资源上限和真实多轮 smoke。M7 只负责最终交付收口：全量复验、README.txt、录屏、密钥/仓库扫描、交付清单和最终提交。

以下内容不得留到 M7：JSON format/migration、原子写与锁、Session API、follow-up 上下文、重启收敛、删除、资源关闭、M6 自动化测试。M7 发现这些缺口时应退回 M6 修复，而不是在交付阶段临时拼接。
