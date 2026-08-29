# Coding Agent M5 UX 重构实施计划（修订版）

> 阶段名称：M5 — 可组合任务运行 UX、确定性执行轨迹与任务总结
>
> 建议周期：2026-08-29 至 2026-08-31
>
> 前置条件：M1–M4 已完成；M4 固定 Demo 最近一次真实模型验收为 3/3
>
> 目标：不改变 LLM、Tool Schema、StopController 和工具执行语义，把结构化执行事实组织成易读、可恢复、可验证的单次任务运行（TaskRun），并为 M6 的历史任务与多轮会话保留稳定组合接口。

## 0. 审查结论与本次修订

原计划的方向正确：保留结构化事件、使用确定性 Formatter、按 `call_id` 合并工具生命周期、从 Runtime 事实生成 Summary，并在完成后重跑 M4。

但以下内容若不调整会造成返工或错误承诺，本版已经修正：

1. **里程碑冲突**：M5 保留为 UX 重构；历史任务与多轮会话统一为 M6；最终交付统一顺延为 M7。
2. **“Codex 风格”不可验收**：不以品牌相似度或像素复制为目标，改为可衡量的任务线程、信息层级、响应式和无障碍标准。
3. **ASCII 草图不是视觉目标**：实施前必须截取当前关键状态，并形成一份被接受的桌面/窄屏视觉基线；未完成前不进入大规模 CSS 重构。
4. **当前不是多轮会话，但 M5 不能封死 M6**：每次提交仍创建新的 Task。M5 不展示尚不存在的“继续对话”，但把单个 Task 视为可组合的 `TaskRun`，避免 M6 重写 Thread reducer、Composer 和 Summary。
5. **Workspace API 不暴露绝对路径**：Sidebar 继续显示安全的工作区名称，不新增绝对路径泄露。
6. **Tool/File/Command 不能重复成为三条主活动**：同一 `call_id` 必须形成一个 Activity，文件 Diff 或命令输出作为该 Activity 的附件。
7. **ExecutionTrace 不能只在成功返回时存在**：Trace 必须由 Task 生命周期拥有，确保失败、取消和服务关闭也能生成 partial summary。
8. **不能扫描有界 EventLog 生成 Summary**：采用实时 Trace Recorder，在同一发布路径中消费原始结构化事实；不在 Runtime 里维护第二套易漂移的手工统计。
9. **`tests_passed` 判定原文有歧义**：第一版仅识别明确的 pytest 命令，并以“最后一次识别出的 pytest 命令”的退出状态为准。
10. **前端单测没有基础设施**：当前只有 typecheck/build；若 Formatter/Reducer 测试列为验收项，必须明确引入 Vitest，组件测试再引入 Vue Test Utils 和 jsdom。
11. **Browser smoke 依赖未固定**：如果它是退出标准，必须把 Playwright 测试依赖和脚本纳入 lockfile，而不是依赖开发机偶然安装。
12. **缺少无障碍与长任务行为**：本版把键盘、焦点、live region、对比度、reduced motion、自动滚动和大事件序列列为 P0。
13. **选中内容与运行状态不能是同一个状态**：M5 先把“当前展示的 TaskRun”和“全局正在运行的 Task”概念分离；M6 才能在后台任务运行时安全浏览历史会话。

## 1. 范围与非目标

### 1.1 P0 交付

- Sidebar + ConversationThread 壳层 + 单个 TaskRun + Composer 的页面结构；M5 的 `runs` 长度固定为 0 或 1；
- 用户 Prompt、非空 Agent 消息、Recovery、工具活动和终态 Summary 的统一时间流；
- 六种工具的确定性自然语言 Formatter；
- `tool_started`、`tool_finished` 及同 `call_id` 的 `file_changed` / `command_finished` 聚合；
- 真实 Diff、命令结果、截断/超时/清理状态；
- 完整任务 ExecutionTrace 与成功/失败 Summary；
- 刷新恢复、410 历史过期、404 服务重启和终态一致性回归；
- 桌面/窄屏、键盘和基本无障碍验收；
- M4 真实模型 Demo 重新连续 3/3。

### 1.2 P1（时间允许）

- Raw Event 调试抽屉；
- 温和的状态动画和自动滚动；
- 更细致的 Diff 行统计；
- 活动耗时和聚合统计的视觉优化。

### 1.3 明确不做

