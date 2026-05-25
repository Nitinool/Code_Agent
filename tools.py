# tools.py — 工具注册表 + 内置工具实现
# 只保留文件操作和命令执行核心工具：Read / Write / Bash / Glob / Grep

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
        filtered = []
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
        for f in sorted(files):
            parts = Path(f).parts
            if any(p in skip_dirs for p in parts):
                continue
            filtered.append(f)

        if not filtered:
            return "No files found."

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
            skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea"}
            if any(p in skip_dirs for p in f.parts):
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
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

def register_builtin_tools():
    """注册所有内置工具：Read / Write / Bash / Glob / Grep"""

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