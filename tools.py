# tools.py — 工具注册表 + 内置工具实现

import subprocess
import glob
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Callable


# ===== 核心数据结构 =====

Config = dict  # 包含: model, cwd, permission_mode, api_key 等

@dataclass
class ToolDef:
    """工具定义 — 注册到路由表的最小单元"""
    name: str                              # 工具名（如 "Read", "Bash"）
    description: str                       # 自然语言描述（LLM 看的）
    parameters: dict                       # JSON Schema 参数定义
    func: Callable[[dict, dict], str]      # (params, config) → result
    read_only: bool = False                # 只读工具可跳过权限检查


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
    
    try:
        result = tool.func(params, config)
    except Exception as e:
        result = f"Error executing {name}: {e}"
    
    # 输出截断（防止上下文爆炸）
    MAX_OUTPUT = 32000
    if len(result) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        result = result[:half] + f"\n... [truncated {len(result) - MAX_OUTPUT} chars] ...\n" + result[-half:]
    
    return result


def get_tool_schemas() -> list[dict]:
    """返回所有工具的 schema（给 LLM 看的，OpenAI function calling 格式）"""
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        }
        for t in _registry.values()
    ]


def get_registry() -> dict[str, ToolDef]:
    """获取工具注册表（权限检查用）"""
    return _registry


# ===== 辅助函数 =====

def resolve_path(file_path: str, cwd: str) -> Path:
    """解析文件路径（支持相对路径和绝对路径）"""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    return p.resolve()


# ===== 内置工具实现 =====

def _read_file(params: dict, config: dict) -> str:
    """读取文件内容"""
    path = resolve_path(params["file_path"], config["cwd"])
    if not path.exists():
        return f"Error: file not found: {path}"
    if path.is_dir():
        return f"Error: {path} is a directory, not a file"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def _write_file(params: dict, config: dict) -> str:
    """写入文件内容"""
    path = resolve_path(params["file_path"], config["cwd"])
    content = params["content"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        # 统计行数
        lines = content.count("\n") + 1
        return f"Successfully wrote {len(content)} chars ({lines} lines) to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _bash(params: dict, config: dict) -> str:
    """执行 shell 命令"""
    command = params["command"]
    timeout = params.get("timeout", 30)
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=config.get("cwd", "."),
            timeout=timeout,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += f"\nSTDERR:\n{result.stderr}"
            else:
                output += result.stderr
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error executing command: {e}"


def _list_files(params: dict, config: dict) -> str:
    """列出文件和目录"""
    pattern = params.get("pattern", "**/*")
    cwd = config.get("cwd", ".")
    
    try:
        files = glob.glob(pattern, root_dir=cwd, recursive=True)
        # 过滤掉常见的不需要的目录
        filtered = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
        for f in sorted(files):
            parts = Path(f).parts
            if any(p in skip_dirs for p in parts):
                continue
            filtered.append(f)
        
        if not filtered:
            return "No files found."
        
        # 限制输出数量
        if len(filtered) > 200:
            output = "\n".join(filtered[:200])
            output += f"\n... and {len(filtered) - 200} more files"
            return output
        return "\n".join(filtered)
    except Exception as e:
        return f"Error listing files: {e}"


def _search_files(params: dict, config: dict) -> str:
    """在文件中搜索正则 pattern"""
    pattern = params["pattern"]
    search_path = params.get("path", config.get("cwd", "."))
    
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"
    
    # 可搜索的文件扩展名
    searchable_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".c", ".cpp", ".h",
        ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".conf",
        ".html", ".css", ".scss", ".xml", ".sql", ".sh", ".bat", ".ps1",
        ".rb", ".php", ".swift", ".kt", ".scala",
    }
    
    results = []
    search_dir = resolve_path(search_path, config.get("cwd", "."))
    
    if not search_dir.exists():
        return f"Error: path not found: {search_dir}"
    
    try:
        for f in search_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in searchable_extensions:
                continue
            # 跳过不需要的目录
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea"}
            if any(p in skip_dirs for p in f.parts):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        # 显示相对路径
                        try:
                            rel_path = f.relative_to(search_dir)
                        except ValueError:
                            rel_path = f
                        results.append(f"{rel_path}:{i}: {line.strip()}")
                        if len(results) >= 50:
                            return "\n".join(results) + "\n... (truncated, more matches exist)"
            except Exception:
                pass
    except Exception as e:
        return f"Error searching: {e}"
    
    return "\n".join(results) if results else "No matches found."


