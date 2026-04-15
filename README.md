# 🤖 My Agent — Autonomous AI Coding Agent v3

一个功能完整的命令行自治 AI Agent，支持多 Agent 协作、工作图任务管理、定时调度、错误恢复等企业级特性。基于 OpenAI 兼容 API，支持智谱清言、百炼千问、OpenAI 等多种 LLM 后端。

## ✨ 核心特性

### 基础能力
- 🤖 **多模型支持** — 智谱 GLM、通义千问、OpenAI GPT，一键切换
- 📂 **文件操作** — 读取、写入、搜索代码，完整的项目感知能力
- 💻 **命令执行** — 运行测试、安装依赖、Git 操作
- 🧠 **跨会话记忆** — 记住你的偏好和上下文，重启后依然了解你
- 💾 **对话管理** — 保存/加载对话历史，随时继续未完成的工作
- 🔒 **权限控制** — 安全的执行沙箱，写操作需用户确认
- 📉 **上下文压缩** — 自动管理对话长度，支持微压缩 + LLM 摘要
- 🎯 **流式输出** — 实时流式响应，打字机般的交互体验

### v3 新特性

- 🔄 **自动错误恢复 (s11)** — 速率限制自动重试、超时重试、上下文溢出自动压缩，内置 Recovery Budget 预算管理
- 📋 **工作图任务 (s12)** — DAG 依赖任务图，支持 `blockedBy` 自动阻塞/解锁，`TaskCreate` / `TaskComplete` / `TaskFail` 全生命周期管理
- ⚡ **后台任务 (s13)** — `BackgroundRun` 异步执行长命令，实时查询状态和输出，不阻塞 REPL
- ⏰ **Cron 定时调度 (s14)** — 自然语言或 cron 表达式创建定时任务，后台自动触发，支持启用/禁用
- 👥 **多 Agent 协作 (s15-s17)** — Boss/Worker 架构，持久化名册，独立线程 + 独立上下文，原子任务认领
- 📬 **收件箱系统** — 结构化消息通道，Boss ↔ Worker 实时通信，JSONL 持久化
- 📜 **协作协议 (s16)** — `ProtocolEnvelope` 结构化信封，任务分配/审批/关机协议，带 `request_id` 的状态追踪

## 🚀 快速开始

### 1. 创建虚拟环境（推荐 Python 3.12+）

```bash
# 使用 Python 3.12 创建虚拟环境
py -3.12 -m venv venv

# 激活
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

依赖非常精简：
- `openai>=1.0.0` — LLM API 调用
- `python-dotenv>=1.0.0` — 环境变量加载

### 2. 配置 API Key

在项目目录创建 `.env` 文件（参考 `.env.example`）：

```env
# 百炼千问 (Qwen / Dashscope)
QWEN_API_KEY=sk-your-key-here

# 智谱清言 (GLM / Zhipu)
ZHIPU_API_KEY=your-key-here

# OpenAI
OPENAI_API_KEY=sk-your-key-here

# 默认模型
AGENT_MODEL=qwen-plus
```

### 3. 启动

```bash
python main.py
```

启动后你会看到：

```
╔══════════════════════════════════════════╗
║     My Agent - Autonomous Agent v3       ║
╚══════════════════════════════════════════╝
  Model: qwen-plus
  Provider: qwen
  Working directory: /your/project
  Permission: normal
  Subsystems: Recovery(s11) ✓ | WorkGraph(s12) ✓ | Background(s13) ✓ | Scheduler(s14) ✓ | Team(s15-s17) ✓

  Type your message, or /help for commands.
