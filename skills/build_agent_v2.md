---
name: build_agent_v2
description: 构建一个精简、实用的个人 Code Agent 框架。只包含核心必需组件，每一步都有数据结构和伪代码定义。
type: architecture-guideline
---

# 精简 Agent 框架实现指南

> 基于 build_agent_harness 的实战评估，去掉过度工程，保留核心骨架。
> 目标：用最少的代码构建一个真正能用的 Code Agent。

---

## 项目结构

```
my_agent/
├── agent.py          # 核心：Agent Loop + 主入口
├── tools.py          # 工具注册表 + 内置工具实现
├── context.py        # System Prompt 动态构建
├── providers.py      # LLM 提供者适配（Anthropic/OpenAI/Ollama）
├── compact.py        # 上下文压缩
├── config.py         # 配置加载与持久化
├── memory.py         # 跨会话记忆（极简版）
├── permissions.py    # 权限控制（极简版）
└── CLAUDE.md         # 项目级规则文件（Agent 自动读取）
```

---

## 核心数据结构

```python
# ===== 全部核心数据结构，共 4 个 =====

@dataclass
class AgentState:
    """会话状态 — Agent Loop 的可变核心"""
    messages: list[dict]          # 对话历史（中性格式）
    turn_count: int = 0           # 当前轮次
    total_input_tokens: int = 0   # 累计输入 token
    total_output_tokens: int = 0  # 累计输出 token

@dataclass
class ToolDef:
    """工具定义 — 注册到路由表的最小单元"""
    name: str                              # 工具名（如 "Read", "Bash"）
    description: str                       # 自然语言描述（LLM 看的）
    input_schema: dict                     # JSON Schema 参数定义
    func: Callable[[dict, dict], str]      # (params, config) → result
    read_only: bool = False                # 只读工具可跳过权限检查

# config 字典充当 ToolUseContext 的角色
Config = dict  # 包含: model, cwd, permission_mode, api_key 等

# 中性消息格式（所有 provider 归一化为此格式）
Message = dict  # {"role": "user"|"assistant"|"tool", "content": str, ...}
```

---

## Phase 1: 最小可用 Agent

### 1.1 Agent Loop（agent.py）

这是整个系统的心脏。理解这个循环就理解了 Agent。

```python
# agent.py

def run(user_input: str, state: AgentState, config: Config) -> Generator[Event, None, None]:
    """
    核心 Agent Loop。
    
    流程：追加用户消息 → 压缩上下文 → 调用 LLM → 解析输出 → 执行工具 → 循环
    通过 Generator yield 事件，将显示逻辑与核心逻辑解耦。
    """
    # 1. 追加用户消息
    state.messages.append({"role": "user", "content": user_input})
    
    while True:
        # 2. 上下文压缩（防止超出窗口限制）
        maybe_compact(state, config)
        
        # 3. 动态构建 System Prompt
        system_prompt = build_system_prompt(config)
        
        # 4. 获取可用工具的 schema 列表
        tool_schemas = get_tool_schemas()
        
        # 5. 调用 LLM（流式）
        assistant_turn = None
        for event in stream_llm(
            model=config["model"],
            system=system_prompt,
            messages=state.messages,
            tools=tool_schemas,
        ):
            if isinstance(event, TextChunk):
                yield event                          # 文本流式输出
            elif isinstance(event, ThinkingChunk):
                yield event                          # 思考过程（可选显示）
            elif isinstance(event, AssistantTurn):
                assistant_turn = event               # 完整的助手回复
        
        # 6. 追加助手消息到历史
        state.messages.append(assistant_turn.to_message())
        state.turn_count += 1
        
        # 7. 没有工具调用 → 本轮结束
        if not assistant_turn.tool_calls:
            yield TurnDone(state.total_input_tokens, state.total_output_tokens)
            break
        
        # 8. 逐个执行工具（串行，安全且简单）
        for tc in assistant_turn.tool_calls:
            yield ToolStart(tc.name, tc.params)      # 通知 UI：工具开始
            
            # 权限检查
            if not check_permission(tc, config):
                yield PermissionRequest(tc)          # 请求用户授权
                # ... 等待用户响应 ...
            
            # 执行工具
            result = execute_tool(tc.name, tc.params, config)
            
            # 追加工具结果到历史
            state.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
            
            yield ToolEnd(tc.name, result)           # 通知 UI：工具完成
```

