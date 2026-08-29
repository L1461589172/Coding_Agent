# Coding Agent M1 工具系统完成说明

更新日期：2026-08-27；2026-08-29 补充状态导航。六工具功能已实现，D001 修复阶段全量 **194 passed**；详见 [D001 修复说明](Coding%20Agent%20D001%20修复说明.md)。第 6 节保留 M1 的 172 passed 历史记录，第 7 节保留发现 D001 时的 171 passed / 1 failed 证据。此后 M2–M5 已接入；当前 254 项验证见 [文档导航](README.md)。

## 1. 当前完成范围

六个工具都通过 `create_registry(Workspace(...))` 的 `execute()` 调用。工具 Schema 与参数保持兼容；`GET /api/meta` 中六个 `tool_statuses` 都为 `ready`，前端显示“工具就绪”。默认网页任务仍只验证任务/SSE 链路，并返回 `NOT_IMPLEMENTED`，不会自动读取、写入或执行命令。

M1 实现阶段没有新增依赖、模型调用、文件查询 API、任务取消 API 或自动 Git 提交。仓库现在已有本地阶段提交；本次修复命令缓存策略并补回归，没有提交或推送。测试中的真实命令只运行临时工作区内的测试样例。

### 注册表接口

```python
create_registry(
    workspace: Workspace,
    limits: ReadLimits | None = None,
    command_limits: CommandLimits | None = None,
) -> ToolRegistry
```

`await registry.execute(name, arguments)` 接受工具名与参数字典，返回 `ToolResult`。参数严格校验、禁止额外字段；预算由创建注册表的 Python 调用方注入，没有对应 HTTP、CLI 或模型参数可以直接提高预算。`schemas()` 返回六工具 JSON Schema，`availability()` 返回六个 ready；ready 仅表示 handler 已实现，不保证 Node/npm 等外部程序一定安装或每次调用成功。

Registry 自身仍不产生事件；Runtime 现已根据 Registry 结果发布 tool_started/tool_finished/file_changed/command_finished。文件 Diff/哈希会进入受限内存事件历史，但这不是持久化审计日志。

## 2. M1 实现阶段的文件变更与当前职责

| 文件 | M1 实现阶段的变更 |
|---|---|
| [tools/files.py](../backend/app/tools/files.py) | 实现 write_file / replace_in_file 的异步入口与线程执行，唯一匹配校验 |
| [tools/writes.py](../backend/app/tools/writes.py)（新增） | 快照、冲突检查、原子提交、清理、SHA-256、单段统一 Diff |
| [tools/read_only.py](../backend/app/tools/read_only.py) | 抽出有界原始字节读取与 UTF-8 解码，供写前快照复用 |
| [tools/workspace.py](../backend/app/tools/workspace.py) | 同一 Workspace 的写锁；过滤内部临时文件名，复用既有路径守卫 |
| [tools/shell.py](../backend/app/tools/shell.py) | 监督执行、双流捕获、资源上限、退出码、超时/取消与进程回收 |
| [tools/command_policy.py](../backend/app/tools/command_policy.py)（新增） | 受限 argv 语法、命令白名单、程序定位与子进程环境白名单 |
| [tools/command_worker.py](../backend/app/tools/command_worker.py)（新增） | 等待监督器许可后才启动目标进程，转发退出状态 |
| [tools/windows_job.py](../backend/app/tools/windows_job.py)（新增） | Windows Job Object 的创建、分配、终止和句柄关闭 |
| [tools/registry.py](../backend/app/tools/registry.py) | 注册六个可执行 handler，注入 CommandLimits 并统一新错误码 |
| [tools/__init__.py](../backend/app/tools/__init__.py) | 更新工具能力与非沙箱说明 |
| [frontend/src/App.vue](../frontend/src/App.vue) | 显示六工具就绪，明确页面尚未接入工具 |
| [tests/test_write_tools.py](../tests/test_write_tools.py)（新增） | 写入/替换、Diff、大小限制、安全边界、冲突与失败清理测试 |
| [tests/test_shell_tools.py](../tests/test_shell_tools.py)（新增） | 命令策略、环境、输出、超时/取消、进程树、Node/npm、真实 pytest 流程 |
| [tests/test_agent_contracts.py](../tests/test_agent_contracts.py)、[test_api.py](../tests/test_api.py)、[test_read_only_tools.py](../tests/test_read_only_tools.py) | 同步 handler 可用状态和只读不变性断言 |
| [scripts/test.ps1](../scripts/test.ps1)（新增） | 自动选择独立随机临时/缓存目录运行 pytest，避免账户权限冲突 |

