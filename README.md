# 🤖 My Agent — AI Coding Assistant

一个极简的命令行 AI 编程助手 —— **单文件 Agent 循环 + 5 个核心工具 + 流式 REPL**。
默认走 **DeepSeek-V4-Pro**（cixtech 端点，OpenAI 兼容协议），开箱即用。

> 设计哲学：**少即是多**。整个项目 9 个 Python 文件，没有插件系统、没有 MCP、没有 sub-agent —— 只有一个能稳定干活的 Agent 循环。

## ✨ 核心特性

- 🤖 **单一模型** — DeepSeek-V4-Pro（**1M 上下文**），API Key 已内置默认值
- 🔁 **事件驱动循环** — `agent.py` 用 generator 流式发出 `TextEvent / ThinkingEvent / ToolCallEvent / ToolResultEvent`，UI 与执行完全解耦
- 🛡️ **三段式权限管道** — accept-all 模式 → 只读工具白名单 → Bash 安全前缀白名单 → 询问用户
- 🗜️ **两级上下文压缩** — 微压缩（截断旧 tool 结果） + 摘要压缩（LLM 总结旧历史）
- 💾 **会话持久化** — 保存/加载/列出/删除，退出时自动存档到 `~/.my_agent/sessions/`
- 📏 **截断感知** — 输出撞到 `max_tokens` 上限时显式提示用户（不再静默截断）
- 🪟 **Windows 友好** — 启动时自动修复 stdout/stderr 编码为 UTF-8

## 📦 安装

```bash
pip install -r requirements.txt
```

依赖只有两个：`openai` + `python-dotenv`。

## 🔑 API 配置

API Key 已内置默认值，**开箱即用**。如需覆盖，按以下优先级生效：

1. 环境变量 `DEEPSEEK_API_KEY` 或 `AGENT_API_KEY`
2. `.env` 文件（脚本目录 / 工作目录 / `~/.my_agent/.env`）
3. 内置默认值

```bash
# .env 示例
DEEPSEEK_API_KEY=sk-xxxxx
AGENT_MODEL=deepseek-v4-pro           # 可选
AGENT_BASE_URL=https://aihub.cixtech.com/v1   # 可选
AGENT_MAX_TOKENS=16384                # 可选，长文档可调到 32768
AGENT_TEMPERATURE=0.7                 # 可选
AGENT_PERMISSION=normal               # normal | accept-all
```

> 💡 **关于 `AGENT_MAX_TOKENS`**：这是**单次回复**的输出上限，不是上下文窗口。
>
> 默认值演进历史：
> - `4096` (GPT-3.5 时代默认) — 中文长回复经常被截
> - `8192` — 一般够用，但聊嗨/长解释还是会撞墙
> - **`16384` (当前默认)** — 实测可舒适承载万字级回复
>
> 长文档生成 / 大段代码场景可调到 `32768`。中文 1 字 ≈ 1.5–2 token，所以 16384 token ≈ 8000–10000 中文字。

## 🚀 启动

```bash
python main.py
```

### 命令行选项

```bash
python main.py --cwd D:\path\to\project   # 指定工作目录
python main.py --accept-all               # 自动批准所有工具调用
python main.py --model deepseek-v4-pro    # 指定模型
```

## 💬 交互命令

| 命令 | 说明 |
| --- | --- |
| `/help`, `/h` | 显示帮助 |
| `/quit`, `/exit`, `/q` | 退出（自动保存当前对话） |
| `/clear` | 清空当前对话历史 |
| `/status` | 查看模型 / 工作目录 / 消息数 / 轮数 |
| `/save [name]` | 保存对话（不传名字则自动生成） |
| `/load <name>` | 加载历史对话（支持模糊匹配） |
| `/list` | 列出所有已保存对话 |
| `/delete <name>` | 删除一个对话 |
| `/model <name>` | 切换模型 |
| `/accept-all` | 切换为自动放行模式 |
| `/normal` | 切换为询问模式 |
| `/cwd <path>` | 修改工作目录 |

## 🛠️ 内置工具（5 个）

