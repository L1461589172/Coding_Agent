# Coding Agent M5 UX 重构实施计划

> 阶段名称：M5 - Codex 风格前端体验、自然语言执行轨迹与任务总结  
> 目标：在不破坏现有 Agent Runtime、工具系统和 M4 真实模型闭环的前提下，将当前偏工程调试风格的前端重构为更接近 Codex 的任务交互界面，并将工具调用结果从原始结构化 JSON 转换为自然语言执行过程，最终为每次任务生成可信、完整的任务总结。

---

# 1. 背景

当前 Coding Agent 已经完成核心执行能力：

- M0：项目基础框架；
- M1：六个本地工具；
- M2：Agent Runtime；
- M3：Task API、SSE 与前端 Timeline；
- M4：真实模型 Demo、红测到绿测闭环及连续三次成功验证。

当前系统已经能够完成：

```text
用户输入任务
    ↓
Agent Runtime
    ↓
LLM 决策
    ↓
Tool Call
    ↓
文件读取 / 搜索 / 修改 / 命令执行
    ↓
Tool Result
    ↓
继续模型决策
    ↓
真实 pytest 验证
    ↓
最终结果
```

但是当前前端主要围绕“事件调试”设计。

存在以下问题：

1. 页面整体仍偏工程控制台，而不是 Coding Agent 产品；
2. `tool_started`、`tool_finished`、`file_changed`、`command_finished` 等事件展示过于技术化；
3. 工具调用结果中存在较多 JSON 风格内容，不利于普通用户阅读；
4. 同一次工具调用可能拆成多个事件卡片，信息密度过高；
5. Agent 对话与执行行为之间缺少统一的任务流体验；
6. 最终结果主要依赖模型最终回复，没有系统化总结整个任务过程；
7. 用户难以快速回答以下问题：
   - Agent 看了哪些文件？
   - Agent 修改了哪些文件？
   - Agent 执行了哪些命令？
   - 测试是否真的通过？
   - 任务经过了多少步骤？
   - 是否发生过失败和恢复？

因此 M5 的重点不是继续增强 Agent 的底层能力，而是将现有执行能力重新组织成更清晰、更接近 Codex 的交互体验。

---

# 2. M5 总体目标

本阶段包含三个核心目标。

## 2.1 Codex 风格页面重构

将当前：

```text
Workspace Panel
+
Task Status
+
Event Timeline
+
Tool JSON
+
Final Result
```

重构为：

```text
Sidebar
+
Task Thread
+
Agent Message
+
Natural Language Activity
+
File Diff
+
Command Result
+
Task Summary
+
Bottom Composer
```

最终页面重点从：

> “后端发生了哪些事件”

转变为：

> “Agent 正在怎样完成这个任务”。

---

## 2.2 工具结果自然语言化

后端仍然保留结构化 JSON Event。

前端增加独立 Formatter 层：

```text
Structured Event
      ↓
Formatter
      ↓
Human-readable Activity
```

例如：

```text
read_file
```

不再默认展示：

```json
{
  "tool": "read_file",
  "arguments": {
    "path": "calculator.py"
  }
}
```

而展示：

```text
✓ 阅读了 calculator.py
```

---

## 2.3 任务结束后生成完整总结

任务完成后增加 Task Summary。

总结必须同时包含：

```text
模型总结
+
真实执行事实
```

例如：

```text
任务完成

修复了 divide 在除数为 0 时抛出异常的问题。

修改
• calculator.py

验证
• python -m pytest -q
• 2 passed

执行统计
• 阅读 2 个文件
• 修改 1 个文件
• 执行 1 条命令
• 5 个 Agent 决策步骤
• 5 次工具调用
```

其中执行事实必须来源于 Runtime，而不能完全依赖模型自行描述。

---

# 3. 设计原则

M5 必须遵循以下原则。

## 3.1 后端保存结构，前端负责人类表达

不得为了页面显示方便，将后端 Event 改成纯自然语言。

仍保持：