M1 实现时已同步 README、实施计划和结构设计文档。只读阶段说明保留首次变更记录，同时可作为当前只读工具参考；本轮 D001 的具体修改与最新验证见修复说明及 docs/README.md。

## 3. write_file 与 replace_in_file

### 参数与行为

- `write_file(path, content)`：创建或整体覆盖 UTF-8 文本，必要时逐层创建父目录。content 最多 100,000 字符，编码后的文件仍受 `ReadLimits.max_file_bytes` 默认 1 MiB 限制。
- `replace_in_file(path, old_text, new_text)`：目标必须已存在；old_text 非空且必须恰好匹配一次。重叠匹配也算多次，例如 `aaa` 中的 `aa` 会拒绝。old_text/new_text 各最多 100,000 字符。
- 保留现有 UTF-8 BOM；唯一替换不转换换行符，未替换区域及末尾换行状态保持不变。整体覆盖按调用方提供的换行写入。
- 拒绝读取/覆盖二进制、非 UTF-8、过大、链接、敏感路径和目录。所有路径继续遵循上一阶段 Workspace 守卫。
- 新内容与原字节一致时返回 `unchanged`，不重写文件、不改变修改时间。新建空文件仍属于 `created`。

### 提交与冲突策略

1. 读取有界快照，记录字节和文件身份、大小、时间戳。
2. 同目录创建随机临时文件，写入后 flush/fsync。
3. 再次校验目标快照及父目录身份，发现变化则返回 `FILE_CHANGED`。
4. 已存在文件用 `os.replace` 原子替换；新文件用同卷硬链接发布实现“目标若已出现就拒绝覆盖”，随后删除临时链接。
5. 失败时尽力清理本次临时文件和本次创建的空目录，不递归删除，也不删除其他进程创建的内容。

新文件创建要求文件系统支持硬链接；不支持时返回 I/O 错误，不降级为可能覆盖并发新文件的写法。相同 Workspace 对象中的写操作串行化；不同进程/不同 Workspace 实例不共享锁。

原子替换避免读到半份正文，但不等于完整事务或恶意并发安全。最终检查与提交之间仍有竞争窗口；不提供自动备份/撤销，不保证保留所有 ACL、扩展属性和创建时间，也未对父目录执行持久化 fsync。写入在工作线程执行，取消等待不等于撤销已开始的写入，后续 Runtime 必须考虑这一点。

### 结果字段

| 字段 | 说明 |
|---|---|
| path / action / changed | 工作区相对路径；created、updated、unchanged；是否发生写入 |
| bytes_before / bytes_after | 原始与提交后字节数 |
| sha256_before / sha256_after | 前后内容哈希；新文件的 before 为 null |
| diff / diff_truncated | 单段 unified diff；默认最多 20,000 字符，截断同时置 ToolResult.truncated |
| added_lines / removed_lines | 单段差异中新增/移除的行数，不保证最小编辑距离 |
| cleanup_pending | 成功提交后，临时文件清理是否未能确认；为 true 时应人工检查，不应盲目重试写入 |

Diff 使用共同前后缀和三行上下文生成单个 hunk，线性开销，不使用可能昂贵的全局最短匹配；多处相距较远的修改会合并为一个 hunk。保留无末尾换行标记。截断 Diff 仅用于展示，不能直接当作完整补丁应用；创建空文件或只有 BOM 差异时正文 Diff 可为空，应结合 action/哈希判断。

## 4. run_command

### 接口与白名单

参数仍为 `command`（1–4000 字符）与 `timeout_seconds`（默认 30，1–120 秒）。cwd 固定为授权 Workspace 根目录，调用参数不能另设目录。代码使用 `shlex.split(..., posix=True)`，不是 PowerShell/cmd 的原生分词；路径建议写 `src/check.py`，含空格时加引号。不进行 Shell 变量展开。