**关键设计决策：**
- 用 `Generator[yield]` 而非直接 print → 核心逻辑与 UI 解耦
- 串行执行工具 → 简单、安全、无竞态
- `maybe_compact` 在每次 LLM 调用前检查 → 自动的上下文管理

---

### 1.2 Tool Registry（tools.py）

```python
# tools.py

# ===== 全局工具注册表 =====
_registry: dict[str, ToolDef] = {}

def register(tool_def: ToolDef):
    """注册一个工具"""
    _registry[tool_def.name] = tool_def

def execute_tool(name: str, params: dict, config: Config) -> str:
    """路由 + 执行 + 输出截断"""
    tool = _registry.get(name)
    if tool is None:
        return f"Error: unknown tool '{name}'"
    
    result = tool.func(params, config)
    
    # 输出截断（防止上下文爆炸）
    MAX_OUTPUT = 32000
    if len(result) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        result = result[:half] + f"\n... [truncated {len(result) - MAX_OUTPUT} chars] ...\n" + result[-half:]
    
    return result

def get_tool_schemas() -> list[dict]:
    """返回所有工具的 JSON Schema（给 LLM 看的）"""
    return [t.input_schema for t in _registry.values()]


# ===== 内置工具 =====

def _read_file(params: dict, config: dict) -> str:
    path = resolve_path(params["file_path"], config["cwd"])
    if not path.exists():
        return f"Error: file not found: {path}"
    return path.read_text(encoding="utf-8", errors="replace")

def _write_file(params: dict, config: dict) -> str:
    path = resolve_path(params["file_path"], config["cwd"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(params["content"], encoding="utf-8")
    return f"Written {len(params['content'])} chars to {path}"

def _bash(params: dict, config: dict) -> str:
    import subprocess
    result = subprocess.run(
        params["command"], shell=True, capture_output=True, text=True,
        cwd=config.get("cwd", "."), timeout=30,
    )
    output = result.stdout
    if result.stderr:
        output += f"\nSTDERR:\n{result.stderr}"
    if result.returncode != 0:
        output += f"\nExit code: {result.returncode}"
    return output or "(no output)"

def _list_files(params: dict, config: dict) -> str:
    import glob
    pattern = params.get("pattern", "**/*")
    files = glob.glob(pattern, root_dir=config.get("cwd", "."), recursive=True)
    return "\n".join(sorted(files)[:200]) or "No files found."

def _search_files(params: dict, config: dict) -> str:
    """在文件中搜索正则 pattern"""
    import re
    from pathlib import Path
    pattern = params["pattern"]
    path = params.get("path", ".")
    results = []
    for f in Path(path).rglob("*"):
        if f.is_file() and f.suffix in (".py", ".js", ".ts", ".md", ".txt", ".json", ".yaml", ".toml"):
            try:
                for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                    if re.search(pattern, line):
                        results.append(f"{f}:{i}: {line.strip()}")
            except Exception:
                pass
    return "\n".join(results[:50]) or "No matches found."


# ===== 注册所有内置工具 =====
def register_builtin_tools():
    register(ToolDef("Read", "Read file contents", {
        "type": "object",
        "properties": {"file_path": {"type": "string", "description": "File path"}},
        "required": ["file_path"],
    }, _read_file, read_only=True))

    register(ToolDef("Write", "Write content to file", {
        "type": "object", 
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["file_path", "content"],
    }, _write_file, read_only=False))

    register(ToolDef("Bash", "Execute shell command", {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "Shell command"}},
        "required": ["command"],
    }, _bash, read_only=False))

    register(ToolDef("Glob", "List files by pattern", {
        "type": "object",
        "properties": {"pattern": {"type": "string", "description": "Glob pattern"}},
    }, _list_files, read_only=True))

    register(ToolDef("Grep", "Search file contents by regex", {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern"},
            "path": {"type": "string", "description": "Directory to search"},
        },
        "required": ["pattern"],
    }, _search_files, read_only=True))
```

---

### 1.3 Prompt Pipeline（context.py）