```

### 4. 命令行参数

```bash
python main.py --model glm-4-plus          # 指定模型
python main.py --cwd /path/to/project      # 指定工作目录
python main.py --accept-all                # 自动批准所有工具调用
python main.py --provider zhipu            # 指定 Provider
```

## 🛠️ 内置工具（28 个）

### 文件操作

| 工具 | 说明 | 权限 |
|------|------|------|
| **Read** | 读取文件内容 | 只读，自动放行 |
| **Write** | 写入文件（自动创建目录） | 需确认 |
| **Glob** | 按 Glob 模式列出文件 | 只读，自动放行 |
| **Grep** | 正则搜索文件内容 | 只读，自动放行 |

### 命令执行

| 工具 | 说明 | 权限 |
|------|------|------|
| **Bash** | 执行 Shell 命令 | 安全命令自动放行，其余需确认 |
| **BackgroundRun** | 后台异步执行长命令 | 需确认 |
| **BackgroundStatus** | 查询后台任务状态 | 只读 |
| **BackgroundOutput** | 获取后台任务输出 | 只读 |

### 任务管理 (s12)

| 工具 | 说明 |
|------|------|
| **TaskCreate** | 创建任务（支持 `blockedBy` 依赖链） |
| **TaskInfo** | 查看任务详情 |
| **TaskList** | 列出所有任务 |
| **TaskComplete** | 完成任务（自动解锁下游依赖） |
| **TaskFail** | 标记任务失败 |

### 定时调度 (s14)

| 工具 | 说明 |
|------|------|
| **ScheduleCreate** | 创建 Cron 定时任务 |
| **ScheduleList** | 列出所有定时任务 |
| **ScheduleInfo** | 查看定时任务详情 |
| **ScheduleToggle** | 启用/禁用定时任务 |
| **ScheduleDelete** | 删除定时任务 |

### 团队协作 (s15-s17)

| 工具 | 说明 |
|------|------|
| **TeamSpawn** | 创建并启动一个 Worker 队友 |
| **TeamList** | 列出团队成员及状态 |
| **TeamShutdown** | 关闭指定或所有队友 |
| **SendMessage** | 向指定队友发送消息 |
| **Broadcast** | 向所有队友广播消息 |
| **AssignTask** | 将任务分配给指定队友 |

### 记忆

| 工具 | 说明 | 权限 |
|------|------|------|
| **MemorySave** | 保存用户偏好到长期记忆 | 需确认 |
| **MemoryLoad** | 加载所有已保存的记忆 | 只读 |
| **MemoryDelete** | 删除一条记忆 | 需确认 |

## 🔄 自动错误恢复 (s11)

Agent 内置三层恢复机制，自动处理 LLM 调用中的常见错误：

| 错误类型 | 恢复策略 | 最大重试 |
|----------|---------|---------|
| 速率限制 (429) | 指数退避重试 | 3 次 |
| 超时 | 延迟重试 | 2 次 |
| 上下文溢出 | 自动压缩上下文 | 1 次 |
| 服务器错误 (5xx) | 延迟重试 | 2 次 |
| 其他错误 | 中止并报告 | 0 次 |

每个 Agent turn 有独立的 `RecoveryBudget`，防止无限重试。

## 📋 工作图任务 (s12)

支持 DAG 依赖的任务管理系统：

```
Task A (初始化项目)
    ↓
Task B (编写核心模块)  ← blockedBy: [A]
    ↓
Task C (编写测试)      ← blockedBy: [B]
```

- 自动阻塞：被依赖的任务未完成时，下游任务不可执行
- 自动解锁：上游任务 `TaskComplete` 后，下游自动变为 `ready`
- 原子认领：多 Agent 环境下，`claim_task()` 使用线程锁保证原子性
- 持久化：任务保存在 `.tasks/` 目录，重启后不丢失

## ⚡ 后台任务 (s13)

```python
# LLM 可以这样使用:
BackgroundRun(command="npm test", description="运行测试套件")  # 立即返回
BackgroundStatus(id="rt_xxx")      # 查看状态: running/completed/failed
BackgroundOutput(id="rt_xxx")      # 获取输出
```

后台任务独立运行，不阻塞 REPL。适合长时间运行的测试、构建、数据处理等。

## ⏰ Cron 定时调度 (s14)

```python
# 每 5 分钟检查一次测试
ScheduleCreate(cron="*/5 * * * *", prompt="运行测试并报告结果")

