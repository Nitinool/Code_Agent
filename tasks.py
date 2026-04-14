# tasks.py — s12 工作图 + s13 后台运行时 + s14 定时调度器
# 严格分离"工作目标" (TaskRecord) 与"执行槽位" (RuntimeTaskRecord)

import json
import uuid
import time
import threading
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable


# ===================================================================
# s12 - Durable Work Graph (工作图任务)
# ===================================================================

TASKS_DIR_NAME = ".tasks"


def _tasks_dir(cwd: str) -> Path:
    """获取任务存储目录"""
    d = Path(cwd) / TASKS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class TaskRecord:
    """
    工作图中的任务节点 — 代表宏大的业务目标。
    
    与 RuntimeTaskRecord 严格分离！
    TaskRecord 追踪的是"要做什么"，不是"机器在跑什么"。
    """
    id: str
    subject: str                              # 任务标题
    status: str = "pending"                   # pending | in_progress | done | failed | cancelled
    blockedBy: list = field(default_factory=list)  # 依赖的任务 ID 列表
    blocks: list = field(default_factory=list)     # 被哪些任务依赖
    owner: str = ""                           # 认领者（agent 名称）
    claim_role: str = ""                      # 认领角色要求
    created_at: str = ""
    updated_at: str = ""
    result: str = ""                          # 任务结果/输出
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.updated_at:
            self.updated_at = self.created_at


def _task_path(cwd: str, task_id: str) -> Path:
    """获取单个任务文件路径"""
    return _tasks_dir(cwd) / f"{task_id}.json"


def create_task(cwd: str, subject: str, blocked_by: list = None,
                claim_role: str = "") -> TaskRecord:
    """创建一个新任务"""
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    task = TaskRecord(
        id=task_id,
        subject=subject,
        blockedBy=blocked_by or [],
        claim_role=claim_role,
    )
    _save_task(cwd, task)
    return task


def _save_task(cwd: str, task: TaskRecord):
    """持久化任务到 JSON 文件"""
    task.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    path = _task_path(cwd, task.id)
    path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False), encoding="utf-8")