```python
# context.py

# 核心理念：动态构建，绝不硬编码

SYSTEM_PROMPT_TEMPLATE = """You are a helpful coding assistant with access to tools.

## Environment
- Date: {date}
- Current directory: {cwd}
- Platform: {platform}
{git_info}

## Rules
- Always read files before editing them.
- Use tools to verify your work (run tests, check output).
- Be concise. Act, don't explain unless asked.
- When editing files, show the minimal change needed.
{project_rules}
{memory_context}
"""

def build_system_prompt(config: Config) -> str:
    """动态构建 System Prompt — 每轮调用都重新生成"""
    
    # ── 动态上下文 ──
    git_info = _get_git_info()  # "Git branch: main, last commit: abc123"
    
    # ── 项目规则（CLAUDE.md）──
    project_rules = ""
    claude_md = Path(config.get("cwd", ".")) / "CLAUDE.md"
    if claude_md.exists():
        project_rules = f"\n## Project Rules\n{claude_md.read_text()[:2000]}"
    
    # ── 记忆上下文 ──
    memory_context = ""
    mem = load_memory_summary()  # 极简版：只返回索引
    if mem:
        memory_context = f"\n## User Context\n{mem}"
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd=os.getcwd(),
        platform=sys.platform,
        git_info=git_info,
        project_rules=project_rules,
        memory_context=memory_context,
    )
```

---

### 1.4 LLM Provider 适配（providers.py）

```python
# providers.py

# 核心理念：内部使用中性消息格式，按 provider 转换

def stream_llm(model, system, messages, tools, config):
    """统一的 LLM 调用入口，返回流式事件"""
    provider = detect_provider(model)  # "anthropic" | "openai" | "ollama"
    
    if provider == "anthropic":
        yield from _stream_anthropic(model, system, messages, tools, config)
    elif provider in ("openai", "ollama"):
        yield from _stream_openai_compat(model, system, messages, tools, config, provider)

def _stream_anthropic(model, system, messages, tools, config):
    """Anthropic API 流式调用 + 输出块解析"""
    import anthropic
    client = anthropic.Anthropic(api_key=config["api_key"])
    
    with client.messages.stream(
        model=model, system=system, messages=messages, tools=tools, max_tokens=4096,
    ) as stream:
        for event in stream:
            # 将 Anthropic 原生事件转换为中性事件
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield TextChunk(event.delta.text)
            elif event.type == "message_stop":
                parsed = _parse_anthropic_response(stream.get_final_message())
                yield parsed  # AssistantTurn with tool_calls

# 中性消息格式 → Anthropic 格式
def messages_to_anthropic(messages):
    """归一化转换（关键：tool role 的格式差异）"""
    result = []
    for m in messages:
        if m["role"] == "tool":
            result.append({
                "role": "tool",
                "tool_call_id": m["tool_call_id"],
                "content": m["content"],
            })
        else:
            result.append(m)
    return result
```

---

## Phase 2: 让 Agent 好用

### 2.1 Context Compact（compact.py）

```python
# compact.py

# 两级压缩，覆盖 95% 场景

def maybe_compact(state: AgentState, config: Config):
    """每次 LLM 调用前检查，超阈值则压缩"""
    model = config["model"]
    limit = get_context_limit(model)    # 如 claude-3.5: 200000
    usage = estimate_tokens(state.messages)
    
    if usage <= limit * 0.7:            # 70% 以下不压缩
        return
    
    # 层级 1: 微压缩 — 截断旧的 tool_result
    snip_old_results(state.messages)
    
    # 层级 2: 摘要压缩 — 如果微压缩还不够
    if estimate_tokens(state.messages) > limit * 0.8:
        summary_compact(state, config)


def snip_old_results(messages: list[dict], keep_last_n: int = 6, max_chars: int = 2000):
    """微压缩：将 6 轮之前的旧 tool_result 截断"""
    # 找到最近的 N 轮（通过 assistant 消息计数）
    assistant_indices = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    cutoff = assistant_indices[-keep_last_n] if len(assistant_indices) > keep_last_n else 0
    
    for i in range(cutoff):
        m = messages[i]
        if m["role"] == "tool" and len(m.get("content", "")) > max_chars:
            content = m["content"]
            m["content"] = content[:500] + "\n... [snipped] ...\n" + content[-500:]


def summary_compact(state: AgentState, config: Config):
    """摘要压缩：用 LLM 总结旧历史，保留最近消息"""
    # 找分割点：保留最近 30% 消息
    split = max(1, len(state.messages) * 7 // 10)
    old_messages = state.messages[:split]
    recent_messages = state.messages[split:]
    
    # 调用 LLM 生成摘要
    summary = llm_summarize(old_messages, config)
    
    # 替换历史为 [摘要 + 最近消息]
    state.messages = [
        {"role": "user", "content": f"[Conversation Summary]\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the context from the previous conversation."},
        *recent_messages,
    ]
```