| 工具 | 用途 | 权限 |
| --- | --- | --- |
| `Read` | 读取文件内容 | 自动放行（只读） |
| `Glob` | 按文件名模式查找文件（自动跳过 `.git` / `__pycache__` / `node_modules` 等） | 自动放行（只读） |
| `Grep` | 在源码文件中搜索正则（限定常见代码/文本后缀，最多返回 50 条） | 自动放行（只读） |
| `Write` | 写入/创建文件（自动创建父目录，**覆盖**写入） | 需要确认 |
| `Bash` | 执行 Shell 命令（默认 30s 超时） | 安全前缀自动放行，其他需确认 |

### Bash 安全前缀白名单

以下前缀的命令在 `normal` 模式下也会自动放行：

```
ls dir cat head tail find grep wc
git status / log / diff / branch / show
python python3 node npm pip pipenv poetry
echo which pwd whoami env type
```

> 工具输出超过 32000 字符会自动头尾截断，防止上下文爆炸。

## 🧠 上下文管理

`compact.py` 在每次 LLM 调用前检查 token 使用率：

- **< 70%**：不动
- **≥ 70%**：微压缩 —— 把 6 轮以前的 tool 结果截断为头尾各 500 字符
- **≥ 80%**：摘要压缩 —— 把前 70% 的消息交给 LLM 总结，替换为一对 user/assistant 摘要消息，保留最近 30% 原始对话

### 支持的模型上下文窗口

| 模型 | 窗口 |
| --- | --- |
| `deepseek-v4-pro` | **1,000,000** |
| `deepseek-chat` / `deepseek-reasoner` | 128,000 |
| `qwen-plus` / `qwen-turbo` | 131,072 |
| `qwen-long` | 10,000,000 |
| `qwen-max` | 32,768 |
| `glm-4-*` | 128,000 |
| `gpt-4o` / `gpt-4` | 128,000 |
| `gpt-3.5-turbo` | 16,385 |
| 其它未知模型 | 128,000（默认 fallback） |

模型名支持前缀匹配，例如 `deepseek-v4-pro-20251101` 也会匹配到 1M 窗口。

## 📏 输出截断感知

每次 LLM 调用后，`providers.py` 会检查 `finish_reason`：

- `"stop"` — 正常结束 ✅
- `"tool_calls"` — 转去执行工具 ✅
- `"length"` — **撞到 `max_tokens` 上限被截断** ⚠️

撞到 `length` 时，会在回复末尾追加显式提示：

```
[⚠ Output truncated at max_tokens=16384. Try a larger AGENT_MAX_TOKENS, or ask me to continue.]
```

这样你能立刻发现"为什么 AI 话说一半"，而不是干瞪眼。

## 📁 项目结构

```
Code_Agent/
├── main.py          # REPL 入口、斜杠命令、事件渲染、ANSI 着色
├── agent.py         # Agent 主循环（generator 事件流，最多 30 轮）
├── providers.py     # OpenAI SDK 流式封装 + 消息/工具格式转换 + 截断检测
├── tools.py         # 工具注册表 + 5 个内置工具实现
├── context.py       # System Prompt 构建（注入日期/cwd/平台/git/CLAUDE.md）
├── permissions.py   # 三段式权限管道
├── compact.py       # 两级上下文压缩
├── session.py       # 会话保存/加载/列出/删除
├── config.py        # 配置加载（环境变量 > .env > 内置默认）
├── requirements.txt
├── .env.example
└── README.md
```

## 🔄 Agent 主循环简述

```
用户输入
   ↓
[while iteration < 30]
   maybe_compact()                          # 上下文压缩检查
   build_system_prompt()                    # 注入最新环境信息
   stream_llm() ──► TextEvent / ThinkingEvent  （流式打字机输出）
                  └► AssistantTurn          （含 tool_calls + finish_reason）
   if 没有 tool_calls: → DoneEvent, 退出循环
   for tc in tool_calls:
       check_permission()                   # 自动放行 or 询问用户
       execute_tool()                       # 路由 + 截断
       将 tool 结果追加进 messages
   继续下一轮（让模型基于工具结果继续）
```

## 🪪 项目规则注入

如果工作目录下存在 `CLAUDE.md` 或 `AGENT.md`，会被自动注入到 System Prompt 的 `## Project Rules` 部分（最多 2000 字符）。

## 📜 License

MIT
