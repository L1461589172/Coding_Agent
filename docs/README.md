# 文档导航与当前代码状态

更新日期：2026-08-28。当前为 M2 LLM HTTP 适配工作区：在已完成的 M1/D001 基础上新增模型请求、响应校验、超时/有限重试、错误脱敏与资源关闭，不改变依赖、前端或原始需求 PDF。

## 阅读顺序

| 文档 | 用途与状态 |
|---|---|
| [项目结构与功能设计](Coding%20Agent%20项目结构与功能设计文档.md) | 目标架构与当前实现对照；第 9 节逐文件职责，第 13 节当前状态 |
| [实施计划](Coding%20Agent%20实施计划.md) | 已完成、待接入、待修复和后续验收；日期是原定计划，不代表自动完成 |
| [M1 工具系统完成说明](Coding%20Agent%20M1%20工具系统完成说明.md) | 当前写入/命令契约及限制；第 7 节保留 D001 的历史发现证据 |
| [M2 LLM HTTP 适配说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md) | 当前模型请求、响应校验、超时/重试、错误与资源关闭契约 |
| [M2 上下文预算与 Agent Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md) | 总预算、模型侧结果裁剪、调用 ID 回填、停止规则和应用组装 |
| [D001 修复说明](Coding%20Agent%20D001%20修复说明.md) | 命令级字节码缓存策略、确定性回归、重复运行记录与三类缓存/权限问题区分 |
| [M1 只读工具实现说明](Coding%20Agent%20M1%20只读工具实现说明.md) | 当前只读工具参考；首次实现清单和 104 项测试属于历史阶段 |
| [基础框架修改说明](Coding%20Agent%20基础框架修改说明.md) | M0 历史记录；当时的“工具未实现”和 35 项测试不代表当前状态 |
| [项目要求.pdf](项目要求.pdf) | 原始需求资料；本轮未修改 |
| [根目录 README](../README.md) | 安装、配置、启动与验证方式 |

## 当前能力

| 模块 | 已有实现 | 尚缺少的部分 |
|---|---|---|
| M0 工程基础 | CLI、FastAPI、Vue、任务/SSE 链路；已有本地阶段提交 | 打包与单端口交付，不等于真实 Agent |
| M1 工具 | 六工具可独立调用；路径守卫、原子写入、唯一替换、Diff、受限命令与清理；D001 已修复 | POSIX 实机验收；真实 Runtime 接入属于 M2 |
| M2 Runtime | HTTP 客户端；字符/token 总预算及结果裁剪；Conversation/Registry/StopController Agent Loop；调用 ID 回填 | 工具事件、连续错误/超时恢复、关闭中写入语义 |
| M3 API/UI | 创建/查询、SSE、输入/状态/通用 Timeline、去重、防重复提交与手动重连 | 真实工具事件、专用 Tool/Shell/Diff 卡片、长期恢复验收 |
| M4/M5 演示交付 | demo_workspace 占位 README、开发说明与测试基础 | 真实模型 Demo、稳定成功率、README.txt、视频与最终提交材料 |

`/api/meta` 的六个 `tool_statuses` 均为 `ready`。模型三项配置完整时为 `agent_ready=true`、`mode=agent` 并运行真实 Loop；配置不完整时为 scaffold，任务以 `NOT_IMPLEMENTED` 结束且不执行工具。仍没有独立 HTTP 工具执行入口。

安全边界：可信单用户本地工具，不是文件/网络沙箱。入口白名单并不限制获准脚本内部的文件、网络或子命令行为；Windows Job Object 只管理进程生命周期，POSIX 分支尚未实机验收。

## 本次验证

| 检查 | 结果 |
|---|---|
| 源码清单 | 后端 30 个 Python 文件；前端 8 个源码文件、5 个入口/配置文件；9 个测试模块和 conftest.py |
| pytest 收集 | 234 项（历史 194 + M2 新增 40） |
| 本轮全量复验 | **234 passed, 1 warning**；独立随机 pytest 临时/缓存目录，未调用真实模型 |
| M2 上下文/Loop 针对性验证 | 新增 13 项；受影响组件/API 共 30 passed；见 [Loop 说明](Coding%20Agent%20M2%20上下文预算与%20Agent%20Loop%20说明.md) |
| M2 LLM 针对性验证 | LLM 客户端 26 项 + Agent 契约 5 项，共 31 passed；见 [M2 说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md) |
| D001 历史全量复验 | 连续三轮各 194 passed, 1 warning；见 [D001 修复说明](Coding%20Agent%20D001%20修复说明.md#4-验证记录) |
| D001 针对性验证 | 新增 22 项 + 原无模型流程，共 23 passed；固定 mtime、等长修改、真实旧缓存与连续调用 |
| Ruff lint / format / pip check | 通过，43 个 Python 文件格式符合配置，依赖一致 |
| 前端构建、浏览器 smoke | 本次未重跑；此前阶段记录保留，不冒充本次复验结果 |

已有的 Starlette TestClient/httpx 弃用警告保留，未为消除它升级依赖。历史 172 passed、D001 发现时的 171 passed / 1 failed、D001 修复后的三轮 194 passed 及 HTTP 适配阶段的 221 passed 均保留原意；当前结论基于 Loop 接入后的 234 项全量验证。

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
