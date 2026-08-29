# Coding Agent M1 只读工具实现说明

> 2026-08-28 状态导航：第 1、3–7 节作为当前只读工具参考；第 2、8 节保留首次实现/验证记录。六工具与 D001 修复阶段全量 194 passed；此后 M2–M4 已接入，当前全量 248 passed，见 [M4 Demo 与可靠性完成说明](Coding%20Agent%20M4%20Demo%20与可靠性完成说明.md) 和 [文档导航](README.md)。

首次实现日期：2026-08-27。本文件重点说明路径解析、`list_files`、`read_file`、`search_text`；后续写入、替换、Diff 和命令功能已在 M1 完整说明中记录。

## 1. 当前可用能力

三个工具可以通过绑定 Workspace 的 `ToolRegistry.execute()` 独立调用。`main.py` 已把相同 Workspace 注入注册表，但默认 Agent Runtime 尚未调用这些工具，因此网页提交任务仍以 `FAILED / NOT_IMPLEMENTED` 结束。

当前 `GET /api/meta` 的六个 `tool_statuses` 均为 `ready`，前端显示“工具就绪”；`agent_ready` 仍为 false。首次只读阶段才是“三个 ready、三个 not_implemented”，不能沿用为当前 API 预期。当前没有文件查询/工具执行 HTTP API，也没有模型调用或自动执行任务。

## 2. 首次只读实现的修改文件（历史）

本表只记录首次只读阶段的变更，“写入未实现/关闭”属于当时状态；当前逐文件职责见设计文档第 9 节。

| 文件 | 修改内容 |
|---|---|
| `backend/app/tools/workspace.py` | 强化相对路径、根目录身份、Windows 路径歧义、敏感路径和链接检查 |
| `backend/app/tools/read_only.py`（新增） | 共享资源上限、受限遍历、UTF-8 读取与文件身份核验 |
| `backend/app/tools/files.py` | 实现目录列表与按行读取；写入/替换保持未实现 |
| `backend/app/tools/search.py` | 实现有界字面搜索与跳过/截断统计 |
| `backend/app/tools/base.py` | ToolSpec 增加 implemented 状态 |
| `backend/app/tools/registry.py` | 必须绑定 Workspace，注册真实只读 handler，统一错误码和可用状态 |
| `backend/app/tools/__init__.py` | 更新能力说明 |
| `backend/app/main.py` | 使用 `create_registry(workspace)`，避免隐式采用进程 cwd |
| `backend/app/api/routes.py` | 元数据返回工具可用状态 |
| `frontend/src/types.ts`、`App.vue` | 接收并展示只读就绪状态，保留 Agent 未接入说明 |
| `tests/test_read_only_tools.py`（新增） | 只读工具行为、安全边界、资源预算、错误与隔离测试 |
| `tests/test_workspace.py` | 扩展路径别名、内部链接、junction、硬链接和根目录变化测试 |
| `tests/test_agent_contracts.py`、`test_api.py` | 更新注册表注入与元数据预期，确认写入/Shell 仍关闭 |

README、实施计划和设计文档第 9/13 节已同步。M0 修改说明作为历史记录保留，并添加本阶段文档入口。

## 3. 路径规则

- CLI 的 Workspace 根目录仍须存在，启动时解析为真实绝对路径；工具只接受相对于该根目录的路径。
- 支持 `.`、`src/main.py`、`src\main.py`；输出路径统一使用 `/`，始终相对于 Workspace，而非当前搜索子目录。
- 拒绝 `..`（即使最终仍在工作区内）、绝对路径、UNC/设备路径、驱动器相对路径、冒号数据流、控制字符、非法 Unicode、过长路径与组件。
- 拒绝 Windows 保留设备名、尾点/尾空格、通配字符以及形如 `NAME~1` 的短名称别名；同一策略也在其他系统执行，保证可移植的保守行为。
- 拒绝符号链接、junction 及其他 reparse point，**即使链接指向工作区内部**；普通文件的硬链接也拒绝。此策略可能排除 OneDrive 等工具创建的 reparse 文件。
- 忽略/拒绝固定的敏感、版本控制、依赖与构建路径，例如 `.git`、`.env`/`.env.*`、`.ssh`、`.aws`、`.npmrc`、私钥后缀、`node_modules`、`.venv`、`dist`、`build`。完整规则以 Workspace.BLOCKED 与 `_check_parts()` 为准；`.env.example` 也被规则排除。
- 目前不解析项目 `.gitignore`，也不对任意文本内容进行凭据识别；普通源码中若含密钥，仍可能被读取。
- 当前还会排除 `.coding-agent-write-` 前缀的内部写入临时文件；写入工具也使用相同路径规则。
- 显式请求被禁止的路径会返回 `PATH_NOT_ALLOWED`；遍历发现时跳过并计数，不返回该条目的内容。