# ===== 注册所有内置工具 =====

# ===== s12/s13/s14 任务引擎工具 =====

def _task_create(params: dict, config: dict) -> str:
    """创建工作图任务"""
    from tasks import create_task
    subject = params.get("subject", "")
    if not subject:
        return "Error: 'subject' is required"
    blocked_by = params.get("blocked_by", [])
    claim_role = params.get("claim_role", "")
    task = create_task(config["cwd"], subject, blocked_by, claim_role)
    return f"Created task: {task.id}\n  Subject: {task.subject}\n  Status: {task.status}\n  Blocked by: {task.blockedBy or 'none'}"


def _task_list(params: dict, config: dict) -> str:
    """列出工作图任务"""
    from tasks import list_tasks
    status_filter = params.get("status", None)
    tasks = list_tasks(config["cwd"], status_filter)
    if not tasks:
        return "No tasks found."
    lines = []
    for t in tasks:
        ready = " [READY]" if t.status == "pending" and not t.blockedBy else ""
        owner = f" (owner: {t.owner})" if t.owner else ""
        lines.append(f"  {t.id}  [{t.status}]{ready}  {t.subject}{owner}")
    return "\n".join(lines)


def _task_complete(params: dict, config: dict) -> str:
    """完成工作图任务"""
    from tasks import complete_task
    task_id = params.get("task_id", "")
    result = params.get("result", "")
    task = complete_task(config["cwd"], task_id, result)
    if task is None:
        return f"Error: task not found: {task_id}"
    return f"Completed task: {task.id} — {task.subject}"


def _task_fail(params: dict, config: dict) -> str:
    """标记任务失败"""
    from tasks import fail_task
    task_id = params.get("task_id", "")
    reason = params.get("reason", "")
    task = fail_task(config["cwd"], task_id, reason)
    if task is None:
        return f"Error: task not found: {task_id}"
    return f"Failed task: {task.id} — {task.subject}\n  Reason: {reason}"


def _task_info(params: dict, config: dict) -> str:
    """查看任务详情"""
    from tasks import load_task, is_ready
    task_id = params.get("task_id", "")
    task = load_task(config["cwd"], task_id)
    if task is None:
        return f"Error: task not found: {task_id}"
    ready = is_ready(task, config["cwd"])
    lines = [
        f"Task: {task.id}",
        f"  Subject: {task.subject}",
        f"  Status: {task.status}",
        f"  Owner: {task.owner or 'unassigned'}",
        f"  Blocked by: {task.blockedBy or 'none'}",
        f"  Blocks: {task.blocks or 'none'}",
        f"  Ready: {ready}",
        f"  Created: {task.created_at}",
        f"  Updated: {task.updated_at}",
    ]
    if task.result:
        lines.append(f"  Result: {task.result[:500]}")
    return "\n".join(lines)


def _task_delete(params: dict, config: dict) -> str:
    """删除工作图任务"""
    from tasks import delete_task
    task_id = params.get("task_id", "")
    if delete_task(config["cwd"], task_id):
        return f"Deleted task: {task_id}"
    return f"Error: task not found: {task_id}"


def _background_run(params: dict, config: dict) -> str:
    """启动后台任务"""
    from tasks import background_run
    command = params.get("command", "")
    if not command:
        return "Error: 'command' is required"
    rt = background_run(command, config["cwd"], config)
    return (
        f"Background task started: {rt.id}\n"
        f"  Command: {command}\n"
        f"  Status: {rt.status}\n"
        f"  Output file: {rt.output_file}\n"
        f"  The task is running in the background. Results will be delivered as a notification."
    )


