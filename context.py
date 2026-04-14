# context.py — System Prompt 动态构建

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime


# ===== System Prompt 模板 =====

SYSTEM_PROMPT_TEMPLATE = """You are a helpful coding assistant with access to tools. You can read files, write files, search code, execute commands, manage tasks, run background jobs, and schedule recurring work.

## Environment
- Date: {date}
- Current directory: {cwd}
- Platform: {platform}
{git_info}

## Available Tools

### File Operations
- **Read**: Read file contents
- **Write**: Write content to files
- **Glob**: List files by pattern
- **Grep**: Search file contents by regex

### Execution
- **Bash**: Execute shell commands (synchronous, blocks until done)
- **BackgroundRun**: Execute long-running commands in the background (returns immediately, results delivered as notification)
- **BackgroundStatus**: Check background task status
- **BackgroundOutput**: Get full output of a background task
- **BackgroundCancel**: Cancel a running background task

### Task Management (Work Graph)
- **TaskCreate**: Create a task with optional dependencies (blockedBy)
- **TaskList**: List all tasks (optional status filter)
- **TaskInfo**: Get detailed task info
- **TaskComplete**: Mark task done (auto-unblocks dependent tasks)
- **TaskFail**: Mark task as failed
- **TaskDelete**: Delete a task

### Scheduling
- **ScheduleCreate**: Create a recurring scheduled task (cron expression)
- **ScheduleList**: List all schedules
- **ScheduleDelete**: Delete a schedule
- **ScheduleToggle**: Enable/disable a schedule

### Memory
- **MemorySave**: Save user preferences to long-term memory (survives restarts)
- **MemoryLoad**: Load all saved memories
- **MemoryDelete**: Delete a saved memory

### Team Management (Multi-Agent)
- **TeamSpawn**: Spawn a new teammate agent (runs independently with its own context)
- **TeamList**: List all team members and their status
- **TeamShutdown**: Shut down a teammate gracefully
- **SendMessage**: Send a direct message to a specific teammate
- **Broadcast**: Send a message to all active teammates
- **AssignTask**: Assign a task to a specific teammate via protocol

## Rules
- Always read files before editing them. Use Read to check current content.
- When writing files, provide the COMPLETE file content, not just changes.
- Use Bash for quick commands. Use BackgroundRun for commands that take more than a few seconds (builds, test suites, long scripts).
- Use TaskCreate to plan complex multi-step work. Set blockedBy to enforce execution order.
- Be concise. Act, don't explain unless asked.
- When searching, use Grep first to find relevant code, then Read to understand context.
- For multi-file changes, plan first, then execute step by step.
- If a command fails, read the error carefully and fix it.
- Background task notifications will appear as inbox messages in the conversation.
{project_rules}
{memory_context}
{task_context}
{team_context}
"""


def _get_git_info(cwd: str) -> str:
    """获取 git 信息"""
    try:
        # 获取当前分支
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if branch.returncode != 0:
            return ""
        
        branch_name = branch.stdout.strip()
        
        # 获取最近的 commit
        last_commit = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        commit_info = last_commit.stdout.strip() if last_commit.returncode == 0 else ""
        
        result = f"- Git branch: {branch_name}"
        if commit_info:
            result += f"\n- Last commit: {commit_info}"
        return result
    except Exception:
        return ""


def build_system_prompt(config: dict) -> str:
    """
    动态构建 System Prompt — 每轮调用都重新生成。
    
    注入：日期时间、工作目录、平台信息、git 状态、项目规则、用户记忆。
    """
    cwd = config.get("cwd", os.getcwd())
    
    # ── Git 信息 ──
    git_info = _get_git_info(cwd)
    
    # ── 项目规则（CLAUDE.md）──
    project_rules = ""
    claude_md = Path(cwd) / "CLAUDE.md"
    if claude_md.exists():
        try:
            content = claude_md.read_text(encoding="utf-8")
            # 限制长度，避免 system prompt 过长
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            project_rules = f"\n## Project Rules\n{content}"
        except Exception:
            pass
    
    # ── 记忆上下文 ──
    memory_context = ""
    try:
        from memory import load_memory_summary
        mem = load_memory_summary()
        if mem:
            memory_context = f"\n## User Context\n{mem}"
    except Exception:
        pass
    
    # ── 任务上下文 ──
    task_context = ""
    try:
        from tasks import list_tasks, list_runtime_tasks, is_ready
        pending = list_tasks(cwd, "pending")
        ready_tasks = [t for t in pending if is_ready(t, cwd)]
        in_progress = list_tasks(cwd, "in_progress")
        running_bg = list_runtime_tasks(cwd, "running")
        
        parts = []
        if ready_tasks:
            parts.append(f"{len(ready_tasks)} task(s) ready to execute")
        if in_progress:
            parts.append(f"{len(in_progress)} task(s) in progress")
        if running_bg:
            parts.append(f"{len(running_bg)} background job(s) running")
        
        if parts:
            task_context = f"\n## Current Tasks\n" + "\n".join(f"- {p}" for p in parts)
    except Exception:
        pass
    
    # ── 团队上下文 ──
    team_context = ""
    try:
        from team import get_all_teammates, list_team_members
        members = list_team_members(cwd)
        active = get_all_teammates()
        if members:
            lines = ["\n## Team (Multi-Agent)"]
            lines.append(f"Total members: {len(members)}, Active: {len(active)}")
            lines.append("You are the **Boss** agent. You coordinate work and assign tasks.")
            for m in members:
                h = active.get(m.name)
                if h:
                    info = h.get_info()
                    lines.append(f"  - {m.name} [{info['status']}] role={m.role} task={info['current_task'] or 'none'}")
                else:
                    lines.append(f"  - {m.name} [offline] role={m.role}")
            lines.append("Use TeamSpawn to start a teammate, AssignTask to delegate work.")
            team_context = "\n".join(lines)
    except Exception:
        pass
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd=cwd,
        platform=sys.platform,
        git_info=git_info,
        project_rules=project_rules,
        memory_context=memory_context,
        task_context=task_context,
        team_context=team_context,
    )