# 每天早上 9 点总结
ScheduleCreate(cron="0 9 * * *", prompt="总结昨天的代码变更")
```

调度器后台运行，到时间自动将 prompt 注入 Agent。

## 👥 多 Agent 协作 (s15-s17)

### 架构

```
┌──────────────────────────────────────────────┐
│                    Boss Agent                  │
│  (主 REPL 循环，接收用户输入，分配任务)          │
└──────────┬──────────────┬─────────────────────┘
           │              │
    ┌──────▼──────┐ ┌─────▼───────┐
    │  Worker-1   │ │  Worker-2   │
    │  (Coder)    │ │ (Reviewer)  │
    │  独立线程    │ │  独立线程    │
    │  独立上下文  │ │  独立上下文  │
    │  独立 inbox  │ │  独立 inbox  │
    └─────────────┘ └─────────────┘
```

### 核心设计

- **每个 Agent 有独立的 `messages` 数组** — 严禁共享上下文
- **每个 Agent 有独立的 JSONL inbox** — 文件级消息通道
- **原子认领** — `claim_task()` 线程锁保护，防止重复认领
- **身份注入** — 每次 LLM 调用动态注入 System Prompt，防止失忆
- **WORK/IDLE 两态循环** — IDLE 排空 inbox + 扫描任务板认领；WORK 执行任务直到完成

### 协作协议 (s16)

高危操作通过结构化协议执行：

| 协议类型 | 说明 |
|----------|------|
| `task_assign` | 任务分配，带 `request_id` 追踪 |
| `plan_approval` | 计划审批，需 Boss 确认 |
| `shutdown` | 优雅关机，通知目标 Agent 停止 |

所有协议落地到 `.team/requests/` 目录，可审计追溯。

### 使用方式

```
» /team-init              # 启动 worker-1 (Coder) + worker-2 (Reviewer)
» /team                   # 查看团队状态
» /team-stop              # 关闭所有队友

# 或通过 LLM 工具调用:
» 帮我创建两个 worker，一个写代码，一个做 code review
» 把 task_xxx 分配给 worker-1
» 通知所有成员：项目结构已更新
```

## 📝 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/exit`, `/quit` | 退出（自动保存对话） |
| `/clear` | 清空当前对话 |
| `/status` | 查看当前状态（模型、token 用量等） |
| `/model <name>` | 切换模型 |
| `/cwd <path>` | 切换工作目录 |
| `/accept-all` | 切换到自动批准模式 |
| `/normal` | 切换回正常权限模式 |
| `/save [name]` | 保存当前对话 |
| `/load <name>` | 加载已保存的对话 |
| `/sessions` | 列出所有已保存的对话 |
| `/delete-session <name>` | 删除对话 |
| `/memory` | 查看已保存的用户偏好 |
| `/tasks` | 列出工作图任务 |
| `/bg` | 列出后台运行任务 |
| `/schedules`, `/cron` | 列出 Cron 定时任务 |
| `/inbox` | 查看收件箱消息 |
| `/team` | 查看团队成员和状态 |
| `/team-init` | 初始化默认团队 (2 Workers) |
| `/team-stop` | 关闭所有队友 |

## 🔒 权限控制

采用三层安全管道：

1. **accept-all 模式** — 全部自动放行（`/accept-all` 或 `-a` 参数）
2. **白名单放行** — 只读工具（Read、Glob、Grep、MemoryLoad）自动放行
3. **安全命令前缀** — `ls`、`git status`、`python`、`pip` 等安全命令自动放行
4. **用户确认** — 其余操作（写入文件、执行命令等）需用户手动确认

## 🏗️ 项目结构

```
my_agent/
├── main.py          # CLI 入口 + REPL 循环 + 斜杠命令
├── agent.py         # 核心 Agent Loop（系统心脏）
├── providers.py     # LLM 提供者适配（OpenAI 兼容 API）
├── tools.py         # 工具注册表 + 28 个工具实现
├── config.py        # 配置加载与持久化
├── context.py       # System Prompt 动态构建
├── compact.py       # 上下文压缩（微压缩 + LLM 摘要）
├── memory.py        # 跨会话记忆
├── session.py       # 对话历史保存与加载
├── permissions.py   # 权限控制
├── recovery.py      # 自动错误恢复 (s11)
├── tasks.py         # 工作图任务管理 (s12)
├── inbox.py         # 收件箱消息系统
├── team.py          # 多 Agent 名册 + 协作协议 (s15-s16)
├── teammate.py      # Worker 自治认领循环 (s17)
├── requirements.txt # 依赖
├── .env.example     # 环境变量模板
└── test_v3_team.py  # 多 Agent 离线测试 (47 tests)
```

