# 文档导航与当前代码状态

核对日期：2026-08-27。源码基线：本地提交 `39697d6`（完成M1修改文件运行指令功能）。本次只更新文档，不改变前后端代码、依赖、测试或原始需求 PDF。

## 阅读顺序

| 文档 | 用途与状态 |
|---|---|
| [项目结构与功能设计](Coding%20Agent%20项目结构与功能设计文档.md) | 目标架构与当前实现对照；第 9 节逐文件职责，第 13 节当前状态 |
| [实施计划](Coding%20Agent%20实施计划.md) | 已完成、待接入、待修复和后续验收；日期是原定计划，不代表自动完成 |
| [M1 工具系统完成说明](Coding%20Agent%20M1%20工具系统完成说明.md) | 写入/命令契约及限制；第 7 节记录本次发现的稳定性问题 |
| [M1 只读工具实现说明](Coding%20Agent%20M1%20只读工具实现说明.md) | 当前只读工具参考；首次实现清单和 104 项测试属于历史阶段 |
| [基础框架修改说明](Coding%20Agent%20基础框架修改说明.md) | M0 历史记录；当时的“工具未实现”和 35 项测试不代表当前状态 |
| [项目要求.pdf](项目要求.pdf) | 原始需求资料；本轮未修改 |
| [根目录 README](../README.md) | 安装、配置、启动方式；本次仅更新 docs，最新复验结果以本页为准 |

## 当前能力

| 模块 | 已有实现 | 尚缺少的部分 |
|---|---|---|
| M0 工程基础 | CLI、FastAPI、Vue、任务/SSE 链路；已有本地阶段提交 | 打包与单端口交付，不等于真实 Agent |
| M1 工具 | 六工具可独立调用；路径守卫、原子写入、唯一替换、Diff、受限命令与清理 | D001：修改后重复 pytest 可能复用旧字节码，稳定性复验待修复 |
| M2 Runtime | LLMClient 协议、Conversation、StopController、ToolRegistry | LLM HTTP 实现、完整循环、结果回填、预算与错误恢复 |
| M3 API/UI | 创建/查询、SSE、输入/状态/通用 Timeline、去重、防重复提交与手动重连 | 真实工具事件、专用 Tool/Shell/Diff 卡片、长期恢复验收 |
| M4/M5 演示交付 | demo_workspace 占位 README、开发说明与测试基础 | 真实模型 Demo、稳定成功率、README.txt、视频与最终提交材料 |

`/api/meta` 的六个 `tool_statuses` 均为 `ready`，但 `agent_ready=false`、`mode=scaffold`。网页任务仍是 `task_started → assistant_message → task_failed(NOT_IMPLEMENTED)`；没有 HTTP 工具执行入口，独立调用需要 Python 中的 `ToolRegistry.execute()`。

安全边界：可信单用户本地工具，不是文件/网络沙箱。入口白名单并不限制获准脚本内部的文件、网络或子命令行为；Windows Job Object 只管理进程生命周期，POSIX 分支尚未实机验收。

## 本次验证

| 检查 | 结果 |
|---|---|
| 源码清单 | 后端 30 个 Python 文件；前端 8 个源码文件、5 个入口/配置文件；8 个测试模块和 conftest.py |
| pytest 收集 | 172 项 |
| `scripts/test.ps1` 全量复验 | **171 passed, 1 failed, 1 warning** |
| 失败项 | `tests/test_shell_tools.py::test_local_tool_workflow_without_llm`，源码已更新但旧 pytest `.pyc` 被复用，详见 [D001](Coding%20Agent%20M1%20工具系统完成说明.md#7-本次文档核对与已知问题) |
| Ruff lint / format | 通过，39 个 Python 文件格式符合配置 |
| 前端构建、普通用户账户、浏览器 smoke | 本次未重跑；此前阶段记录保留，不冒充本次复验结果 |

已有的 Starlette TestClient/httpx 弃用警告不是上述失败原因。M1 曾有 **172 passed** 的阶段结果，但本次复验发现时序相关缺陷，因此不能宣称当前已稳定全通过。

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

pytest 会清空指定的 `--basetemp`，只能使用新建的专用随机路径，不能指定仓库根目录或已有数据目录。`--basetemp` / `cache_dir` **不管理 Python 的 `__pycache__`**，所以不能解决 D001；即使重跑偶然全通过也不能视为问题已修复。

维护约定：当前能力看源码和最新验证；M0/只读阶段的历史数字保留原意，不覆盖成当前数字。后续修改工具时同步契约文档，修复 D001 后再更新复验结论。