---

### 2.2 Permission System（permissions.py）

```python
# permissions.py

# 三步管道，够用：模式检查 → 白名单放行 → 询问用户

READONLY_TOOLS = {"Read", "Glob", "Grep"}  # 只读工具白名单

SAFE_BASH_PREFIXES = (
    "ls", "cat", "head", "tail", "find", "grep", "wc",
    "git status", "git log", "git diff", "git branch",
    "python", "python3", "node", "npm", "pip",
    "echo", "which", "pwd", "whoami", "env",
)

def check_permission(tool_call, config: Config) -> bool:
    """权限检查 — 返回 True 表示放行，False 表示需询问用户"""
    mode = config.get("permission_mode", "auto")
    name = tool_call.name
    
    # 步骤 1: 模式检查
    if mode == "accept-all":
        return True
    
    # 步骤 2: 白名单放行（只读工具）
    if name in READONLY_TOOLS:
        return True
    
    # 步骤 3: Bash 特殊处理 — 安全前缀自动放行
    if name == "Bash":
        cmd = tool_call.params.get("command", "").strip()
        if any(cmd.startswith(prefix) for prefix in SAFE_BASH_PREFIXES):
            return True
    
    # 步骤 4: 其余都要询问用户
    return False
```

---

### 2.3 Memory System（memory.py）

```python
# memory.py

# 极简版：一个 JSON 文件存用户偏好，启动时加载到 config

MEMORY_FILE = Path.home() / ".my_agent" / "memory.json"

def load_memory() -> dict:
    """启动时加载"""
    if MEMORY_FILE.exists():
        return json.loads(MEMORY_FILE.read_text())
    return {}

def save_memory(key: str, value: str):
    """保存一条记忆"""
    data = load_memory()
    data[key] = {"value": value, "updated_at": datetime.now().isoformat()}
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_memory_summary() -> str:
    """加载为 System Prompt 的一段文字（只返回摘要，不返回完整内容）"""
    data = load_memory()
    if not data:
        return ""
    lines = ["User preferences and context:"]
    for key, entry in data.items():
        lines.append(f"- {key}: {entry['value']}")
    return "\n".join(lines)

# 工具注册：让 Agent 能自主保存记忆
def _memory_save(params: dict, config: dict) -> str:
    save_memory(params["key"], params["value"])
    return f"Saved: {params['key']}"

# 注册：
# register(ToolDef("MemorySave", "Save user preference", schema, _memory_save, read_only=True))
```

**关键原则（从 Skill 保留的最重要的一句话）：**
> **绝对不要保存代码状态或当前任务。** 只保存"人"的信息：偏好、反馈、决策理由。
> 代码状态可以从代码库推导，任务状态会过时。

---

## Phase 3: 进阶功能（按需添加）

### 3.1 Plan Mode（加到 permissions.py）

```python
# 当用户说"先做计划"时，切换为只读模式，只允许写计划文件

def enter_plan_mode(config: Config, plan_file: str):
    config["permission_mode"] = "plan"
    config["_plan_file"] = plan_file

def check_permission_plan_aware(tool_call, config):
    """扩展权限检查：plan mode 下只允许写计划文件"""
    if config.get("permission_mode") == "plan":
        if tool_call.name in ("Write", "Edit"):
            target = tool_call.params.get("file_path", "")
            if target != config.get("_plan_file"):
                return False  # 拒绝：只能写计划文件
    # ... 正常权限检查 ...
```

### 3.2 Subagents（加到 agent.py）

