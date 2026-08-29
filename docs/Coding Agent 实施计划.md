# Coding Agent 实施计划

> 计划周期：2026-08-27 至 2026-09-07（因新增 M6 持久化与多轮会话，建议重新基线）
> 交付目标：先完成可重复的端到端 Agent 闭环，再补展示与提交材料。任何 P1 功能不得阻塞 P0。

> 2026-08-29 更新：M0 至 M6 已实现；M6 自动化、前端构建与真实模型多轮/重启 smoke 已通过，最终交付为 M7。详见 [当前状态](README.md)、[M5 完成说明](Coding%20Agent%20M5%20UX%20重构完成说明.md) 与 [M6 计划](Coding%20Agent%20M6%20历史任务与多轮对话实施计划.md)。

## 1. 里程碑

| 原定日期 | 里程碑 | 完成定义 | 当前状态 |
|---|---|---|---|
| 08-27 | 架构冻结与框架建立 | 可导入、健康检查、核心协议 | 基础框架已实现 |
| 08-28 | 本地工具闭环 | 六工具与路径/超时/稳定测试 | 已实现；D001 已修复并验证 |
| 08-29 | Agent Loop 闭环 | 模型调用、结果回填、终止生效 | M2 已完整实现并通过确定性测试 |
| 08-30 | API 与前端时间线 | 完整真实执行事件 | M3 已实现并通过确定性 API/UI 契约验证 |
| 08-31 | Demo 打通 | 真实模型连续成功至少 3 次 | 已实现；正式验收连续 3/3 成功 |
| 08-29–09-01 | 可组合 TaskRun UX | 自然语言活动、完整 Trace/Summary、恢复与无障碍不回退；为多 Task 组合保留接口 | 已实现并重新取得 M4 真实模型 3/3；详见 M5 完成说明 |
| 09-02–09-06 | 历史任务与多轮会话 | 项目内版本化 JSON 持久化、原子写/锁、重启收敛、Session/follow-up API、有界历史上下文与历史 UI | 已完成 |
| 09-07 | 最终交付 | 全量复验、README.txt、视频、密钥扫描、材料检查和最终提交 | M7 待实施，不推断远程仓库状态 |

## 2. 工作分解

### M0：框架与约束（08-27）

- [x] 阅读项目要求并完成设计可行性复核。
- [x] 明确禁止 Agent 框架和托管代码/文件工具。
- [x] 建立后端、前端、测试和配置目录框架。
- [x] 安装依赖并运行健康检查。
- [x] 已有本地阶段提交：框架 `8b1a65a`、只读工具 `0809a24`、写入/命令 `39697d6`；持续提交仍是后续开发要求，本轮不执行提交或推送。

### M1：工具系统（08-28）

当前状态：六个工具已绑定到指定 Workspace，可经 ToolRegistry.execute 调用并已接入 Agent Loop。D001 已修复并补充确定性回归；仍不承诺 OS 安全沙箱。

- [x] 完成 Workspace 路径解析与敏感路径拒绝（保守拒绝所有链接/reparse point，不等于强沙箱）。
- [x] 完成 `list_files`、`read_file`、`search_text`（UTF-8、字面匹配、扫描/读取/输出上限）。
- [x] 覆盖只读工具、路径别名、符号链接、Windows junction、硬链接、截断与错误结果的测试。
- [x] 完成 `write_file`、`replace_in_file` 和统一 diff（同目录原子提交、哈希、唯一匹配与冲突检测）。
- [x] 完成 `run_command`、超时、输出截断和危险命令检查（受限 argv 白名单，不解释 Shell 运算符）。
- [x] 补齐写入唯一替换、命令超时及进程清理测试（正常退出、超时、取消、Job 分配失败均覆盖）。
- [x] 修复 D001：每命令独立字节码前缀 + 禁写；固定同秒等长修改/真实旧缓存回归，覆盖连续调用与生命周期。
- [x] 修复后重新完成全量测试，区分临时目录权限、pytest 状态缓存与 Python 字节码缓存，记录重复验证结果。

退出标准：不经过模型，工具层测试全部通过；任何文件写入都能给出可审计结果。

