from __future__ import annotations
# teammate.py — s17 自治认领循环 (WORK/IDLE 两态)
# 每个队友运行的独立主循环
#
# IDLE: 排空 inbox → 扫描任务板 → 认领
# WORK: 执行任务 → 调用 LLM → 完成后通知 Boss
#
# 强制约束：
# - 独立 messages 数组，严禁共享
# - 认领必须通过 claim_task() 原子操作
# - 认领成功后重新注入 Identity 防止失忆
# - 所有通知走文件 Inbox

import time
import json
from datetime import datetime

from providers import stream_llm, AssistantTurn, TextChunk
from tools import execute_tool, get_tool_schemas
from compact import maybe_compact
from recovery import classify_error, decide_recovery, RecoveryBudget
from team import (
    drain_teammate_inbox, send_to_teammate,
    TeammateHandle,
)


# ===== 队友 System Prompt 模板 =====

TEAMMATE_SYSTEM_TEMPLATE = """You are **{name}**, an autonomous worker agent on a team.

## Your Identity
- Name: {name}
- Role: {role}
- Role Description: {role_desc}
- Current Task: {current_task}

## Team Members
{team_members}

## Available Tools
You have access to the same tools as the boss agent:
- **Read/Write/Glob/Grep** — File operations
- **Bash** — Execute shell commands
- **BackgroundRun** — Run long commands in background
- **TaskInfo/TaskComplete/TaskFail** — Manage your assigned task
- **MemorySave/MemoryLoad** — Save/load preferences

## Rules
- You are an autonomous worker. Complete your assigned task independently.
- When done, use TaskComplete to mark the task as done with a result summary.
- If stuck, use TaskFail to report failure with a reason.
- Be concise and efficient. Act, don't over-explain.
- Always read files before modifying them.
- Use Bash to verify your work.
{context_info}
"""


def _build_system_prompt(handle: TeammateHandle) -> str:
    """构建队友的 System Prompt（含身份注入）"""
    from team import list_team_members
    
    # 构建团队成员列表
    members = list_team_members(handle.cwd)
    team_lines = []
    for m in members:
        team_lines.append(f"  - {m.name} ({m.role}): {m.role_desc or m.role}")
    team_members = "\n".join(team_lines) if team_lines else "  (none)"
    
    # 当前任务信息
    current_task = "None (idle)"
    if handle.current_task_id:
        from tasks import load_task
        task = load_task(handle.cwd, handle.current_task_id)
        if task:
            current_task = f"{task.subject} (status: {task.status})"
    
    # 上下文信息
    context_info = ""
    if handle.current_task_id:
        context_info = f"\n## Important\nYou are currently working on task: {handle.current_task_id}\nComplete it using the available tools."
    
    return TEAMMATE_SYSTEM_TEMPLATE.format(
        name=handle.name,
        role=handle.role,
        role_desc=handle.role_desc,
        current_task=current_task,
        team_members=team_members,
        context_info=context_info,
    )