def _background_status(params: dict, config: dict) -> str:
    """查看后台任务状态"""
    from tasks import load_runtime_task, list_runtime_tasks
    task_id = params.get("task_id", "")
    if task_id:
        rt = load_runtime_task(config["cwd"], task_id)
        if rt is None:
            return f"Error: runtime task not found: {task_id}"
        lines = [
            f"Runtime Task: {rt.id}",
            f"  Command: {rt.command}",
            f"  Status: {rt.status}",
            f"  Exit code: {rt.exit_code}",
            f"  Started: {rt.started_at}",
            f"  Finished: {rt.finished_at or 'still running'}",
        ]
        if rt.preview:
            lines.append(f"  Preview:\n{rt.preview[:1000]}")
        return "\n".join(lines)
    else:
        # 列出所有
        tasks = list_runtime_tasks(config["cwd"])
        if not tasks:
            return "No runtime tasks."
        lines = []
        for rt in tasks[:20]:
            lines.append(f"  {rt.id}  [{rt.status}]  {rt.command[:60]}")
        return "\n".join(lines)


def _background_output(params: dict, config: dict) -> str:
    """获取后台任务完整输出"""
    from tasks import get_runtime_output
    task_id = params.get("task_id", "")
    return get_runtime_output(config["cwd"], task_id)


def _background_cancel(params: dict, config: dict) -> str:
    """取消后台任务"""
    from tasks import cancel_runtime_task
    task_id = params.get("task_id", "")
    return cancel_runtime_task(config["cwd"], task_id)


def _schedule_create(params: dict, config: dict) -> str:
    """创建定时调度"""
    from tasks import create_schedule
    cron_expr = params.get("cron", "")
    prompt = params.get("prompt", "")
    if not cron_expr or not prompt:
        return "Error: both 'cron' and 'prompt' are required"
    sched = create_schedule(config["cwd"], cron_expr, prompt)
    return (
        f"Schedule created: {sched.id}\n"
        f"  Cron: {cron_expr}\n"
        f"  Prompt: {prompt[:100]}\n"
        f"  Enabled: {sched.enabled}"
    )


def _schedule_list(params: dict, config: dict) -> str:
    """列出定时调度"""
    from tasks import list_schedules
    schedules = list_schedules(config["cwd"])
    if not schedules:
        return "No schedules found."
    lines = []
    for s in schedules:
        enabled = "ON" if s.enabled else "OFF"
        last = s.last_fired_at or "never"
        lines.append(f"  {s.id}  [{enabled}]  {s.cron_expr}  \"{s.prompt[:50]}\"  last: {last}")
    return "\n".join(lines)


def _schedule_delete(params: dict, config: dict) -> str:
    """删除定时调度"""
    from tasks import delete_schedule
    schedule_id = params.get("schedule_id", "")
    if delete_schedule(config["cwd"], schedule_id):
        return f"Deleted schedule: {schedule_id}"
    return f"Error: schedule not found: {schedule_id}"


def _schedule_toggle(params: dict, config: dict) -> str:
    """启用/禁用调度"""
    from tasks import toggle_schedule
    schedule_id = params.get("schedule_id", "")
    enabled = params.get("enabled", None)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes", "on")
    sched = toggle_schedule(config["cwd"], schedule_id, enabled)
    if sched is None:
        return f"Error: schedule not found: {schedule_id}"
    return f"Schedule {schedule_id}: enabled={sched.enabled}"