- 多轮 Conversation UI、任务历史列表和 JSON 文件持久化；这些属于 M6；
- 用户取消 API；
- Monaco、内置 Terminal、IDE 文件树、多 Repo、多 Workspace；
- Git 历史、Git 工具、多用户、多 Agent、插件系统；
- 逐像素复制 Codex 或使用其品牌资产。

M5 虽不实现 M6 功能，但不得把“整个会话”等同于单个 Task，也不得让 Sidebar、Composer 或恢复逻辑直接拥有网络请求。第 5 节定义的兼容接口属于 M5 P0。

## 2. 产品与交互约束

### 2.1 单次 TaskRun 模型

当前 API 是“一次 Prompt 创建一个 Task”。页面必须遵守：

- 运行中 Composer 禁用，不能重复提交；
- `New Task` 在运行中禁用，它不是取消按钮；
- 完成/失败后可以开始一个新 Task；
- 新 Task 会替换当前页面展示和版本化 recent-context 中的最近 Task 引用，但不删除后端内存中的旧 Task；
- 文案使用“开始新任务”，不使用“继续对话”或暗示共享上下文的措辞。

这里的“替换展示”只是 M5 产品行为，不是组件数据结构约束。`ConversationThread` 接收 `TaskRunViewModel[]`；M5 只传入一个 run，M6 再传入同一会话的多个 run。

### 2.2 Workspace 与安全

- Sidebar 只展示 `/api/meta.workspace` 返回的名称；
- 不新增绝对路径、API Key、Base URL 或供应商原始响应 JSON 展示；Agent 的受限消息仍按 Thread 契约显示；
- 文件、模型和命令文本继续按不可信内容处理；禁止 `v-html`；
- Raw Event 默认折叠，并继续受后端事件载荷上限约束。

### 2.3 事实层级

1. Task 状态、Trace、ToolResult、FileChange、CommandResult 是执行事实；
2. 模型最终回复是 Agent Narrative；
3. Formatter 只翻译已有事实，不推断缺失事实；
4. Narrative 与事实冲突时，UI 明确分区并以事实为准。

## 3. Phase 0：基线与视觉目标

在改页面前，先用同一浏览器、同一 viewport 捕获并检查当前页面：

1. Idle / scaffold 或 agent-ready；
2. Running，至少包含一个进行中的工具调用；
3. Completed，包含 File Diff、pytest 命令和最终结果；
4. Failed / recovery；
5. 390px 窄屏关键状态。

根据证据形成桌面和窄屏视觉目标，至少确定：

- Thread 最大宽度、Sidebar 宽度和 Composer 位置；
- 消息、活动、Diff、Command、Summary 的层级；
- running/success/error/warning 的颜色和非颜色提示；
- focus、hover、展开、长文本、空内容和截断状态。

ASCII 图只表达信息架构，不能替代视觉目标。Phase 0 未通过，不开始全局样式重写。

## 4. 页面信息架构

### 4.1 Sidebar

展示：

- Coding Agent；
- Workspace 名称；
- Agent Ready / 未配置状态；
- `开始新任务`。

六工具清单不再常驻主导航。需要保留时放入 P1 的 Runtime Details，并默认折叠。

Sidebar 在 M5 只渲染上述内容，但组件输入预留 `historyItems`、`selectedId`、`onSelect` 和加载/空状态；M5 传入空列表且不显示伪历史。这样 M6 只增加数据源和历史分组，不重写 Sidebar 框架。

### 4.2 ConversationThread 与 TaskRunSection

主区域由 `ConversationThread` 壳层和一个 `TaskRunSection` 组成。单个 TaskRun 按用户理解组织为：

- User Message：来自 `Task.prompt`，时间使用 `Task.created_at`；
- Agent Message：只展示非空 `assistant_message.payload.message`；
- Recovery：独立 warning，不伪装成模型推理；
- Tool Activity：按 `call_id` 聚合的单条活动；
- Terminal Summary：来自 Task API 的终态和 Summary。

页面不能生成模型没有说过的“为什么”。没有 Agent 文本时直接展示确定性活动，不补写推理过程。

`TaskRunSection` 必须有以 `task_id` 为根的稳定 key 和清楚的运行边界；M6 将多个 TaskRun 按会话内序号追加时，已有 Activity 不得重新挂载或跳动。

### 4.3 Composer

