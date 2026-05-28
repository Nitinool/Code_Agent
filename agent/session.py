# session.py — 对话历史保存与加载
# 每个对话保存为一个 JSON 文件，存储在 ~/.my_agent/sessions/ 目录下

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional


# 对话存储目录
SESSIONS_DIR = Path.home() / ".my_agent" / "sessions"

# 单个对话文件的最大大小（MB）
MAX_SESSION_SIZE_MB = 10


def _ensure_dir():
    """确保 sessions 目录存在"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _get_session_path(name: str) -> Path:
    """获取对话文件路径"""
    # 清理文件名中的非法字符
    safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-", ".", " ")).strip()
    if not safe_name:
        safe_name = datetime.now().strftime("session_%Y%m%d_%H%M%S")
    return SESSIONS_DIR / f"{safe_name}.json"


def save_session(name: str, messages: list, config: dict) -> str:
    """
    保存当前对话。
    
    name: 对话名称（用户指定或自动生成）
    messages: AgentState.messages 列表
    config: 当前配置
    """
    _ensure_dir()
    
    # 序列化 messages（只保留可序列化的部分）
    serializable_messages = []
    for msg in messages:
        sm = {}
        if isinstance(msg, dict):
            sm = msg
        elif hasattr(msg, "__dict__"):
            # dataclass 或其他对象
            sm = {k: v for k, v in msg.__dict__.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
        else:
            sm = {"content": str(msg)}
        serializable_messages.append(sm)
    
    # 生成摘要（取第一条用户消息的前 50 字）
    summary = ""
    for msg in serializable_messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user" and content:
            summary = content[:50]
            if len(content) > 50:
                summary += "..."
            break
    
    # 构建保存数据
    session_data = {
        "name": name,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": config.get("model", ""),
        "provider": config.get("provider", ""),
        "cwd": config.get("cwd", ""),
        "message_count": len(serializable_messages),
        "summary": summary,
        "messages": serializable_messages,
    }
    
    # 检查文件大小
    json_str = json.dumps(session_data, indent=2, ensure_ascii=False)
    size_mb = len(json_str.encode("utf-8")) / (1024 * 1024)
    if size_mb > MAX_SESSION_SIZE_MB:
        # 截断过长的消息内容
        for msg in serializable_messages:
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 5000:
                msg["content"] = content[:5000] + f"\n... [truncated {len(content) - 5000} chars]"
        session_data["messages"] = serializable_messages
        json_str = json.dumps(session_data, indent=2, ensure_ascii=False)
    
    path = _get_session_path(name)
    path.write_text(json_str, encoding="utf-8")
    
    return f"Session saved: {name} ({len(serializable_messages)} messages)"


def load_session(name: str) -> Optional[dict]:
    """
    加载一个对话。返回 session 数据 dict，包含 messages。
    如果不存在返回 None。
    """
    path = _get_session_path(name)
    if not path.exists():
        # 尝试模糊匹配
        sessions = list_sessions()
        for s in sessions:
            if name.lower() in s["name"].lower():
                path = _get_session_path(s["name"])
                break
    
    if not path.exists():
        return None
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (json.JSONDecodeError, Exception):
        return None


def list_sessions(limit: int = 20) -> list[dict]:
    """
    列出所有保存的对话，按时间倒序排列。
    返回摘要列表（不含 messages 内容）。
    """
    _ensure_dir()
    
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append({
                "name": data.get("name", f.stem),
                "created_at": data.get("created_at", ""),
                "model": data.get("model", ""),
                "message_count": data.get("message_count", 0),
                "summary": data.get("summary", ""),
            })
        except Exception:
            sessions.append({
                "name": f.stem,
                "created_at": "",
                "model": "",
                "message_count": 0,
                "summary": "(corrupted session file)",
            })
    
    # 按时间倒序
    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return sessions[:limit]


def delete_session(name: str) -> str:
    """删除一个对话"""
    path = _get_session_path(name)
    if path.exists():
        path.unlink()
        return f"Session deleted: {name}"
    return f"Session not found: {name}"


def auto_save_name() -> str:
    """生成自动保存的对话名称"""
    return datetime.now().strftime("autosave_%Y%m%d_%H%M%S")
