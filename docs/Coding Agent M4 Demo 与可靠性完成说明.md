# Coding Agent M4 Demo 与可靠性完成说明

> 完成日期：2026-08-28  
> 范围：真实供应商联网、可重复 Bug Demo、Prompt 调优、三轮连续成功与独立验证。

## 1. Demo 场景

`demo_workspace` 是一个最小 Python 项目：`calculator.divide` 的契约要求除数为零时返回 `None`，初始实现却直接执行除法。初始 `pytest -q` 的真实结果为 1 failed、1 passed。

提交给 Agent 的任务要求它检查工作区和相关源码/测试，只修改实现，运行完整 pytest，并且只有测试真实通过后才能结束。验收不接受只生成总结或只修改测试。

## 2. 可靠性验收器

`scripts/run_m4_demo.py` 通过真实 FastAPI Task/SSE 链路和默认 AgentRuntime 调用已配置模型。每轮执行：

1. 恢复相同的初始 Bug 和测试文件；
2. 独立运行 pytest，确认基线确实失败；
3. 创建真实任务并读取到终态事件；
4. 检查出现 `file_changed` 和成功的 pytest `command_finished`；
5. 校验测试文件 SHA-256 未变化；
6. 在 Agent 结束后独立运行 pytest；
7. 无论成功或异常，都把工作区恢复到初始失败状态。

验收器只从进程环境读取模型配置，报告不保存 API Key、Base URL、模型响应正文或请求头。原始本地报告位于被 Git 忽略的 `output/m4-real-demo.json`。

## 3. Prompt 调优

首轮探测在 15.781 秒内成功，但模型先调用 `replace_in_file`，随后又使用 `write_file`。根据真实轨迹，System Prompt 增加了这些约束：

- 明确采用 inspect → edit → verify；
- 先阅读相关实现和测试；
- 优先精确替换和最小修改，不为通过而修改测试；
- 将每次 ToolResult 视为 Observation，失败时纠正参数或方案；
- 修改后运行相关完整测试，只有返回的退出状态成功才能结束；
- 最终总结必须给出变更文件和真实验证命令/结果。

调优后正式三轮均只使用成功的工具结果，以 `replace_in_file` 修改实现，没有再整文件重写。

## 4. 三轮真实模型结果

| 轮次 | 结果 | 耗时 | 决策步 | 工具调用 | 文件变化 | Agent 测试 | 独立复验 |
|---|---:|---:|---:|---:|---|---|---|
| 1 | 成功 | 12.219 s | 5 | 5 | `calculator.py` | 2 passed | 2 passed |
| 2 | 成功 | 12.500 s | 5 | 7 | `calculator.py` | 2 passed | 2 passed |
| 3 | 成功 | 12.891 s | 5 | 5 | `calculator.py` | 2 passed | 2 passed |

汇总：3/3 成功，成功率 100%；平均耗时 12.537 秒，平均 5 个决策步、5.67 次工具调用。三轮测试文件哈希均未变化，SSE 末事件均为 `task_completed`，任务查询均为 `COMPLETED`，失败原因均为空。

三轮都自主完成目录/代码检查、最小文件修改和 pytest。第二轮额外使用 `search_text` 和一次额外读取，但没有失败工具调用或无关文件变化。

## 5. 安全与边界

- 真实调用使用用户本机配置，本说明不记录供应商地址、模型名或密钥。
- 当前 `.env.example` 被仓库规则忽略，但真实密钥仍建议移入仅本机可读的 `.env` 或密钥管理器；若该文件曾被分享，应轮换密钥。
- Demo 证明当前模型对这个固定小任务连续成功，不代表对任意仓库或复杂任务有 100% 成功率。
- 工具仍是可信单用户本地执行边界，不是 OS 文件/网络沙箱。
- 工作区在验收结束后保持初始失败状态，方便网页现场演示同一闭环。

## 6. 复验

先在当前 PowerShell 进程设置 README 中的三项模型环境变量，然后运行：

```powershell
.\.venv\Scripts\python.exe scripts\run_m4_demo.py --runs 3
```

联网调用会产生真实模型费用。退出码只有在全部轮次同时满足基线失败、实现修改、测试未篡改、Agent pytest 成功、独立 pytest 成功和终态一致时才为 0。

## 7. M5 后重新验收（2026-08-29）

M5 收口后重新连续运行 3 轮，结果仍为 3/3，耗时分别为 12.000、12.969、11.750 秒，平均 12.240 秒；每轮均为 5 个决策步、6 次成功工具调用，Agent pytest 与独立 pytest 都是 2 passed。

验收器同时新增 M5 硬检查：terminal Summary 必须存在、`files_changed` 必须包含 `calculator.py`、最后一次 pytest Verification 必须为 passed。三轮全部通过，测试文件哈希均未变化，报告保存于 Git 忽略的 `output/m5-real-demo.json`。