| 支持的入口 | 示例与限制 |
|---|---|
| echo | `echo "hello world"`，由固定 Python 实现，不调用系统 Shell 内建命令 |
| python / python3 / pytest | 使用后端当前 Python 解释器；允许版本查询、工作区 `.py` 脚本及 `-m pytest`、`-m unittest`、`-m compileall` |
| node | 版本查询或工作区 `.js` / `.cjs` / `.mjs` 脚本；从可信绝对 PATH 定位 |
| npm | `npm test`、`npm run <单个脚本名>`、版本查询；通过 Node 执行 npm CLI，避免直接运行 `.cmd` 包装器 |

拒绝白名单外的程序名、绝对可执行文件路径、`python -c`、`node -e`、白名单外 Python 模块、pip/npm install、npx、cmd/PowerShell/bash 包装器，以及 `| & ; < >`、反引号、`$ % ^`、控制字符等；即使它们在引号内也保守拒绝。当前不支持 npm 脚本额外参数、交互输入、管道、后台常驻服务。Python/Node 的入口脚本路径受 Workspace 校验，但脚本后续参数和 Python 模块参数并非通用文件访问白名单。

这是误操作防护，不是恶意代码检测：允许的 Python 模块、项目脚本、pytest 插件和 npm 生命周期脚本仍能访问工作区外的文件、网络和其他命令。npm 脚本内部仍由 npm 调用系统 Shell。必须只对可信样例使用，不能用该功能评估不可信仓库的安全性。

### 环境与输出

- 仅传递必要的 OS/路径/临时目录/用户配置目录/语言变量；不继承 API Key、任意 token、PYTHONPATH、NODE_OPTIONS 等。固定 Windows ComSpec 到系统 cmd.exe，供 npm 生命周期使用。
- Python 设置 UTF-8、无缓冲输出，关闭用户 site 与 pytest 第三方插件自动发现；需要第三方插件的项目应显式配置，而非继承任意宿主插件。
- 每命令固定 `PYTHONDONTWRITEBYTECODE=1`，并将 `PYTHONPYCACHEPREFIX` 指向新建临时目录：绕过已有 CPython/pytest 字节码，避免 D001 同秒等长修改复用旧缓存；不删除或重写工作区已有 `.pyc`。正常继承环境的 Python 子进程也使用该策略。
- 不返回整个环境字典。stdout/stderr 是目标程序产生的不可信文本，仍可能含项目自行读取的凭据或绝对路径；本阶段没有通用输出脱敏，调用方必须谨慎展示和记录。
- 两个流独立读取并持续排空，每流保留前 32 KiB；UTF-8 无效字节替换为 `�`。超过保留量标记截断，但不因此改变成功退出状态。
- 总输出超过 4 MiB 时终止进程，返回 `COMMAND_OUTPUT_LIMIT`；阈值由监督器轮询观察，实际累计读取可能略超阈值，但保留缓冲区有界，不将无限输出写入磁盘。

### 生命周期与清理

`CommandLimits` 默认是每流保留 32,768 字节、总输出阈值 4,194,304 字节、cleanup_seconds=3。正文输出限制、运行超时停止和清理等待是不同约束；启动器使用 Python 隔离模式，但目标 Python 脚本不是 OS 沙箱。

- 可信 Python 启动器先等待 JSON 请求。Windows 监督器创建 kill-on-close Job 并将启动器加入后，才发送目标 argv；Job 分配失败不启动用户命令。
- Windows 下新子孙默认继承 Job；退出、超时、输出超限、取消均终止 Job 并关闭句柄。取消协程会先请求工作线程停止，再等待清理，不把工作线程遗留运行。
- POSIX 下启动新会话并在清理时终止进程组；主动 `setsid` 逃离的进程不在该保证内。该分支本轮未在 Linux/macOS 实机验收。
- 正常命令退出后也清理其后台子进程。因此该工具不适合启动长期开发服务器。
- 默认进程回收等待最多 3 秒，输出线程总回收窗口最多 3 秒；失败返回 `COMMAND_CLEANUP_FAILED`。OS 的进程创建、阻塞 I/O 和恶意逃逸不受 Python 硬实时保证。
- 进程/管道清理后回收本次字节码目录；创建失败不启动命令，清理无法确认不能按成功处理。默认 `compileall` 显式生成的字节码也进入该目录并清理；该工具不是持久预编译产物交付入口。临时目录文件系统清理没有硬实时保证。

