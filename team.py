from __future__ import annotations
# team.py — s15 持久队友 + s16 协作协议
# 多 Agent 架构核心：名册管理、结构化通信、审批流
#
# 强制约束：
# - 每个 Agent 有独立 messages 数组、独立 JSONL inbox
# - 严禁共享 messages 上下文
# - 高危动作使用 ProtocolEnvelope（带 request_id）
# - 认领必须加锁（原子操作）

import json
import uuid
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional
from queue import Queue, Empty


# ===================================================================
# s15 - Team Config (名册管理)
# ===================================================================

TEAM_DIR_NAME = ".team"


def _team_dir(cwd: str) -> Path:
    """获取团队目录"""
    d = Path(cwd) / TEAM_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class TeamMember:
    """团队成员定义"""
    name: str               # 唯一名称，如 "boss", "worker-1", "worker-2"
    role: str = "worker"    # "boss" | "worker"
    role_desc: str = ""     # 角色描述（注入到 system prompt）
    status: str = "offline" # "online" | "offline" | "busy"
    model: str = ""         # 使用的模型（空则用默认）
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _config_path(cwd: str) -> Path:
    return _team_dir(cwd) / "config.json"


def load_team_config(cwd: str) -> dict:
    """加载团队配置"""
    path = _config_path(cwd)
    if not path.exists():
        return {"members": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"members": []}


def save_team_config(cwd: str, config: dict):
    """保存团队配置"""
    path = _config_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def list_team_members(cwd: str) -> list[TeamMember]:
    """列出所有团队成员"""
    config = load_team_config(cwd)
    members = []
    for m_data in config.get("members", []):
        try:
            members.append(TeamMember(**m_data))
        except Exception:
            pass
    return members


def get_team_member(cwd: str, name: str) -> Optional[TeamMember]:
    """获取指定成员"""
    for m in list_team_members(cwd):
        if m.name == name:
            return m
    return None


def add_team_member(cwd: str, member: TeamMember) -> TeamMember:
    """添加团队成员"""
    config = load_team_config(cwd)
    # 检查重名
    for m in config["members"]:
        if m["name"] == member.name:
            raise ValueError(f"Member '{member.name}' already exists")
    config["members"].append(asdict(member))
    save_team_config(cwd, config)
    return member


def remove_team_member(cwd: str, name: str) -> bool:
    """移除团队成员"""
    config = load_team_config(cwd)
    original_len = len(config["members"])
    config["members"] = [m for m in config["members"] if m["name"] != name]
    if len(config["members"]) == original_len:
        return False
    save_team_config(cwd, config)
    return True


def update_member_status(cwd: str, name: str, status: str):
    """更新成员状态"""
    config = load_team_config(cwd)
    for m in config["members"]:
        if m["name"] == name:
            m["status"] = status
            break
    save_team_config(cwd, config)


# ===== 队友专属 Inbox (每个队友独立) =====

def _member_inbox_path(cwd: str, name: str) -> Path:
    """获取队友的 inbox 文件路径"""
    return _team_dir(cwd) / f"inbox_{name}.jsonl"


