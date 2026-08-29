# Coding Agent M7 最终交付计划

> 阶段名称：M7 — 最终复验、文档、录屏、安全检查与提交
>
> 建议周期：1 个完整工作日；当前总计划建议为 2026-09-07
>
> 前置条件：M5 与 M6 的全部 P0 退出标准已通过，不存在待交付阶段补做的 JSON format、原子持久化、API、上下文或 UI 实现
>
> 目标：基于同一个候选提交完成可复现、无密钥、材料一致的最终交付，不在录屏后继续改变产品行为。

## 1. 范围与原则

M7 只做交付收口：

- 冻结候选版本；
- 在干净环境复验后端、前端、API、浏览器、重启、多轮与真实模型 Demo；
- 更新开发 README.md 和 1000 汉字以内的正式 `README.txt`；
- 录制不超过 2 分钟、200 MB 的 MP4；
- 扫描仓库、Git 历史可见范围、日志、历史 JSON 样例、报告和视频画面中的敏感信息；
- 核对远程仓库、提交、压缩包与材料命名；
- 形成最终 Go/No-Go 记录。

M7 不实现产品功能。以下缺口一旦发现必须退回相应里程碑：

- M5：TaskRun/Activity/Summary、响应式或无障碍缺口；
- M6：JSON format migration、原子写/锁、历史持久化、follow-up、预算、重启收敛、删除、保留或资源关闭缺口；
- M1–M4：工具、Agent Loop、SSE 或真实 Demo 回归。

不得为了赶交付在 M7 关闭失败测试、跳过重启步骤、手改历史 JSON、剪掉失败过程后声称成功，或把真实密钥写入录屏配置。

## 2. 进入条件

开始 M7 前必须满足：

- [ ] M5 与 M6 P0 清单全部完成并有自动化证据；
- [ ] 工作树中的预期代码和文档均已审查，无来源不明的生成物；
- [ ] JSON HistoryRepository 能从空目录初始化，并能迁移/读取上一 format fixture；
- [ ] 正常重启保留历史，在途 Task 重启后收敛为 `SERVER_RESTARTED`；
- [ ] follow-up 通过有界 TaskRecap 接入 M2 总预算；
- [ ] M4 独立三轮 3/3 与 M6 多轮 smoke 已经通过；
- [ ] 没有已知 P0/P1 缺陷被错误标成“以后再说”；
- [ ] 已确认最终仓库地址、提交截止时间、提交者姓名和压缩包命名规则；
- [ ] 已获得真实模型调用与产生少量费用的授权。

若外部截止仍是原 09-02，应先由用户确认缩减范围或延期。不能把仅存在计划文档的 M5/M6 写成已实现。

当前预检已发现根目录 `.env.example` 中的 `CODING_AGENT_API_KEY` 疑似不是占位值。该文件目前被忽略、未被 Git 跟踪且未发现进入当前可见历史，但仍必须在交付前恢复为占位符并轮换密钥；检查过程不得输出原值。

## 3. 候选版本冻结

1. 记录候选 commit SHA、分支、Python/Node 版本和验证日期；
2. `git status` 区分预期修改、未跟踪材料和用户原有改动；
3. 生成最终测试/报告后只允许修正文档、材料或阻塞缺陷；
4. 任一代码修复都会使旧测试报告和视频失效，必须重新执行受影响矩阵；
5. 视频、README.txt、压缩包必须指向同一最终 commit；
6. 不执行未经用户授权的 push、公开仓库设置或发布动作。

## 4. 最终复验矩阵

### 4.1 确定性自动化

- 后端全量 pytest；
- Ruff lint/format check；
- 前端 Vitest、`vue-tsc --noEmit`、production build；
- browser smoke 覆盖 idle、running、completed、failed、410、refresh、窄屏；
- M6 JSON repository/format migration/atomic replace/lock/restart/retention/context/delete 故障注入测试；
- 依赖一致性检查，例如 `pip check` 与 lockfile 安装验证；
- 测试输出记录真实数量、耗时、warning 和失败，不沿用旧阶段数字。

### 4.2 干净启动与升级