### 结果与错误

输出包含 `stdout`、`stderr`、各流实际读取字节数与截断标志、`cwd="."`、`exit_code`、`timed_out`、`termination_reason`、`cleanup_ok`、`duration_seconds`。exit_code 是正常观察到的退出状态；强制停止且未观察到正常退出时为 null。

| 错误码 | 说明 |
|---|---|
| COMMAND_NOT_ALLOWED | 命令语法或入口不在白名单 |
| COMMAND_NOT_FOUND | 所需 Node/npm 程序未安装或布局无法识别 |
| COMMAND_START_FAILED | 监督进程启动/Job 分配等失败，原始系统错误不直接透出 |
| COMMAND_FAILED | 命令非零退出；查看输出及 exit_code |
| COMMAND_TIMEOUT | 超出运行时间预算 |
| COMMAND_OUTPUT_LIMIT | 超出总输出预算并终止 |
| COMMAND_CLEANUP_FAILED | 无法确认进程/管道/本次字节码目录清理，不能按成功处理 |
| COMMAND_CANCELLED | 工作线程观察到取消；正常异步调用方收到 CancelledError |
| TEXT_NOT_FOUND / AMBIGUOUS_MATCH | 替换的旧文本未找到 / 不唯一 |
| FILE_CHANGED | 检测到写前竞争变化，未应用本次编辑 |

路径、类型、编码、大小和 I/O 错误沿用只读阶段定义。启动器收到请求后若目标程序未能启动，会打印固定错误并以 127 退出，按 `COMMAND_FAILED` 返回。

## 5. 独立调用示例

先按 README 安装后端。在仓库根目录的 Python 解释器执行下列代码；它只在新建的临时目录内写文件和运行测试，不修改 demo_workspace 或仓库源码。预期先失败、修改后通过；D001 已修复并覆盖同秒等长修改的回归。仍须检查实际 ToolResult，不能忽略命令失败。

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tools.registry import create_registry
from app.tools.workspace import Workspace

async def main():
    with TemporaryDirectory(prefix="coding-agent-demo-") as directory:
        tools = create_registry(Workspace(Path(directory)))
        calls = [
            ("write_file", {
                "path": "test_sum.py",
                "content": "def test_sum():\n    assert 1 + 1 == 3\n",
            }),
            ("run_command", {"command": "python -m pytest test_sum.py -q"}),
            ("replace_in_file", {
                "path": "test_sum.py", "old_text": "== 3", "new_text": "== 2",
            }),
            ("run_command", {"command": "python -m pytest test_sum.py -q"}),
        ]
        for name, arguments in calls:
            result = await tools.execute(name, arguments)
            print(name, result.model_dump_json(indent=2))