- Idle：可创建 Task；
- Pending/Running：禁用，并说明正在处理；
- Completed/Failed：允许“开始新任务”；
- 保留 8000 字符限制、去空白和防重复提交；
- 窄屏下不遮挡 Summary 或系统提示。

Composer 只负责输入与发出意图，不直接调用 `POST /api/tasks`：

```typescript
type ComposerIntent =
  | { kind: 'new_task'; prompt: string }
  // M6 增加：{ kind: 'follow_up'; sessionId: string; prompt: string }
```

M5 只能产生 `new_task`。这既避免虚假多轮承诺，也使 M6 可以在不改输入组件的情况下接入 follow-up API。

## 5. Thread View Model

前端不再由组件直接解释原始事件。新增纯函数层：

```typescript
type ThreadItem =
  | UserThreadItem
  | AgentThreadItem
  | ToolActivityThreadItem
  | RecoveryThreadItem
  | TerminalThreadItem

interface ToolActivityThreadItem {
  key: string              // task_id + call_id
  callId: string
  tool: string
  state: 'running' | 'success' | 'error' | 'cancelled' | 'unknown'
  started?: ToolStartedPayload
  finished?: ToolFinishedPayload
  fileChange?: FileChangedPayload
  command?: CommandFinishedPayload
  rawEvents: AgentEvent[]
}

interface TaskRunViewModel {
  taskId: string
  status: TaskStatus
  createdAt: string
  items: ThreadItem[]
  summary: TaskSummary | null
  eventWindowComplete: boolean
}

interface ConversationThreadViewModel {
  conversationId?: string   // M5 未持久化会话时为空
  runs: TaskRunViewModel[]  // M5 长度为 0 或 1；M6 可为多个
}
```

`buildTaskRun(task, events)` 必须：

- 按数字事件 ID 处理，复杂度保持 O(n)；
- 使用 `Map<call_id, activity>` 聚合并保持首次出现顺序；
- 让 `file_changed` 和 `command_finished` 成为同一活动的附件，不重复生成主活动；
- 支持 started 尚未 finished 的 running 状态；
- 支持只有 finished、只有 specialized event、取消事件和 `payload_truncated` 的降级展示；
- 忽略空的 agent message，但保留 recovery/scaffold；
- 410 后只表示“当前保留的事件窗口”，不得暗示时间线完整；
- 使用稳定 key 更新已有 Activity，避免流式到达时卡片跳动。

`buildConversationThread(runs)` 在 M5 仅负责保序组合，不重新解释事件。M6 可以从持久化 Session 加载多个 Task，再复用同一 `buildTaskRun`。Summary 仍以 Task 为单位，禁止提前设计一份会覆盖各 Task 事实的可变“会话总总结”。

### 5.1 M6 前向兼容状态边界

- `activeTask`：全局唯一的在途任务及 SSE 观察状态；
- `selectedContext`：当前展示的 TaskRun，M5 与 activeTask 通常相同但类型上独立；
- `recentContextStore`：封装版本化 localStorage 读写与损坏数据清理；组件不得直接访问 key；
- `TaskRunViewModel`：纯展示数据，不拥有 SSE、fetch 或 localStorage；
- Event ID 只在单个 Task 内排序，跨 Task 的顺序由 M6 的会话 ordinal 决定，不比较不同 Task 的 Event ID；
- Tool `call_id` 只在 Task 内唯一，所有前端 key 必须带 `task_id` 前缀。

M5 使用 `coding-agent:recent-context:v1` 保存 `{ taskId }`，并继续兼容读取旧的 `coding-agent:last-task-id`。M6 将 v1 数据迁移为 `{ sessionId, taskId }`；迁移失败只清除该引用，不影响后端历史。

## 6. 确定性 Formatter

建议文件：

```text
frontend/src/thread/buildTaskRun.ts
frontend/src/thread/buildConversationThread.ts
frontend/src/formatters/toolActivity.ts
frontend/src/formatters/fileActivity.ts
frontend/src/formatters/commandActivity.ts
```

Formatter 返回展示模型，不返回业务结论：

```typescript
interface ActivityPresentation {
  title: string
  detail?: string
  status: 'running' | 'success' | 'error' | 'warning'
}
```

规则：