至少验证两种隔离的历史目录：

1. 全新空 `.coding-agent/history`：启动、创建会话、完成 Task、follow-up、重启、读取、删除；
2. 上一 format fixture：备份、CURRENT 切换、迁移、读取历史、follow-up、重启。

不得使用开发者长期历史目录作为唯一验收源。测试 history_dir 与真实 `.coding-agent/history` 分离；任何清理命令都只针对已解析并确认的专用临时目录。

### 4.3 真实模型

- 重跑 M4 固定 Demo 三轮，每轮恢复同一失败基线，Agent 与独立 pytest 都通过；
- 跑一组 M6 最小多轮 smoke：首轮代码任务、承接 follow-up、服务重启、只读 follow-up；
- 记录模型标识、成功率、步数、工具次数、耗时、错误码和费用可见信息；
- 报告不保存 API Key、Authorization 或供应商 raw response；
- 若真实供应商不可用，M7 为 No-Go，不以 Fake LLM 替代真实验收，但可用 Fake LLM 定位本地问题。

## 5. README.txt

正式 `README.txt` 不超过 1000 汉字，并至少包含：

- 项目名称和一句话能力；
- 公开/最终仓库地址和对应 commit/tag；
- Python、Node 和系统前提；
- 最短安装、配置、启动命令；
- 模型环境变量只写变量名，不写真实值；
- 如何创建新会话、follow-up、恢复和删除历史；
- 本地历史存储与 Workspace/安全边界；
- 最短测试命令；
- 已知限制：本地单用户、全局单活动 Task、受限命令、非强沙箱；
- 视频文件名。

开发 README.md 可以更详细，但两份 README 的端口、命令、能力、限制、测试数字和里程碑状态必须一致。不得把计划、可选项或未执行的浏览器测试写成已完成。

## 6. 录屏脚本

### 6.1 录制前

- 使用专用 Demo Workspace 和专用临时数据目录；
- 终端、浏览器、编辑器和系统通知中不显示密钥、用户名敏感路径或无关项目；
- 清理浏览器自动填充、历史建议和开发者工具敏感请求头；
- 预先验证网络、模型额度、字体、缩放、窗口尺寸和音频；
- 准备可重复失败基线，不在镜头外手工修复代码；
- 显示的历史会话全部使用无敏感内容的演示数据。

### 6.2 建议 2 分钟叙事

```text
00:00–00:15  项目启动、Agent Ready、Workspace 与历史恢复
00:15–00:35  新建会话并提交固定 Bug 任务
00:35–01:15  展示模型决策、工具 Activity、真实 Diff、pytest 与 Summary
01:15–01:35  在同一 Session follow-up，展示多 TaskRun 和承接上下文
01:35–01:50  刷新/重启后历史仍在，说明在途任务不会自动重放
01:50–02:00  展示最终测试通过、仓库地址与安全边界
```

若真实运行超过 2 分钟，可做连续剪辑并用明确转场压缩等待，但不能改变事件顺序、隐藏失败或把不同候选 commit 的片段拼成一次执行。

### 6.3 视频验收

- MP4 可在常见播放器完整播放；
- 时长 ≤ 2 分钟，大小 ≤ 200 MB；
- 文字在 1080p 下可读，关键状态不只靠颜色；
- 没有密钥、Authorization、`.env` 内容、真实敏感路径或通知；
- 展示的功能与最终 commit 一致；
- 文件名满足提交要求。

## 7. 安全与隐私扫描

扫描范围：

- tracked/untracked 文件；
- 可见 Git 历史和 diff；
- `.env*`、日志、pytest 输出、M4/M6 报告；
- 演示 History JSON、backups、trash、quarantine 和残留临时文件；
- 浏览器网络/控制台截图；
- 视频逐段画面与音轨；
- README.txt、压缩包清单和文件元数据。

规则：

