# agent.py — 核心 Agent Loop (事件驱动版)
# 系统心脏。统一事件消息总线 + 韧性恢复 + 收件箱排空。
#
# 架构范式：每次主循环调用 LLM 之前，必须执行：
#   Drain Notifications (s13/s14) → Drain Inbox → Append to Messages → Call LLM
#
# s11: Recovery State Machine — LLM 调用外层包装错误分类器
# s12: Work Graph — Agent 可创建/查询/完成工作图任务
# s13: Runtime Tasks — 后台命令立即返回，异步通知
# s14: Cron Scheduler — 定时调度消息入 Inbox

import time
from dataclasses import dataclass, field

from providers import stream_llm, AssistantTurn, TextChunk, ToolCall
from tools import execute_tool, get_tool_schemas
from context import build_system_prompt
from compact import maybe_compact, force_compact
from permissions import check_permission, format_permission_request
from inbox import NotificationInbox, MessageEnvelope, get_inbox
from recovery import (
    classify_error, decide_recovery, RecoveryBudget, RecoveryAction, RecoveryEvent,
)


# ===== 事件类型 =====

@dataclass
class ToolStart:
    """工具开始执行"""
    name: str
    params: dict

@dataclass
class ToolEnd:
    """工具执行完成"""
    name: str
    result: str

@dataclass
class PermissionRequest:
    """请求用户授权"""
    tool_call: ToolCall
    description: str
    granted: bool = False

@dataclass
class TurnDone:
    """一轮对话完成"""
    input_tokens: int
    output_tokens: int

@dataclass
class ErrorEvent:
    """错误事件"""
    message: str

@dataclass
class InboxDrainEvent:
    """收件箱排空事件 — 通知 UI 有后台消息被注入"""
    count: int
    previews: list  # 简短预览列表


# ===== Agent State =====

@dataclass
class AgentState:
    """会话状态 — Agent Loop 的可变核心"""
    messages: list = field(default_factory=list)  # 对话历史（中性格式）
    turn_count: int = 0                           # 当前轮次
    total_input_tokens: int = 0                   # 累计输入 token
    total_output_tokens: int = 0                  # 累计输出 token
    inbox: NotificationInbox = None               # 统一收件箱
    recovery_budget: RecoveryBudget = None        # 恢复预算追踪器


def create_agent_state(inbox: NotificationInbox = None) -> AgentState:
    """创建 AgentState（含默认收件箱和恢复预算）"""
    return AgentState(
        messages=[],
        inbox=inbox or get_inbox(),
        recovery_budget=RecoveryBudget(),
    )


# ===== 核心 Agent Loop =====

