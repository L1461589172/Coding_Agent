# Coding Agent D001 修复说明

日期：2026-08-27。状态：**已修复并完成重复验证**。基于本地提交 `6786d21` 后的工作区修复；未新增依赖，未接入 M2，也未提交或推送 Git。

## 1. 问题与修复

D001 的原因不是文件未写入：同秒等长修改后，源码已更新，但旧 CPython/pytest `.pyc` 的秒级 mtime 和文件大小仍匹配。先前全量复验出现 **171 passed / 1 failed**，证据保留在 [M1 说明第 7 节](Coding%20Agent%20M1%20工具系统完成说明.md#7-本次文档核对与已知问题)。

本次在 `run_command` 层处理，不改变文件写入时间、不等待跨秒，也不删除工作区原有缓存：

1. 命令通过白名单校验后，为本次调用创建系统临时目录 `coding-agent-pycache-*`，设置 `PYTHONPYCACHEPREFIX` 指向该新目录。
2. 子环境固定设置 `PYTHONDONTWRITEBYTECODE=1`，覆盖宿主的缓存设置。前者绕过既有缓存，后者避免常规导入与 pytest 生成新字节码；仅禁写不能阻止读取旧缓存。
3. 目标命令及正常继承环境的 Python 子进程使用同一策略；下一次工具调用使用另一个新目录。
4. 在进程树和输出管道清理之后清理本次目录，覆盖成功、非零退出、超时、取消、启动/Job 分配失败。创建失败返回 `COMMAND_START_FAILED`；正常执行后清理无法确认返回 `COMMAND_CLEANUP_FAILED`，不泄露原始路径异常。

依据：[Python sys.pycache_prefix](https://docs.python.org/3.12/library/sys.html#sys.pycache_prefix) 说明重定向读写并忽略源码树中的 `__pycache__`；[sys.dont_write_bytecode](https://docs.python.org/3.12/library/sys.html#sys.dont_write_bytecode) 只控制导入时的写入。pytest 的断言重写也使用缓存，见 [pytest 断言缓存说明](https://docs.pytest.org/en/stable/how-to/assert.html#assertion-rewriting-caches-files-on-disk)，并已核对本地 pytest 9.1.1 的 `get_cache_dir` / `_read_pyc` 实现。

## 2. 修改文件

| 文件 | 修改内容 |
|---|---|
| [command_policy.py](../backend/app/tools/command_policy.py) | 子环境固定禁写字节码，说明其不能单独解决旧缓存读取 |
| [shell.py](../backend/app/tools/shell.py) | 每命令创建新缓存前缀，统一生命周期清理及失败处理 |
| [test_command_bytecode.py](../tests/test_command_bytecode.py) | 新增 22 项确定性回归和生命周期测试 |
| README 与 docs | 同步修复状态、测试记录、源码职责与缓存排查方式 |

`write_file` / `replace_in_file`、`scripts/test.ps1`、命令白名单和参数 Schema 不变。

## 3. 确定性回归

| 覆盖 | 数量 | 验证方式 |
|---|---:|---|
| 旧断言/普通模块缓存 | 12 | 三种入口（pytest / python -m pytest / python3 -m pytest）× 两种写工具 × 两种缓存 |
| 缓存继承、隔离、清理 | 1 | 连续三次 Python 父子进程调用；确认前缀各不相同、宿主设置未继承、结束后目录移除 |
| 六种退出路径 | 6 | 成功、非零、超时、取消、启动失败、Windows Job 分配失败；目录内含临时内容 |
| 创建失败 | 1 | 返回安全错误，命令不启动 |
| 清理失败 | 1 | 即使命令退出码为 0 也不能报告成功 |
| 显式 compileall | 1 | 确认字节码写到本次前缀，退出后清理，不写入工作区缓存 |

12 项核心回归先用真实 Python/pytest 生成旧缓存并验证其头部，再经工具等长修改文件，强制将文件时间戳恢复到完全相同的固定值。随后在同一 Workspace/Registry 中连续执行两次 pytest，均须加载新源码；最后确认工作区既有 `.pyc` 字节保持不变。固定时间戳不依赖机器速度，也没有靠等待一秒避开故障。

修复前已确认首个核心回归在第二次 pytest 因旧断言失败；修复后完整针对性验证为 **23 passed**（新增 22 项 + 原无模型修复流程），不是删除断言或仅重试旧测试。

## 4. 验证记录

环境：Windows、项目 `.venv` 的 Python 3.12.4 / pytest 9.1.1。当前收集 194 项（原 172 + 新增 22）；代码修复完成后连续三轮全量均通过，没有靠反复重试消除失败。

| 验证 | 入口/环境 | 结果 |
|---|---|---|
| 修复前确定性回归 | 固定 mtime + 等长写入 + 真实旧缓存，首项即复现 | 预期失败，证实旧实现仍运行旧断言 |
| 修复后针对性验证 | 22 项新测试 + 原无模型流程 | 23 passed，39.94 秒 |
| 全量第 1 轮 | 仓库根目录，Codex 沙箱内，scripts/test.ps1 | 194 passed，53.25 秒 |
| 全量第 2 轮 | backend 目录，Codex 沙箱内，../scripts/test.ps1 | 194 passed，52.06 秒 |
| 全量第 3 轮 | 仓库根目录，批准后沙箱外普通用户环境，scripts/test.ps1 | 194 passed，50.52 秒 |
| Ruff lint / format | backend + tests | 通过，40 文件格式符合配置 |
| pip check | 项目 .venv | No broken requirements found |

每轮使用新随机 pytest 临时/状态缓存目录；没有 tmp_path 权限失败或 pytest 缓存权限警告。各轮仅有原已存在的 Starlette TestClient/httpx 弃用警告（1 warning），没有为消除它调整依赖。前端未变更，本轮未重跑构建/浏览器；未调用真实模型，未在 Linux/macOS 实机验收。

复验命令（在仓库根目录）：

```powershell
# 新回归与原无模型流程
.\scripts\test.ps1 -PytestArgs @('-k', 'bytecode or local_tool_workflow_without_llm')

# 全量测试，每次调用自动使用新的 pytest 临时目录与缓存目录
.\scripts\test.ps1

.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m pip check
```

## 5. 三类问题不能混为一谈

| 类别 | 典型症状/位置 | 本项目处理 | 不解决什么 |
|---|---|---|---|
| pytest 临时目录权限 | `tmp_path` 初始化、`pytest-of-*` 的 PermissionError | `scripts/test.ps1` 每次分配随机 `--basetemp`，隔离执行账户 | 不会让旧字节码失效 |
| pytest 状态缓存 | `.pytest_cache` 的 lastfailed/nodeids 或写权限提示 | 脚本使用独立 `cache_dir`；按需查看 pytest 缓存选项 | `cache_dir` / `--cache-clear` 不清除 Python `.pyc` |
| Python/pytest 字节码缓存 | 源码已变但断言/导入仍运行旧内容，通常在 `__pycache__` | 本次工具命令的独立 `PYTHONPYCACHEPREFIX` + 禁写策略 | 不是权限修复，也不接管工具外的手动 Python 进程 |

不要把 `--basetemp` 指向仓库或已有数据目录，pytest 会清空它。修复无需手工删除用户缓存；测试临时样例仍保留供排查，只有命令自身新建的字节码临时目录在生命周期结束时清理。

## 6. 边界与代价

- 冷导入开销会增加；本次优先确保修改后运行的是新源码，不复用不同命令的字节码。
- `compileall` 属于显式写入，不受常规禁写开关限制；默认产物进入临时前缀并清理，不用于持久预编译交付。显式指定其他输出布局的命令不在此保证内。
- 这是命令级运行策略，不是 OS 沙箱。可信脚本仍可自行覆盖环境、使用 Python `-E/-I` 或自定义加载器；同一长驻 Python 进程的 `sys.modules` 热重载也不在修复范围内。
- 缓存目录清理在进程/线程清理之后进行；文件系统操作没有硬实时保证。获准程序仍只适用于可信项目。
- 本文完成时 M2 尚未开始；此后已实现 LLM HTTP 适配，但真实模型、Agent Loop、工具事件及 Linux/macOS 实机验收仍待完成。当前状态见 [文档导航](README.md)。
