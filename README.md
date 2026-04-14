# My Agent — 个人 AI 编程助手

一个轻量级的命令行 AI Agent，具备文件读写、代码搜索、命令执行和跨会话记忆能力。基于 OpenAI 兼容 API，支持智谱清言、百炼千问、OpenAI 等多种 LLM 后端。

## ✨ 特性

- 🤖 **多模型支持** — 智谱 GLM、通义千问、OpenAI GPT，一键切换
- 📂 **文件操作** — 读取、写入、搜索代码，完整的项目感知能力
- 💻 **命令执行** — 运行测试、安装依赖、Git 操作
- 🧠 **跨会话记忆** — 记住你的偏好和上下文，重启后依然了解你
- 💾 **对话管理** — 保存/加载对话历史，随时继续未完成的工作
- 🔒 **权限控制** — 安全的执行沙箱，写操作需用户确认
- 📉 **上下文压缩** — 自动管理对话长度，支持微压缩 + LLM 摘要
- 🎯 **流式输出** — 实时流式响应，打字机般的交互体验

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖非常精简：
- `openai>=1.0.0` — LLM API 调用
- `python-dotenv>=1.0.0` — 环境变量加载

### 2. 配置 API Key

在项目目录创建 `.env` 文件：

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
║        My Agent - Code Assistant         ║
╚══════════════════════════════════════════╝
  Model: qwen-plus
  Provider: qwen
  Working directory: /your/project
  Permission: normal

  Type your message, or /help for commands.
```

### 4. 命令行参数

```bash
python main.py --model glm-4-plus          # 指定模型
python main.py --cwd /path/to/project      # 指定工作目录
python main.py --accept-all                # 自动批准所有工具调用
python main.py --provider zhipu            # 指定 Provider
```

## 🛠️ 内置工具

| 工具 | 说明 | 权限 |
|------|------|------|
| **Read** | 读取文件内容 | 只读，自动放行 |
| **Write** | 写入文件（自动创建目录） | 需确认 |
| **Bash** | 执行 Shell 命令 | 安全命令自动放行，其余需确认 |
| **Glob** | 按 Glob 模式列出文件 | 只读，自动放行 |
| **Grep** | 正则搜索文件内容 | 只读，自动放行 |
| **MemorySave** | 保存用户偏好到长期记忆 | 需确认 |
| **MemoryLoad** | 加载所有已保存的记忆 | 只读，自动放行 |
| **MemoryDelete** | 删除一条记忆 | 需确认 |

## 🔒 权限控制

采用三层安全管道：

1. **accept-all 模式** — 全部自动放行（`/accept-all` 或 `-a` 参数）
2. **白名单放行** — 只读工具（Read、Glob、Grep、MemoryLoad）自动放行
3. **安全命令前缀** — `ls`、`git status`、`python`、`pip` 等安全命令自动放行
4. **用户确认** — 其余操作（写入文件、执行命令等）需用户手动确认

## 📝 斜杠命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/exit` | 退出（自动保存对话） |
| `/clear` | 清空当前对话 |
| `/status` | 查看当前状态 |
| `/model <name>` | 切换模型 |
| `/cwd <path>` | 切换工作目录 |
| `/accept-all` | 切换到自动批准模式 |
| `/normal` | 切换回正常权限模式 |
| `/save [name]` | 保存当前对话 |
| `/load <name>` | 加载已保存的对话 |
| `/sessions` | 列出所有已保存的对话 |
| `/delete-session <name>` | 删除对话 |
| `/memory` | 查看已保存的用户偏好 |

## 🧠 跨会话记忆

Agent 会自动记住你的偏好，存储在 `~/.my_agent/memory.json`：

- 编程语言偏好
- 编辑器偏好
- 项目风格
- 其他用户决策

记忆原则：**只保存"人"的信息**（偏好、反馈、决策），不保存代码状态或临时任务。

## 📉 上下文压缩

当对话接近模型上下文窗口限制时，自动触发两级压缩：

1. **微压缩** — 截断旧的 `tool_result`，保留头尾各 500 字符
2. **摘要压缩** — 用 LLM 总结旧历史，保留最近 30% 的消息

支持的模型上下文限制：

| 模型 | 上下文窗口 |
|------|-----------|
| qwen-plus / qwen-turbo | 131,072 |
| qwen-max | 32,768 |
| glm-4 / glm-4-plus / glm-4-flash | 128,000 |
| gpt-4o / gpt-4 | 128,000 |

## 🏗️ 项目结构

```
my_agent/
├── main.py          # CLI 入口，REPL 循环
├── agent.py         # 核心 Agent Loop（系统心脏）
├── providers.py     # LLM 提供者适配（OpenAI 兼容 API）
├── tools.py         # 工具注册表 + 内置工具实现
├── config.py        # 配置加载与持久化
├── context.py       # System Prompt 动态构建
├── compact.py       # 上下文压缩（微压缩 + 摘要）
├── memory.py        # 跨会话记忆
├── session.py       # 对话历史保存与加载
├── permissions.py   # 权限控制
├── requirements.txt # 依赖
└── .env             # API Key 配置（需自行创建）
```

### 核心架构

```
用户输入
  │
  ▼
┌─────────────────────────────────────┐
│          Agent Loop (agent.py)       │
│                                     │
│  1. 追加用户消息                     │
│  2. 上下文压缩 (compact.py)          │
│  3. 构建 System Prompt (context.py)  │
│  4. 调用 LLM (providers.py)          │
│  5. 解析输出                         │
│  6. 执行工具 (tools.py)              │
│     └─ 权限检查 (permissions.py)     │
│  7. 循环或结束                       │
│                                     │
└─────────────────────────────────────┘
  │
  ▼
流式输出事件（TextChunk / ToolStart / ToolEnd / TurnDone）
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

所有数据存储在 `~/.my_agent/` 目录下：

```
~/.my_agent/
├── memory.json          # 用户偏好记忆
├── config.json          # 配置持久化
├── .env                 # 全局环境变量
└── sessions/            # 对话历史
    ├── autosave_20260413_220500.json
    └── ...
```

## License

MIT
