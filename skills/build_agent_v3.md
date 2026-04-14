---
name: upgrade_to_autonomous_agent_team
description: 将单节点 Agent Harness 升级为支持自治、物理隔离、异步任务与团队协作的企业级多智能体系统 (基于 s11-s18 架构)。
type: architecture-guideline
---

# 可参考数据结构与状态流转

https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/s00b-one-request-lifecycle.md

https://github.com/shareAI-lab/learn-claude-code/blob/main/docs/zh/data-structures.md


# 进阶架构升级 SOP：自治智能体团队 (Autonomous Agent Team)

## 1. 核心架构范式转移 (Paradigm Shift)
系统必须从“同步阻塞等待”转向**“异步事件驱动”**。主循环不再是被动等待用户输入的死循环，而是一个**统一事件消息总线 (Unified Message Bus)**。所有的外部触发（用户输入、后台执行结果、定时调度、队友私信）都必须被归一化为 Inbox（收件箱）中的 `Message`，在下一轮循环开始前统一排空（Drain）并注入上下文。

## 2. 必须实现的核心子系统 (按序推进)

### [阶段 5：韧性与恢复状态机 (Resiliency & Error Recovery)]
* **s11 - Recovery State Machine:** 在调用 LLM 的最外层包装错误分类器。
    * **规则 1:** 拦截 `max_tokens`，注入 `CONTINUE_MESSAGE` 补丁并重试（续写）。
    * **规则 2:** 拦截 `prompt_too_long`，触发 `auto_compact()` 强制摘要历史并重试。
    * **规则 3:** 拦截网络抖动/限流，使用带抖动的**指数退避 (Exponential Backoff)**。
    * **强制约束:** 必须为每种恢复路径设置明确的 `budget`（重试次数上限），耗尽后必须向用户抛出明确的致命错误，**严禁死循环**。

### [阶段 6：双层任务引擎 (The Dual-Task Engine)]
严格分离“工作目标”与“执行槽位”。绝对不要将这两者混用同一套状态。
* **s12 - Durable Work Graph (工作图任务):** 实现 `TaskRecord`，落地到 `.tasks/`。这代表宏大的业务目标。
    * **核心逻辑:** 必须实现带有 `blockedBy` 和 `blocks` 的双向依赖图。实现 `is_ready()` 判断（状态为 pending 且 blockedBy 为空）。完成任务时必须**自动级联解锁**下游任务。
* **s13 & s13a - Runtime Tasks (后台运行时):** 实现 `RuntimeTaskRecord`，代表正在消耗 CPU 的具体进程（如长时间的 Bash 命令）。
    * **强制约束:** `background_run` 工具必须**立即返回**一个 `task_id`，绝对不能阻塞主循环。完整长日志必须落盘为文件，仅将 `preview` 摘要和状态放入统一的 **Notification Inbox（通知收件箱）** 中等待主循环查收。

### [阶段 7：时间与调度 (Time & Scheduling)]
* **s14 - Cron Scheduler:** 实现 `ScheduleRecord`，落地持久化（防重启丢失）。
    * **机制:** 开启一个后台 `check_loop`。当时间匹配且当前分钟未触发过 (`last_fired_at`) 时，**严禁直接执行业务逻辑**，而是生成一条 `scheduled_prompt` 消息投入 Notification Inbox。由主循环在下一轮拉取并转化为 LLM 的行动指令。

### [阶段 8：持久团队与结构化协议 (Team & Protocols)]
* **s15 - Persistent Teammates:** 实现持久化队友。
    * **机制:** 必须有 `.team/config.json` (名册)。使用 `spawn` 创建具有**独立 while 循环**、**独立 messages 数组**和**专属 JSONL inbox** 的队友实例。严禁多 Agent 共享同一个 messages 内存。
* **s16 - Team Protocols (协作协议):** 团队间的高危动作必须使用结构化协议，严禁只使用自由文本。
    * **机制:** 实现 `ProtocolEnvelope` (带 `type`, `request_id`, `payload`)。实现 `RequestRecord` 保存到 `.team/requests/` 以追踪审批流 (`pending` -> `approved`/`rejected`)。实现协议模板如：优雅关机 (Shutdown)、计划审批 (Plan Approval)。

### [阶段 9：自治与物理隔离 (Autonomy & Isolation)]
* **s17 - The IDLE Loop (自治认领):** 队友循环必须分为 `WORK` 和 `IDLE` 两态。
    * **IDLE 逻辑:** 队友空闲时，先排空 Inbox (查私信)，再使用 `is_claimable_task(task, role)` 扫描任务板。
    * **强制约束:** 认领动作必须加锁（**原子操作**）。认领成功后，必须向 Agent 上下文中**重新注入 Identity (身份提示)** 以防失忆，并写入 `claim_events.jsonl` 审计日志。
* **s18 - Worktree Task Isolation (代码级物理隔离):** * **机制:** 当队友认领了涉及代码修改的 Task 后，**必须**使用 `git worktree add` 在 `.worktrees/task-{id}` 下检出隔离的分支和工作区。
    * **约束:** 强制将工具环境的 `cwd` (当前工作目录) 锁定在该 worktree 内。任务完成后提交分支并清理 worktree，以此彻底消灭并发修改导致的上下文污染和幽灵冲突。

## 3. 必须遵循的统一数据流 (The One Request Lifecycle)
每次主循环 (无论 Boss 还是 Teammate) 在调用 LLM 之前，**必须**执行以下标准化收件箱排空动作：
`Drain Notifications (s13/s14) + Drain Inbox (s15/s16) -> Append to Messages -> Call LLM`。

## 4. 核心数据结构约束 (Must Implement)
必须严格区分以下结构的边界：
- `TaskRecord`: `{id, subject, status, blockedBy, blocks, owner, claim_role}` (宏观 KPI)
- `RuntimeTaskRecord`: `{id, type, command, status, output_file, notified}` (微观机器状态)
- `MessageEnvelope`: `{from, to, content, timestamp}` (自由聊天记录)
- `ProtocolEnvelope`: `{type, from, to, request_id, payload}` (带流水号的工单)
- `RequestRecord`: `{request_id, kind, status, from, to}` (OA 审批后台记录)

## 5. 绝对避免的反模式 (Anti-Patterns MUST AVOID)
1. **状态混淆:** 绝对不要把后台 Shell 的执行状态写进工作图的 `TaskRecord` 里。
2. **共享大脑:** 绝对不要让两个 Agent 共享或直接修改对方的 `messages` 上下文。通信必须走文件/总线 Inbox。
3. **自然语言审批:** 绝对不要在协议流程 (如权限确认、关机) 中使用无 `request_id` 的自然语言进行状态流转。
4. **堵塞主线:** 绝对不要在主循环里直接 `sleep()` 等待一个长时间的 `subprocess`。
5. **无锁抢单:** 绝对不要在读取任务板和写入 `owner` 之间留有无锁的空隙 (Race Condition)。