# Coding Agent M5 UX 重构完成说明

> 完成日期：2026-08-29

M5 已完成单 Task 的可组合 TaskRun UX、确定性 Activity 聚合、完整有界 ExecutionTrace 与终态 Summary，并保留 M6 多 Task/会话组合接口。M5 没有实现历史持久化或伪多轮；这些仍属于 M6。

## 1. 后端事实链

- `TraceRecorder` 在 EventLog 成功发布同一份原始结构化事实后更新 Trace，不从受限事件历史回读 Summary；事件被裁剪或淘汰不影响终态统计。
- Task 生命周期拥有 Trace；完成、Runtime 失败、取消和服务关闭都先设置终态与 `finished_at`，再生成 Summary，最后发布终态事件。
- Summary 有界保存去重后的读取/变更路径、命令事实、工具调用数、Agent 决策轮、错误码和耗时；不复制完整 Diff、stdout/stderr 或供应商正文。
- pytest 仅识别 `pytest`、`python -m pytest`、`python3 -m pytest`，以最后一次识别命令的结构化结果为准。
- `TaskRunner` 依赖最小 `EventPublisher` 协议；既有 Tool Schema、Runtime、Context、StopController 和工具输出上限未重复实现或改变语义。

## 2. 前端任务线程

- 页面重构为 Sidebar、ConversationThread、单个 TaskRunSection 和 Composer；`activeTask` 与当前展示 Task 分离。
- `buildTaskRun` 按数字事件 ID 处理，去重事件，并用 `task_id + call_id` 稳定聚合工具生命周期；File Change 与 Command 是同一 Activity 的附件。
- 六工具由纯 Formatter 翻译结构化事实。没有 `file_changed` 时不会声称文件已经修改；截断、取消、timeout 和 cleanup failure 都有文字降级。
- Terminal Summary 将模型 Narrative 与 Runtime Facts 分区展示；前端严格校验嵌套 Summary DTO。
- recent-context 使用版本化 v1 JSON，并迁移旧 task key；刷新、410、404、204 和终态二次查询沿用 M3 语义。
- Composer 只发出 `new_task` 意图，Sidebar 只在收到历史数据时显示列表，为 M6 保留输入边界但不展示伪历史或伪 follow-up。
- 自动滚动仅在用户已接近底部时跟随；窄屏 Composer 回到文档流，不覆盖 Summary。

## 3. 验证结果

| 检查 | 结果 |
|---|---|
| 后端全量 pytest | 254 passed, 1 个既有 Starlette/httpx 弃用 warning |
| M5 后端针对性 | 6 passed：历史淘汰、API 前后终态、失败、shutdown、发布拒绝、显式边界 |
| 前端 Vitest | 4 files / 20 tests passed；含 600 事件、乱序/重复、跨 Task key、六工具、严格 parser、存储迁移 |
| 类型与构建 | `vue-tsc --noEmit` 通过；Vite 33 modules，JS 93.60 kB，CSS 14.28 kB |
| Ruff | 全项目 lint 与 format check 通过（禁用共享缓存） |
| 浏览器 smoke | failed/running/completed、附件、刷新、410/404/204、键盘 focus、390px 无溢出全部通过 |
| 视觉检查 | 桌面/390px 截图已检查；移动端 Composer 遮挡问题在验收中发现并修复 |
| 对比度目标 | 抽查主要前景/背景组合为 5.99–14.97:1，满足普通文本 AA 目标 |
| 真实模型 M4 回归 | 新的 3/3；平均 12.240 s，每轮 Agent 与独立 pytest 均为 2 passed，Summary 事实检查全部通过 |

浏览器截图和真实模型报告位于 Git 忽略的 `output/qa/m5-framework-*.png` 与 `output/m5-real-demo.json`。报告不保存 API Key、Base URL 或模型名。

## 4. 当前边界

- 后端 Task/Event 仍在内存中，重启后不可恢复；404 会明确提示。这不是 M6 JSON 历史。
- M5 页面一次只组合 0 或 1 个 TaskRun；数据结构可组合多个 run，但 API 尚无 Session/follow-up。
- Browser 完成态用确定性 API/SSE fixture 验收呈现语义；真实供应商可靠性由独立 M4 三轮验收器验证，两类证据不混用。
- Raw Event 抽屉、更多测试框架识别与动画细化属于 P1，不阻塞 M6。