def register_task_tools():
    """注册 s12/s13/s14 任务引擎相关工具"""
    
    # s12 — Work Graph
    register(ToolDef(
        name="TaskCreate",
        description="Create a task in the work graph. Tasks represent business goals and can have dependencies (blockedBy). Use this to plan complex multi-step work.",
        parameters={
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Task title/description"},
                "blocked_by": {"type": "array", "items": {"type": "string"}, "description": "List of task IDs this task depends on"},
                "claim_role": {"type": "string", "description": "Required role to claim this task"},
            },
            "required": ["subject"],
        },
        func=_task_create,
        read_only=False,
    ))

    register(ToolDef(
        name="TaskList",
        description="List all tasks in the work graph. Optionally filter by status (pending, in_progress, done, failed).",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter by status (optional)"},
            },
        },
        func=_task_list,
        read_only=True,
    ))

    register(ToolDef(
        name="TaskComplete",
        description="Mark a task as completed. This automatically unblocks downstream tasks that depend on this one.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to complete"},
                "result": {"type": "string", "description": "Optional result summary"},
            },
            "required": ["task_id"],
        },
        func=_task_complete,
        read_only=False,
    ))

    register(ToolDef(
        name="TaskFail",
        description="Mark a task as failed with a reason.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to fail"},
                "reason": {"type": "string", "description": "Reason for failure"},
            },
            "required": ["task_id"],
        },
        func=_task_fail,
        read_only=False,
    ))

    register(ToolDef(
        name="TaskInfo",
        description="Get detailed information about a specific task.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID"},
            },
            "required": ["task_id"],
        },
        func=_task_info,
        read_only=True,
    ))

    register(ToolDef(
        name="TaskDelete",
        description="Delete a task from the work graph.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "The task ID to delete"},
            },
            "required": ["task_id"],
        },
        func=_task_delete,
        read_only=False,
    ))

    # s13 — Runtime Tasks (Background Execution)
    register(ToolDef(
        name="BackgroundRun",
        description="Run a shell command in the background. Returns immediately with a task ID. Output is saved to a file and a notification is sent when complete. Use this for long-running commands (tests, builds, etc).",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute in the background"},
            },
            "required": ["command"],
        },
        func=_background_run,
        read_only=False,
    ))

    register(ToolDef(
        name="BackgroundStatus",
        description="Check the status of background tasks. Provide task_id for details, or omit to list all.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Runtime task ID (omit to list all)"},
            },
        },
        func=_background_status,
        read_only=True,
    ))

    register(ToolDef(
        name="BackgroundOutput",
        description="Get the full output of a completed background task.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Runtime task ID"},
            },
            "required": ["task_id"],
        },
        func=_background_output,
        read_only=True,
    ))

    register(ToolDef(
        name="BackgroundCancel",
        description="Cancel a running background task.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Runtime task ID to cancel"},
            },
            "required": ["task_id"],
        },
        func=_background_cancel,
        read_only=False,
    ))

    # s14 — Cron Scheduler
    register(ToolDef(
        name="ScheduleCreate",
        description="Create a scheduled task using cron expression. The prompt will be sent to the agent at the specified times. Cron format: minute hour day month weekday (e.g., '*/5 * * * *' = every 5 minutes, '0 9 * * 1-5' = 9am weekdays).",
        parameters={
            "type": "object",
            "properties": {
                "cron": {"type": "string", "description": "Cron expression (minute hour day month weekday)"},
                "prompt": {"type": "string", "description": "The prompt/instruction to send when triggered"},
            },
            "required": ["cron", "prompt"],
        },
        func=_schedule_create,
        read_only=False,
    ))

    register(ToolDef(
        name="ScheduleList",
        description="List all scheduled tasks.",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=_schedule_list,
        read_only=True,
    ))

    register(ToolDef(
        name="ScheduleDelete",
        description="Delete a scheduled task.",
        parameters={
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string", "description": "The schedule ID to delete"},
            },
            "required": ["schedule_id"],
        },
        func=_schedule_delete,
        read_only=False,
    ))

    register(ToolDef(
        name="ScheduleToggle",
        description="Enable or disable a scheduled task.",
        parameters={
            "type": "object",
            "properties": {
                "schedule_id": {"type": "string", "description": "The schedule ID"},
                "enabled": {"type": "boolean", "description": "True to enable, false to disable"},
            },
            "required": ["schedule_id"],
        },
        func=_schedule_toggle,
        read_only=False,
    ))


# ===== s15/s16 Team 工具 =====