| 工具 | 默认成功文案 | 事实来源 |
|---|---|---|
| `list_files` | 查看了项目目录 / `{path}` 目录 | started arguments + finished ok |
| `read_file` | 阅读了 `{path}` | finished result output 优先，arguments 兜底 |
| `search_text` | 搜索了“{query}” | arguments；匹配数仅在 output 明确提供时显示 |
| `write_file` | 创建/更新了 `{path}` | `file_changed.action`，无 file_changed 不声称已修改 |
| `replace_in_file` | 修改了 `{path}` | `file_changed`，无 file_changed 不声称已修改 |
| `run_command` | 运行测试 / 执行命令 | `command_finished` 的 ok、exit、timeout、cleanup |

共同要求：

- 失败优先展示结构化 `error_code` 的友好映射，原消息在 Details；
- `payload_truncated` 使用“活动详情已截断”的安全降级，不解析 preview 为可信结构；
- 路径、query、command 长度在视觉层省略，完整受限值可在 Details 查看；
- 不重复裁剪 ToolResult 业务输出；只做视觉省略和可滚动容器。

## 7. File 与 Command 附件

### 7.1 File Change

- 清楚区分 created / modified；
- 展示真实文本 Diff；
- `diff_truncated` 和事件 `payload_truncated` 分开说明；
- 不根据 Diff 文本猜测业务含义；
- 不展示“修改失败”的 File Change，因为失败时本来不应有 `file_changed`；失败归属 Tool Activity。

### 7.2 Command

- 默认显示命令、成功/失败、exit code、duration、timeout、cleanup；
- stdout/stderr 默认折叠，展开后展示后端受限内容；
- 测试通过以 `ok=true` 且 exit code 为 0 为事实；
- `2 passed` 等文本只是命令输出摘录，不替代结构化成功状态；
- timeout 和 cleanup failure 必须有文字/图标，不能只靠颜色。

### 7.3 Debug Details

P1 可显示合并活动的 `rawEvents[]`，而不是单个 Raw Event。默认折叠，并明确这是开发信息。

## 8. ExecutionTrace 与 Summary 架构

### 8.1 所有权

ExecutionTrace 由 TaskManager 的单 Task 生命周期拥有，不放在全局 Runtime 状态，也不只依赖 `AgentRuntime.run()` 成功返回。

推荐增加轻量 `TraceRecorder`：

```text
Runtime / injected runner
        │ publish(raw structured event)
        ▼
TraceRecorder ─────► ExecutionTrace
        │
        ▼
EventLog（payload/history bounds）
```

它在同一 `publish` 调用中保留原始结构化 payload，并在 EventLog 发布成功后更新 Trace；这不是“任务结束后扫描 EventLog”，因此即使 payload 被裁剪或历史被淘汰也能保留完整的有界统计。EventLog 发布失败时不得记录未发生的事实。Recorder 不改变事件、不进入 LLM context、不改变 Tool Schema。

为避免强耦合，`TaskRunner` 应依赖只包含 `publish()` 的 EventPublisher Protocol；TaskManager 把 TraceRecorder 传给 Runner，SSE 仍读取真正的 EventLog。现有注入 Runner 测试必须同步迁移。

### 8.2 Trace 记录规则

- `tool_calls`：每个唯一 `tool_started.call_id` 计一次；重复事件不重复计数；
- `decision_steps`：只统计 `assistant_message.mode == agent` 的成功模型决策，不把 recovery 重试算作决策；
- `files_read`：成功 `read_file` 的结果路径，保持首次出现顺序并去重；
- `files_changed`：成功 `file_changed.path`，保持首次出现顺序并去重；
- `commands`：按 `command_finished` 顺序记录有界事实；
- `errors`：记录安全错误码，不保存供应商响应正文或密钥；
- `duration_ms`：由 Task `started_at` / `finished_at` 计算，避免另一个时钟口径。

所有列表和字符串必须有显式上限。Summary 不是无限审计日志。

### 8.3 建议模型

```python
class CommandSummary(BaseModel):
    command: str
    ok: bool
    exit_code: int | None = None
    timed_out: bool = False
    cleanup_ok: bool = True

class VerificationSummary(BaseModel):
    kind: Literal['pytest']
    command: str
    passed: bool
    exit_code: int | None = None
    output_excerpt: str | None = None
    output_truncated: bool = False

class TaskSummary(BaseModel):
    files_read: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    commands: list[CommandSummary] = Field(default_factory=list)
    verification: VerificationSummary | None = None
    tool_calls: int = 0
    decision_steps: int = 0
    error_codes: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
```