历史记录为 172 passed，随后复验发现 D001（171 passed / 1 failed）。M1 修复阶段达到 194 passed，M2 达到 242，M3 达到 246，M4 达到 248，M5 达到 254，M6 Phase 0–2 达到 276；M6 完成后当前全量为 281 passed。M4 的三轮真实模型验收仍有效；M6 多轮/重启真实 smoke 也为 3/3。POSIX 分支仍待实机验收。

### M2：Agent Runtime（08-29）

当前基础：具体 LLM HTTP 适配、双总预算 Conversation、StopController 与 ToolRegistry 已接入默认 Runtime；模型配置完整时运行 Agent Loop，配置不完整时保持安全 scaffold。

- [x] 已有 LLMClient / ModelReply / ToolCall 接口，以及六工具 Schema 生成与 ToolRegistry 分发。
- [x] 已有 Conversation 完整轮次配对/最近轮次裁剪，StopController 步数与重复调用独立策略。
- [x] 实现具体 LLM HTTP 适配、响应校验、超时/重试和资源关闭；原样复用既有工具 Schema。详见 [M2 说明](Coding%20Agent%20M2%20LLM%20HTTP%20适配说明.md)。
- [x] 实现上下文字符/token 总预算及模型侧结果裁剪整合；总量包含既有工具 Schema，不重复实现工具层输出上限。
- [x] 将 Conversation、ToolRegistry、StopController 接入 Agent Loop，按调用 ID 和原顺序回填结果。
- [x] 发布真实 tool_started/tool_finished/file_changed/command_finished 事件并限制事件/历史体积；过期游标返回 410。
- [x] 补充连续 LLM/Runtime 错误与连续命令超时的跨轮恢复阈值及终止语义。
- [x] 处理关闭时已开始的文件写入与命令取消；先等待操作落定/进程清理，再发布终态，且明确取消不会回滚文件。
- [x] 使用 Fake LLM 编写确定性循环测试，不消耗真实 API；覆盖读文件、修改、pytest 和最终回复。

退出标准：Fake LLM 能按“读文件 -> 修改 -> 运行测试 -> 最终回复”完成一条可重复测试。

### M3：API 与 UI（08-30）

- [x] 完成 TaskManager、创建/查询任务 API；模型配置完整时接入 AgentRuntime，否则保留 scaffold 诊断模式。
- [x] 完成事件历史回放与 SSE 订阅（包含游标、心跳及终态关闭）。
- [x] 完成 Vue 输入、状态、通用 Timeline、最终结果区与六工具可用状态展示。
- [x] 实现防重复提交、错误/断线提示、自动重连、手动查询/重连、事件 ID 去重和终态关闭。
- [x] 实现 Tool/Shell/File Change 专用卡片、判别联合与逐类运行时 payload 校验；复用后端真实工具事件。
- [x] 实现有界退避重连、410 历史窗口恢复、404 服务重启降级、整页刷新任务恢复和终态二次查询。
- [x] 验收断线回放、服务重启、真实大载荷和成功/失败终态一致性；不把内存任务引用误称为持久化。

退出标准：浏览器能观察真实 Agent 从 task_started 到 task_completed/failed 的完整过程，包含实际工具、文件变化与命令结果，不能仅以占位失败链路验收。

注意：配置完整时前端按专用卡片展示真实 Tool/Shell/File Change 事件；配置不完整时仍是 `task_started -> assistant_message -> task_failed(NOT_IMPLEMENTED)`，这是安全诊断模式。真实供应商 Demo 连续成功率仍属于 M4。

### M4：Demo 与可靠性（08-31）

- [x] 创建只包含少量代码的 `demo_workspace`；初始测试稳定为 1 failed、1 passed。
- [x] 根据真实探测轨迹优化 System Prompt，让 Agent 先检查、最小修改、主动验证且不得修改测试作弊。
- [x] 验证真实 OpenAI-compatible 响应、工具参数、事件和终态；调优后三轮无失败工具调用。
- [x] 连续执行 3 次并记录成功率、耗时、步数、工具调用和失败原因；结果为 3/3、失败原因为空。

退出标准：相同 Demo 至少连续成功 3 次；失败时前端可解释而非卡死。

### M5：可组合 TaskRun UX（08-29 至 09-01）