def _team_spawn(params: dict, config: dict) -> str:
    """启动队友"""
    from team import spawn_teammate, get_teammate
    name = params.get("name", "")
    role = params.get("role", "worker")
    role_desc = params.get("role_desc", "")
    model = params.get("model", "")
    
    if not name:
        return "Error: 'name' is required"
    
    # 检查是否已运行
    if get_teammate(name):
        return f"Teammate '{name}' is already running."
    
    try:
        handle = spawn_teammate(
            cwd=config["cwd"],
            name=name,
            role=role,
            role_desc=role_desc,
            config=config,
            model=model,
        )
        return f"Spawned teammate: {name} (role: {role})\n  Status: {handle.status}\n  Model: {handle.model}"
    except ValueError as e:
        return f"Error: {e}"


def _team_list(params: dict, config: dict) -> str:
    """列出团队成员"""
    from team import list_team_members, get_teammate, peek_teammate_inbox
    
    members = list_team_members(config["cwd"])
    if not members:
        return "No team members registered."
    
    lines = []
    for m in members:
        handle = get_teammate(m.name)
        if handle:
            info = handle.get_info()
            lines.append(
                f"  {m.name}  [{info['status']}]  role={m.role}  "
                f"task={info['current_task'] or 'none'}  "
                f"inbox={info['pending_inbox']}  "
                f"msgs={info['messages_count']}"
            )
        else:
            lines.append(f"  {m.name}  [offline]  role={m.role}")
    
    return f"Team Members ({len(members)}):\n" + "\n".join(lines)


def _team_shutdown(params: dict, config: dict) -> str:
    """关闭队友"""
    from team import shutdown_teammate, create_shutdown_protocol
    name = params.get("name", "")
    reason = params.get("reason", "")
    
    if not name:
        return "Error: 'name' is required"
    
    if name == "boss":
        return "Error: Cannot shut down boss agent!"
    
    # 先发送关机协议
    create_shutdown_protocol(config["cwd"], "boss", name, reason)
    
    # 然后强制关闭
    if shutdown_teammate(config["cwd"], name, reason):
        return f"Shutdown teammate: {name}"
    return f"Error: Teammate '{name}' not found or not running"


def _team_send_message(params: dict, config: dict) -> str:
    """向队友发送消息"""
    from team import send_to_teammate, get_teammate
    target = params.get("target", "")
    content = params.get("content", "")
    
    if not target or not content:
        return "Error: 'target' and 'content' are required"
    
    handle = get_teammate(target)
    if not handle:
        return f"Error: Teammate '{target}' is not running"
    
    handle.send_message(content)
    return f"Message sent to {target}: {content[:100]}"


def _team_broadcast(params: dict, config: dict) -> str:
    """广播消息给所有队友"""
    from team import get_all_teammates
    content = params.get("content", "")
    if not content:
        return "Error: 'content' is required"
    
    teammates = get_all_teammates()
    if not teammates:
        return "No active teammates to broadcast to."
    
    for name, handle in teammates.items():
        handle.send_message(content)
    
    return f"Broadcast sent to {len(teammates)} teammate(s): {', '.join(teammates.keys())}"


def _team_assign_task(params: dict, config: dict) -> str:
    """分配任务给队友"""
    from team import get_teammate, create_task_assign_protocol
    target = params.get("target", "")
    task_id = params.get("task_id", "")
    
    if not target or not task_id:
        return "Error: 'target' and 'task_id' are required"
    
    handle = get_teammate(target)
    if not handle:
        return f"Error: Teammate '{target}' is not running"
    
    from tasks import load_task
    task = load_task(config["cwd"], task_id)
    if not task:
        return f"Error: Task '{task_id}' not found"
    
    protocol, record = create_task_assign_protocol(
        config["cwd"], "boss", target, task_id, task.subject
    )
    
    return f"Task {task_id} assigned to {target} (request: {record.request_id})"