- `.env.example` 只能包含占位符，不能包含可用 token；若用户曾把真实值放入该文件，立即从工作树和交付材料移除并轮换密钥；
- 使用 canary/模式扫描加人工复核，不能只搜索一个供应商前缀；
- Prompt 是持久会话正文，若演示时误输入秘密，应删除 Session、清理相应备份/演示历史并轮换秘密；
- 发现密钥进入 Git 历史时停止交付，由用户决定历史清理和远程处置；不得只删除最新文件后继续；
- 扫描报告保存规则和结论，不回显完整疑似密钥。

## 8. 仓库与压缩包

- 核对最终分支、commit SHA、tag（若要求）、远程地址和公开可访问性；
- 检查 Git/压缩包不含 `.env`、`.coding-agent` 用户历史、日志、node_modules、虚拟环境、测试缓存、临时 Workspace 或超大构建产物；
- README 链接、相对路径和命令在仓库克隆后仍有效；
- 压缩包只包含要求的 `README.txt`、MP4 和明确要求的其他材料；
- 压缩包按姓名/要求命名，解压后无多余嵌套层级和隐藏敏感文件；
- 计算并记录最终文件大小与 SHA-256，重新解压检查一次；
- push、改远程可见性、创建 release 等外部状态变更必须在用户授权后执行。

## 9. M7 执行顺序

### Phase 0：冻结与预检

- 确认进入条件、候选 SHA、真实调用授权和最终命名；
- 运行快速 lint/typecheck 与密钥预扫描；
- 若失败，立即退回相应里程碑。

### Phase 1：完整验证

- 确定性测试、构建、浏览器 smoke；
- 空历史目录/旧 format fixture/restart/delete；
- M4 3/3 和 M6 多轮真实 smoke；
- 记录一份脱敏最终验证报告。

### Phase 2：文档与录屏

- 更新 README.md 和 README.txt；
- 按固定脚本录屏；
- 检查视频真实性、可读性、时长和大小。

### Phase 3：最终安全检查

- 对冻结后的仓库、Git 历史、History JSON、报告、视频和材料重新扫描；
- 检查 `.gitignore` 与压缩包内容；
- 任何代码或配置修复后回到 Phase 1 的受影响部分。

### Phase 4：提交与归档

- 生成最终 commit/tag（若需要）；
- 经用户授权后 push/发布；
- 重新核对远程 SHA；
- 创建、解压验证并校验压缩包；
- 保存 Go/No-Go 结论、测试摘要和材料 SHA-256。

## 10. M7 Go/No-Go

只有以下条件全部满足才可交付：

- [ ] 候选 commit 与 README.txt、视频、报告一致；
- [ ] 后端、lint、前端单测/类型/构建、browser smoke 全部通过；
- [ ] 空目录、format migration、原子替换/锁、重启收敛、历史恢复、follow-up 和删除通过；
- [ ] M4 真实模型连续 3/3，M6 真实多轮 smoke 通过；
- [ ] M5 Activity/Summary 与 M6 历史 Thread 不伪造执行事实；
- [ ] README.txt ≤ 1000 汉字，命令、仓库地址、限制和历史隐私说明正确；
- [ ] MP4 ≤ 2 分钟且 ≤ 200 MB，可播放、可读、无敏感画面；
- [ ] 工作树、Git 历史可见范围、日志、History JSON 样例、报告、视频和压缩包通过敏感信息检查；
- [ ] Git 与压缩包不含 `.coding-agent` 用户历史、`.env`、缓存或临时工作区；
- [ ] 最终远程 SHA（若已授权发布）与材料记录一致；
- [ ] 压缩包命名和内容正确，已重新解压检查；
- [ ] 没有把 M5/M6 P0 缺口作为“交付后修复”。

任一项失败即为 No-Go。记录失败原因并退回对应阶段，修复后更新候选 SHA、重新复验和重新录制受影响材料。

## 11. 建议交付记录

最终保留一份不含秘密的记录：

```text
candidate_commit:
repository_url:
verification_date:
backend_tests:
frontend_tests:
browser_smoke:
m4_real_model:
m6_multiturn:
json_format_atomic_restart_delete:
secret_scan:
readme_txt_chars:
video_duration_and_size:
archive_sha256:
known_limitations:
go_no_go:
```

该记录只描述证据，不复制完整命令输出、Prompt、History JSON 内容或供应商响应。
