# context.py — System Prompt 动态构建

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime


SYSTEM_PROMPT_TEMPLATE = """You are a helpful coding assistant with access to tools. You can read files, write files, search code, and execute shell commands.

## Environment
- Date: {date}
- Current directory: {cwd}
- Platform: {platform}
{git_info}

## Available Tools

### File Operations
- **Read**: Read file contents
- **Write**: Write content to files (full content overwrite)
- **Glob**: List files by pattern (e.g., '**/*.py')
- **Grep**: Search file contents by regex

### Execution
- **Bash**: Execute shell commands (run tests, install dependencies, git operations, etc.)

## Rules
- Always read files before editing them.
- When writing files, provide the COMPLETE file content, not just changes.
- Be concise. Act, don't explain unless asked.
- When searching, use Grep first to find relevant code, then Read to understand context.
- For multi-file changes, plan first, then execute step by step.
- If a command fails, read the error carefully and fix it.
{project_rules}
{active_skills}
"""


def _get_git_info(cwd: str) -> str:
    """获取 git 信息"""
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, cwd=cwd, timeout=5,
        )
        if branch.returncode != 0:
            return ""

        branch_name = branch.stdout.strip()

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
    """动态构建 System Prompt — 注入日期/工作目录/平台/git 状态/项目规则/已激活 skill"""
    cwd = config.get("cwd", os.getcwd())

    git_info = _get_git_info(cwd)

    # 项目规则（CLAUDE.md 或 AGENT.md）
    project_rules = ""
    for fname in ("CLAUDE.md", "AGENT.md"):
        rule_file = Path(cwd) / fname
        if rule_file.exists():
            try:
                content = rule_file.read_text(encoding="utf-8")
                if len(content) > 2000:
                    content = content[:2000] + "\n... (truncated)"
                project_rules = f"\n## Project Rules\n{content}"
                break
            except Exception:
                pass

    # 已激活的 Skills
    active_skills = ""
    active_names = config.get("active_skills", [])
    if active_names:
        try:
            from skills import get_active_skill_contents
            skills_content = get_active_skill_contents(active_names, cwd)
            if skills_content:
                active_skills = f"\n## Active Skills\n\nThe following skills are active. Follow their instructions carefully.\n{skills_content}"
        except Exception:
            pass

    return SYSTEM_PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cwd=cwd,
        platform=sys.platform,
        git_info=git_info,
        project_rules=project_rules,
        active_skills=active_skills,
    )
