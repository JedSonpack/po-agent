# s11 Error Recovery 实现计划

**目标：** s11 Error Recovery——LLM 调用韧性外壳（with_retry 429/529 退避 + max_tokens 升级/续写 + prompt_too_long reactive + 优雅返回），行为对齐 `learn-claude-code/s11_error_recovery`。
**架构：** `s11_error_recovery` 包，沿用 s10；新增 `recovery.py`；`agent_loop` LLM 调用包 `with_retry`，加 max_tokens 升级/续写、outer except 优雅返回。保留 s10 全部。
**规格：** `docs/superpowers/specs/2026-07-04-s11-error-recovery-design.md`（impl 见 §4/§5）

从 po-agent 根目录运行，`source .venv/bin/activate`（或 `.venv/bin/pytest`）。main，每任务一 commit，阶段末 push。

---

## 任务 1：包骨架 + recovery.py（TDD）

- [ ] `s11_error_recovery/__init__.py`、`tests/__init__.py`
- [ ] **tests/test_recovery.py**：
```python
import pytest
from s11_error_recovery import recovery
from s11_error_recovery.recovery import (RecoveryState, with_retry, retry_delay,
                                          is_prompt_too_long_error)


def text_resp(t="ok"): 
    from types import SimpleNamespace
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


class RateLimitError(Exception):
    pass


class OverloadedError(Exception):
    pass


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
```
- [ ] 实现 `recovery.py`（规格 §4）
- [ ] `.venv/bin/pytest s11_error_recovery/tests/test_recovery.py -v` → 全通过
- [ ] Commit `feat(s11): 实现 recovery（with_retry + RecoveryState + 升级/续写）`

---

## 任务 2：s10 模块复制（config/tools/skills/hooks/todo/subagent/compact/memory/system_prompt）

- [ ] 9 模块 + 8 测试从 s10 原样复制（sed `s10_system_prompt/s11_error_recovery`）
- [ ] `.venv/bin/pytest s11_error_recovery/tests/test_tools.py s11_error_recovery/tests/test_skills.py s11_error_recovery/tests/test_hooks.py s11_error_recovery/tests/test_todo.py s11_error_recovery/tests/test_subagent.py s11_error_recovery/tests/test_compact.py s11_error_recovery/tests/test_memory.py s11_error_recovery/tests/test_system_prompt.py s11_error_recovery/tests/test_config.py -v` → 全通过
- [ ] Commit `feat(s11): 复制 s10 模块（同 s10）`

---

## 任务 3：agent.py（s10 + recovery 集成，TDD）

- [ ] **tests/test_agent.py**：s10 的 17 个 sed 复制；改 `test_reactive_does_not_swallow_unrelated_error` → `test_unrelated_error_exits_gracefully`：
```python
def test_unrelated_error_exits_gracefully():
    class BoomClient:
        @property
        def messages(self): return self
        def create(self, **kw): raise ValueError("network down")
    spy = SpyCompactor()
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=BoomClient(), model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "reactive" not in spy.calls
    assert "[Error]" in str(msgs[-1]["content"])
    assert "ValueError" in str(msgs[-1]["content"])
```
加 max_tokens 测试：
```python
def test_max_tokens_escalates_without_append():
    client = FakeClient([
        make_response([text_block("half")], "max_tokens"),
        make_response([text_block("done")], "end_turn"),
    ])
    captured = []
    class Cap(FakeClient):
        def create(self, **kw):
            captured.append(kw.get("max_tokens")); return self._r.pop(0)
    c = Cap([make_response([text_block("half")], "max_tokens"),
             make_response([text_block("done")], "end_turn")])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=c, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert captured[0] == 8000 and captured[1] == 64000  # 升级
    # 第一次 max_tokens 的截断输出未 append（messages 只有 user + 最终 assistant）
    assert len(msgs) == 2


def test_max_tokens_continuation_after_escalation():
    client = FakeClient([
        make_response([text_block("half1")], "max_tokens"),  # 触发升级
        make_response([text_block("half2")], "max_tokens"),  # 升级后仍截断 → 续写
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert any("continue from where" in str(m.get("content", "")).lower() for m in msgs)


def test_with_retry_429_in_loop(monkeypatch):
    from s11_error_recovery import recovery
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)
    class Flaky:
        def __init__(self): self.n = 0
        @property
        def messages(self): return self
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise Exception("429 too many requests")
            return make_response([text_block("done")], "end_turn")
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=Flaky(), model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert "done" in str(msgs[-1]["content"])
```
- [ ] 实现 `agent.py`（规格 §5）
- [ ] `.venv/bin/pytest s11_error_recovery/tests/test_agent.py -v` → 全通过
- [ ] Commit `feat(s11): agent_loop 集成 recovery（with_retry + 升级/续写 + 优雅返回）`

---

## 任务 4：cli.py + __main__.py（s10 原样 sed）

- [ ] sed 复制 s10 cli.py / __main__.py；banner 改 s11
- [ ] `python -c "from s11_error_recovery.cli import main; print('ok')"`
- [ ] Commit `feat(s11): REPL 入口（同 s10）`

---

## 任务 5：README + 全测 + 冒烟 + push + PROGRESS

- [ ] README（`## 本阶段完成（相对 s10）`：recovery.py；RecoveryState+with_retry+retry_delay+is_prompt_too_long_error；max_tokens 升级/续写；prompt_too_long reactive；优雅返回；保留 s10 全部）
- [ ] 全测 `pytest s01_*/tests ... s11_error_recovery/tests -v` → 全通过
- [ ] 冒烟 `echo '列出当前目录的 .py 文件' | python -m s11_error_recovery` → 跑通
- [ ] Commit README + 更新 PROGRESS（s11 ✅ + 详情节）
- [ ] `git push origin main`

---

## 自检
**规格覆盖度：** §4 recovery → 任务 1 ✓；§5 agent → 任务 3 ✓；§8 验收 → 任务 5 ✓。**类型一致：** `RecoveryState(current_model=model)` 规格/任务一致；`with_retry(fn, state)` 一致；`agent_loop(max_tokens=DEFAULT_MAX_TOKENS)` 一致。✓
