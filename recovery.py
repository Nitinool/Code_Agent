# recovery.py — s11 韧性与恢复状态机 (Resiliency & Error Recovery)
# 在 LLM 调用的最外层包装错误分类器，自动恢复常见错误

import time
import random
from dataclasses import dataclass
from typing import Optional, Callable


# ===== 错误分类 =====

@dataclass
class ClassifiedError:
    """分类后的错误"""
    raw: Exception
    category: str       # "max_tokens", "prompt_too_long", "rate_limit", "network", "unknown"
    message: str
    recoverable: bool   # 是否可恢复
    budget_used: int     # 已消耗的重试次数


def classify_error(error: Exception) -> ClassifiedError:
    """
    错误分类器 — 根据异常类型和信息判断错误类别。
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # 规则 1: max_tokens 截断
    # OpenAI SDK 对 max_tokens 截断不会抛异常，但部分 API 会返回特定错误
    if any(kw in error_str for kw in ("max_tokens", "maxtokens", "maximum context length", "context_length_exceeded")):
        if "context" in error_str or "prompt" in error_str or "token" in error_str:
            return ClassifiedError(
                raw=error,
                category="prompt_too_long",
                message=f"Prompt too long: {error}",
                recoverable=True,
                budget_used=0,
            )
        return ClassifiedError(
            raw=error,
            category="max_tokens",
            message=f"Output truncated (max_tokens reached): {error}",
            recoverable=True,
            budget_used=0,
        )
    
    # 规则 2: prompt_too_long (上下文超限)
    if any(kw in error_str for kw in ("prompt_too_long", "context_window", "too many tokens", "input is too long")):
        return ClassifiedError(
            raw=error,
            category="prompt_too_long",
            message=f"Context window exceeded: {error}",
            recoverable=True,
            budget_used=0,
        )
    
    # 规则 3: 限流 (Rate Limit)
    if any(kw in error_str for kw in ("rate_limit", "rate limit", "too many requests", "429", "throttl")):
        return ClassifiedError(
            raw=error,
            category="rate_limit",
            message=f"Rate limited: {error}",
            recoverable=True,
            budget_used=0,
        )
    
    # 规则 4: 网络错误
    if any(kw in error_str for kw in ("connection", "timeout", "network", "timed out", "dns", "refused")):
        return ClassifiedError(
            raw=error,
            category="network",
            message=f"Network error: {error}",
            recoverable=True,
            budget_used=0,
        )
    
    # 未知错误 — 默认不可恢复
    return ClassifiedError(
        raw=error,
        category="unknown",
        message=f"Unexpected error: {error}",
        recoverable=False,
        budget_used=0,
    )


# ===== 恢复动作 =====

# 续写补丁 — 当 max_tokens 截断时，注入此消息让 LLM 继续
CONTINUE_MESSAGE = {
    "role": "user",
    "content": "Please continue exactly where you left off. Do not repeat what you already said.",
}


# ===== 指数退避 =====

def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    带抖动的指数退避。
    
    delay = min(base_delay * 2^attempt, max_delay) + random_jitter
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    jitter = random.uniform(0, delay * 0.1)  # 10% 抖动
    return delay + jitter


# ===== 恢复预算 =====

# 每种错误类别的最大重试次数
RECOVERY_BUDGET = {
    "max_tokens": 3,        # 续写最多 3 次
    "prompt_too_long": 2,   # 压缩最多 2 次
    "rate_limit": 5,        # 限流最多重试 5 次
    "network": 3,           # 网络错误最多重试 3 次
    "unknown": 0,           # 未知错误不重试
}


@dataclass
class RecoveryBudget:
    """恢复预算追踪器 — 确保不会死循环"""
    spent: dict = None  # category -> count
    
    def __post_init__(self):
        if self.spent is None:
            self.spent = {}
    
    def can_retry(self, category: str) -> bool:
        """检查是否还有重试预算"""
        limit = RECOVERY_BUDGET.get(category, 0)
        spent = self.spent.get(category, 0)
        return spent < limit
    
    def consume(self, category: str):
        """消耗一次重试预算"""
        self.spent[category] = self.spent.get(category, 0) + 1
    
    def remaining(self, category: str) -> int:
        """剩余重试次数"""
        limit = RECOVERY_BUDGET.get(category, 0)
        spent = self.spent.get(category, 0)
        return max(0, limit - spent)
    
    def reset(self):
        """重置所有预算（新一轮用户输入时）"""
        self.spent = {}


# ===== 恢复策略执行器 =====

@dataclass
class RecoveryAction:
    """恢复动作"""
    action: str          # "continue", "compact", "retry", "abort"
    delay: float = 0.0   # 重试前的等待时间
    inject_message: dict = None  # 需要注入到 messages 的补丁


def decide_recovery(classified: ClassifiedError, budget: RecoveryBudget) -> RecoveryAction:
    """
    根据错误类别和预算，决定恢复策略。
    
    规则 1: max_tokens → 注入 CONTINUE_MESSAGE 续写
    规则 2: prompt_too_long → 触发 auto_compact() 强制摘要
    规则 3: rate_limit/network → 指数退避重试
    规则 4: 预算耗尽 → abort（致命错误）
    """
    category = classified.category
    
    if not budget.can_retry(category):
        return RecoveryAction(
            action="abort",
            delay=0,
        )
    
    if category == "max_tokens":
        budget.consume(category)
        return RecoveryAction(
            action="continue",
            inject_message=CONTINUE_MESSAGE,
        )
    
    elif category == "prompt_too_long":
        budget.consume(category)
        return RecoveryAction(
            action="compact",
        )
    
    elif category in ("rate_limit", "network"):
        budget.consume(category)
        delay = exponential_backoff(budget.spent.get(category, 1) - 1)
        return RecoveryAction(
            action="retry",
            delay=delay,
        )
    
    else:
        return RecoveryAction(action="abort")


# ===== 事件类型（供 agent.py 使用）=====

@dataclass
class RecoveryEvent:
    """恢复事件 — 通知 UI 发生了什么"""
    category: str
    action: str
    attempt: int
    message: str