def send_to_teammate(cwd: str, from_addr: str, to_name: str, content: str,
                     msg_type: str = "direct_message", metadata: dict = None):
    """
    向指定队友发送消息（写入其 JSONL inbox 文件）。
    
    这是队友间通信的唯一合法通道。
    """
    msg = {
        "from_addr": from_addr,
        "to_addr": to_name,
        "content": content,
        "msg_type": msg_type,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": metadata or {},
    }
    
    inbox_path = _member_inbox_path(cwd, to_name)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(inbox_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def drain_teammate_inbox(cwd: str, name: str) -> list[dict]:
    """
    排空队友的 JSONL inbox — 原子读取并清空。
    
    Returns: 消息列表（已反序列化为 dict）
    """
    inbox_path = _member_inbox_path(cwd, name)
    if not inbox_path.exists():
        return []
    
    try:
        lines = inbox_path.read_text(encoding="utf-8").strip().split("\n")
        messages = []
        for line in lines:
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        
        # 清空文件
        inbox_path.write_text("", encoding="utf-8")
        return messages
    except Exception:
        return []


def peek_teammate_inbox(cwd: str, name: str) -> int:
    """查看队友 inbox 中有多少条待处理消息（不消费）"""
    inbox_path = _member_inbox_path(cwd, name)
    if not inbox_path.exists():
        return 0
    try:
        text = inbox_path.read_text(encoding="utf-8").strip()
        if not text:
            return 0
        return len([l for l in text.split("\n") if l.strip()])
    except Exception:
        return 0


# ===================================================================
# s16 - Team Protocols (结构化协作协议)
# ===================================================================

REQUESTS_DIR_NAME = "requests"


def _requests_dir(cwd: str) -> Path:
    d = _team_dir(cwd) / REQUESTS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ProtocolEnvelope:
    """
    结构化协议信封 — 团队间高危动作必须使用此格式。
    
    严禁使用无 request_id 的自然语言进行状态流转。
    """
    type: str              # "shutdown", "plan_approval", "task_assign", "review_request"
    from_addr: str         # 发起方
    to_addr: str           # 接收方
    request_id: str = ""   # 流水号（自动生成）
    payload: dict = field(default_factory=dict)  # 协议负载
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.request_id:
            self.request_id = f"req_{uuid.uuid4().hex[:8]}"
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class RequestRecord:
    """
    审批记录 — 追踪协议的审批状态。
    落地到 .team/requests/<request_id>.json
    """
    request_id: str
    kind: str              # 协议类型
    status: str = "pending"  # "pending" | "approved" | "rejected" | "expired"
    from_addr: str = ""
    to_addr: str = ""
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    resolved_at: str = ""
    resolution_note: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _request_path(cwd: str, request_id: str) -> Path:
    return _requests_dir(cwd) / f"{request_id}.json"


def create_request(cwd: str, protocol: ProtocolEnvelope) -> RequestRecord:
    """创建审批请求"""
    record = RequestRecord(
        request_id=protocol.request_id,
        kind=protocol.type,
        from_addr=protocol.from_addr,
        to_addr=protocol.to_addr,
        payload=protocol.payload,
    )
    path = _request_path(cwd, record.request_id)
    path.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8")
    
    # 同时发送给目标
    send_to_teammate(
        cwd, protocol.from_addr, protocol.to_addr,
        content=json.dumps(asdict(protocol), ensure_ascii=False),
        msg_type="protocol",
        metadata={"request_id": protocol.request_id, "protocol_type": protocol.type},
    )
    
    return record


def load_request(cwd: str, request_id: str) -> Optional[RequestRecord]:
    """加载审批请求"""
    path = _request_path(cwd, request_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RequestRecord(**data)
    except Exception:
        return None


def resolve_request(cwd: str, request_id: str, status: str, note: str = "") -> Optional[RequestRecord]:
    """
    解决审批请求 — approved 或 rejected。
    
    严禁直接修改状态，必须通过此函数。
    """
    record = load_request(cwd, request_id)
    if record is None:
        return None
    if record.status != "pending":
        return None  # 已处理
    
    record.status = status
    record.resolved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record.resolution_note = note
    
    path = _request_path(cwd, record.request_id)
    path.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8")
    
    # 通知发起方
    send_to_teammate(
        cwd, record.to_addr, record.from_addr,
        content=f"Request {request_id} ({record.kind}) has been {status}. {note}",
        msg_type="protocol_response",
        metadata={"request_id": request_id, "status": status},
    )
    
    return record


def list_requests(cwd: str, status: str = None) -> list[RequestRecord]:
    """列出所有审批请求"""
    r_dir = _requests_dir(cwd)
    requests = []
    for f in r_dir.glob("req_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            record = RequestRecord(**data)
            if status is None or record.status == status:
                requests.append(record)
        except Exception:
            pass
    return sorted(requests, key=lambda r: r.created_at)


# ===== 协议模板 =====

def create_shutdown_protocol(cwd: str, from_addr: str, target: str, reason: str = "") -> tuple[ProtocolEnvelope, RequestRecord]:
    """优雅关机协议"""
    protocol = ProtocolEnvelope(
        type="shutdown",
        from_addr=from_addr,
        to_addr=target,
        payload={"reason": reason or "Graceful shutdown requested"},
    )
    record = create_request(cwd, protocol)
    return protocol, record


def create_task_assign_protocol(cwd: str, from_addr: str, target: str,
                                 task_id: str, task_subject: str) -> tuple[ProtocolEnvelope, RequestRecord]:
    """任务分配协议"""
    protocol = ProtocolEnvelope(
        type="task_assign",
        from_addr=from_addr,
        to_addr=target,
        payload={"task_id": task_id, "subject": task_subject},
    )
    record = create_request(cwd, protocol)
    return protocol, record


def create_plan_approval_protocol(cwd: str, from_addr: str, target: str,
                                   plan: str) -> tuple[ProtocolEnvelope, RequestRecord]:
    """计划审批协议"""
    protocol = ProtocolEnvelope(
        type="plan_approval",
        from_addr=from_addr,
        to_addr=target,
        payload={"plan": plan},
    )
    record = create_request(cwd, protocol)
    return protocol, record


# ===================================================================
# s15 - TeammateHandle (队友实例管理)
# ===================================================================

# 全局队友注册表
_teammates: dict[str, "TeammateHandle"] = {}


@dataclass
class TeammateHandle:
    """
    队友实例句柄 — 管理一个独立的 Agent 线程。
    
    每个队友有：
    - 独立的 while 循环
    - 独立的 messages 数组
    - 专属 JSONL inbox
    - 独立的 recovery budget
    """
    name: str
    role: str
    role_desc: str
    cwd: str
    model: str
    config: dict                   # 共享的全局 config 引用
    status: str = "idle"           # "idle" | "working" | "offline"
    messages: list = field(default_factory=list)  # 独立上下文！
    current_task_id: str = ""      # 当前正在执行的任务 ID
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = None
    
    def start(self):
        """启动队友线程"""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self.status = "idle"
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"teammate-{self.name}",
        )
        self._thread.start()
        update_member_status(self.cwd, self.name, "online")
        _teammates[self.name] = self
    
    def stop(self):
        """停止队友线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.status = "offline"
        update_member_status(self.cwd, self.name, "offline")
        _teammates.pop(self.name, None)
    
    def _run_loop(self):
        """
        队友主循环 — s17 WORK/IDLE 两态。
        
        IDLE: 排空 inbox → 扫描任务板 → 认领
        WORK: 执行已认领的任务 → 完成后通知 Boss
        """
        from teammate import run_teammate_loop
        run_teammate_loop(self)
    
    def send_message(self, content: str, msg_type: str = "direct_message", metadata: dict = None):
        """向此队友发送消息"""
        send_to_teammate(
            self.cwd, "boss", self.name,
            content=content, msg_type=msg_type, metadata=metadata,
        )
    
    def get_info(self) -> dict:
        """获取队友信息"""
        inbox_count = peek_teammate_inbox(self.cwd, self.name)
        return {
            "name": self.name,
            "role": self.role,
            "role_desc": self.role_desc,
            "status": self.status,
            "current_task": self.current_task_id,
            "pending_inbox": inbox_count,
            "messages_count": len(self.messages),
        }


def spawn_teammate(cwd: str, name: str, role: str, role_desc: str,
                   config: dict, model: str = "") -> TeammateHandle:
    """
    创建并启动一个队友。
    
    Args:
        cwd: 工作目录
        name: 队友名称（唯一）
        role: 角色 ("worker")
        role_desc: 角色描述
        config: 全局配置
        model: 使用的模型（空则用默认）
    """
    # 检查是否已存在
    if name in _teammates:
        raise ValueError(f"Teammate '{name}' is already running")
    
    # 注册到名册
    member = TeamMember(
        name=name,
        role=role,
        role_desc=role_desc,
        model=model or config.get("model", ""),
    )
    try:
        add_team_member(cwd, member)
    except ValueError:
        pass  # 已在名册中
    
    # 创建 Handle 并启动
    handle = TeammateHandle(
        name=name,
        role=role,
        role_desc=role_desc,
        cwd=cwd,
        model=model or config.get("model", ""),
        config=config,
    )
    handle.start()
    return handle


def shutdown_teammate(cwd: str, name: str, reason: str = "") -> bool:
    """优雅关机"""
    handle = _teammates.get(name)
    if handle is None:
        return False
    handle.stop()
    return True


def get_teammate(name: str) -> Optional[TeammateHandle]:
    """获取队友 Handle"""
    return _teammates.get(name)


def get_all_teammates() -> dict[str, TeammateHandle]:
    """获取所有活跃队友"""
    return dict(_teammates)


def shutdown_all_teammates():
    """关闭所有队友"""
    for name in list(_teammates.keys()):
        _teammates[name].stop()
