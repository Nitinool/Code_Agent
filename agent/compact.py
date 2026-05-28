# compact.py — 上下文压缩
# 两级压缩：微压缩（截断旧 tool_result）+ 摘要压缩（LLM 总结）


# ===== Token 估算 =====

# 平均 1 个中文字符 ≈ 1.5 token，1 个英文单词 ≈ 1.3 token
# 简单估算：4 字符 ≈ 1 token
CHARS_PER_TOKEN = 4


def estimate_tokens(messages: list[dict]) -> int:
    """粗略估算消息列表的 token 数"""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content) // CHARS_PER_TOKEN
        elif isinstance(content, list):
            # content 可能是 list of parts
            for part in content:
                if isinstance(part, str):
                    total += len(part) // CHARS_PER_TOKEN
                elif isinstance(part, dict):
                    total += len(str(part)) // CHARS_PER_TOKEN
        
        # tool_calls 也占 token
        if "tool_calls" in m:
            for tc in m["tool_calls"]:
                total += len(str(tc)) // CHARS_PER_TOKEN
    
    return total


# ===== 模型上下文限制 =====

CONTEXT_LIMITS = {
    # DeepSeek（默认，cixtech 端点）— V4-Pro 支持 1M 上下文
    "deepseek-v4-pro": 1_000_000,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    # Qwen / 通义千问
    "qwen-plus": 131_072,
    "qwen-max": 32_768,
    "qwen-turbo": 131_072,
    "qwen-long": 10_000_000,
    # GLM / 智谱清言
    "glm-4-plus": 128_000,
    "glm-4": 128_000,
    "glm-4-flash": 128_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4": 128_000,
    "gpt-3.5-turbo": 16_385,
}

# 默认上下文限制（未知模型 fallback）
DEFAULT_CONTEXT_LIMIT = 128_000

# 默认模型（与 config.py 保持一致）
DEFAULT_MODEL = "deepseek-v4-pro"


def get_context_limit(model: str) -> int:
    """获取模型的上下文窗口限制（支持前缀匹配，例如 deepseek-v4-pro-xxx）"""
    if model in CONTEXT_LIMITS:
        return CONTEXT_LIMITS[model]
    # 前缀匹配：处理带版本号/后缀的模型名
    for known_model, limit in CONTEXT_LIMITS.items():
        if model.startswith(known_model):
            return limit
    return DEFAULT_CONTEXT_LIMIT


# ===== 压缩逻辑 =====

def maybe_compact(state, config: dict):
    """
    每次 LLM 调用前检查，超阈值则压缩。
    
    state: AgentState（有 messages 属性）
    config: 配置字典
    """
    model = config.get("model", DEFAULT_MODEL)
    limit = get_context_limit(model)
    usage = estimate_tokens(state.messages)
    
    # 70% 以下不压缩
    if usage <= limit * 0.7:
        return
    
    # 层级 1: 微压缩 — 截断旧的 tool_result
    snip_old_results(state.messages)
    
    # 层级 2: 摘要压缩 — 如果微压缩还不够
    if estimate_tokens(state.messages) > limit * 0.8:
        summary_compact(state, config)


def snip_old_results(messages: list[dict], keep_last_n: int = 6, max_chars: int = 2000):
    """
    微压缩：将 keep_last_n 轮之前的旧 tool_result 截断。
    只保留头尾各 500 字符。
    """
    # 找到最近的 N 轮（通过 assistant 消息计数）
    assistant_indices = [i for i, m in enumerate(messages) if m["role"] == "assistant"]
    
    if len(assistant_indices) <= keep_last_n:
        return  # 不需要截断
    
    cutoff = assistant_indices[-keep_last_n]
    
    for i in range(cutoff):
        m = messages[i]
        if m["role"] == "tool" and len(m.get("content", "")) > max_chars:
            content = m["content"]
            m["content"] = content[:500] + "\n... [snipped for context management] ...\n" + content[-500:]


def summary_compact(state, config: dict):
    """
    摘要压缩：用 LLM 总结旧历史，保留最近消息。
    
    保留最近 30% 的消息，将前面的消息交给 LLM 生成摘要。
    """
    if len(state.messages) < 6:
        return  # 消息太少，不值得压缩
    
    # 找分割点：保留最近 30% 消息
    split = max(2, len(state.messages) * 7 // 10)
    old_messages = state.messages[:split]
    recent_messages = state.messages[split:]
    
    # 调用 LLM 生成摘要
    summary = _llm_summarize(old_messages, config)
    
    # 替换历史为 [摘要 + 最近消息]
    state.messages = [
        {"role": "user", "content": f"[Conversation Summary from previous context]\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the context from the previous conversation and will continue from here."},
        *recent_messages,
    ]


def _llm_summarize(messages: list[dict], config: dict) -> str:
    """用 LLM 总结旧消息历史"""
    try:
        from agent.providers import call_llm
        
        # 构建摘要请求
        conversation_text = _messages_to_text(messages)
        
        # 如果文本太长，只取前面部分
        if len(conversation_text) > 10000:
            conversation_text = conversation_text[:10000] + "\n... (truncated)"
        
        summarize_messages = [
            {
                "role": "user",
                "content": (
                    "Please summarize the following conversation concisely. "
                    "Focus on: what was discussed, what decisions were made, "
                    "what files were read or modified, and any important context.\n\n"
                    f"{conversation_text}"
                ),
            }
        ]
        
        return call_llm(
            model=config.get("model", DEFAULT_MODEL),
            system="You are a conversation summarizer. Be concise but capture all important details.",
            messages=summarize_messages,
            config=config,
        )
    except Exception as e:
        # 摘要失败时，返回简单的关键信息提取
        return _fallback_summarize(messages)


def _messages_to_text(messages: list[dict]) -> str:
    """将消息列表转换为可读文本"""
    lines = []
    for m in messages:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if isinstance(content, str) and content:
            # 截断过长的内容
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(f"[{role}]: {content}")
    return "\n".join(lines)


def _fallback_summarize(messages: list[dict]) -> str:
    """LLM 摘要失败时的回退方案：简单提取关键信息"""
    lines = ["[Auto-summary (LLM unavailable)]"]
    
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user" and isinstance(content, str) and content:
            # 只保留用户消息的前 100 字符
            lines.append(f"User asked: {content[:100]}...")
        elif role == "tool":
            name = m.get("name", "unknown")
            lines.append(f"Tool ({name}) was called.")
    
    return "\n".join(lines[:20])  # 最多 20 行