模型最终 Narrative 继续由现有 `Task.result` 提供，失败事实由 `Task.error` 提供，避免再复制一份可能漂移的 `final_message`。TaskSummary 只保存 Runtime Facts。

### 8.4 pytest 判定

M5 第一版只识别命令 argv 等价于：

- `pytest ...`
- `python -m pytest ...`
- `python3 -m pytest ...`

若执行多次，以最后一次识别出的 pytest 命令为 Verification：

- exit code 0 且 `ok=true` → passed；
- 非 0、timeout 或 `ok=false` → failed；
- 未执行已识别命令 → `verification=None`。

命令字符串中偶然包含“pytest”不能算测试。`output_excerpt` 是受限展示摘录，不参与 passed 判定。npm/vitest/jest/cargo/go 留到 P1。

### 8.5 终态顺序

TaskManager 在所有成功、失败、取消和 shutdown 路径中必须按以下顺序收口：

```text
设置 Task terminal status/error/result
→ 设置 finished_at
→ build TaskSummary
→ 保存到 Task.summary
→ 发布 task_completed/task_failed
```

这样终态 SSE 到达后，`GET /api/tasks/{id}` 已经能返回一致 Summary。`summary` 在 PENDING/RUNNING 时为 `null`，在 terminal 时必须非空。

终态事件无需复制完整 Summary，避免放大有界事件历史；前端沿用 M3 的终态二次查询取得 Summary。

## 9. API 与前端契约

扩展现有 Task：

```python
class Task(BaseModel):
    ...
    summary: TaskSummary | None = None
```

要求：

- 不增加独立 Summary API；
- PENDING/RUNNING 返回 `summary=null`；
- COMPLETED/FAILED 返回 summary；
- 旧字段 `result` / `error` 保持兼容；
- 前端 `parseTask` 必须严格校验嵌套 Summary；
- Summary 中不包含完整 stdout/stderr、Diff 或 Raw Event；
- 404 重启后仍明确不可恢复，不能把 Summary 设计误称为持久化。

M5 不提前增加 `session_id` API 字段。前端的 `conversationId?` 只是展示层兼容位；M6 必须通过正式、严格校验的 Session DTO 填充，不能从 task_id 或 localStorage 推导伪会话。

## 10. 组件落点

建议结构：

```text
frontend/src/
├── App.vue
├── types.ts
├── api/client.ts
├── state/recentContext.ts
├── thread/buildTaskRun.ts
├── thread/buildConversationThread.ts
├── formatters/
│   ├── toolActivity.ts
│   ├── fileActivity.ts
│   └── commandActivity.ts
└── components/
    ├── Sidebar.vue
    ├── ConversationThread.vue
    ├── TaskRunSection.vue
    ├── TaskComposer.vue
    ├── UserMessage.vue
    ├── AgentMessage.vue
    ├── ActivityItem.vue
    ├── FileChangeDetails.vue
    ├── CommandDetails.vue
    ├── RecoveryItem.vue
    └── TaskSummary.vue
```

不要求为了目录好看一次性删除现有 M3 组件。先让新 Thread 通过相同事件 fixture，再替换 App 中的 AgentTimeline；确认无引用后再删除旧组件。

## 11. 视觉、响应式与无障碍 P0

- Thread 主列在宽屏限制可读宽度，Diff/Command 可比正文略宽但不突破 viewport；
- 窄屏 Sidebar 收起为顶部项目信息，Composer 不遮挡内容；
- 所有状态同时使用图标/文字和颜色；
- 交互控件有可见 focus，Details 可用键盘展开；
- 连接、恢复、终态使用适当 `role=status` / `aria-live`，避免每条流式事件都打断读屏；
- DOM 顺序与视觉顺序一致；
- 时间、状态、按钮具有可理解名称；
- 文字和交互元素满足 WCAG AA 对比度目标；
- 尊重 `prefers-reduced-motion`；
- 自动滚动只在用户本来位于底部附近时发生，用户上滚后不抢回位置；
- 长路径、长命令、无空格文本和 512 个事件不会造成横向页面溢出。

截图只能支持视觉风险判断，键盘、读屏、focus 和 live region 必须实际测试，不能声称仅凭截图达到完整无障碍合规。

## 12. 修订后的实施阶段

### Phase 0：视觉基线和目标

完成第 3 节截图、状态清单和桌面/窄屏目标。此阶段不改业务逻辑。