- [x] 完成当前 idle/running/completed/failed 与窄屏视觉基线，并确认可实施视觉目标。
- [x] 实现 ConversationThread 壳层、单个 TaskRunSection、确定性 Tool Activity、`call_id` 聚合及 File/Command 附件。
- [x] 实现不依赖 EventLog 回读的完整 ExecutionTrace 和成功/失败 TaskSummary。
- [x] 保持刷新、410、404、204、终态一致性、安全边界和单 Task 语义。
- [x] 拆分 activeTask / selectedContext；Composer 只发意图；Sidebar、recent-context 和 TaskRun key 可平滑接入多轮历史。
- [x] 完成前端单测基础、无障碍/窄屏/browser smoke，并重新取得 M4 真实模型 3/3。

详细契约、阶段和止损规则见 [M5 UX 重构实施计划](Coding%20Agent%20M5%20UX%20重构实施计划.md)。M5 不显示伪历史或伪 follow-up，但不得把整个 Conversation 建模成一个 Task。P1 视觉增强不得挤压 M6。

### M6：历史任务与多轮对话（09-02 至 09-06）

- [x] 在项目 `/.coding-agent/history/` 建立版本化 JSON Repository、跨进程单写锁、原子替换、格式迁移和资源关闭边界；目录受 Git ignore 与 Workspace.BLOCKED 双重保护。
- [x] 持久化 Session、Task、TaskSummary 和受既有上限约束的 Events；Repository 取代内存历史事实源。
- [x] 保持 `POST /api/tasks` 向后兼容，并新增 Session 列表/详情/Task 分页/follow-up/删除 API。
- [x] 实现 persist-before-SSE、terminal 原子收口、重启后 durable replay 与 PENDING/RUNNING → `SERVER_RESTARTED` 幂等收敛。
- [x] 从历史 Task/TaskSummary 确定性构建 TaskRecap；复用 M2 字符/token 总预算，按最近完整回合选择，不重放旧工具输出。
- [x] 接入 M5 ConversationThread/TaskRunSection：历史 Sidebar、多 TaskRun、New Conversation、Follow-up、URL/recent-context 恢复。
- [x] 保持全局单活动 Task；浏览旧会话时 active SSE watcher 继续工作，follow-up 使用新的 Conversation/StopController/call_id 生命周期。
- [x] 完成原子移入 trash 的删除、硬上限、损坏 JSON 隔离/重建、故障注入、文件锁/SSE 关闭和 canary secret 验证。
- [x] 通过 format migration、restart、context、API、前端与 M6 browser smoke；经授权完成最小真实模型多轮/重启 smoke 3/3，并保持 M4 独立 3/3 历史证据。M7 仍统一复验最终候选。

详细 JSON format、目录布局、原子性、API、上下文算法、测试矩阵和退出标准见 [M6 历史任务与多轮对话实施计划](Coding%20Agent%20M6%20历史任务与多轮对话实施计划.md)。搜索、重命名、归档、分支和自动长期记忆均为 P1/P2，不得挤压持久化一致性、隐私删除和上下文预算。

### M7：交付（09-07）

- [x] 已有开发 README.md：环境、启动、配置、测试方式和能力边界。
- [ ] 最终交付前核对文档中的最新测试状态与已知缺陷，补 1000 汉字以内 README.txt 和最终仓库地址。
- [ ] 对最终版本重新执行全量测试、前端构建、API/浏览器 smoke、M6 重启/多轮 smoke，不以阶段记录替代最终验收。
- [ ] 扫描 API Key、`.env`、日志和视频画面。
- [ ] 录制 2 分钟内 MP4：启动、历史恢复、新会话/follow-up、Agent 工具活动、失败恢复与测试通过。
- [ ] 检查视频不超过 200 MB，压缩 README.txt 与视频为姓名命名的 zip。
- [ ] 按最终确认的提交截止时间提前完成最后一次仓库推送，截止后不再推送。

M7 不实现 M6 功能。若 JSON format/migration、原子写/锁、重启收敛、follow-up 上下文、删除或资源关闭仍有缺口，返回 M6 修复后再开始最终录制。

完整的进入条件、候选冻结、复验矩阵、录屏脚本、安全扫描、压缩包和 Go/No-Go 规则见 [M7 最终交付计划](Coding%20Agent%20M7%20最终交付计划.md)。