### 系统架构

```
用户输入
  │
  ▼
┌─────────────────────────────────────────────┐
│          Agent Loop (agent.py)               │
│                                             │
│  1. 追加用户消息                             │
│  2. 上下文压缩 (compact.py)                  │
│  3. 构建 System Prompt (context.py)          │
│  4. 调用 LLM (providers.py)                  │
│  5. 错误恢复 (recovery.py, s11)              │
│  6. 解析输出                                 │
│  7. 执行工具 (tools.py)                      │
│     ├─ 权限检查 (permissions.py)             │
│     ├─ 后台任务 (BackgroundRun, s13)         │
│     ├─ 工作图任务 (TaskCreate..., s12)        │
│     └─ 团队工具 (TeamSpawn..., s15)          │
│  8. 收件箱通知 (inbox.py)                    │
│  9. Cron 调度检查 (s14)                      │
│  10. 循环或结束                              │
│                                             │
└─────────────────────────────────────────────┘
  │
  ▼
流式输出事件（TextChunk / ToolStart / ToolEnd / TurnDone / RecoveryEvent / InboxDrainEvent）
```

### 多 Agent 架构

```
Worker Loop (teammate.py)
  │
  ├─ IDLE 状态:
  │   1. 排空 JSONL inbox (team.py)
  │   2. 扫描任务板 (.tasks/)
  │   3. claim_task() 原子认领
  │   4. 认领成功 → WORK 状态
  │
  ├─ WORK 状态:
  │   1. 排空 inbox（可能收到关机协议）
  │   2. 调用 LLM 执行任务
  │   3. 执行工具（Read/Write/Bash...）
  │   4. TaskComplete → 通知 Boss → 回到 IDLE
  │
  └─ 通信通道:
      Boss → Worker: send_to_teammate() → inbox_worker-1.jsonl
      Worker → Boss: send_to_teammate() → inbox_boss.jsonl
      协议: ProtocolEnvelope (带 request_id) → .team/requests/
```

## ⚙️ 支持的模型

| Provider | 模型 | 环境变量 | API 地址 |
|----------|------|---------|---------|
| 智谱清言 | glm-4-plus, glm-4, glm-4-flash | `ZHIPU_API_KEY` | open.bigmodel.cn |
| 百炼千问 | qwen-plus, qwen-max, qwen-turbo | `QWEN_API_KEY` | dashscope.aliyuncs.com |
| OpenAI | gpt-4o, gpt-4 | `OPENAI_API_KEY` | api.openai.com |

模型名会自动推断 Provider（如 `glm-` 前缀 → 智谱，`qwen-` → 千问，`gpt-` → OpenAI）。

## ⚙️ 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_MODEL` | `qwen-plus` | 默认模型 |
| `AGENT_PROVIDER` | 自动推断 | 显式指定 Provider |
| `AGENT_PERMISSION` | `normal` | 权限模式：`normal` / `accept-all` |
| `AGENT_MAX_TOKENS` | `4096` | 最大输出 token 数 |
| `AGENT_TEMPERATURE` | `0.7` | 生成温度 |
| `QWEN_API_KEY` | — | 百炼千问 API Key |
| `ZHIPU_API_KEY` | — | 智谱清言 API Key |
| `OPENAI_API_KEY` | — | OpenAI API Key |

## 📂 数据存储

```
~/.my_agent/
├── memory.json          # 用户偏好记忆
├── config.json          # 配置持久化
├── .env                 # 全局环境变量
└── sessions/            # 对话历史

<project>/
├── .tasks/              # 工作图任务 (s12)
├── .team/               # 团队配置 (s15)
│   ├── config.json      #   名册
│   ├── inbox_*.jsonl    #   队友 inbox
│   └── requests/        #   协议审批记录 (s16)
└── .runtime/            # 后台任务运行时 (s13)
```

## 🧪 测试

```bash
# 多 Agent 架构离线测试（不需要 API Key，47 个测试用例）
python test_v3_team.py

# 导入测试
python test_v3_imports.py

# 工具离线功能测试
python test_v3_tools_offline.py
```

## 📄 License

MIT
