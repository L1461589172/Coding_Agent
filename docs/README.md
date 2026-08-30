# 文档导航与当前代码状态

更新日期：2026-08-30。M1–M6 已收口；此后已增加前端单活动 Workspace 安全切换、最近路径持久化与失败回滚；最终交付为 M7。

## 阅读顺序

| 文档 | 用途与状态 |
|---|---|
| [项目结构与功能设计](Coding%20Agent%20项目结构与功能设计文档.md) | 目标架构与当前实现对照；第 9 节逐文件职责，第 13 节当前状态 |
| [实施计划](Coding%20Agent%20实施计划.md) | 已完成、待接入、待修复和后续验收；日期是原定计划，不代表自动完成 |
| [M1 工具系统完成说明](Coding%20Agent%20M1%20工具系统完成说明.md) | 当前写入/命令契约及限制；第 7 节保留 D001 的历史发现证据 |
| [M2 LLM HTTP 适配说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md) | 当前模型请求、响应校验、超时/重试、错误与资源关闭契约 |
| [M2 上下文预算与 Agent Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md) | 总预算、模型侧结果裁剪、调用 ID 回填、停止规则和应用组装 |
| [M3 API 与 UI 完成说明](Coding%20Agent%20M3%20API%20与%20UI%20完成说明.md) | Tool/Shell/File Change 卡片、运行时契约校验、SSE 与整页恢复、终态一致性 |
| [M4 Demo 与可靠性完成说明](Coding%20Agent%20M4%20Demo%20与可靠性完成说明.md) | 真实 Bug 样例、Prompt 调优、三轮真实模型指标、双重 pytest 验收 |
| [M5 UX 重构实施计划](Coding%20Agent%20M5%20UX%20重构实施计划.md) | 可组合 TaskRun、Activity 聚合、Trace/Summary、无障碍和 M6 前向兼容接口 |
| [M5 UX 重构完成说明](Coding%20Agent%20M5%20UX%20重构完成说明.md) | 实际代码落点、验证证据、真实模型复验与 M6 边界 |
| [M6 历史任务与多轮对话实施计划](Coding%20Agent%20M6%20历史任务与多轮对话实施计划.md) | `/.coding-agent/history/` 版本化 JSON、原子写/锁、重启收敛、Session/follow-up、有界上下文与隐私 |
| [M7 最终交付计划](Coding%20Agent%20M7%20最终交付计划.md) | 候选冻结、全量复验、README.txt、录屏、敏感信息扫描、材料与 Go/No-Go |
| [D001 修复说明](Coding%20Agent%20D001%20修复说明.md) | 命令级字节码缓存策略、确定性回归、重复运行记录与三类缓存/权限问题区分 |
| [M1 只读工具实现说明](Coding%20Agent%20M1%20只读工具实现说明.md) | 当前只读工具参考；首次实现清单和 104 项测试属于历史阶段 |
| [基础框架修改说明](Coding%20Agent%20基础框架修改说明.md) | M0 历史记录；当时的“工具未实现”和 35 项测试不代表当前状态 |
| [项目要求.pdf](项目要求.pdf) | 原始需求资料；本轮未修改 |
| [根目录 README](../README.md) | 安装、配置、启动与验证方式 |

## 当前能力

| 模块 | 已有实现 | 尚缺少的部分 |
|---|---|---|
| M0 工程基础 | CLI、FastAPI、Vue、任务/SSE 链路；已有本地阶段提交 | 打包与单端口交付，不等于真实 Agent |
| M1 工具 | 六工具可独立调用且已接入 Runtime；路径守卫、原子写入、唯一替换、Diff、受限命令与清理；D001 已修复 | POSIX 实机验收 |
| M2 Runtime | HTTP 客户端；双总预算与结果裁剪；Agent Loop/ID 回填；真实工具事件及历史限制；有界恢复；关闭中写入/命令清理 | 已完成并通过 M4 真实供应商验收 |
| M3 API/UI | 创建/查询、严格响应校验、专用 Tool/Shell/File Change 卡片、有界重连、整页恢复与终态核对 | 已完成；跨进程持久化不在范围内 |
| M4 Demo | 初始失败的真实 Bug、可重复验收器、Prompt 调优；真实模型连续 3/3 成功 | 已完成；不外推为任意任务 100% 成功率 |
| M5 UX | ConversationThread/TaskRun、`call_id` Activity 聚合、File/Command 附件、完整 Trace/Summary、版本化恢复与响应式/无障碍 | 已完成；历史持久化与 follow-up 仍属于 M6 |
| M6 历史/多轮 | 项目内版本化 JSON、原子替换/单写锁、持久 Task/Event、durable replay、Session/follow-up API、确定性有界 TaskRecap、历史 UI、删除/容量/关闭 | 已完成；真实模型多轮/重启 smoke 3/3 |
| Workspace 切换 | 前端绝对路径/最近列表；后端单活动资源图、任务阻断、历史隔离、失败回滚、Runtime/工具重绑定 | 已完成；不支持并行 Workspace 或磁盘扫描 |
| M7 交付 | 开发说明与测试基础 | 待 M5/M6 完成后制作 README.txt、视频、密钥扫描与最终提交材料 |