def register_team_tools():
    """注册 s15/s16 团队工具"""
    
    register(ToolDef(
        name="TeamSpawn",
        description="Spawn a new teammate agent. The teammate runs in its own thread with independent context and can autonomously claim and execute tasks.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique name for the teammate (e.g., 'worker-1', 'coder')"},
                "role": {"type": "string", "description": "Role (default: 'worker')"},
                "role_desc": {"type": "string", "description": "Description of what this teammate does"},
                "model": {"type": "string", "description": "Model to use (default: same as boss)"},
            },
            "required": ["name"],
        },
        func=_team_spawn,
        read_only=False,
    ))

    register(ToolDef(
        name="TeamList",
        description="List all team members and their status.",
        parameters={"type": "object", "properties": {}},
        func=_team_list,
        read_only=True,
    ))

    register(ToolDef(
        name="TeamShutdown",
        description="Shut down a teammate agent gracefully. Sends a shutdown protocol first, then stops the thread.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the teammate to shut down"},
                "reason": {"type": "string", "description": "Reason for shutdown"},
            },
            "required": ["name"],
        },
        func=_team_shutdown,
        read_only=False,
    ))

    register(ToolDef(
        name="SendMessage",
        description="Send a direct message to a specific teammate. The teammate will see it in their next inbox drain cycle.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Name of the target teammate"},
                "content": {"type": "string", "description": "Message content"},
            },
            "required": ["target", "content"],
        },
        func=_team_send_message,
        read_only=False,
    ))

    register(ToolDef(
        name="Broadcast",
        description="Send a message to all active teammates.",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Message content"},
            },
            "required": ["content"],
        },
        func=_team_broadcast,
        read_only=False,
    ))

    register(ToolDef(
        name="AssignTask",
        description="Assign a task to a specific teammate using the task assignment protocol.",
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Name of the teammate"},
                "task_id": {"type": "string", "description": "Task ID to assign"},
            },
            "required": ["target", "task_id"],
        },
        func=_team_assign_task,
        read_only=False,
    ))


def register_memory_tools():
    """注册记忆相关工具"""
    from memory import _memory_save, _memory_load, _memory_delete

    register(ToolDef(
        name="MemorySave",
        description="Save a user preference or context to long-term memory. Use this to remember user preferences, decisions, and important context across conversations. Do NOT save code state or current tasks.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "A unique key for this memory (e.g., 'preferred_language', 'project_style')",
                },
                "value": {
                    "type": "string",
                    "description": "The value to remember",
                },
            },
            "required": ["key", "value"],
        },
        func=_memory_save,
        read_only=False,
    ))

    register(ToolDef(
        name="MemoryLoad",
        description="Load all saved memories. Returns all user preferences and context stored in long-term memory.",
        parameters={
            "type": "object",
            "properties": {},
        },
        func=_memory_load,
        read_only=True,
    ))

    register(ToolDef(
        name="MemoryDelete",
        description="Delete a specific memory entry by key.",
        parameters={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the memory to delete",
                },
            },
            "required": ["key"],
        },
        func=_memory_delete,
        read_only=False,
    ))


def register_builtin_tools():
    """注册所有内置工具"""
    
    register(ToolDef(
        name="Read",
        description="Read the contents of a file. Returns the file content as text.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute)",
                },
            },
            "required": ["file_path"],
        },
        func=_read_file,
        read_only=True,
    ))

    register(ToolDef(
        name="Write",
        description="Write content to a file. Creates the file and any parent directories if they don't exist. Overwrites existing content.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write (relative or absolute)",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        },
        func=_write_file,
        read_only=False,
    ))

    register(ToolDef(
        name="Bash",
        description="Execute a shell command and return the output. Use for running tests, installing packages, git operations, etc.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 30)",
                },
            },
            "required": ["command"],
        },
        func=_bash,
        read_only=False,
    ))

    register(ToolDef(
        name="Glob",
        description="List files and directories matching a glob pattern. Use '**/*' to list all files recursively.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts', '**/*')",
                },
            },
        },
        func=_list_files,
        read_only=True,
    ))

    register(ToolDef(
        name="Grep",
        description="Search for a regex pattern in file contents. Returns matching lines with file path and line number.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "Regular expression pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory to search in (default: current directory)",
                },
            },
            "required": ["pattern"],
        },
        func=_search_files,
        read_only=True,
    ))