当前预检记录（2026-08-29）：根目录 `.env.example` 被 `.gitignore` 忽略、未被 Git 跟踪且未发现进入当前可见历史，但其中 `CODING_AGENT_API_KEY` 疑似为非占位值。M7 前应将示例恢复为占位符、改用启动进程环境变量，并轮换该密钥；此记录不包含或回显密钥值。

## 3. 测试策略

| 层级 | 方法 | 必测内容 |
|---|---|---|
| 单元/工具集成 | pytest | Workspace、工具、LLM HTTP、上下文、事件、Agent Loop、M3 恢复、M4 Demo、M5 Trace/Summary、M6 Repository/migration/restart/context/API；当前为 281 passed |
| 无模型工具流程 | tests/test_shell_tools.py / test_command_bytecode.py | 真实写入、pytest 失败、替换与复验；固定时间戳旧缓存及重复执行验证 |
| 组件 | Fake LLM | 调用 ID 回填、参数错误恢复、并行调用、预算裁剪、步数/重复停止和真实本地修复流程 |
| API | FastAPI TestClient | 任务冲突、Session/follow-up/delete、游标分页、事件持久回放、服务重启与终态一致性 |
| 前端 | Vitest + 严格类型 + 构建 + browser smoke | TaskRun 聚合、历史导航、多轮追加、刷新恢复、active watcher、失败/完成与 SSE 断线提示 |
| E2E | Fake LLM + 经授权真实模型 + demo_workspace | 真实修改/测试、持久重启、历史恢复、有界 follow-up 上下文与结果一致性 |

## 4. 风险与降级顺序

1. **真实模型格式不稳定**：优先收紧 Tool Schema、System Prompt 和响应校验；不通过引入 Agent SDK 解决。
2. **前端耗时超预期**：保留单页 Timeline，优先删文件树、代码查看器和高级 Diff。
3. **SSE 重连复杂**：M5 沿用当前有界内存恢复；M6 改为持久事件 replay，继续保留 410/204 语义，并用启动收敛替代重启后的在途任务 404。
4. **Shell 安全不足**：只在专用 Demo Workspace、普通用户权限下演示，并明确非强沙箱。
5. **时间不足**：P1 全部停止；必须保住工具闭环、M5 TaskRun/Summary、M6 JSON 原子写/format migration/重启收敛/预算/删除/资源关闭和 M7 真实验证。若 09-02 是不可变外部截止，应明确缩减里程碑或延期，不得把不可靠的持久化伪装成完成。
6. **D001 字节码缓存复用（已修复）**：保留确定性回归和命令级缓存隔离，不靠等待一秒或改变内容长度避免失败；后续改命令策略时持续验证子进程继承与清理。
7. **历史存储敏感数据**：`/.coding-agent/history/` 被 Git 与工具层双重隔离，持久 payload 有界，日志脱敏，提供删除和保留策略；不保存配置 API Key、供应商 raw response 或旧工具完整输出。

## 5. 每日完成检查

每天结束前执行：

```text
1. 运行当前自动化测试
2. 用一条最短路径手工 smoke test
3. 检查 git diff 是否只包含预期变更
4. 检查是否误写 API Key
5. 更新勾选项和次日第一优先级
6. 提交一个内容清晰的 Git commit
```

## 6. 最终 Go/No-Go 清单

只有以下条件全部满足才录制最终视频：

- [ ] Agent 决策来自模型原生 tool calling。
- [x] 六个工具均由本项目本地实现；完整稳定性另见下一项。
- [x] 修复并验证 D001，全量测试通过；后续版本仍需重新验收。
- [x] Tool Result 确实按调用 ID 回到下一轮模型输入。
- [x] 最大步骤、重复调用和命令超时已有确定性测试证明。
- [ ] Demo 中真实文件发生变化，真实测试从失败变为通过。
- [ ] Timeline 与最终总结没有伪造或遗漏失败。
- [ ] 历史在服务重启后仍可浏览，在途任务不会被自动重放。
- [ ] follow-up 只注入有界完整 TaskRecap，且继续通过 M2 字符/token 总预算。
- [ ] 会话可删除，历史 JSON/事件/日志不包含配置 API Key 或供应商原始响应。
- [ ] M5/M6/M7 的实现与文档边界一致，没有把 P0 遗留到交付阶段。
- [ ] 仓库与交付材料不存在密钥。
- [ ] README.txt、视频、公开仓库和 zip 满足格式要求。