### Phase 1：契约与测试基础

- 定义 TaskSummary、ThreadItem、TaskRunViewModel、ConversationThreadViewModel 和 fixture；
- 定义 `ComposerIntent`、`activeTask` / `selectedContext` 边界和版本化 recent-context 迁移；
- 前端加入 Vitest；若做 Vue 组件测试，同时加入 `@vue/test-utils` 与 jsdom；
- 若 browser smoke 是退出标准，将 `@playwright/test` 作为明确测试依赖并更新 lockfile；
- 先写 reducer/formatter/summary 的失败测试。

### Phase 2：Trace 与 Summary 后端

- 实现 ExecutionTrace、TraceRecorder、SummaryBuilder；
- 更新 TaskRunner 的 EventPublisher Protocol 和注入 Runner；
- 覆盖成功、失败、取消、shutdown、历史淘汰、重复 call_id 和多次 pytest；
- 扩展 Task API 和前端 Task parser。

### Phase 3：Thread Reducer 与 Formatter

- 实现 O(n) `buildTaskRun` reducer 与只负责组合的 `buildConversationThread`；
- 六工具自然语言；
- 生命周期聚合、orphan/truncated/cancelled fallback；
- 使用真实 M4 事件 fixture 回归。

### Phase 4：页面骨架与任务线程

- Sidebar、ConversationThread、TaskRunSection、TaskComposer；M5 仅显示一个 TaskRun；
- User/Agent/Recovery/Terminal；
- 保留 M3 的 watchTask、410、404、restoreTask、refreshTask 和终态一致性逻辑，但把网络观察状态移出展示组件；
- 验证 Sidebar 空历史输入和 Composer `new_task` 意图，为 M6 接入点加契约测试。

### Phase 5：File / Command / Summary

- File 和 Command 作为 Tool Activity 附件；
- TaskSummary 展示 Narrative、Changes、Verification、Execution、Failure；
- 事件窗口不完整时仍用 Task Summary 展示完整终态事实。

### Phase 6：无障碍、响应式与 Debug

- 完成键盘/focus/live region/reduced motion/自动滚动；
- 完成 390px 和长内容压力测试；
- 时间允许再加入 Raw Event Debug。

### Phase 7：收口验证

- 后端全量 pytest、Ruff；
- 前端 Vitest、typecheck、production build；
- browser smoke 覆盖 idle/running/completed/failed/refresh/410/404/窄屏；
- 在用户明确授权真实调用和费用后，重新运行 M4 三轮；
- 密钥扫描和文档更新。

## 13. 测试矩阵

### 13.1 Reducer / Formatter

- 六工具 running/success/error/cancelled；
- started + finished + specialized event 聚合；
- out-of-order fixture、orphan event、重复 ID/call_id；
- `payload_truncated`；
- 空 assistant message；
- 410 后不完整窗口；
- 两个 TaskRun 的 event ID / call_id 相同仍生成不同稳定 key，组合后顺序不串线；
- 500+ 事件保持线性处理且 UI 不横向溢出。

### 13.2 Trace / Summary

- 工具调用与 agent decision 计数；
- files_read/files_changed 去重且保持顺序；
- commands 顺序和字段上限；
- pytest 最后一次成功/失败、timeout、未测试；
- completed/failed/runtime error/shutdown 均有 summary；
- Summary 不受 EventLog 历史淘汰影响；
- 终态 SSE 与 GET Task Summary 一致。

### 13.3 API / 前端

- terminal 前 `summary=null`，terminal 后存在；
- 嵌套 payload 的严格运行时校验；
- 恢复刷新、410、404 和 204；
- 新任务不伪装成原任务后续消息；
- Composer 只发出 `new_task` 意图，Sidebar 空历史不会出现伪条目；
- recent-context v1、旧 key 迁移和损坏 localStorage 降级；
- `activeTask` 与 `selectedContext` 分离后，展示切换不终止任务观察；
- Narrative 与 Runtime Facts 冲突 fixture 下事实优先。

### 13.4 Browser 与 M4

- 页面启动、Agent Ready、提交、自然语言活动、Diff、命令、Summary；
- 键盘操作和 focus；
- 桌面和 390px 窄屏；
- 页面刷新恢复与终态一致性；
- M4 每轮重置、基线失败、真实 Agent 修复、独立 pytest，要求新的 3/3，不复用旧报告。

