# Coding Agent

本地自主编程智能体的基础框架：Vue 3 + TypeScript + FastAPI。核心 Agent 将自行实现，不使用 Agent 框架/SDK 或托管代码执行工具。

> M1 本地工具系统已完成：六个工具均可通过绑定 Workspace 的注册表调用，支持原子写入、唯一替换、Diff、受限命令执行及进程清理。**尚不具备自主编程能力**：默认页面任务仍返回 `FAILED / NOT_IMPLEMENTED`，不调用模型或工具。完整 Agent Loop 属于下一阶段 M2。

## 环境要求

| 工具 | 要求 | 项目验证环境 |
|---|---|---|
| Python | 3.11 或更高版本，包含 pip 与 venv | Windows / Python 3.12.4 |
| Node.js | 20.x 且不低于 20.19.0，或不低于 22.12.0；以 `frontend/package.json` 为准 | Node.js 22.21.1 |
| npm | 用于安装前端依赖和运行 Vite | npm 10.9.4 |
| Git | 获取代码、查看变更与管理版本 | 运行已下载的项目不依赖 Git 命令 |

首次安装依赖需要访问 Python 包源和 npm 包源。当前框架不需要 GPU、数据库、Docker 或模型 API Key。

Windows PowerShell 中先检查环境：

```powershell
python --version
python -m pip --version
node --version
npm.cmd --version
```

命令不存在时，先安装对应工具并重新打开终端；存在多个 Python 时，确认 `python` 指向符合要求的解释器。以下示例假设仓库位于 `D:\Coding_Agent`，实际路径不同请相应替换。

## 快速启动（Windows PowerShell）

### 1. 配置后端环境（首次安装）

```powershell
Set-Location 'D:\Coding_Agent'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
.\.venv\Scripts\python.exe -m pip check
```

`.venv` 是项目独立虚拟环境，不会把依赖安装到全局 Python。`.[dev]` 同时安装运行依赖及 pytest、Ruff；`constraints.txt` 约束已验证的依赖版本。使用虚拟环境内解释器的完整相对路径，无需激活环境，也无需调整 PowerShell 执行策略。

已经配置好环境时，可以跳过创建和安装步骤。依赖清单更新后再重新执行安装命令。

### 2. 安装前端依赖（首次安装）

```powershell
Set-Location 'D:\Coding_Agent\frontend'
npm.cmd ci --ignore-scripts
```

该命令按 `package-lock.json` 安装依赖，并跳过依赖安装脚本。后续锁文件更新时再执行；日常启动无需重复安装。

### 3. 启动后端（终端 A）

```powershell
Set-Location 'D:\Coding_Agent'
.\.venv\Scripts\coding-agent.exe demo_workspace
```

等价的 Python 模块启动方式：

```powershell
.\.venv\Scripts\python.exe -m app.cli demo_workspace
```

两种方式任选其一，**不要同时启动**。默认后端为 `http://127.0.0.1:8000`，只监听本机、只使用一个 worker。看到 Uvicorn 的运行提示后保持此终端开启。

`demo_workspace` 是当前命令目录下的工作区，目前仅含占位说明。也可指定自己的已有项目目录，路径含空格时保留引号：

```powershell
.\.venv\Scripts\coding-agent.exe 'D:\Projects\My Project'
```

工作区必须存在；程序不会自动创建它。无需把目标项目复制进本仓库，也不建议把整个磁盘或用户主目录作为工作区。

### 4. 启动前端（终端 B）

```powershell
Set-Location 'D:\Coding_Agent\frontend'
npm.cmd run dev
```