```text
Backend
    ↓
Structured Event
    ↓
Frontend Formatter
    ↓
Natural Language
```

原因：

- 方便测试；
- 保留机器可读性；
- 支持未来不同 UI；
- 支持 Debug；
- 避免逻辑散落到 Runtime 文本中。

---

## 3.2 不让 LLM 二次翻译 Tool Result

自然语言 Tool Activity 应优先采用确定性程序转换：

```typescript
formatToolActivity(event)
```

而不是：

```text
Tool Result
    ↓
再次请求 LLM
    ↓
自然语言
```

避免：

- 增加 API 成本；
- 增加延迟；
- 引入幻觉；
- 将真实结果错误总结。

---

## 3.3 UI 展示事实优先

例如测试结果：

```text
2 passed
```

必须来自：

```text
command_finished.stdout
exit_code
ok
```

不能只显示模型说：

> 测试已经通过。

---

## 3.4 Runtime 是事实来源

继续遵循项目原有原则：

> LLM 是不可信决策者，Runtime 是可信控制器，Tools 是受约束执行器。

M5 增加：

> UI 是 Runtime 事实的人类可读投影，而不是新的事实来源。

---

## 3.5 不破坏 M4 闭环

任何 UX 修改都不能破坏：

```text
真实模型
→ Tool Calling
→ 文件修改
→ pytest
→ task_completed
```

M5 完成后必须重新执行 M4 Demo。

---

# 4. 最终页面目标

建议最终页面布局：

```text
┌──────────────────┬──────────────────────────────────────────────┐
│ Coding Agent     │                                              │
│                  │  当前任务                                    │
│ Workspace        │                                              │
│ MyProject        │  你                                          │
│                  │  修复当前项目中失败的测试。                  │
│ ● Agent Ready    │                                              │
│                  │  Agent                                       │
│ + New Task       │  我先检查项目结构和相关测试。                │
│                  │                                              │
│                  │  ✓ 查看了项目目录                            │
│                  │  ✓ 阅读了 calculator.py                      │
│                  │  ✓ 阅读了 test_calculator.py                 │
│                  │                                              │
│                  │  Agent                                       │
│                  │  问题出在除零处理。                          │
│                  │                                              │
│                  │  ✓ 修改了 calculator.py                      │
│                  │                                              │
│                  │    Diff                                      │
│                  │    + if divisor == 0:                        │
│                  │    +     return None                          │
│                  │                                              │
│                  │  ✓ 运行测试                                  │
│                  │    python -m pytest -q                       │
│                  │    2 passed                                  │
│                  │                                              │
│                  │  ───────── Task completed ─────────           │
│                  │                                              │
│                  │  修复了 divide 的除零问题。                  │
│                  │                                              │
│                  │  Changes                                     │
│                  │  • calculator.py                             │
│                  │                                              │
│                  │  Verification                                │
│                  │  • python -m pytest -q                       │
│                  │  • 2 passed                                  │
│                  │                                              │
│                  │  [继续输入任务...........................]   │
└──────────────────┴──────────────────────────────────────────────┘
```

---

# 5. 页面信息架构

页面分为以下区域。

---

## 5.1 Sidebar

功能：

```text
项目名称
Workspace 路径
Agent Ready 状态
New Task
```

建议显示：

```text
Coding Agent

Workspace
Coding_Agent_TestWorkspace

● Agent Ready

+ New Task
```

当前六工具列表：

```text
list_files
read_file
search_text
write_file
replace_in_file
run_command
```

不再长期占据主 Sidebar。

可：

- 完全隐藏；
- 或放入一个可展开的 Debug / Runtime Details 区域。

---

## 5.2 Task Thread

Task Thread 是页面主体。

内容类型包括：

```text
User Message
Agent Message
Activity
File Change
Command
Recovery / Warning
Task Summary
```

所有内容按时间顺序排列。

---

## 5.3 Composer

输入区域固定在任务流底部附近。

包含：