def run(user_input: str, state: AgentState, config: dict, permission_callback=None):
    """
    核心 Agent Loop（事件驱动版）。
    
    流程：
    1. 追加用户消息
    2. 【新增】排空收件箱 (Drain Inbox) — 注入后台通知/调度消息
    3. 上下文压缩
    4. 动态构建 System Prompt
    5. 调用 LLM（流式）— 【新增】外层包装 Recovery State Machine
    6. 解析输出
    7. 执行工具
    8. 循环
    
    Yields:
        TextChunk | ToolStart | ToolEnd | PermissionRequest | TurnDone | ErrorEvent
               | InboxDrainEvent | RecoveryEvent
    """
    # 1. 追加用户消息
    state.messages.append({"role": "user", "content": user_input})
    
    # 每轮新的用户输入，重置恢复预算
    state.recovery_budget.reset()
    
    # 最大循环次数（防止无限循环）
    MAX_TOOL_ROUNDS = 20
    round_count = 0
    
    while round_count < MAX_TOOL_ROUNDS:
        round_count += 1
        
        # 2. 排空收件箱 (Drain Inbox) — 注入后台通知/调度消息
        drain_events = _drain_inbox(state, config)
        if drain_events:
            yield drain_events
        
        # 3. 上下文压缩（防止超出窗口限制）
        try:
            maybe_compact(state, config)
        except Exception as e:
            yield ErrorEvent(f"Context compaction error: {e}")
        
        # 4. 动态构建 System Prompt
        system_prompt = build_system_prompt(config)
        
        # 5. 获取可用工具的 schema 列表
        tool_schemas = get_tool_schemas()
        
        # 6. 调用 LLM（流式）— 外层包装 Recovery State Machine
        assistant_turn = None
        try:
            for event in _llm_call_with_recovery(
                state, config, system_prompt, tool_schemas
            ):
                if isinstance(event, RecoveryEvent):
                    yield event  # 恢复事件通知 UI
                elif isinstance(event, TextChunk):
                    yield event  # 文本流式输出
                elif isinstance(event, AssistantTurn):
                    assistant_turn = event
        except Exception as e:
            yield ErrorEvent(f"LLM call error (unrecoverable): {e}")
            break
        
        # 没有收到有效的 assistant_turn
        if assistant_turn is None:
            yield ErrorEvent("No response from LLM")
            break
        
        # 7. 追加助手消息到历史
        state.messages.append(assistant_turn.to_message())
        state.turn_count += 1
        
        # 更新 token 计数
        state.total_input_tokens += assistant_turn.input_tokens
        state.total_output_tokens += assistant_turn.output_tokens
        
        # 8. 没有工具调用 → 本轮结束
        if not assistant_turn.tool_calls:
            yield TurnDone(state.total_input_tokens, state.total_output_tokens)
            break
        
        # 9. 逐个执行工具（串行，安全且简单）
        for tc in assistant_turn.tool_calls:
            yield ToolStart(tc.name, tc.params)
            
            # 9a. 权限检查
            if not check_permission(tc, config):
                if permission_callback is not None:
                    granted = permission_callback(tc)
                else:
                    granted = _cli_permission_request(tc)
                
                if not granted:
                    result = f"[Permission denied by user for tool: {tc.name}]"
                    state.messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                    yield ToolEnd(tc.name, result)
                    continue
            
            # 9b. 执行工具
            try:
                result = execute_tool(tc.name, tc.params, config)
            except Exception as e:
                result = f"Tool execution error: {e}"
            
            # 9c. 追加工具结果到历史
            state.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
            
            yield ToolEnd(tc.name, result)
        
        # 10. 工具执行完毕，继续循环（让 LLM 决定下一步）
    else:
        # 达到最大循环次数
        yield ErrorEvent(f"Reached maximum tool rounds ({MAX_TOOL_ROUNDS}). Stopping.")
        yield TurnDone(state.total_input_tokens, state.total_output_tokens)


# ===== 收件箱排空 =====

def _drain_inbox(state: AgentState, config: dict) -> InboxDrainEvent | None:
    """
    排空收件箱 — 统一消息总线的核心操作。
    
    将所有待处理的后台通知、调度消息等注入到 messages 上下文中。
    """
    if state.inbox is None:
        return None
    
    messages = state.inbox.drain()
    if not messages:
        return None
    
    previews = []
    for msg in messages:
        # 将收件箱消息转换为上下文注入
        if msg.msg_type == "scheduled_prompt":
            # 定时调度 → 注入为用户指令
            state.messages.append({
                "role": "user",
                "content": f"[Scheduled Task Triggered]\n{msg.content}",
            })
            state.messages.append({
                "role": "assistant",
                "content": "I'll handle this scheduled task now.",
            })
        elif msg.msg_type == "notification":
            # 后台通知 → 注入为系统上下文
            state.messages.append({
                "role": "user",
                "content": f"[Background Task Notification]\n{msg.content}",
            })
            state.messages.append({
                "role": "assistant",
                "content": "Acknowledged. I'll take this into account.",
            })
        else:
            # 普通消息
            state.messages.append({
                "role": "user",
                "content": f"[Message from {msg.from_addr}]\n{msg.content}",
            })
            state.messages.append({
                "role": "assistant",
                "content": "Received.",
            })
        
        # 生成预览
        preview = msg.content[:80].replace("\n", " ")
        previews.append(f"[{msg.from_addr}] {preview}...")
    
    return InboxDrainEvent(count=len(messages), previews=previews)