def _drain_inbox_to_context(handle: TeammateHandle):
    """
    排空队友的 JSONL inbox，注入到 messages 上下文。
    
    处理以下消息类型：
    - direct_message: Boss 的指令 → 追加为 user message
    - protocol: 结构化协议 → 解析并处理
    - protocol_response: 协议回复 → 追加为上下文
    """
    messages = drain_teammate_inbox(handle.cwd, handle.name)
    if not messages:
        return
    
    for msg in messages:
        msg_type = msg.get("msg_type", "text")
        content = msg.get("content", "")
        from_addr = msg.get("from_addr", "unknown")
        
        if msg_type == "protocol":
            # 结构化协议 — 解析处理
            try:
                protocol = json.loads(content)
                ptype = protocol.get("type", "")
                
                if ptype == "shutdown":
                    # 收到关机协议 → 停止循环
                    handle.messages.append({
                        "role": "user",
                        "content": f"[SHUTDOWN REQUEST from {from_addr}] {protocol.get('payload', {}).get('reason', '')}",
                    })
                    handle._stop_event.set()
                    return
                
                elif ptype == "task_assign":
                    # 任务分配
                    task_id = protocol.get("payload", {}).get("task_id", "")
                    subject = protocol.get("payload", {}).get("subject", "")
                    handle.messages.append({
                        "role": "user",
                        "content": f"[TASK ASSIGNED by {from_addr}]\nTask ID: {task_id}\nSubject: {subject}\n\nPlease complete this task.",
                    })
                    # 尝试认领
                    from tasks import claim_task
                    claimed = claim_task(handle.cwd, task_id, handle.name, handle.role)
                    if claimed:
                        handle.current_task_id = task_id
                        handle.status = "working"
                
                elif ptype == "plan_approval":
                    # 计划审批请求
                    plan = protocol.get("payload", {}).get("plan", "")
                    handle.messages.append({
                        "role": "user",
                        "content": f"[PLAN APPROVAL REQUEST from {from_addr}]\n{plan}\n\nReview this plan and provide your assessment.",
                    })
                
                else:
                    handle.messages.append({
                        "role": "user",
                        "content": f"[PROTOCOL:{ptype} from {from_addr}]\n{content}",
                    })
                    
            except json.JSONDecodeError:
                handle.messages.append({
                    "role": "user",
                    "content": f"[Message from {from_addr}]\n{content}",
                })
        
        elif msg_type == "protocol_response":
            # 协议回复
            handle.messages.append({
                "role": "user",
                "content": f"[Protocol Response from {from_addr}]\n{content}",
            })
        
        else:
            # 普通消息
            handle.messages.append({
                "role": "user",
                "content": f"[Message from {from_addr}]\n{content}",
            })


def _try_claim_task(handle: TeammateHandle) -> bool:
    """
    IDLE 状态：扫描任务板，尝试认领一个可执行的任务。
    
    Returns: 是否成功认领
    """
    from tasks import list_tasks, is_claimable, claim_task
    
    pending_tasks = list_tasks(handle.cwd, "pending")
    
    for task in pending_tasks:
        if is_claimable(task, handle.cwd, handle.role):
            claimed = claim_task(handle.cwd, task.id, handle.name, handle.role)
            if claimed:
                handle.current_task_id = task.id
                handle.status = "working"
                
                # 注入身份 + 任务上下文（防失忆）
                handle.messages.append({
                    "role": "user",
                    "content": (
                        f"[AUTO-CLAIMED TASK]\n"
                        f"Task ID: {task.id}\n"
                        f"Subject: {task.subject}\n"
                        f"Claimed by: {handle.name} ({handle.role})\n\n"
                        f"Please complete this task now."
                    ),
                })
                
                # 通知 Boss
                send_to_teammate(
                    handle.cwd, handle.name, "boss",
                    content=f"I've claimed task {task.id}: {task.subject}",
                    msg_type="direct_message",
                )
                return True
    
    return False


def _call_llm(handle: TeammateHandle) -> bool:
    """
    调用 LLM 处理当前上下文，执行工具调用。
    
    Returns: 是否产生了有效输出
    """
    config = handle.config.copy()
    config["cwd"] = handle.cwd
    if handle.model:
        config["model"] = handle.model
    
    system_prompt = _build_system_prompt(handle)
    tool_schemas = get_tool_schemas()
    recovery_budget = RecoveryBudget()
    
    MAX_ROUNDS = 10
    for round_num in range(MAX_ROUNDS):
        assistant_turn = None
        
        try:
            for event in stream_llm(
                model=config["model"],
                system=system_prompt,
                messages=handle.messages,
                tools=tool_schemas,
                config=config,
            ):
                if isinstance(event, AssistantTurn):
                    assistant_turn = event
        except Exception as e:
            # 简化版 recovery
            classified = classify_error(e)
            action = decide_recovery(classified, recovery_budget)
            if action.action == "retry":
                time.sleep(action.delay)
                continue
            elif action.action == "compact":
                # 强制压缩
                if len(handle.messages) > 4:
                    handle.messages = handle.messages[-4:]
                continue
            else:
                # 放弃
                send_to_teammate(
                    handle.cwd, handle.name, "boss",
                    content=f"Error processing task: {e}",
                )
                return False
        
        if assistant_turn is None:
            return False
        
        handle.messages.append(assistant_turn.to_message())
        
        # 没有工具调用 → 完成
        if not assistant_turn.tool_calls:
            return True
        
        # 执行工具
        for tc in assistant_turn.tool_calls:
            try:
                result = execute_tool(tc.name, tc.params, config)
            except Exception as e:
                result = f"Tool error: {e}"
            
            handle.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
    
    return True