```text
textarea
Send / Start Task
```

状态根据任务：

```text
Idle
Working
Completed
Failed
```

控制是否可以继续提交。

---

# 6. 前端组件重构

当前组件逐步调整。

建议目录：

```text
frontend/src/
├── App.vue
├── types.ts
│
├── api/
│   └── client.ts
│
├── components/
│   ├── Sidebar.vue
│   ├── TaskThread.vue
│   ├── TaskComposer.vue
│   │
│   ├── UserMessage.vue
│   ├── AgentMessage.vue
│   │
│   ├── ActivityItem.vue
│   ├── FileChangeItem.vue
│   ├── CommandItem.vue
│   ├── RecoveryItem.vue
│   │
│   └── TaskSummary.vue
│
└── formatters/
    ├── toolActivity.ts
    ├── commandActivity.ts
    ├── fileActivity.ts
    └── taskSummary.ts
```

---

# 7. Task Thread 数据组织

当前前端直接按 Event 渲染：

```text
event
event
event
event
```

M5 应增加一层 UI View Model。

例如：

```typescript
type ThreadItem =
  | UserThreadItem
  | AgentThreadItem
  | ToolActivityThreadItem
  | FileChangeThreadItem
  | CommandThreadItem
  | RecoveryThreadItem
  | SummaryThreadItem
```

实现：

```text
AgentEvent[]
    ↓
buildTaskThread()
    ↓
ThreadItem[]
    ↓
TaskThread.vue
```

这样 UI 不再直接依赖 Event 原始结构。

---

# 8. Tool Started / Finished 合并策略

同一次 Tool Call：

```text
tool_started
tool_finished
```

不应默认显示成两个卡片。

应通过：

```text
call_id
```

合并。

例如：

```text
tool_started:
call_id = call_123
read_file calculator.py

tool_finished:
call_id = call_123
ok = true
```

UI 最终只展示：

```text
✓ 阅读了 calculator.py
```

执行过程中可以先显示：

```text
○ 正在阅读 calculator.py
```

完成后更新成：

```text
✓ 阅读了 calculator.py
```

失败则：

```text
✕ 无法读取 calculator.py
```

---

# 9. 六种工具自然语言格式

---

## 9.1 list_files

### 运行中

```text
○ 正在查看项目目录
```

### 成功

根目录：

```text
✓ 查看了项目目录
```

子目录：

```text
✓ 查看了 src 目录
```

### 可选详情

```text
发现 12 个文件
```

### 失败

```text
✕ 无法查看 src 目录
```

展开：

```text
路径不存在
```

---

## 9.2 read_file

### 成功

```text
✓ 阅读了 calculator.py
```

指定范围：

```text
✓ 阅读了 calculator.py 第 20–80 行
```

### 失败

```text
✕ 无法读取 calculator.py
```

---

## 9.3 search_text

搜索：

```text
divide
```

显示：

```text
✓ 搜索了 “divide”
```

若有统计：

```text
找到 3 处匹配
```

点击展开可以显示：

```text
calculator.py:4
test_calculator.py:5
test_calculator.py:9
```

---

## 9.4 write_file

如果：

```text
action = created
```

显示：

```text
✓ 创建了 utils.py
```

如果覆盖：

```text
✓ 更新了 config.py
```

优先展示对应 `file_changed`。

---

## 9.5 replace_in_file

默认：

```text
✓ 修改了 calculator.py
```

下方展示 Diff。

不要默认展示：

```text
old_text
new_text
arguments
ToolResult JSON
```

---

## 9.6 run_command

pytest：

```text
✓ 运行测试
  python -m pytest -q

  2 passed
```

失败：

```text
✕ 测试失败
  python -m pytest -q

  1 failed, 1 passed
```

普通命令：

```text
✓ 执行命令
  python main.py
```

超时：

```text
✕ 命令执行超时
```

进程清理失败：

```text
⚠ 命令结束，但进程清理存在问题
```

---

# 10. File Change 展示