def load_task(cwd: str, task_id: str) -> Optional[TaskRecord]:
    """加载单个任务"""
    path = _task_path(cwd, task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TaskRecord(**data)
    except Exception:
        return None


def list_tasks(cwd: str, status: str = None) -> list[TaskRecord]:
    """列出所有任务，可选按状态过滤"""
    tasks_dir = _tasks_dir(cwd)
    tasks = []
    for f in tasks_dir.glob("task_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            task = TaskRecord(**data)
            if status is None or task.status == status:
                tasks.append(task)
        except Exception:
            pass
    return sorted(tasks, key=lambda t: t.created_at)


def is_ready(task: TaskRecord, cwd: str) -> bool:
    """
    判断任务是否可执行：状态为 pending 且所有 blockedBy 任务已完成。
    """
    if task.status != "pending":
        return False
    for dep_id in task.blockedBy:
        dep = load_task(cwd, dep_id)
        if dep is None or dep.status != "done":
            return False
    return True


def complete_task(cwd: str, task_id: str, result: str = "") -> Optional[TaskRecord]:
    """
    完成任务 — 自动级联解锁下游任务（从他们的 blockedBy 中移除自己）。
    
    注意：级联不是移除 blockedBy，而是让下游的 is_ready() 自然变为 True。
    所以这里只需标记自己为 done。
    """
    task = load_task(cwd, task_id)
    if task is None:
        return None
    task.status = "done"
    task.result = result
    _save_task(cwd, task)
    return task


def fail_task(cwd: str, task_id: str, reason: str = "") -> Optional[TaskRecord]:
    """标记任务为失败"""
    task = load_task(cwd, task_id)
    if task is None:
        return None
    task.status = "failed"
    task.result = reason
    _save_task(cwd, task)
    return task


def delete_task(cwd: str, task_id: str) -> bool:
    """删除一个任务"""
    path = _task_path(cwd, task_id)
    if path.exists():
        path.unlink()
        return True
    return False


# ===== 原子认领锁 =====
_claim_lock = threading.Lock()


def claim_task(cwd: str, task_id: str, owner: str, role: str = "") -> Optional[TaskRecord]:
    """
    原子认领任务 — 加锁防止竞态条件。
    
    流程：
    1. 加锁
    2. 读取任务，检查 is_ready()
    3. 检查 claim_role 匹配
    4. 设置 owner + status=in_progress
    5. 写入审计日志 claim_events.jsonl
    6. 保存并返回
    
    Returns: 认领成功返回 TaskRecord，失败返回 None
    """
    with _claim_lock:
        task = load_task(cwd, task_id)
        if task is None:
            return None
        if not is_ready(task, cwd):
            return None
        if task.claim_role and role and task.claim_role != role:
            return None
        if task.owner:  # 已被认领
            return None
        
        task.owner = owner
        task.status = "in_progress"
        _save_task(cwd, task)
        
        # 写入审计日志
        _log_claim_event(cwd, task_id, owner, role)
        
        return task


def is_claimable(task: TaskRecord, cwd: str, role: str = "") -> bool:
    """判断任务是否可被认领（不加锁，用于扫描）"""
    if not is_ready(task, cwd):
        return False
    if task.owner:
        return False
    if task.claim_role and role and task.claim_role != role:
        return False
    return True


def _log_claim_event(cwd: str, task_id: str, owner: str, role: str):
    """写入认领审计日志"""
    log_path = Path(cwd) / ".tasks" / "claim_events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": task_id,
        "owner": owner,
        "role": role,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ===================================================================
# s13 - RuntimeTaskRecord (后台运行时)
# ===================================================================

RUNTIME_DIR_NAME = ".runtime"


def _runtime_dir(cwd: str) -> Path:
    d = Path(cwd) / RUNTIME_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class RuntimeTaskRecord:
    """
    运行时任务 — 代表正在消耗 CPU 的具体进程。
    
    与 TaskRecord 严格分离！
    RuntimeTaskRecord 追踪的是"机器在跑什么"，不是"要做什么"。
    """
    id: str
    type: str                  # "bash", "script"
    command: str               # 执行的命令
    status: str = "running"    # running | completed | failed | cancelled
    output_file: str = ""      # 完整日志落盘路径
    notified: bool = False     # 主循环是否已查收
    exit_code: int = -1
    started_at: str = ""
    finished_at: str = ""
    preview: str = ""          # 摘要预览
    
    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _runtime_task_path(cwd: str, task_id: str) -> Path:
    return _runtime_dir(cwd) / f"{task_id}.json"


def _save_runtime_task(cwd: str, rt: RuntimeTaskRecord):
    path = _runtime_task_path(cwd, rt.id)
    path.write_text(json.dumps(asdict(rt), indent=2, ensure_ascii=False), encoding="utf-8")


def load_runtime_task(cwd: str, task_id: str) -> Optional[RuntimeTaskRecord]:
    path = _runtime_task_path(cwd, task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RuntimeTaskRecord(**data)
    except Exception:
        return None


def list_runtime_tasks(cwd: str, status: str = None) -> list[RuntimeTaskRecord]:
    rt_dir = _runtime_dir(cwd)
    tasks = []
    for f in rt_dir.glob("rt_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rt = RuntimeTaskRecord(**data)
            if status is None or rt.status == status:
                tasks.append(rt)
        except Exception:
            pass
    return sorted(tasks, key=lambda t: t.started_at, reverse=True)


def _background_worker(rt: RuntimeTaskRecord, cwd: str, config: dict):
    """
    后台工作线程 — 执行命令并异步通知。
    
    强制约束：
    - 必须立即返回 task_id，绝对不能阻塞主循环
    - 完整日志落盘为文件
    - 仅将 preview 摘要和状态放入 Notification Inbox
    """
    output_path = Path(rt.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        proc = subprocess.Popen(
            rt.command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=config.get("cwd", cwd),
        )
        
        # 实时读取输出并写文件
        output_lines = []
        with open(output_path, "w", encoding="utf-8") as f:
            for line in proc.stdout:
                output_lines.append(line)
                f.write(line)
                f.flush()
        
        proc.wait()
        rt.exit_code = proc.returncode
        rt.status = "completed" if proc.returncode == 0 else "failed"
        
    except Exception as e:
        rt.status = "failed"
        rt.exit_code = -1
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"Error: {e}")
    
    rt.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 生成预览（头尾各 10 行）
    total_lines = len(output_lines)
    if total_lines <= 20:
        rt.preview = "".join(output_lines)
    else:
        head = "".join(output_lines[:10])
        tail = "".join(output_lines[-10:])
        rt.preview = f"{head}\n... [{total_lines - 20} lines omitted] ...\n{tail}"
    
    # 限制 preview 大小
    if len(rt.preview) > 4000:
        rt.preview = rt.preview[:2000] + "\n... [truncated] ...\n" + rt.preview[-2000:]
    
    _save_runtime_task(cwd, rt)
    
    # 推送通知到 Inbox
    try:
        from inbox import get_inbox, MessageEnvelope
        inbox = get_inbox()
        status_emoji = "✓" if rt.status == "completed" else "✗"
        inbox.push(MessageEnvelope(
            from_addr=f"runtime:{rt.id}",
            to_addr="boss",
            content=(
                f"{status_emoji} Background task completed\n"
                f"  Task ID: {rt.id}\n"
                f"  Command: {rt.command}\n"
                f"  Status: {rt.status}\n"
                f"  Exit code: {rt.exit_code}\n"
                f"  Duration: {rt.started_at} → {rt.finished_at}\n\n"
                f"Output preview:\n{rt.preview}"
            ),
            msg_type="notification",
            metadata={"runtime_task_id": rt.id, "status": rt.status},
        ))
    except Exception:
        pass  # Inbox 不可用时静默失败


def background_run(command: str, cwd: str, config: dict) -> RuntimeTaskRecord:
    """
    启动后台任务。
    
    强制约束：立即返回 RuntimeTaskRecord，绝对不阻塞主循环。
    """
    rt_id = f"rt_{uuid.uuid4().hex[:8]}"
    output_file = str(_runtime_dir(cwd) / f"{rt_id}_output.log")
    
    rt = RuntimeTaskRecord(
        id=rt_id,
        type="bash",
        command=command,
        output_file=output_file,
    )
    _save_runtime_task(cwd, rt)
    
    # 启动后台线程
    thread = threading.Thread(
        target=_background_worker,
        args=(rt, cwd, config),
        daemon=True,
        name=f"bg-{rt_id}",
    )
    thread.start()
    
    return rt


def cancel_runtime_task(cwd: str, task_id: str) -> str:
    """取消后台任务（标记为 cancelled，实际进程可能仍在运行）"""
    rt = load_runtime_task(cwd, task_id)
    if rt is None:
        return f"Runtime task not found: {task_id}"
    if rt.status != "running":
        return f"Runtime task is not running (status: {rt.status})"
    rt.status = "cancelled"
    rt.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_runtime_task(cwd, rt)
    return f"Cancelled runtime task: {task_id}"


def get_runtime_output(cwd: str, task_id: str) -> str:
    """获取后台任务的完整输出"""
    rt = load_runtime_task(cwd, task_id)
    if rt is None:
        return f"Runtime task not found: {task_id}"
    output_path = Path(rt.output_file)
    if not output_path.exists():
        return f"Output file not found: {rt.output_file}"
    try:
        return output_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading output: {e}"


# ===================================================================
# s14 - Cron Scheduler (定时调度器)
# ===================================================================

SCHEDULES_DIR_NAME = ".schedules"


def _schedules_dir(cwd: str) -> Path:
    d = Path(cwd) / SCHEDULES_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class ScheduleRecord:
    """
    定时调度记录 — 落地持久化，防重启丢失。
    
    机制：后台 check_loop 定期检查。
    当时间匹配且当前分钟未触发过时，不直接执行业务逻辑，
    而是生成 scheduled_prompt 消息投入 Notification Inbox。
    """
    id: str
    cron_expr: str            # "*/5 * * * *" (分钟 小时 日 月 星期)
    prompt: str               # 到时间后发送给 Agent 的指令
    enabled: bool = True
    last_fired_at: str = ""
    created_at: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _schedule_path(cwd: str, schedule_id: str) -> Path:
    return _schedules_dir(cwd) / f"{schedule_id}.json"


def _save_schedule(cwd: str, schedule: ScheduleRecord):
    path = _schedule_path(cwd, schedule.id)
    path.write_text(json.dumps(asdict(schedule), indent=2, ensure_ascii=False), encoding="utf-8")


def create_schedule(cwd: str, cron_expr: str, prompt: str) -> ScheduleRecord:
    """创建一个定时调度"""
    sched_id = f"sched_{uuid.uuid4().hex[:8]}"
    sched = ScheduleRecord(
        id=sched_id,
        cron_expr=cron_expr,
        prompt=prompt,
    )
    _save_schedule(cwd, sched)
    return sched


def load_schedule(cwd: str, schedule_id: str) -> Optional[ScheduleRecord]:
    path = _schedule_path(cwd, schedule_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ScheduleRecord(**data)
    except Exception:
        return None


def list_schedules(cwd: str) -> list[ScheduleRecord]:
    s_dir = _schedules_dir(cwd)
    schedules = []
    for f in s_dir.glob("sched_*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            schedules.append(ScheduleRecord(**data))
        except Exception:
            pass
    return sorted(schedules, key=lambda s: s.created_at)


def delete_schedule(cwd: str, schedule_id: str) -> bool:
    path = _schedule_path(cwd, schedule_id)
    if path.exists():
        path.unlink()
        return True
    return False


def toggle_schedule(cwd: str, schedule_id: str, enabled: bool = None) -> Optional[ScheduleRecord]:
    """启用/禁用调度"""
    sched = load_schedule(cwd, schedule_id)
    if sched is None:
        return None
    sched.enabled = enabled if enabled is not None else not sched.enabled
    _save_schedule(cwd, sched)
    return sched


# ===== Cron 表达式解析 (简化版) =====

def _parse_cron_field(field: str, current_value: int) -> bool:
    """解析单个 cron 字段，判断当前值是否匹配"""
    if field == "*":
        return True
    
    # */5 形式
    if field.startswith("*/"):
        step = int(field[2:])
        return current_value % step == 0
    
    # 1,3,5 形式
    if "," in field:
        values = [int(v.strip()) for v in field.split(",")]
        return current_value in values
    
    # 1-5 形式
    if "-" in field:
        parts = field.split("-")
        return int(parts[0]) <= current_value <= int(parts[1])
    
    # 直接数字
    return int(field) == current_value


def should_fire(cron_expr: str) -> bool:
    """判断当前时间是否匹配 cron 表达式"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    
    now = datetime.now()
    fields = [
        (parts[0], now.minute),      # 分钟
        (parts[1], now.hour),         # 小时
        (parts[2], now.day),          # 日
        (parts[3], now.month),        # 月
        (parts[4], now.weekday()),    # 星期 (0=Monday)
    ]
    
    return all(_parse_cron_field(f, v) for f, v in fields)


# ===== 调度器后台线程 =====

class CronScheduler:
    """
    定时调度器 — 后台 check_loop。
    
    强制约束：严禁直接执行业务逻辑！
    只生成 scheduled_prompt 消息投入 Notification Inbox。
    由主循环在下一轮拉取并转化为 LLM 的行动指令。
    """
    
    def __init__(self, cwd: str, check_interval: int = 30):
        """
        Args:
            cwd: 工作目录
            check_interval: 检查间隔（秒），默认 30 秒
        """
        self.cwd = cwd
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        """启动后台检查线程"""
        if self._thread is not None and self._thread.is_alive():
            return
        
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._check_loop,
            daemon=True,
            name="cron-scheduler",
        )
        self._thread.start()
    
    def stop(self):
        """停止后台检查线程"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
    
    def _check_loop(self):
        """后台循环：定期检查是否有调度需要触发"""
        while not self._stop_event.is_set():
            try:
                self._check_and_fire()
            except Exception:
                pass  # 调度器不能崩溃
            self._stop_event.wait(self.check_interval)
    
    def _check_and_fire(self):
        """检查所有调度，匹配则推送消息到 Inbox"""
        schedules = list_schedules(self.cwd)
        now_minute = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        for sched in schedules:
            if not sched.enabled:
                continue
            
            # 防止同一分钟重复触发
            if sched.last_fired_at and sched.last_fired_at[:16] == now_minute:
                continue
            
            if should_fire(sched.cron_expr):
                # 更新触发时间
                sched.last_fired_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _save_schedule(self.cwd, sched)
                
                # 推送消息到 Inbox（严禁直接执行！）
                try:
                    from inbox import get_inbox, MessageEnvelope
                    inbox = get_inbox()
                    inbox.push(MessageEnvelope(
                        from_addr=f"scheduler:{sched.id}",
                        to_addr="boss",
                        content=sched.prompt,
                        msg_type="scheduled_prompt",
                        metadata={
                            "schedule_id": sched.id,
                            "cron_expr": sched.cron_expr,
                        },
                    ))
                except Exception:
                    pass