路径命名规则参考 [Windows 文件/路径命名约束](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)，链接和文件类型判断使用 [Python stat 信息](https://docs.python.org/3/library/stat.html)。读取前后检查文件身份，但它不是 OS 级安全沙箱，不能消除父目录被恶意并发替换等所有竞争条件。

## 4. 工具行为与输出

所有调用返回统一 `ToolResult`：`ok`、`output`、`error_code`、`error_message`、`truncated`。参数采用严格类型且禁止额外字段；底层 OSError 不原样回显。文件正文仍是原始不可信内容，可能含路径或凭据，当前不做内容级脱敏。

### list_files

参数：`path="."`，`max_entries=200`（1–1000）。

递归深度优先遍历目录；每个已扫描目录内按名称排序，返回文件和目录，但不返回起点目录本身。扫描预算耗尽时仅对已收集条目排序，不保证被截断集合在不同文件系统上的全局顺序相同。

- `output.entries`：`{path, type}` 列表，type 为 `file` 或 `directory`。
- `scanned_entries`：已枚举条目数，包含随后被过滤的条目，防止大量隐藏文件绕过预算。
- `skipped_entries`：被策略或访问错误跳过的条目数。
- `truncation_reasons`：可能包含 `max_entries`、`output_limit`、`scan_limit`、`depth_limit`、`time_limit`、`unreadable_entries`。

不存在的起点是错误；把普通文件作为起点返回 `NOT_DIRECTORY`。达到深度边界时保守标记截断，即使边界目录可能为空。

### read_file

参数：`path`，`start_line=1`，`end_line=null`；行号从 1 开始，两端包含。显式 end_line 小于 start_line 属于参数错误。

仅接受普通 UTF-8 文本，支持 UTF-8 BOM 并移除 BOM；保留原换行符。包含 NUL 等控制字节的内容判定为二进制；非 UTF-8 数据拒绝，不猜测编码。

- `content`：实际返回文本。
- `start_line`、`end_line`、`returned_lines`、`total_lines`：请求开始行和实际返回范围；空文件/开始行超过 EOF 返回成功的空内容，end_line 为 null。
- `file_bytes`：实际读取的文件字节数。
- `next_start_line`：仍有后续文件行时给出下一行；显式选择小范围并不自动标记 truncated。
- `last_line_truncated`：字符预算是否在最后一条返回行内部截断。
- `truncation_reasons`：`line_limit`、`output_limit`。

`end_line=null` 表示希望读至 EOF，但仍受单次行数上限约束。过长单行可能只返回前缀；下一行游标不会补回该行剩余部分，当前不支持列偏移分页。超过单文件字节上限直接报错，而非伪装为完整读取。

### search_text

参数：`query`（1–1000 字符、单行），`path="."`（文件或目录），`max_results=50`（1–200）。

区分大小写，按字面文本搜索，不使用正则或 Shell；每行最多返回一次匹配，即该行第一次出现的位置。

- `matches`：包含 `path`、`line`、`column`（行列均从 1 开始）、`match_length`、片段 `text`。
- `snippet_start_column`、`snippet_truncated`：说明片段在原行中的起点及是否省略上下文。片段至少包含匹配起点；查询本身长于片段预算时只显示其前缀。片段限制不会遗漏匹配条目，因此只设片段标志，不单独把整个搜索标为 truncated。
- `scanned_files`：尝试处理的普通文件数；`searched_files`：已解码并进入行匹配的文件数。
- `scanned_bytes`：累计实际读取字节，包括发现二进制/编码错误前已读取的内容。
- `skipped_files`：按错误类别统计。目录搜索跳过二进制、非 UTF-8、过大或不可读文件；若显式指定此类文件则返回错误。
- `scanned_entries`、`skipped_entries`：目录遍历统计；显式单文件查询时为 0。
- `truncation_reasons`：遍历原因及 `max_results`、`output_limit`、`file_limit`、`byte_limit`、`unreadable_files`。

没有匹配可以成功返回空列表，但必须同时检查跳过统计与 truncated；这不代表被排除的文件也已搜索。因为大小预算无法容纳下一个候选文件时会停止，不会为了凑满预算跳到后面的文件。

## 5. 默认资源上限

| ReadLimits 字段 | 默认值 | 含义 |
|---|---|---|
| max_file_bytes | 1 MiB | 单次可接受的文件大小 |
| max_output_chars | 20,000 | read_file 的文本字符；或列表/搜索条目的序列化字符预算，少量元数据另计 |
| max_read_lines | 300 | 单次 read_file 最大返回行数 |
| max_scan_entries | 10,000 | 列表/目录搜索最大枚举条目数 |
| max_depth | 20 | 相对起点的最大遍历层级；到达边界的目录可列出但不继续深入 |
| max_search_files | 500 | 搜索最大候选文件数 |
| max_search_bytes | 8 MiB | 搜索累计读取预算 |
| max_snippet_chars | 300 | 单个匹配片段字符数 |
| max_scan_seconds | 5 秒 | 列表/搜索协作式时间预算 |

这些值由注册表构造时注入，不接受模型调用随意提高。检查文件是否在 stat 后增长时，最多额外读取 1 字节作为超限探测；总读取预算可能因此多出这个探测字节。过大文件在 stat 阶段即可跳过，不消耗正文读取预算。

扫描/读取经 `asyncio.to_thread` 执行，避免阻塞事件循环。协作式时间预算不是强制中断：无法中断操作系统正在阻塞的文件 I/O，也不等同于现有命令工具的进程超时。read_file 只有大小/返回量限制，没有单独的时间上限。

## 6. 错误码

| 错误码 | 说明 |
|---|---|
| INVALID_ARGUMENTS | 类型、必填、行范围或数量参数不合法 |
| PATH_NOT_ALLOWED | 越界、敏感路径、链接、路径歧义或检测到文件身份变化 |
| NOT_FOUND / NOT_DIRECTORY / NOT_FILE | 不存在或文件类型与请求不符 |
| PERMISSION_DENIED / IO_ERROR | 文件系统拒绝访问或其他 I/O 错误 |
| FILE_TOO_LARGE | 超过单文件读取限制 |
| BINARY_FILE / UNSUPPORTED_ENCODING | 不是受支持的 UTF-8 文本 |
| UNKNOWN_TOOL / TOOL_ERROR | 工具未注册或其他非预期工具错误 |

`NOT_IMPLEMENTED` 当前是默认 Agent 任务的错误，不是这六个工具 handler 的返回状态。写入与命令错误码见 M1 完整说明。

## 7. 独立调用示例

完成 README 中的后端可编辑安装后，可在仓库根目录的 Python 解释器中运行下列代码。示例只读取 demo_workspace，未写入任何项目文件。

```python
import asyncio
from pathlib import Path

from app.tools.registry import create_registry
from app.tools.workspace import Workspace

async def main():
    tools = create_registry(Workspace(Path("demo_workspace")))
    calls = [
        ("list_files", {"path": "."}),
        ("read_file", {"path": "README.md", "start_line": 1, "end_line": 10}),
        ("search_text", {"path": ".", "query": "占位"}),
    ]
    for name, arguments in calls:
        result = await tools.execute(name, arguments)
        print(name, result.model_dump_json(indent=2))

asyncio.run(main())
```

`create_registry()` 不再允许无参数调用；调用方必须显式传入 Workspace。这避免独立测试或未来 Runtime 意外把进程当前目录当作授权目录。

## 8. 首次只读阶段验证与当前复验

以下是首次只读阶段的历史记录，不代表当前全量测试数量或本次结果：

- 后端：`python -m pytest -q`，**104 passed**；包括真实 Windows junction、符号链接、硬链接、工作区隔离、打开期间替换、UTF-8/BOM/CRLF、只读内容不变与预算边界。
- Ruff：lint 和格式检查通过。
- 前端：TypeScript 检查及 Vite 生产构建通过。
- 保留一条已有的 Starlette TestClient/httpx 弃用提示，不影响测试结果；本轮没有变更依赖。
- 仅在当前 Windows/Python 3.12 环境验证。没有声称完成真实 Agent 任务、Shell 超时、所有文件系统竞争场景或跨平台验收。

当前补充：写入/替换/Shell 已实现；此前重复 pytest 的 D001 已修复，M1 修复阶段新增 22 项回归后全量 194 passed。此后 M2 新增客户端测试，当前总数见 [文档导航](README.md)。详见 [D001 修复说明](Coding%20Agent%20D001%20修复说明.md)，不把已完成的写入/Shell 列为下一步实现项。