# ===== 带 Recovery State Machine 的 LLM 调用 =====

def _llm_call_with_recovery(state: AgentState, config: dict,
                             system_prompt: str, tool_schemas: list):
    """
    带 Recovery State Machine 的 LLM 调用。
    
    Yields: TextChunk | AssistantTurn | RecoveryEvent
    
    恢复规则：
    - max_tokens → 注入 CONTINUE_MESSAGE 续写重试
    - prompt_too_long → force_compact() 强制摘要重试
    - rate_limit/network → 指数退避重试
    - 预算耗尽 → 抛出致命错误
    """
    budget = state.recovery_budget
    MAX_RECOVERY_ATTEMPTS = 10  # 绝对上限，防止任何形式的死循环
    total_attempts = 0
    
    while total_attempts < MAX_RECOVERY_ATTEMPTS:
        total_attempts += 1
        
        assistant_turn = None
        llm_error = None
        
        # 尝试调用 LLM
        try:
            for event in stream_llm(
                model=config["model"],
                system=system_prompt,
                messages=state.messages,
                tools=tool_schemas,
                config=config,
            ):
                if isinstance(event, TextChunk):
                    yield event
                elif isinstance(event, AssistantTurn):
                    assistant_turn = event
        except Exception as e:
            llm_error = e
        
        # 没有错误 → 正常返回
        if llm_error is None:
            if assistant_turn is not None:
                yield assistant_turn
            return
        
        # 有错误 → 分类并决定恢复策略
        classified = classify_error(llm_error)
        action = decide_recovery(classified, budget)
        
        # 通知 UI
        yield RecoveryEvent(
            category=classified.category,
            action=action.action,
            attempt=total_attempts,
            message=f"Recovery: {classified.category} → {action.action} (attempt {total_attempts})",
        )
        
        if action.action == "abort":
            # 预算耗尽 → 致命错误
            raise Exception(
                f"Fatal error after {total_attempts} recovery attempts: "
                f"{classified.message}. Budget exhausted for category '{classified.category}'."
            )
        
        elif action.action == "continue":
            # max_tokens → 注入续写补丁
            state.messages.append(action.inject_message)
        
        elif action.action == "compact":
            # prompt_too_long → 强制压缩
            force_compact(state, config)
        
        elif action.action == "retry":
            # rate_limit/network → 等待后重试
            time.sleep(action.delay)
    
    # 绝对上限兜底
    raise Exception(f"Fatal error: exceeded maximum recovery attempts ({MAX_RECOVERY_ATTEMPTS}).")


# ===== CLI 权限请求 =====

def _cli_permission_request(tool_call: ToolCall) -> bool:
    """CLI 交互式权限请求"""
    desc = format_permission_request(tool_call)
    print(f"\n{desc}")
    
    while True:
        response = input("   Allow? (y/n/a=accept-all): ").strip().lower()
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        elif response in ("a", "accept-all"):
            return True
        else:
            print("   Please enter y/n/a")


# ===== 便捷方法：单次调用 =====

def single_turn(user_input: str, state: AgentState, config: dict) -> str:
    """
    单次调用 Agent，收集所有文本输出返回。
    不涉及交互式权限，自动拒绝需要权限的操作。
    """
    output_parts = []
    for event in run(user_input, state, config, permission_callback=lambda tc: False):
        if isinstance(event, TextChunk):
            output_parts.append(event.text)
        elif isinstance(event, ErrorEvent):
            output_parts.append(f"\n[Error: {event.message}]")
    return "".join(output_parts)
