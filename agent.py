# agent.py — Agent 核心循环
# 流式接收 LLM 输出 → 检测工具调用 → 权限检查 → 执行工具 → 回灌结果 → 继续

from dataclasses import dataclass, field
from typing import Generator

from providers import stream_llm, TextChunk, ThinkingChunk, ToolCall, AssistantTurn
from tools import execute_tool, get_tool_schemas
from permissions import check_permission, format_permission_request
from context import build_system_prompt
from compact import maybe_compact


# ===== Agent 状态 =====

@dataclass
class AgentState:
    """单次对话的运行时状态"""
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0


# ===== 事件类型（给 UI 渲染用）=====

@dataclass
class TextEvent:
    """流式文本输出"""
    text: str

@dataclass
class ThinkingEvent:
    """思考过程"""
    text: str

@dataclass
class ToolCallEvent:
    """工具调用即将执行"""
    name: str
    params: dict

@dataclass
class ToolResultEvent:
    """工具执行完成"""
    name: str
    result: str

@dataclass
class PermissionRequestEvent:
    """需要用户授权"""
    tool_call: ToolCall
    message: str

@dataclass
class TurnEndEvent:
    """一轮 LLM 调用结束（可能还有下一轮）"""
    has_more: bool

@dataclass
class DoneEvent:
    """整个 agent 循环结束（用户可以输入下一条消息）"""
    pass


# ===== 主循环 =====

def run_agent_turn(state: AgentState, user_input: str, config: dict,
                   permission_callback=None) -> Generator:
    """
    运行一轮完整的 agent 交互。
    
    user_input: 用户的本轮输入（如果为 None 或空，跳过添加用户消息）
    permission_callback: (tool_call) -> bool，用户是否授权
    
    Yields: TextEvent | ThinkingEvent | ToolCallEvent | ToolResultEvent 
            | PermissionRequestEvent | TurnEndEvent | DoneEvent
    """
    # 添加用户消息
    if user_input:
        state.messages.append({"role": "user", "content": user_input})

    max_iterations = 30  # 防止无限循环
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        state.turn_count += 1

        # 上下文压缩检查
        maybe_compact(state, config)

        # 构建 system prompt（每轮重新构建以注入最新上下文）
        system_prompt = build_system_prompt(config)

        # 调用 LLM（流式）
        assistant_turn = None
        try:
            for event in stream_llm(
                model=config["model"],
                system=system_prompt,
                messages=state.messages,
                tools=get_tool_schemas(),
                config=config,
            ):
                if isinstance(event, TextChunk):
                    yield TextEvent(text=event.text)
                elif isinstance(event, ThinkingChunk):
                    yield ThinkingEvent(text=event.text)
                elif isinstance(event, AssistantTurn):
                    assistant_turn = event
        except Exception as e:
            yield TextEvent(text=f"\n[Stream error: {e}]")
            yield DoneEvent()
            return

        if assistant_turn is None:
            yield TextEvent(text="\n[No response from model]")
            yield DoneEvent()
            return

        # 累计 token 用量
        state.total_input_tokens += assistant_turn.input_tokens
        state.total_output_tokens += assistant_turn.output_tokens

        # 将 assistant 消息存入历史
        state.messages.append(assistant_turn.to_message())

        # 没有工具调用 — 本次对话结束
        if not assistant_turn.tool_calls:
            yield TurnEndEvent(has_more=False)
            yield DoneEvent()
            return

        # 有工具调用 — 依次执行
        yield TurnEndEvent(has_more=True)

        for tool_call in assistant_turn.tool_calls:
            yield ToolCallEvent(name=tool_call.name, params=tool_call.params)

            # 权限检查
            allowed = check_permission(tool_call, config)
            if not allowed:
                if permission_callback is None:
                    # 没有回调，默认拒绝
                    result = f"Permission denied: tool '{tool_call.name}' requires user approval"
                else:
                    msg = format_permission_request(tool_call)
                    yield PermissionRequestEvent(tool_call=tool_call, message=msg)
                    approved = permission_callback(tool_call)
                    if not approved:
                        result = f"User denied permission to execute '{tool_call.name}'"
                    else:
                        result = execute_tool(tool_call.name, tool_call.params, config)
            else:
                result = execute_tool(tool_call.name, tool_call.params, config)

            yield ToolResultEvent(name=tool_call.name, result=result)

            # 将工具结果加入消息历史
            state.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        # 工具执行完成 → 进入下一轮 LLM 调用，让模型继续

    # 达到最大轮数
    yield TextEvent(text=f"\n[Reached max iterations ({max_iterations})]")
    yield DoneEvent()