文件修改是 Coding Agent 中最重要的可视化之一。

建议：

```text
✓ 修改了 calculator.py

  3 additions · 1 deletion

  ┌──────────────────────────────
    def divide(a, b):
  +     if b == 0:
  +         return None
        return a / b
  └──────────────────────────────
```

支持：

```text
created
modified
```

若 diff 被截断：

```text
Diff 过长，仅显示部分内容
```

不得假装展示完整 Diff。

---

# 11. Command 展示

Command Item 包含：

```text
状态
命令
exit code
stdout
stderr
duration
```

默认折叠 stdout/stderr。

例如：

```text
✓ 运行测试
python -m pytest -q

2 passed in 0.18s
```

点击：

```text
Show output
```

展开完整的受限输出。

---

# 12. Raw JSON 调试模式

自然语言化以后不要彻底丢弃 JSON。

建议：

```text
Activity
    ↓
Details
    ↓
Raw Event
```

默认折叠。

仅供：

```text
Debug
开发
排查契约问题
```

普通用户不应直接看到。

---

# 13. Agent Message 展示

对于：

```text
assistant_message
```

应区分：

```text
mode = agent
mode = recovery
mode = scaffold
```

---

## Agent

例如：

```text
Agent

我先检查项目结构和失败测试。
```

---

## Recovery

例如：

```text
⚠ 模型请求暂时失败，正在重试。
```

可展开：

```text
LLM_TIMEOUT
2 / 3
```

---

## Scaffold

例如：

```text
模型尚未配置，Agent 无法执行任务。
```

---

# 14. Task Summary 设计

任务结束必须显示完整 Summary。

目标：

```text
✓ Task completed

修复了 calculator.py 中 divide 的除零行为。

Changes
• calculator.py
  增加 divisor == 0 时返回 None 的处理

Verification
• python -m pytest -q
• 2 passed

Execution
• 阅读 2 个文件
• 修改 1 个文件
• 执行 1 条命令
• 5 个 Agent steps
• 5 个 tool calls

Result
所有测试通过。
```

失败则：

```text
✕ Task failed

Agent 未能在最大步骤内完成任务。

Changes
• calculator.py

Verification
• python -m pytest -q
• 1 failed

Failure
AGENT_STEP_LIMIT
```

---

# 15. Summary 数据来源

Summary 分成：

```text
Agent Narrative
+
Execution Facts
```

---

## 15.1 Agent Narrative

来源：

```text
AgentRuntime final reply
```

例如：

```text
修复了 divide 对零除数的处理，并确认测试通过。
```

---

## 15.2 Execution Facts

必须来源于真实 Runtime。

包括：

```text
files_read
files_changed
commands
tests
tool_calls
decision_steps
errors
duration
```

不得依赖 LLM 自行声称。

---

# 16. 后端 TaskSummary 数据模型

建议新增：

```python
class CommandSummary(BaseModel):
    command: str
    exit_code: int | None = None
    ok: bool
    timed_out: bool = False


class TaskSummary(BaseModel):
    final_message: str = ""

    files_read: list[str] = []
    files_changed: list[str] = []

    commands: list[CommandSummary] = []

    tool_calls: int = 0
    decision_steps: int = 0

    tests_passed: bool | None = None

    duration_ms: float | None = None
```

可根据现有 Task Model 风格调整。

---

# 17. ExecutionTrace

不要依赖 EventLog 最终反向统计完整任务。

原因：

```text
Event History
```

有：

```text
字符上限
事件数量上限
410 历史淘汰
```

所以 EventLog 不是完整业务状态存储。

建议增加：

```text
backend/app/agent/trace.py
```

或：

```text
backend/app/agent/summary.py
```

---

## ExecutionTrace 示例

```python
@dataclass
class ExecutionTrace:
    tool_calls: int = 0
    decision_steps: int = 0

    files_read: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)

    commands: list[CommandSummary] = field(default_factory=list)

    started_at: float | None = None
    finished_at: float | None = None
```