asyncio.run(main())
```

这个例子中的测试不需要 tmp_path。测试本项目时请使用 `scripts/test.ps1`，它把 pytest 临时目录与状态缓存分离到随机路径，避免此前“6 项通过，98 项 tmp_path 初始化权限失败”的账户冲突。D001 的字节码隔离由 `run_command` 实现，不是脚本的 `--basetemp` / `cache_dir` 功能。完整命令见 [文档导航](README.md#如何复验)，机制区别见 D001 修复说明。

## 6. M1 实现阶段的历史验证与未完成项

以下保留 M1 实现阶段记录，不是本次文档核对的结果；本次发现的问题和新结论见下一节。

- 全量 **172 passed, 1 warning**；沙箱账户与正常用户账户均已跑通。最终普通用户测试使用随机临时/缓存路径，没有此前的 pytest cache 权限警告。
- 包括真实文件读写、重叠/多处替换拒绝、写前冲突与失败清理；真实 Python/Node/npm 命令、UTF-8、stdout/stderr 截断、持续输出终止、超时、取消、正常退出后的子孙回收、Job 分配失败不执行目标。
- 无模型流程确实执行 pytest：先失败，再替换，再通过；没有伪造命令结果。
- Ruff 检查与格式检查通过；前端 TypeScript + Vite 构建通过。本轮未重新运行浏览器视觉 smoke，也未调用模型。
- 仍有已有的 Starlette TestClient/httpx 弃用提示。没有为消除提示而升级依赖。
- 后续进展：M2 的 HTTP/循环/回填/预算/事件与 M3 的 Tool/Shell/File Change 专用卡片、刷新恢复均已完成；真实供应商 Demo 与连续成功率仍属于 M4。本节 172 项数字只保留 M1 历史含义。
- 安全边界：可信单用户、单工作区本地开发工具，不是 OS 级文件/网络沙箱；Windows 实测，其他系统待验收。

实现依据：[Python subprocess](https://docs.python.org/3/library/subprocess.html)、[Python os 原子替换](https://docs.python.org/3/library/os.html#os.replace)、[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[Job 扩展限制](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)。

## 7. 本次文档核对与已知问题

本节保留上一次文档核对时的问题记录。**D001 现已修复**，当前 194 passed；本轮方案、22 项新回归及重复验证见 [D001 修复说明](Coding%20Agent%20D001%20修复说明.md)。以下 171/1 不是修复后结果。

### 发现问题时的验证记录

在当前 Windows/Python 3.12.4、pytest 9.1.1 环境，以 `scripts/test.ps1` 的独立随机临时/缓存路径重新运行，结果为 **171 passed, 1 failed, 1 warning**。未修改源码或测试，未删除失败样例。Ruff lint 与 39 文件格式检查通过；本次没有重跑普通用户账户、前端构建或浏览器 smoke。

| 测试模块 | 收集数量 |
|---|---:|
| test_agent_contracts.py | 4 |
| test_api.py | 10 |
| test_events.py | 2 |
| test_read_only_tools.py | 44 |
| test_shell_tools.py | 38 |
| test_task_manager.py | 2 |
| test_workspace.py | 42 |
| test_write_tools.py | 30 |
| 总计 | 172 |

### D001：同秒等长修改后重复 pytest 可能执行旧断言

发现时状态为已确认、未修复；现已通过命令级缓存策略修复。原失败项为 [test_local_tool_workflow_without_llm](../tests/test_shell_tools.py)，发生于替换之后的第二次 `run_command`。它不同于此前 tmp_path 权限错误，也不是 Starlette 弃用警告造成的失败。

本次失败样例的只读检查证据：

| 检查对象 | 实际值 |
|---|---|
| 当前 test_example.py | `assert 1 + 1 == 2`，说明替换已经写入 |
| 当前文件大小 | 38 字节 |
| 当前文件秒级 mtime | 1787843210 |
| pytest `.pyc` 头部 flags / mtime / size | 0 / 1787843210 / 38 |
| 缓存函数的常量 | 仍含旧期望值 3，而不是 2 |

当前安装的 `_pytest/assertion/rewrite.py::_read_pyc` 使用 `int(st_mtime)` 与文件大小判断缓存是否有效。原内容 `== 3` 与新内容 `== 2` 长度相同，且写入发生在同一秒，缓存校验因此接受旧断言字节码。是否跨过秒边界影响复现，所以历史全通过与本次失败并不矛盾；重试偶然通过不代表修复。

修复前的影响：文件工具返回成功和哈希变化不能保证下一次 Python/pytest 加载新源码。当时环境白名单没有设置字节码缓存控制项；本轮已增加独立前缀与禁写策略，未开放任意解释器选项。普通 `--basetemp`、pytest `cache_dir` 与 Python `__pycache__` 是不同机制。

当时提出的验收要求已纳入本轮修复：兼顾已有/新增缓存，固定时间戳与等长修改回归，重复运行工具流程和全量测试。未通过“等待一秒”“改成不同长度”或删掉失败断言绕过故障。历史发现阶段仅更新文档，本轮按用户要求完成代码修复。
