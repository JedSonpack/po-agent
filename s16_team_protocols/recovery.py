"""Error Recovery — LLM 调用韧性外壳：429/529 退避重试 + max_tokens 升级/续写 + prompt_too_long reactive。

with_retry 处理瞬态错误（429/529），agent_loop 处理 max_tokens 升级/续写与不可恢复的优雅返回。
"""
import os
import random
import time

DEFAULT_MAX_TOKENS = 8000
ESCALATED_MAX_TOKENS = int(os.getenv("ESCALATED_MAX_TOKENS", "64000"))
MAX_RETRIES = 10
MAX_CONSECUTIVE_529 = 3
MAX_RECOVERY_RETRIES = 3
BASE_DELAY_MS = 500
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")  # None if unset
CONTINUATION_PROMPT = "Please continue from where you left off."

_PROMPT_TOO_LONG_MARKERS = ("prompt is too long", "prompt_is_too_long", "prompt_too_long",
                            "context_length_exceeded", "max_context_window", "too many tokens")


class RecoveryState:
    """跨循环迭代跟踪恢复状态。"""

    def __init__(self, current_model=None):
        self.has_escalated = False
        self.recovery_count = 0
        self.consecutive_529 = 0
        self.has_attempted_reactive_compact = False
        self.current_model = current_model


def retry_delay(attempt, retry_after=None):
    """指数退避：Retry-After 优先；否则 min(500×2^attempt, 32000)/1000 + 0~25% 抖动。"""
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


def is_prompt_too_long_error(e) -> bool:
    """字符串匹配判断上下文超限错误（参考串 + po-agent s08 串并集）。"""
    s = str(e).lower()
    return any(m in s for m in _PROMPT_TOO_LONG_MARKERS)


def with_retry(fn, state: RecoveryState):
    """对 fn() 做 429/529 指数退避重试（最多 MAX_RETRIES）；529 连续 3 次切备用模型；非瞬态 re-raise。"""
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0  # 成功即重置 529 计数
            return result
        except Exception as e:
            name = type(e).__name__.lower()
            msg = str(e).lower()
            # 429 rate limit -> exponential backoff
            if "ratelimit" in name or "429" in msg:
                time.sleep(retry_delay(attempt))
                continue
            # 529 overloaded -> exponential backoff + fallback model
            if "overloaded" in name or "529" in msg or "overloaded" in msg:
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                    state.consecutive_529 = 0
                time.sleep(retry_delay(attempt))
                continue
            # Not transient -> re-raise for outer try/except
            raise
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")
