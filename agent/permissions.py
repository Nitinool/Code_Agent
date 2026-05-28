# permissions.py — 权限控制
# 三步管道：模式检查 → 白名单放行 → 安全命令前缀 → 询问用户

from agent.providers import ToolCall

# 只读工具白名单（自动放行）
READONLY_TOOLS = {"Read", "Glob", "Grep"}

# 安全的 Bash 命令前缀（自动放行）
SAFE_BASH_PREFIXES = (
    "ls", "dir", "cat", "head", "tail", "find", "grep", "wc",
    "git status", "git log", "git diff", "git branch", "git show",
    "python", "python3", "node", "npm", "pip",
    "echo", "which", "pwd", "whoami", "env", "type",
    "pipenv", "poetry",
)


def check_permission(tool_call: ToolCall, config: dict) -> bool:
    """
    权限检查 — 返回 True 表示放行，False 表示需询问用户。
    
    管道：
    1. accept-all 模式 → 全部放行
    2. 只读工具 → 放行
    3. Bash 安全前缀 → 放行
    4. 其余 → 需询问用户（返回 False）
    """
    mode = config.get("permission_mode", "normal")
    name = tool_call.name
    
    # 步骤 1: accept-all 模式全部放行
    if mode == "accept-all":
        return True
    
    # 步骤 2: 只读工具白名单放行
    if name in READONLY_TOOLS:
        return True
    
    # 步骤 3: Bash 特殊处理 — 安全前缀自动放行
    if name == "Bash":
        cmd = tool_call.params.get("command", "").strip()
        # 去掉前导空格后检查
        cmd_stripped = cmd.lstrip()
        if any(cmd_stripped.startswith(prefix) for prefix in SAFE_BASH_PREFIXES):
            return True
    
    # 步骤 4: 其余都要询问用户
    return False


def format_permission_request(tool_call: ToolCall) -> str:
    """格式化权限请求消息，供 UI 显示"""
    name = tool_call.name
    
    if name == "Bash":
        cmd = tool_call.params.get("command", "")
        return f"⚡ Tool: {name}\n   Command: {cmd}"
    elif name == "Write":
        path = tool_call.params.get("file_path", "")
        content_len = len(tool_call.params.get("content", ""))
        return f"⚡ Tool: {name}\n   File: {path}\n   Content size: {content_len} chars"
    else:
        params_str = ", ".join(f"{k}={v}" for k, v in tool_call.params.items())
        return f"⚡ Tool: {name}({params_str})"