## 14. M5 退出标准

只有同时满足以下条件才完成：

- [ ] 已有经过检查的桌面/窄屏视觉目标，不以 ASCII 图替代；
- [ ] 页面是 Sidebar + ConversationThread + 单个 TaskRunSection + Composer；
- [ ] 用户 Prompt、非空 Agent Message、Recovery 和失败终态清楚；
- [ ] 六工具默认使用确定性自然语言；
- [ ] 同一 `call_id` 只有一个主 Activity，File/Command 是附件；
- [ ] Diff、stdout/stderr、timeout、cleanup 和两类 truncated 均不误导；
- [ ] Summary Facts 来自完整 Trace，模型 Narrative 不覆盖事实；
- [ ] completed 和 failed（含 shutdown）均有 terminal Summary；
- [ ] 刷新、410、404、204 和终态查询保持 M3 语义；
- [ ] 新任务文案不暗示多轮上下文或取消能力；
- [ ] `buildTaskRun` 可被多 Task 组合复用，Task/Event/Tool key 均不会跨 Task 冲突；
- [ ] Composer、Sidebar 和 recent-context 通过前向兼容契约测试，且 M5 不显示伪历史/伪 follow-up；
- [ ] 键盘、focus、live region、AA 对比度目标、reduced motion 和窄屏通过；
- [ ] 后端 pytest/Ruff、前端 Vitest/typecheck/build、browser smoke 全部通过；
- [ ] 经用户授权后，M4 真实模型 Demo 重新连续 3/3；
- [ ] 报告、截图、日志和仓库不包含 API Key。

## 15. 风险与止损

| 风险 | 预防与止损 |
|---|---|
| CSS 重构破坏恢复链路 | App 网络状态机保持不动，先替换 presentation；每 Phase 跑 M3 恢复测试 |
| Trace 与事件事实漂移 | TraceRecorder 消费同一原始发布事实，不在 Runtime 重写一套分支 |
| Summary 无限增长 | 所有列表/字符串显式上限，不保存完整输出/Diff |
| UI 把缺失事实写成成功 | Formatter 仅在 finished/specialized 事件证明时使用成功动词 |
| “新任务”被理解为多轮 | M5 明确新 Task 且不复用上下文；内部使用可组合 TaskRun，但不暴露尚未实现的 follow-up |
| M6 接入时重写 M5 | ConversationThread 组合 TaskRun；Composer 发意图；Sidebar 以数据输入驱动；recent-context 版本化 |
| 大事件序列卡顿 | O(n) reducer、稳定 key；使用 500+ fixture 测试，必要时再评估虚拟列表 |
| 真实模型回归产生费用 | 只在确定性测试和 smoke 通过后，经用户授权运行三轮 |
| M5 挤压后续里程碑 | P1 首先下砍；不得挪用 M6 的持久化/重启安全，也不得挪用 M7 的密钥扫描、README.txt、视频和提交检查 |

## 16. 建议提交划分

```text
test(ui): add thread reducer and formatter fixtures
feat(agent): add bounded execution trace and terminal task summary
feat(ui): build reusable task-run reducer and deterministic activity formatters
feat(ui): compose single task run in conversation thread shell
feat(ui): attach file command details and task summary
fix(ui): preserve recovery accessibility and narrow-screen behavior
test: add m5 browser and m4 real-model regressions
docs: document m5 ux contracts and verification
```

每个提交都应保持已有测试可运行。不要在一个提交中同时更改 Runtime、API 契约、完整页面结构和全部样式。

## 17. M5 完成后的边界

M5 的成果是“用户能理解一个真实 Task 如何被完成”，不是完整 IDE，也不是多轮聊天产品。它应让用户快速确认：

- Agent 检查了什么；
- 哪些行为成功、失败或恢复；
- 哪些文件真实发生变化；
- 执行了哪些命令，最后一次识别出的 pytest 是否通过；
- Task 为何完成或失败；
- Summary 中哪些是模型叙述，哪些是 Runtime 事实。

完成 M5 后进入 M6“历史任务与多轮对话”。M6 复用本计划的 TaskRun、Summary、Composer intent 和 Sidebar 接口；不再重复实现活动格式化、工具输出裁剪或 Task 事实提取。M6 完成后进入 M7 最终交付，不再以新增 P1 功能阻塞 README.txt、视频、密钥扫描和最终提交检查。