`/api/meta` 的六个 `tool_statuses` 均为 `ready`。模型三项配置完整时为 `agent_ready=true`、`mode=agent` 并运行真实 Loop；配置不完整时为 scaffold，任务以 `NOT_IMPLEMENTED` 结束且不执行工具。仍没有独立 HTTP 工具执行入口。

安全边界：可信单用户本地工具，不是文件/网络沙箱。入口白名单并不限制获准脚本内部的文件、网络或子命令行为；Windows Job Object 只管理进程生命周期，POSIX 分支尚未实机验收。

## 本次验证

| 检查 | 结果 |
|---|---|
| 源码清单 | 后端 42 个 Python 文件；前端 `src` 28 个文件；17 个测试模块和 conftest.py；M4 与 browser 验收脚本各 1 个 |
| pytest 收集/全量复验 | **288 passed, 1 warning** |
| M6 Phase 3–7 定向复验 | Session/API/context/retention 30 passed；Ruff lint/format 全通过 |
| 前端 | 22 passed；严格类型与生产构建通过；M6 browser smoke 保留 2026-08-29 历史证据 |
| M6 真实模型 smoke | 3/3 COMPLETED；重启恢复与 8 项检查全部通过，34.688 秒 |
| M5 后真实模型 | 新的连续 3/3；平均 12.240 秒，Agent/独立 pytest 均为 2 passed，Summary 三项检查均通过 |
| M3 API/UI 契约 | 新增 4 项：断线回放、大载荷、服务重启、成功/失败终态一致性 |
| M2 Runtime 收口验证 | 新增 8 项事件/恢复/关闭测试；见 [Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md) |
| M2 LLM 针对性验证 | LLM 客户端 26 项 + Agent 契约 5 项，共 31 passed；见 [M2 说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md) |
| D001 历史全量复验 | 连续三轮各 194 passed, 1 warning；见 [D001 修复说明](Coding%20Agent%20D001%20修复说明.md#4-验证记录) |
| D001 针对性验证 | 新增 22 项 + 原无模型流程，共 23 passed；固定 mtime、等长修改、真实旧缓存与连续调用 |
| Ruff | 全项目 lint 与 format check 无缓存检查通过 |
| 前端单测/类型/构建 | Vitest 4 files / 22 tests；`vue-tsc --noEmit`；Vite 33 modules，全部通过 |
| 浏览器 smoke | Playwright/Edge 已实测 failed/running/completed、附件、刷新、410/404/204、focus 与 390px |

已有的 Starlette TestClient/httpx 弃用警告保留，未为消除它升级依赖。历史阶段数字均保留原意；当前结论基于 Workspace 切换接入后的 288 项 Python 测试和 22 项前端测试。本轮未重跑 browser 或真实模型 smoke。

## 如何复验

PowerShell 中可在任意位置调用：

```powershell
& 'D:\Coding_Agent\scripts\test.ps1'
```

在 backend 目录也可用 `..\scripts\test.ps1`。脚本使用项目 `.venv`，为每次运行选择独立随机 `--basetemp` 和 `cache_dir`，避免账户共享目录的权限问题。若执行策略阻止 `.ps1`，按实际仓库路径运行：

```powershell
$pytestRunDir = Join-Path $env:TEMP ("coding-agent-pytest-" + [guid]::NewGuid().ToString("N"))
& 'D:\Coding_Agent\.venv\Scripts\python.exe' -m pytest 'D:\Coding_Agent\tests' -q --basetemp "$pytestRunDir" -o "cache_dir=$pytestRunDir-cache"
```

pytest 会清空指定的 `--basetemp`，只能使用新建的专用随机路径，不能指定仓库根目录或已有数据目录。`--basetemp` 处理临时目录隔离，`cache_dir` 处理 pytest 状态缓存，二者**不管理 Python 的 `__pycache__`**。D001 由 `run_command` 的独立 `PYTHONPYCACHEPREFIX` + 禁写策略修复，不是测试脚本清缓存；详见 [三类问题对照](Coding%20Agent%20D001%20修复说明.md#5-三类问题不能混为一谈)。

维护约定：当前能力看源码和最新验证；M0/只读阶段的历史数字保留原意，不覆盖成当前数字。后续修改工具时同步契约文档与回归测试。