---

# 18. Runtime Trace 更新

在：

```text
AgentRuntime.run()
```

创建：

```text
trace = ExecutionTrace()
```

每次模型成功决策：

```text
trace.decision_steps += 1
```

每次 Tool Call：

```text
trace.tool_calls += 1
```

---

## read_file

成功：

```text
trace.files_read += path
```

---

## write_file / replace_in_file

成功并 changed：

```text
trace.files_changed += path
```

---

## run_command

记录：

```text
command
exit_code
ok
timed_out
```

---

# 19. Summary Builder

建议新增：

```text
backend/app/agent/summary.py
```

职责：

```text
ExecutionTrace
+
final_message
+
terminal status
    ↓
TaskSummary
```

例如：

```python
def build_task_summary(
    trace: ExecutionTrace,
    final_message: str,
) -> TaskSummary:
    ...
```

---

# 20. tests_passed 判定

不能仅通过：

```text
command contains pytest
```

长期建议采用相对保守的方式。

第一版：

```text
存在 command：
包含 pytest
且
exit_code == 0
```

则：

```text
tests_passed = True
```

存在 pytest command 但最后一次失败：

```text
tests_passed = False
```

未执行 pytest：

```text
tests_passed = None
```

未来可以扩展：

```text
npm test
vitest
jest
cargo test
go test
```

当前不是 P0。

---

# 21. Task Model 扩展

建议：

```python
class Task(BaseModel):
    ...
    summary: TaskSummary | None = None
```

任务完成：

```text
COMPLETED
+
summary
```

任务失败也可以产生 Summary：

```text
FAILED
+
partial summary
```

这样前端即使 Event History 不完整，仍可以：

```text
GET /api/tasks/{id}
```

拿到最终 Summary。

---

# 22. API 契约

现有：

```text
GET /api/tasks/{id}
```

直接增加：

```json
{
  "id": "...",
  "status": "COMPLETED",
  "result": "...",
  "summary": {
    "files_read": [],
    "files_changed": [],
    "commands": [],
    "tool_calls": 5,
    "decision_steps": 5,
    "tests_passed": true
  }
}
```

不需要额外增加 Summary API。

---

# 23. 前端 TaskSummary 组件

新增：

```text
TaskSummary.vue
```

输入：

```typescript
summary: TaskSummary
status: TaskStatus
error?: TaskError
```

展示：

```text
Completion status
Agent narrative
Changes
Verification
Execution stats
Failure
```

---

# 24. 前端 Formatter 设计

新增：

```text
frontend/src/formatters/toolActivity.ts
```

核心接口：

```typescript
export interface ActivityPresentation {
  title: string
  detail?: string
  status: 'running' | 'success' | 'error' | 'warning'
}
```

例如：

```typescript
formatToolActivity(toolStarted, toolFinished)
```

返回：

```typescript
{
  title: '阅读了 calculator.py',
  status: 'success'
}
```

---

# 25. Formatter 不得承担业务逻辑

Formatter 可以：

```text
翻译名称
格式化路径
生成简洁句子
```

但不应该：

```text
判断文件是否真的修改成功
判断 pytest 是否真的通过
推断 Tool Result 没有表达的事实
```

这些必须来自 Event。

---

# 26. CSS / 视觉方向

目标是接近 Codex 的信息密度与层次，而不是逐像素复制。

建议：

### 主体

```text
最大宽度适中
大量留白
任务流居中
```

### Sidebar

```text
窄
低视觉权重
```

### Message

避免每条都使用大 Card。

更多使用：

```text
Avatar / Label
Text
```

### Activity

类似：

```text
✓ Read calculator.py
```

紧凑行式设计。

### File Diff

使用：

```text
monospace
局部背景
可滚动
```

### Command

默认摘要，输出可展开。

---

# 27. 不应复制 Codex 的内容

M5 不做：

```text
复杂代码编辑器
Monaco
内置 Terminal
多 Panel
IDE 文件树
多 Repo 管理
Git History
多 Agent
```