保持两个终端开启，访问 [前端工作台](http://127.0.0.1:5173)。前端通过 Vite 将 `/api` 和 `/health` 转发至后端，不直接访问本地文件系统。

### 5. 确认启动成功

1. 打开 [健康检查](http://127.0.0.1:8000/health)，确认返回 `status: "ok"`。
2. 打开 [Swagger 接口文档](http://127.0.0.1:8000/docs)，确认接口列表可见。
3. 在前端输入任务并点击“检查任务链路”。
4. 预期看到 `task_started`、`assistant_message`、`task_failed` 三个事件，以及 `NOT_IMPLEMENTED` 结果。

也可以用 PowerShell 检查后端：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'
```

`agent_ready: false` 和 `NOT_IMPLEMENTED` 都是当前框架的预期状态，不是缺少 API Key 或安装失败。访问后端根路径只会返回运行说明，**尚未托管前端静态文件**。

### 6. 停止与再次启动

两个服务分别在对应终端按 `Ctrl+C` 退出。停止后端会清空内存任务历史；当前没有用户任务取消 API。

下次只需分别执行第 3、4 步。后端没有启用代码热重载，修改 Python 代码后需重启；前端开发模式由 Vite 更新页面。

## 环境变量配置

### 配置规则

后端仅从启动进程的环境变量读取配置，**不会自动读取仓库根目录的 `.env` 文件**。`.env.example` 只用于说明配置项，复制为 `.env` 并不会使配置生效。

在对应服务的终端中设置 `$env:变量名` 后再启动服务；这些设置作用于该终端及其子进程，不会自动共享给另一个终端。修改后需重启对应服务。

| 变量 | 默认值 | 设置位置与作用 | 当前状态 |
|---|---|---|---|
| `CODING_AGENT_WORKSPACE` | `.` | 后端：应用工厂未传工作区时的默认值 | CLI 仍要求显式传入工作区参数，且该参数优先 |
| `CODING_AGENT_MAX_STEPS` | `20` | 后端：必须为正整数 | 已读取并校验，尚未接入完整 Loop |
| `CODING_AGENT_API_KEY` | 空 | 后端：模型密钥 | 预留；当前无需配置 |
| `CODING_AGENT_BASE_URL` | 空 | 后端：模型服务地址 | 预留；当前不发起外部请求 |
| `CODING_AGENT_MODEL` | 空 | 后端：模型名称 | 预留 |
| `CODING_AGENT_BACKEND_URL` | `http://127.0.0.1:8000` | 前端终端：Vite 代理的后端地址 | 已使用，启动开发服务或预览服务前设置 |

后端监听端口使用 CLI 的 `--port` 参数配置，不存在 `CODING_AGENT_PORT` 配置项。前端工具不会接收或使用模型 API Key。

### 示例：后端改用 8001 端口

终端 A：

```powershell
Set-Location 'D:\Coding_Agent'
$env:CODING_AGENT_MAX_STEPS = '20'
.\.venv\Scripts\coding-agent.exe demo_workspace --port 8001
```

终端 B：

```powershell
Set-Location 'D:\Coding_Agent\frontend'
$env:CODING_AGENT_BACKEND_URL = 'http://127.0.0.1:8001'
npm.cmd run dev
```

此时前端仍访问 `http://127.0.0.1:5173`，健康检查改为 `http://127.0.0.1:8001/health`。前端固定使用 5173，端口占用会直接报错，不会自动切换；自定义前端端口还需同步后端 Origin 允许列表，不属于当前开箱即用配置。

### 模型配置（未来接入后使用）

当前可完全跳过本节。下面仅说明预留变量的配置方式，**设置它们不会使尚未实现的 Agent 开始工作**。服务地址和模型名应以实际接入的供应商为准。

```powershell
# 在后端终端设置；示例地址和模型名是占位值，不能直接用于真实请求。
$env:CODING_AGENT_BASE_URL = 'https://your-provider.example/v1'
$env:CODING_AGENT_MODEL = 'your-model-name'

# 隐藏输入，避免把密钥字面量写进命令历史。
$env:CODING_AGENT_API_KEY = [System.Net.NetworkCredential]::new(
    '', (Read-Host '请输入 API Key（输入隐藏）' -AsSecureString)
).Password
```

环境变量中的密钥仍是进程可访问的明文，不是加密存储。不要回显密钥、提交含密钥的文件，或将它放进前端配置、用户任务、截图和视频。

## Linux / macOS 启动参考

以下与 Windows 使用相同的工程入口，但尚未在 Linux/macOS 验证。先进入仓库根目录，再运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
.venv/bin/coding-agent demo_workspace
```

第二个终端，从仓库根目录运行：

```bash
cd frontend
npm ci --ignore-scripts
npm run dev
```

可选环境变量使用 `export CODING_AGENT_MAX_STEPS=20` 等形式，在启动后端前设置；自定义后端代理时，在前端终端使用 `export CODING_AGENT_BACKEND_URL=http://127.0.0.1:8001`。

## 构建与本地预览

在前端目录执行：

```powershell
npm.cmd run build
npm.cmd run preview
```

构建产物位于 `frontend/dist/`。预览服务同样使用 `http://127.0.0.1:5173`，因此必须先停止已有的 `npm.cmd run dev`；后端需要保持运行。

`preview` 用于检查本机构建结果，不是生产部署方案。当前还没有 FastAPI 静态资源托管、前后端一键打包或公网部署能力。

## 验证

仓库根目录：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend tests
.\.venv\Scripts\python.exe -m ruff format --check backend tests
.\.venv\Scripts\python.exe -m pip check
```

Windows 下建议使用独立临时目录与缓存的测试脚本，避免 Codex 执行账户和普通用户共用 pytest 目录造成权限错误：

```powershell
.\scripts\test.ps1
```

该脚本从任何工作目录调用都可以，会使用仓库 `.venv`；例如在 `backend` 目录中运行 `..\scripts\test.ps1`。若执行策略不允许运行 `.ps1`，无需修改系统策略，直接执行：

```powershell
$pytestRunDir = Join-Path $env:TEMP ("coding-agent-pytest-" + [guid]::NewGuid().ToString("N"))
& D:\Coding_Agent\.venv\Scripts\python.exe -m pytest D:\Coding_Agent\tests -q --basetemp "$pytestRunDir" -o "cache_dir=$pytestRunDir-cache"
```

按实际克隆位置调整上述绝对路径。pytest 会清空 `--basetemp`：必须使用新建的专用随机路径，不能指定项目根目录或已有数据目录。脚本不删除旧测试目录；运行记录保留在系统临时目录，便于检查失败样例。

本轮在 Windows/Python 3.12 下修复 D001，新增 22 项回归后全量 **194 项测试通过**，包含真实子进程、Node/npm、超时/取消/子进程回收，以及固定时间戳、等长修改和已有旧 `.pyc` 的无模型验证。重复运行记录见 [D001 修复说明](docs/Coding%20Agent%20D001%20修复说明.md)。可选 Node/npm 或符号链接在不支持的环境会明确 skip；保留已有 Starlette/httpx 弃用提示，前端构建本轮未重跑。

三类机制应分开处理：`--basetemp` 隔离 pytest 临时目录及账户权限；`cache_dir` 管理 pytest 状态缓存；Python/pytest 字节码则由 `run_command` 为每次命令设置独立 `PYTHONPYCACHEPREFIX` 并禁写常规字节码。修复不删除工作区已有 `.pyc`，也不要求手动清缓存。该策略只作用于工具命令，不接管用户手动启动的 Python。

前端目录：

```powershell
npm.cmd run typecheck
npm.cmd run build
```

`constraints.txt` 记录本次已验证的 Python 依赖快照，`frontend/package-lock.json` 锁定前端依赖。测试不使用真实模型或凭据。

可选浏览器 smoke test 位于 `scripts/smoke_browser.cjs`：需要独立提供 Playwright、安装 Microsoft Edge，并先按上文启动两个服务。它检查元数据、任务提交、三个 SSE 事件、未实现结果和移动端溢出，截图保存到被 Git 忽略的 `output/qa/`。Playwright 不属于 Agent 运行依赖。

## 常见问题

| 现象 | 检查或处理方式 |
|---|---|
| 找不到 `python`、`node` 或 `npm` | 确认工具已安装并加入 PATH，重新打开终端，再运行版本检查 |
| PowerShell 提示不能运行 `npm.ps1` 或激活脚本 | 使用本文的 `npm.cmd` 和 `.venv\Scripts\python.exe` 命令，无需修改执行策略 |
| 找不到 `coding-agent.exe` / `No module named app` | 在根目录重新执行 `.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"`，确认使用同一个虚拟环境 |
| `Invalid workspace or configuration` | 确认工作区目录已存在、含空格路径有引号、`MAX_STEPS` 为正整数、端口在 1–65535 之间 |
| 页面显示无法连接后端 | 先检查 `/health`；确认两个服务都在运行，且前端代理地址与后端端口一致 |
| 8000 或 5173 端口已占用 | 检查是否重复启动；停止自己此前启动的服务，或按上文修改后端端口；不要直接结束未知进程 |
| 通过局域网 IP 访问失败 | 当前仅允许本机访问，请使用 `127.0.0.1` 或 `localhost`，不要改成公网服务 |
| 修改 `.env` 后没有生效 | 后端不自动加载它；在后端终端设置环境变量并重启 |
| 任务返回 `NOT_IMPLEMENTED` | 预期行为：六个工具已实现，但默认 Runtime 尚未接入它们和 LLM，不是密钥错误 |
| pytest 只有 6 项通过，其余在 tmp_path 初始化报权限错误 | 使用 `scripts/test.ps1` 或上面的随机 `--basetemp` / `cache_dir` 命令，避免不同账户共用临时目录与缓存 |
| pytest 提示 `.pytest_cache` 无法写入 | 使用脚本的独立 `cache_dir`；这是 pytest 状态缓存权限，不是 Python `.pyc` |
| 修改源码后仍运行旧断言（D001） | 工具命令已通过独立字节码前缀 + 禁写修复；`--cache-clear` / `--basetemp` 不处理旧 `.pyc`。详情及回归命令见 D001 修复说明 |
| run_command 返回 `COMMAND_NOT_ALLOWED` | 只接受文档列出的开发命令；不支持 Shell 运算符、内联代码、安装依赖或任意可执行文件 |
| 创建任务返回 409 / 503 | 409 表示已有活动任务；503 表示达到 100 个内存任务上限，确认不需保留历史后重启后端 |
| 依赖下载失败 | 检查网络、代理或包源设置，保持锁文件/约束文件不变；当前没有提供离线依赖包 |

## 目录

```text
backend/app/
  api/          # 任务、元数据与 SSE 接口
  agent/        # Runtime/LLM 协议、Conversation、StopController
  core/         # Settings 与 EventLog
  models/       # Task、Event 模型
  services/     # 单活动任务管理与生命周期
  tools/        # Workspace 守卫、六个工具、原子写入/Diff、命令策略与进程管理
  cli.py        # coding-agent 命令
  main.py       # FastAPI 应用工厂
frontend/src/   # Vue 任务输入、状态、时间线和 API 客户端
tests/          # 不使用真实 LLM 的后端测试
scripts/        # 独立临时目录测试脚本、可选浏览器检查
demo_workspace/ # 演示任务占位目录
docs/           # 设计、实施计划与修改说明
```

## 当前边界

- 内存状态、最多 100 个任务；达到上限返回 503，重启服务会清空历史。
- TaskManager 仅适用于单进程、单 event loop；不要使用多 worker 部署。
- Workspace 已拒绝越界、常见敏感路径、链接/reparse point、硬链接及 Windows 设备/短名称等歧义路径，但不是 OS 沙箱，不能消除所有并发文件系统竞争。
- 六个工具均已实现，可独立调用；写入只接受受限大小的 UTF-8 普通文件，替换必须唯一匹配。详细参数、错误码和示例见 M1 完成说明。
- `run_command` 接受 Python/pytest、Node 工作区脚本、npm 本地脚本和 echo 等白名单入口，不解释管道/重定向。获准脚本仍可访问工作区外文件和网络，必须只运行可信项目。
- 命令使用精简子进程环境、输出上限、超时、Windows Job Object/POSIX 进程组清理；Job Object 仅管理进程生命周期，不隔离文件和网络。POSIX 分支尚未在本轮实机验证。
- LLM 客户端只有协议；没有 HTTP 请求、模型响应解析和完整 Agent Loop。
- Context 按完整交互轮次保留最近记录；字符/token 预算、输出截断和摘要待实现。
- StopController 是可单测的策略，还未接入 Runtime；命令超时与取消清理已在工具层实现，页面尚无任务取消入口。
- 本机 Host/Origin 限制不是身份认证，不能作为对公网或多用户部署的安全保障。
- 项目文件和命令输出将来要作为不可信数据处理；实际日志脱敏管道待实现。

## 项目文档

- [D001 修复说明](docs/Coding%20Agent%20D001%20修复说明.md)：命令级缓存策略、22 项新增回归、重复全量验证及三类缓存/权限问题。
- [M1 工具系统完成说明](docs/Coding%20Agent%20M1%20工具系统完成说明.md)：写入/替换/Diff、命令白名单、资源边界、修改文件与完整验证。
- [M1 只读工具说明](docs/Coding%20Agent%20M1%20只读工具实现说明.md)：调用方法、输出字段、路径策略、资源限制和验证结果。
- [项目结构与功能设计](docs/Coding%20Agent%20项目结构与功能设计文档.md)：第 9 节包含前后端逐文件职责、已实现/待实现部分、调用关系与测试文件对照。
- [实施计划](docs/Coding%20Agent%20实施计划.md)
- [基础框架修改说明](docs/Coding%20Agent%20基础框架修改说明.md)

`README.txt`、真实 Bug Demo、视频与提交压缩包属于后续里程碑，当前没有生成正式提交材料。
