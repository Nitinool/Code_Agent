# providers.py — LLM 提供者适配
# 智谱清言和百炼千问都兼容 OpenAI API 格式，统一使用 openai SDK

from openai import OpenAI
from dataclasses import dataclass, field


# ===== 事件类型 =====

@dataclass
class TextChunk:
    """流式文本片段"""
    text: str

@dataclass
class ThinkingChunk:
    """思考过程片段（部分模型支持）"""
    text: str

@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    params: dict

@dataclass
class AssistantTurn:
    """完整的助手回复"""
    content: str
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = ""   # "stop" | "length" | "tool_calls" | ""
    truncated: bool = False   # True 表示输出被 max_tokens 截断

    def to_message(self) -> dict:
        """转换为中性消息格式"""
        msg = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": _json_dumps(tc.params),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


# ===== JSON 工具函数 =====

import json

def _json_dumps(obj: dict) -> str:
    """安全序列化 dict 为 JSON 字符串"""
    return json.dumps(obj, ensure_ascii=False)

def _json_loads(s: str) -> dict:
    """安全反序列化 JSON 字符串为 dict"""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


# ===== 消息格式转换 =====
# 内部使用中性消息格式，调用 API 时转为 OpenAI 格式

def messages_to_openai(messages: list[dict], system: str) -> list[dict]:
    """
    将中性消息转换为 OpenAI API 格式。
    
    中性格式:
      - {"role": "user", "content": "..."}
      - {"role": "assistant", "content": "...", "tool_calls": [...]}  (可选)
      - {"role": "tool", "tool_call_id": "...", "content": "..."}
    
    OpenAI 格式基本一致，但需要确保 tool_calls 格式正确。
    """
    result = []
    
    # system 消息放在最前面
    if system:
        result.append({"role": "system", "content": system})
    
    for m in messages:
        role = m["role"]
        
        if role == "tool":
            # tool 结果消息
            result.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            })
        elif role == "assistant" and "tool_calls" in m:
            # 带工具调用的 assistant 消息
            result.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": m["tool_calls"],
            })
        else:
            # 普通消息
            result.append({
                "role": role,
                "content": m.get("content", ""),
            })
    
    return result


def tools_to_openai_schema(tool_schemas: list[dict]) -> list[dict]:
    """
    将内部工具 schema 转换为 OpenAI function calling 格式。
    
    内部格式: {"name": "...", "description": "...", "parameters": {...}}
    OpenAI 格式: {"type": "function", "function": {...}}
    """
    result = []
    for s in tool_schemas:
        # 兼容两种格式：已有 function 包裹的 和 没有的
        if "type" in s and s["type"] == "function":
            result.append(s)
        else:
            result.append({
                "type": "function",
                "function": {
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "parameters": s.get("parameters", s),
                }
            })
    return result


# ===== 默认输出上限 =====
# 历史演进：4096 (GPT-3.5 时代) → 8192 (够用但聊嗨会断) → 16384 (当前)
# 中文回复尤其耗 token（1 中文 ≈ 1.5-2 token），所以中文长回答场景需要更大值。
# 真正权威的默认值定义在 config.py，这里只是 fallback 用。
DEFAULT_MAX_TOKENS = 16384


# ===== 核心 LLM 调用 =====

def stream_llm(model: str, system: str, messages: list[dict], 
               tools: list[dict], config: dict):
    """
    统一的 LLM 流式调用入口。
    
    智谱清言和百炼千问都兼容 OpenAI API，统一走 OpenAI SDK。
    
    Yields:
        TextChunk | ThinkingChunk | AssistantTurn
    """
    api_key = config["api_key"]
    base_url = config.get("base_url")
    
    # 构建 OpenAI client
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    
    client = OpenAI(**client_kwargs)
    
    # 转换消息格式
    openai_messages = messages_to_openai(messages, system)
    
    # 转换工具格式
    openai_tools = tools_to_openai_schema(tools) if tools else None
    
    # 调用参数
    call_kwargs = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": config.get("max_tokens", DEFAULT_MAX_TOKENS),
        "temperature": config.get("temperature", 0.7),
        "stream": True,
        "stream_options": {"include_usage": True},  # 让最后一个 chunk 带 usage
    }
    if openai_tools:
        call_kwargs["tools"] = openai_tools
    
    # 流式调用
    try:
        stream = client.chat.completions.create(**call_kwargs)
    except Exception as e:
        yield TextChunk(f"\n[API Error: {e}]")
        yield AssistantTurn(content=f"[API Error: {e}]", tool_calls=[])
        return
    
    # 解析流式响应
    content_parts = []
    tool_calls_map = {}  # index -> {id, name, arguments_str}
    finish_reason = ""
    input_tokens = 0
    output_tokens = 0
    
    for chunk in stream:
        # 末尾 usage chunk 可能没有 choices
        if getattr(chunk, "usage", None):
            input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
        
        if not chunk.choices:
            continue
        
        choice = chunk.choices[0]
        delta = choice.delta
        
        # 记录结束原因（最后一个非空的 finish_reason 为准）
        if choice.finish_reason:
            finish_reason = choice.finish_reason
        
        # 文本内容
        if delta.content:
            content_parts.append(delta.content)
            yield TextChunk(delta.content)
        
        # 工具调用
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_calls_map:
                    tool_calls_map[idx] = {
                        "id": "",
                        "name": "",
                        "arguments": "",
                    }
                
                if tc_delta.id:
                    tool_calls_map[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_calls_map[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_calls_map[idx]["arguments"] += tc_delta.function.arguments
    
    # 构建最终的 AssistantTurn
    final_content = "".join(content_parts)
    final_tool_calls = []
    
    for idx in sorted(tool_calls_map.keys()):
        tc_data = tool_calls_map[idx]
        params = _json_loads(tc_data["arguments"])
        final_tool_calls.append(ToolCall(
            id=tc_data["id"],
            name=tc_data["name"],
            params=params,
        ))
    
    # 截断检测
    truncated = (finish_reason == "length")
    
    # 如果被截断，在文本末尾追加显式标记并提示用户
    if truncated:
        truncation_notice = (
            f"\n\n[⚠ Output truncated at max_tokens={call_kwargs['max_tokens']}. "
            f"Try a larger AGENT_MAX_TOKENS, or ask me to continue.]"
        )
        final_content += truncation_notice
        yield TextChunk(truncation_notice)
    
    turn = AssistantTurn(
        content=final_content,
        tool_calls=final_tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
        truncated=truncated,
    )
    
    yield turn


# ===== 非流式调用（用于摘要压缩等场景） =====

def call_llm(model: str, system: str, messages: list[dict], config: dict) -> str:
    """非流式调用，直接返回完整文本响应"""
    api_key = config["api_key"]
    base_url = config.get("base_url")
    
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    
    client = OpenAI(**client_kwargs)
    openai_messages = messages_to_openai(messages, system)
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=openai_messages,
            max_tokens=min(config.get("max_tokens", DEFAULT_MAX_TOKENS), 2048),  # 摘要用较短输出
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"[Error generating summary: {e}]"