当前项目重点仍然是：

```text
Agent Task Execution
```

---

# 28. 开发阶段划分

---

# Phase A：页面骨架重构

目标：

```text
Sidebar
+
Task Thread
+
Composer
```

修改：

```text
App.vue
style.css
TaskInput.vue
```

新增：

```text
Sidebar.vue
TaskComposer.vue
```

验收：

- Workspace 正确显示；
- Agent Ready 状态正确；
- Task 可以正常提交；
- 当前 M3 功能不丢失；
- 页面在窄屏下不横向溢出。

---

# Phase B：Task Thread

新增：

```text
TaskThread.vue
UserMessage.vue
AgentMessage.vue
```

将：

```text
AgentTimeline.vue
```

逐步替换。

验收：

- 用户 Prompt 显示在 Thread；
- assistant_message 显示为 Agent 消息；
- 顺序和真实 Event 一致。

---

# Phase C：Tool Activity Formatter

新增：

```text
formatters/toolActivity.ts
ActivityItem.vue
```

支持六工具。

验收：

```text
list_files
read_file
search_text
write_file
replace_in_file
run_command
```

全部默认自然语言展示。

---

# Phase D：Tool Call 合并

根据：

```text
call_id
```

将：

```text
tool_started
+
tool_finished
```

合并。

验收：

单次：

```text
read_file
```

只出现一个 Activity。

运行：

```text
○ 正在阅读 calculator.py
```

完成：

```text
✓ 阅读了 calculator.py
```

---

# Phase E：File / Command UX

实现：

```text
FileChangeItem.vue
CommandItem.vue
```

重点：

```text
Diff
pytest result
stdout/stderr
truncate state
```

验收：

- 修改文件时显示真实 Diff；
- 创建和修改明确区分；
- pytest 结果明显；
- stderr 可以展开；
- truncated 状态明确。

---

# Phase F：ExecutionTrace

后端新增：

```text
ExecutionTrace
```

Runtime 执行过程中同步维护真实统计。

验收：

- read_file 统计正确；
- changed file 统计正确；
- command 统计正确；
- step 数正确；
- tool call 数正确；
- 不依赖 EventLog History 回读。

---

# Phase G：TaskSummary

新增：

```text
TaskSummary
SummaryBuilder
```

Task API 返回 Summary。

验收：

```text
COMPLETED
FAILED
```

都能返回有效 Summary。

---

# Phase H：TaskSummary UI

新增：

```text
TaskSummary.vue
```

验收：

任务完成后展示：

```text
Agent Summary
Changes
Verification
Execution
```

失败后展示：

```text
Partial Changes
Commands
Failure
```

---

# Phase I：Debug Details

自然语言 Activity 中增加：

```text
Details
```

可选显示：

```text
arguments
result
raw event
```

默认折叠。

验收：

普通页面无 JSON 噪声，但开发者仍可检查底层数据。

---

# 29. 测试计划

---

## 29.1 Formatter 单元测试

测试：

```text
read_file success
read_file failure
list_files
search_text
write_file created
write_file updated
replace_in_file
run_command pass
run_command fail
run_command timeout
truncated payload
```

---

## 29.2 ExecutionTrace 测试

验证：

```text
工具调用计数
step 数
files_read 去重
files_changed 去重
commands 顺序
test 状态
```

---

## 29.3 TaskSummary 测试

覆盖：

```text
成功任务
失败任务
无命令任务
pytest 成功
pytest 失败
多次 pytest 最终成功
命令 timeout
```

---

## 29.4 API 测试

验证：

```text
GET Task
```

包含：

```text
summary
```

并满足类型契约。

---

## 29.5 Frontend Typecheck

执行：

```powershell
npm.cmd run typecheck
```

必须通过。

---

## 29.6 Frontend Build

执行：

```powershell
npm.cmd run build
```

必须通过。

---

## 29.7 Browser Smoke

至少覆盖：