```python
# 核心原则：全新消息数组 + 限制工具集 + 只返回总结

def spawn_subagent(prompt: str, config: Config, allowed_tools: list[str] = None) -> str:
    """启动子智能体，返回总结结果"""
    # 1. 全新空白状态（绝不共享父 Agent 的 messages）
    sub_state = AgentState(messages=[], turn_count=0)
    
    # 2. 限制工具集
    sub_config = {**config}
    if allowed_tools:
        sub_config["_allowed_tools"] = allowed_tools  # 如 ["Read", "Glob", "Grep"]
    
    # 3. 运行子 Agent
    for event in run(prompt, sub_state, sub_config):
        pass  # 收集结果
    
    # 4. 只返回最终助手消息（总结），不泄漏完整日志
    for msg in reversed(sub_state.messages):
        if msg["role"] == "assistant" and msg.get("content"):
            return msg["content"]
    return "(sub-agent produced no output)"
```

### 3.3 Skills 按需加载（加到 tools.py）

```python
# 等你的 Skill 超过 5 个再实现这个

SKILLS_DIR = Path.home() / ".my_agent" / "skills"

@dataclass
class SkillDef:
    name: str
    description: str       # 轻量描述（给 System Prompt 的目录用的）
    triggers: list[str]    # 触发词
    prompt_file: Path      # 完整 prompt 的文件路径

def load_skills() -> list[SkillDef]:
    """从 SKILLS_DIR 加载所有 skill 定义"""
    skills = []
    for f in SKILLS_DIR.glob("*.md"):
        # 解析 frontmatter 中的 name, description, triggers
        skills.append(parse_skill(f))
    return skills

def get_skills_catalog() -> str:
    """System Prompt 中的轻量目录（发现机制）— 不加载完整内容"""
    return "\n".join(f"- /{s.name}: {s.description}" for s in load_skills())

def load_skill_prompt(name: str) -> str:
    """按需加载完整 prompt（加载机制）— 只有被调用时才读文件"""
    for s in load_skills():
        if s.name == name:
            return s.prompt_file.read_text()
    return None
```

---

## 事件类型定义

```python
# agent.py 中用到的所有事件类型

@dataclass
class TextChunk:
    text: str

@dataclass  
class ThinkingChunk:
    text: str

@dataclass
class AssistantTurn:
    content: str
    tool_calls: list[ToolCall]
    def to_message(self) -> dict: ...

@dataclass
class ToolStart:
    name: str
    params: dict

@dataclass
class ToolEnd:
    name: str
    result: str

@dataclass
class PermissionRequest:
    description: str
    granted: bool = False

@dataclass
class TurnDone:
    input_tokens: int
    output_tokens: int
```

---

## 主入口（main.py）

```python
# main.py — 把所有东西串起来

def main():
    config = load_config()              # 加载配置
    state = AgentState(messages=[])     # 初始化状态
    register_builtin_tools()            # 注册工具
    
    # 加载记忆到 config
    config["_memory"] = load_memory()
    
    # 主 REPL 循环
    while True:
        user_input = input("» ")
        if user_input.startswith("/"):
            handle_slash_command(user_input, state, config)
            continue
        
        for event in run(user_input, state, config):
            if isinstance(event, TextChunk):
                print(event.text, end="", flush=True)
            elif isinstance(event, ToolStart):
                print(f"  ⚙ {event.name}({list(event.params.values())[:1]})")
            elif isinstance(event, ToolEnd):
                print(f"  ✓ {len(event.result)} chars")
            elif isinstance(event, TurnDone):
                print(f"\n  [tokens: +{event.input_tokens} in / +{event.output_tokens} out]")
```

---

## 必须遵守的反模式（只有 2 条）

### ✅ 反模式 1: 不要膨胀 System Prompt
- 不要把完整 Skill 内容塞进 System Prompt
- 不要把完整对话历史塞进 System Prompt  
- 记忆只放索引/摘要，不放全文

### ✅ 反模式 2: 不要盲目相信记忆
- 记忆中记录的文件路径可能已不存在
- Agent 在根据记忆行动前，先用 Read/Glob 验证文件是否存在
- 原则：**信任，但要核实**

---

## 学习路线图

```
Week 1: Phase 1 (agent.py + tools.py + context.py + providers.py)
        → 你有一个能对话、能读写文件、能跑命令的 Agent

Week 2: Phase 2 (compact.py + permissions.py + memory.py)
        → 你的 Agent 能长对话、有安全边界、记得你的偏好

Week 3+: Phase 3 按需加功能
        → Plan Mode → Subagents → Skills 加载
```

**总代码量估算：Phase 1 约 300 行，Phase 2 约 200 行，Phase 3 约 200 行。**
