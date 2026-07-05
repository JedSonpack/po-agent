import pytest
from types import SimpleNamespace
from s15_agent_teams import recovery
from s15_agent_teams.recovery import (RecoveryState, with_retry, retry_delay,
                                         is_prompt_too_long_error)


class RateLimitError(Exception):
    pass


class OverloadedError(Exception):
    pass


def text_resp(t="ok"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=t)], stop_reason="end_turn")


def test_retry_delay_attempt0():
    d = retry_delay(0)
    assert 0.5 <= d <= 0.625  # base 0.5 + jitter [0, 0.125]


def test_retry_delay_retry_after_priority():
    assert retry_delay(0, retry_after=10) == 10


def test_retry_delay_cap():
    d = retry_delay(10)
    assert d <= 32 + 8  # base cap 32 + jitter ≤8


def test_is_prompt_too_long_markers():
    assert is_prompt_too_long_error(Exception("prompt is too long"))
    assert is_prompt_too_long_error(Exception("prompt_is_too_long"))
    assert is_prompt_too_long_error(Exception("prompt_too_long"))
    assert is_prompt_too_long_error(Exception("context_length_exceeded"))
    assert is_prompt_too_long_error(Exception("max_context_window"))
    assert not is_prompt_too_long_error(Exception("network down"))


def test_with_retry_429_then_success(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)
    calls = [0]

    def fn():
        calls[0] += 1
        if calls[0] == 1:
            raise RateLimitError("429 rate limit")
        return text_resp()

    state = RecoveryState(current_model="m")
    r = with_retry(fn, state)
    assert r is not None
    assert calls[0] == 2


def test_with_retry_429_exhausts(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)

    def fn():
        raise RateLimitError("429")

    state = RecoveryState(current_model="m")
    with pytest.raises(RuntimeError):
        with_retry(fn, state)


def test_with_retry_529_switches_fallback(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)
    monkeypatch.setattr(recovery, "FALLBACK_MODEL", "fallback-model")

    def fn():
        raise OverloadedError("529 overloaded")

    state = RecoveryState(current_model="primary")
    try:
        with_retry(fn, state)
    except RuntimeError:
        pass
    assert state.current_model == "fallback-model"


def test_with_retry_529_no_fallback(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)
    monkeypatch.setattr(recovery, "FALLBACK_MODEL", None)

    def fn():
        raise OverloadedError("overloaded")

    state = RecoveryState(current_model="primary")
    try:
        with_retry(fn, state)
    except RuntimeError:
        pass
    assert state.current_model == "primary"  # 不变


def test_with_retry_529_success_resets(monkeypatch):
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)
    calls = [0]

    def fn():
        calls[0] += 1
        if calls[0] <= 2:
            raise OverloadedError("529")
        return text_resp()

    state = RecoveryState(current_model="m")
    with_retry(fn, state)
    assert state.consecutive_529 == 0


def test_with_retry_non_transient_reraises():
    def fn():
        raise ValueError("boom")

    state = RecoveryState(current_model="m")
    with pytest.raises(ValueError):
        with_retry(fn, state)