```text
页面启动
Workspace
Agent Ready
提交 Task
Activity 自然语言
File Diff
Command Result
Task Summary
刷新恢复
窄屏
```

---

## 29.8 M4 Regression

M5 完成后必须重新执行：

```powershell
.\.venv\Scripts\python.exe scripts\run_m4_demo.py --runs 3
```

要求：

```text
3/3 success
```

不能拿旧 M4 数据代替。

---

# 30. M5 验收标准

---

## 页面结构

- [ ] 页面重构为 Sidebar + Task Thread + Composer；
- [ ] Task Thread 成为主视觉区域；
- [ ] Workspace 和 Agent Ready 保留；
- [ ] 六工具状态不再占据主要空间。

---

## Agent Conversation

- [ ] 用户 Prompt 进入 Thread；
- [ ] Assistant Message 以 Agent 消息显示；
- [ ] Recovery 有独立视觉；
- [ ] Failed 状态明确。

---

## Tool Activity

- [ ] `list_files` 自然语言；
- [ ] `read_file` 自然语言；
- [ ] `search_text` 自然语言；
- [ ] `write_file` 自然语言；
- [ ] `replace_in_file` 自然语言；
- [ ] `run_command` 自然语言；
- [ ] 默认不显示 JSON；
- [ ] Raw JSON 仅在 Debug Details 中可见。

---

## Tool 合并

- [ ] tool_started / tool_finished 按 call_id 合并；
- [ ] running / success / error 状态可更新；
- [ ] 不重复显示相同工具调用。

---

## File Change

- [ ] created / modified 明确；
- [ ] 显示真实 Diff；
- [ ] truncated 明确；
- [ ] 修改失败明确。

---

## Command

- [ ] 显示命令；
- [ ] 显示 exit code；
- [ ] 显示成功 / 失败；
- [ ] pytest 结果清晰；
- [ ] stdout / stderr 可展开；
- [ ] timeout / cleanup 状态明确。

---

## Task Summary

- [ ] 显示模型最终总结；
- [ ] 显示 files read；
- [ ] 显示 files changed；
- [ ] 显示 command history；
- [ ] 显示测试结果；
- [ ] 显示 decision steps；
- [ ] 显示 tool calls；
- [ ] 显示 duration；
- [ ] 失败任务也有 partial summary；
- [ ] Summary Execution Facts 不依赖 LLM 自述。

---

## 稳定性

- [ ] 后端全量 pytest 通过；
- [ ] Ruff 通过；
- [ ] frontend typecheck 通过；
- [ ] frontend production build 通过；
- [ ] browser smoke 通过；
- [ ] M4 real-model Demo 重新 3/3 通过。

---

# 31. 优先级

## P0

必须完成：

```text
Codex 风格 Task Thread
Tool Result 自然语言
Tool Call 合并
File Diff
Command / Test Result
ExecutionTrace
TaskSummary
TaskSummary UI
```

---

## P1

时间允许：

```text
Activity 展开动画
执行时间
图标优化
Raw Event Debug
更漂亮的 Diff
自动滚动
```

---

## P2

本阶段明确不做：

```text
Monaco Editor
文件树 IDE
内置 Terminal
数据库 Task History
多 Workspace
多用户
Git 工具
多 Agent
插件系统
```

---

# 32. 风险

---

## 32.1 前端重构破坏已有 SSE 恢复

风险：

重构 `App.vue` 时误删：

```text
410 recovery
404 restart handling
localStorage restore
terminal consistency
```

措施：

保留：

```text
api/client.ts
watchTask
restoreTask
refreshTask
```

优先只改 Presentation Layer。

---

## 32.2 Formatter 和后端事件脱节

措施：

前端 parser 保持严格类型校验。

Formatter 必须基于：

```text
AgentEvent discriminated union
```

不能使用松散 `any`。

---

## 32.3 Summary 被 Event History 截断影响

措施：

采用：

```text
ExecutionTrace
```

而不是最终扫描 EventLog。

