# inbox.py — 统一消息收件箱 (Unified Message Bus)
# 所有外部触发归一化为 Message，主循环在每轮开始前排空 (Drain)

import json
import threading
from queue import Queue, Empty
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional


@dataclass
class MessageEnvelope:
    """统一消息信封 — 所有外部触发的归一化载体"""
    from_addr: str         # "user", "runtime:<task_id>", "scheduler:<schedule_id>", "system"
    to_addr: str           # "boss", "agent"
    content: str
    timestamp: str = ""
    msg_type: str = "text"  # "text", "notification", "scheduled_prompt"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class NotificationInbox:
    """
    线程安全的通知收件箱。
    
    内存队列 (Queue) + JSONL 文件持久化 (防重启丢失)。
    主循环在每次调用 LLM 前调用 drain() 排空收件箱。
    """
    
    def __init__(self, inbox_dir: str = None):
        self._queue: Queue[MessageEnvelope] = Queue()
        self._lock = threading.Lock()
        self._inbox_dir = Path(inbox_dir) if inbox_dir else Path.home() / ".my_agent" / "inbox"
        self._inbox_dir.mkdir(parents=True, exist_ok=True)
        self._pending_file = self._inbox_dir / "pending.jsonl"
        
        # 启动时恢复未处理的消息
        self._restore_pending()
    
    def push(self, message: MessageEnvelope):
        """推入一条消息（线程安全）"""
        with self._lock:
            self._queue.put(message)
            self._persist_message(message)
    
    def drain(self, max_items: int = 50) -> list[MessageEnvelope]:
        """
        排空收件箱，返回所有待处理消息（线程安全）。
        这是主循环在调用 LLM 前必须执行的核心操作。
        """
        messages = []
        with self._lock:
            while not self._queue.empty() and len(messages) < max_items:
                try:
                    msg = self._queue.get_nowait()
                    messages.append(msg)
                except Empty:
                    break
        # 排空后清理持久化文件
        if messages:
            self._clear_pending()
        return messages
    
    def has_pending(self) -> bool:
        """是否有待处理消息"""
        return not self._queue.empty()
    
    def pending_count(self) -> int:
        """待处理消息数量"""
        return self._queue.qsize()
    
    def _persist_message(self, message: MessageEnvelope):
        """持久化消息到 JSONL 文件（防重启丢失）"""
        try:
            with open(self._pending_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")
        except Exception:
            pass
    
    def _clear_pending(self):
        """清理持久化文件（消息已被消费）"""
        try:
            if self._pending_file.exists():
                self._pending_file.write_text("", encoding="utf-8")
        except Exception:
            pass
    
    def _restore_pending(self):
        """启动时恢复未处理的消息"""
        if not self._pending_file.exists():
            return
        try:
            lines = self._pending_file.read_text(encoding="utf-8").strip().split("\n")
            for line in lines:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    msg = MessageEnvelope(**data)
                    self._queue.put(msg)
                except (json.JSONDecodeError, TypeError):
                    pass
            # 恢复后重写文件（清理损坏的行）
            self._clear_pending()
        except Exception:
            pass


# ===== 全局收件箱单例 =====

_global_inbox: Optional[NotificationInbox] = None


def get_inbox() -> NotificationInbox:
    """获取全局收件箱"""
    global _global_inbox
    if _global_inbox is None:
        _global_inbox = NotificationInbox()
    return _global_inbox


def init_inbox(inbox_dir: str = None) -> NotificationInbox:
    """初始化全局收件箱"""
    global _global_inbox
    _global_inbox = NotificationInbox(inbox_dir)
    return _global_inbox
