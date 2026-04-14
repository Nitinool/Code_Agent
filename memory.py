# memory.py — 跨会话记忆（极简版）
# 一个 JSON 文件存用户偏好，启动时加载到 config

import json
from pathlib import Path
from datetime import datetime


# 记忆文件路径
MEMORY_DIR = Path.home() / ".my_agent"
MEMORY_FILE = MEMORY_DIR / "memory.json"

# 最大记忆条数（防止文件过大）
MAX_MEMORY_ENTRIES = 50


def load_memory() -> dict:
    """启动时加载所有记忆"""
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            return data
        except (json.JSONDecodeError, Exception):
            return {}
    return {}


def save_memory(key: str, value: str) -> str:
    """
    保存一条记忆。
    
    key: 记忆的键（如 "preferred_language", "project_style" 等）
    value: 记忆的值
    
    原则：只保存"人"的信息：偏好、反馈、决策理由。
    绝对不要保存代码状态或当前任务。
    """
    data = load_memory()
    
    data[key] = {
        "value": value,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    
    # 如果超过最大条数，删除最旧的
    if len(data) > MAX_MEMORY_ENTRIES:
        # 按 updated_at 排序，保留最新的
        sorted_items = sorted(
            data.items(),
            key=lambda x: x[1].get("updated_at", ""),
            reverse=True,
        )
        data = dict(sorted_items[:MAX_MEMORY_ENTRIES])
    
    # 保存到文件
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    
    return f"Saved memory: {key}"


def delete_memory(key: str) -> str:
    """删除一条记忆"""
    data = load_memory()
    if key in data:
        del data[key]
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return f"Deleted memory: {key}"
    return f"Memory key not found: {key}"


def load_memory_summary() -> str:
    """
    加载为 System Prompt 的一段文字。
    只返回摘要，不返回完整内容。
    """
    data = load_memory()
    if not data:
        return ""
    
    lines = ["User preferences and context:"]
    for key, entry in data.items():
        value = entry.get("value", "")
        updated = entry.get("updated_at", "")
        lines.append(f"- {key}: {value}  (updated: {updated})")
    
    return "\n".join(lines)


# ===== Agent 可用的记忆工具 =====

def _memory_save(params: dict, config: dict) -> str:
    """Agent 调用：保存一条记忆"""
    key = params.get("key", "")
    value = params.get("value", "")
    
    if not key or not value:
        return "Error: both 'key' and 'value' are required"
    
    return save_memory(key, value)


def _memory_load(params: dict, config: dict) -> str:
    """Agent 调用：加载所有记忆"""
    data = load_memory()
    if not data:
        return "No memories saved yet."
    
    lines = []
    for key, entry in data.items():
        value = entry.get("value", "")
        updated = entry.get("updated_at", "")
        lines.append(f"- {key}: {value}  (updated: {updated})")
    
    return "\n".join(lines)


def _memory_delete(params: dict, config: dict) -> str:
    """Agent 调用：删除一条记忆"""
    key = params.get("key", "")
    if not key:
        return "Error: 'key' is required"
    return delete_memory(key)