---

## 32.4 模型 Summary 与事实不一致

例如模型说：

```text
修改了 2 个文件
```

而 Runtime 只记录：

```text
1 file
```

UI 应优先显示 Runtime Execution Facts。

模型内容单独作为：

```text
Agent Summary
```

不得覆盖真实数据。

---

## 32.5 修改 Runtime 导致真实模型成功率下降

措施：

Summary Trace 不参与：

```text
LLM context
Tool schema
ToolResult
StopController
```

它只旁路记录。

M5 后重新跑 M4 3 次。

---

# 33. 推荐实施顺序

严格按以下顺序：

```text
1. 页面 Layout
2. Task Thread
3. Tool Formatter
4. Tool started/finished 合并
5. File Diff
6. Command UX
7. ExecutionTrace
8. TaskSummary Model
9. Task API Summary
10. TaskSummary UI
11. Debug Details
12. Tests
13. Browser Smoke
14. Real-model M4 Regression
15. 文档
```

不要先同时修改：

```text
Runtime
API
Frontend
Event Protocol
```

避免一次变化范围过大。

---

# 34. 建议 Commit 划分

建议不要一次提交全部。

例如：

```text
feat(ui): restructure page into codex-style task thread
```

```text
feat(ui): render tool activity in human-readable form
```

```text
feat(ui): merge tool lifecycle events and improve file command views
```

```text
feat(agent): add execution trace and task summary
```

```text
feat(ui): add task completion summary
```

```text
test: add m5 ux and task summary regressions
```

```text
docs: document m5 codex-style ux
```

这样出现问题更容易回滚。

---

# 35. 完成后的整体架构

M5 后：

```text
                         User
                          │
                          ▼
                    Task Composer
                          │
                          ▼
                     Task API
                          │
                          ▼
                    TaskManager
                          │
                          ▼
                    AgentRuntime
                     /        \
                    /          \
                   ▼            ▼
                 LLM      ExecutionTrace
                   │            │
              Tool Calls        │
                   │            │
                   ▼            │
              ToolRegistry      │
                   │            │
          ┌────────┼────────┐   │
          ▼        ▼        ▼   │
        Files    Search   Command│
          │        │        │   │
          └────────┴────────┘   │
                   │            │
              Tool Result       │
                   │            │
                   └──────┬─────┘
                          ▼
                     TaskSummary
                          │
               ┌──────────┴──────────┐
               ▼                     ▼
           EventLog                Task API
               │                     │
               ▼                     │
              SSE                    │
               │                     │
               └──────────┬──────────┘
                          ▼
                     Frontend
                          │
              ┌───────────┴──────────┐
              ▼                      ▼
         Task Thread            Task Summary
              │
              ▼
       Natural Language UI
```

---

# 36. M5 退出标准

只有同时满足以下条件，M5 才能认为完成：

```text
用户打开页面后，不需要理解 Event JSON；
用户能够像查看 Codex Task 一样理解 Agent 的完整执行过程；
每个工具行为都有自然语言描述；
文件变化和命令验证能够清晰查看；
任务完成后自动产生完整 Summary；
Summary 的执行事实来自真实 Runtime；
页面刷新、SSE 重连和终态一致性仍正常；
现有后端测试全部通过；
前端 typecheck / build 通过；
M4 真实模型 Demo 再次连续 3/3 成功。
```

---

# 37. 最终目标

M5 完成后，Coding Agent 的体验应该从：

```text
“这是一个能够显示 Agent 后端事件的工程 Demo”
```

提升为：

```text
“这是一个用户能够真正使用和理解的本地 Coding Agent 产品”
```

用户不再关注：

```text
tool_started
tool_finished
payload
call_id
JSON
```

而是看到：

```text
Agent 正在检查什么
Agent 阅读了什么
Agent 修改了什么
Agent 为什么这样修改
Agent 执行了什么
测试是否真的成功
最终整个任务完成了什么
```

这将作为 M5 的核心验收目标。