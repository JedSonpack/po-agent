from types import SimpleNamespace
import pytest
from s08_context_compact.agent import agent_loop
from s08_context_compact.todo import TodoNag


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def tool_use_block(bid, name, inp):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    def __init__(self, responses):
        self._r = list(responses)

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        return self._r.pop(0)


def test_allowed_tool_runs():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: calls.append(n) or "OUT",
               trigger=lambda ev, *a: None)
    assert calls == ["read_file"]
    assert msgs[2]["content"][0]["content"] == "OUT"


def test_blocked_tool_skips_run():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "rm -rf /"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]

    def trigger(ev, *a):
        if ev == "PreToolUse":
            return "Permission denied by deny list"
        return None

    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: calls.append(n) or "OUT", trigger=trigger)
    assert calls == []
    assert msgs[2]["content"][0]["content"] == "Permission denied by deny list"


def test_stop_hook_force_continues():
    client = FakeClient([
        make_response([text_block("first")], "end_turn"),
        make_response([text_block("second")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    state = {"force": True}

    def trigger(ev, *a):
        if ev == "Stop":
            if state["force"]:
                state["force"] = False
                return "continue please"
        return None

    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=trigger)
    assert len(msgs) == 4


def test_post_tool_use_called():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    events = []

    def trigger(ev, *a):
        events.append(ev)
        return None

    agent_loop(client=client, model="m", system="s", tools=[],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=trigger)
    assert "PreToolUse" in events
    assert "PostToolUse" in events
    assert "Stop" in events


def test_nag_injects_reminder_after_three_rounds():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([tool_use_block("t2", "read_file", {"path": "b"})], "tool_use"),
        make_response([tool_use_block("t3", "read_file", {"path": "c"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    nag = TodoNag()
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, nag=nag)
    assert {"role": "user", "content": "<reminder>Update your todos.</reminder>"} in msgs


def test_todo_write_resets_nag_counter():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([tool_use_block("t2", "read_file", {"path": "b"})], "tool_use"),
        make_response([tool_use_block("t3", "todo_write",
                                      {"todos": [{"content": "x", "status": "pending"}]})], "tool_use"),
        make_response([tool_use_block("t4", "read_file", {"path": "d"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    nag = TodoNag()
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, nag=nag)
    assert {"role": "user", "content": "<reminder>Update your todos.</reminder>"} not in msgs


def test_task_dispatches_via_run_tool():
    client = FakeClient([
        make_response([tool_use_block("t1", "task", {"description": "do X"})], "tool_use"),
        make_response([text_block("got summary")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: calls.append((n, i)) or "SUBAGENT SUMMARY",
               trigger=lambda ev, *a: None)
    assert calls == [("task", {"description": "do X"})]
    assert msgs[2]["content"][0]["content"] == "SUBAGENT SUMMARY"


# ── s08 新增：压缩 ───────────────────────────────────────────
class SpyCompactor:
    context_limit = 50_000
    max_reactive_retries = 1

    def __init__(self):
        self.calls = []
        self.size = 0

    def run_pipeline(self, m):
        self.calls.append("pipeline")

    def should_auto_compact(self, m):
        return self.size > self.context_limit

    def compact_history(self, m):
        self.calls.append("compact")
        m[:] = [{"role": "user", "content": "[Compacted]\n\nSUM"}]

    def is_prompt_too_long(self, e):
        return False

    def reactive_compact(self, m):
        self.calls.append("reactive")


def test_compact_tool_triggers_compact_history():
    client = FakeClient([
        make_response([tool_use_block("t1", "compact", {})], "tool_use"),
        make_response([text_block("after compact")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    spy = SpyCompactor()
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "compact" in spy.calls
    assert any("[Compacted]" in str(m.get("content", "")) for m in msgs)


def test_pipeline_runs_each_iteration():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    agent_loop(client=client, model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert spy.calls.count("pipeline") >= 2  # 每轮都跑


def test_auto_compact_when_over_limit():
    client = FakeClient([
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    spy.size = 99999  # > context_limit
    agent_loop(client=client, model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "compact" in spy.calls  # auto-compact 触发


def test_reactive_compact_on_prompt_too_long():
    class FlakyClient:
        def __init__(self):
            self.n = 0

        @property
        def messages(self):
            return self

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise Exception("prompt_too_long")
            return make_response([text_block("ok")], "end_turn")

    spy = SpyCompactor()
    spy.is_prompt_too_long = lambda e: True
    agent_loop(client=FlakyClient(), model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "reactive" in spy.calls


def test_reactive_does_not_swallow_unrelated_error():
    class BoomClient:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            raise ValueError("network down")

    spy = SpyCompactor()
    with pytest.raises(ValueError):
        agent_loop(client=BoomClient(), model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
                   run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