def run_teammate_loop(handle: TeammateHandle):
    """
    队友主循环 — s17 WORK/IDLE 两态。
    
    IDLE → 排空 inbox → 扫描任务板 → 认领 → WORK
    WORK → 调用 LLM 执行任务 → 完成/失败 → IDLE
    """
    IDLE_INTERVAL = 10  # IDLE 状态轮询间隔（秒）
    MAX_CONTEXT = 50    # 消息数上限（防止上下文爆炸）
    
    while not handle._stop_event.is_set():
        try:
            if handle.status in ("idle", "online"):
                # === IDLE 状态 ===
                
                # 1. 排空 inbox
                _drain_inbox_to_context(handle)
                
                # 检查是否被关机
                if handle._stop_event.is_set():
                    break
                
                # 2. 扫描任务板，尝试认领
                if _try_claim_task(handle):
                    # 认领成功 → 进入 WORK 状态（下一轮处理）
                    continue
                
                # 3. 如果有 inbox 消息需要处理，调用 LLM
                if len(handle.messages) > 0:
                    _call_llm(handle)
                    # 上下文压缩
                    if len(handle.messages) > MAX_CONTEXT:
                        handle.messages = handle.messages[-20:]
                
                # 等待下一轮
                handle._stop_event.wait(IDLE_INTERVAL)
            
            elif handle.status == "working":
                # === WORK 状态 ===
                
                # 1. 先排空 inbox（可能有关机指令）
                _drain_inbox_to_context(handle)
                
                if handle._stop_event.is_set():
                    break
                
                # 2. 调用 LLM 执行任务
                _call_llm(handle)
                
                # 3. 检查任务是否完成
                from tasks import load_task
                task = load_task(handle.cwd, handle.current_task_id)
                
                if task and task.status in ("done", "failed"):
                    # 任务完成/失败 → 通知 Boss → 回到 IDLE
                    send_to_teammate(
                        handle.cwd, handle.name, "boss",
                        content=f"Task {handle.current_task_id} is now {task.status}: {task.result[:200]}",
                        msg_type="direct_message",
                    )
                    
                    # 通知 Boss 的主 inbox（让它能看到）
                    try:
                        from inbox import get_inbox, MessageEnvelope
                        inbox = get_inbox()
                        inbox.push(MessageEnvelope(
                            from_addr=f"teammate:{handle.name}",
                            to_addr="boss",
                            content=f"Task {handle.current_task_id} ({task.subject}) completed: {task.status}\nResult: {task.result[:200]}",
                            msg_type="notification",
                            metadata={"teammate": handle.name, "task_id": handle.current_task_id},
                        ))
                    except Exception:
                        pass
                    
                    handle.current_task_id = ""
                    handle.status = "idle"
                    # 清理上下文（保留最近几条）
                    handle.messages = handle.messages[-5:]
                else:
                    # 任务还在进行中 → 短暂等待后继续
                    handle._stop_event.wait(5)
            
            else:
                # 未知状态 → 回到 idle
                handle.status = "idle"
                
        except Exception as e:
            # 不能让循环崩溃
            try:
                send_to_teammate(
                    handle.cwd, handle.name, "boss",
                    content=f"Error in teammate loop: {e}",
                )
            except Exception:
                pass
            handle.status = "idle"
            handle._stop_event.wait(30)
    
    # 循环结束 → 清理
    handle.status = "offline"
    try:
        send_to_teammate(
            handle.cwd, handle.name, "boss",
            content=f"Teammate {handle.name} has shut down.",
        )
    except Exception:
        pass
