from types import SimpleNamespace
import pytest
from s16_team_protocols.agent import agent_loop
from s16_team_protocols.todo import TodoNag
from s16_team_protocols.system_prompt import reset_cache


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def tool_use_block(bid, name, inp):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def ctx(**over):
    base = {"cwd": ".", "tools": [], "skills_catalog": ""}
    base.update(over)
    return base


class FakeClient:
    def __init__(self, responses):
        self._r = list(responses)

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        return self._r.pop(0)


@pytest.fixture(autouse=True)
def _reset():
    from s16_team_protocols import background, cron
    reset_cache()
    background._bg_counter = 0
    background.background_tasks.clear()
    background.background_results.clear()
    cron.cron_queue.clear()
    cron.scheduled_jobs.clear()
    cron._last_fired.clear()
    yield
    reset_cache()
    background._bg_counter = 0
    background.background_tasks.clear()
    background.background_results.clear()
    cron.cron_queue.clear()
    cron.scheduled_jobs.clear()
    cron._last_fired.clear()


def test_allowed_tool_runs():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
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

    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
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

    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
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

    agent_loop(client=client, model="m", context=ctx(), tools=[],
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
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
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
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, nag=nag)
    assert {"role": "user", "content": "<reminder>Update your todos.</reminder>"} not in msgs


def test_task_dispatches_via_run_tool():
    client = FakeClient([
        make_response([tool_use_block("t1", "task", {"description": "do X"})], "tool_use"),
        make_response([text_block("got summary")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
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
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "compact" in spy.calls
    assert any("[Compacted]" in str(m.get("content", "")) for m in msgs)


def test_pipeline_runs_each_iteration():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert spy.calls.count("pipeline") >= 2  # 每轮都跑


def test_auto_compact_when_over_limit():
    client = FakeClient([
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    spy.size = 99999  # > context_limit
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "x"}],
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
    agent_loop(client=FlakyClient(), model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "reactive" in spy.calls


def test_unrelated_error_exits_gracefully():
    class BoomClient:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            raise ValueError("network down")

    spy = SpyCompactor()
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=BoomClient(), model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "reactive" not in spy.calls  # 不误作 prompt_too_long
    assert "[Error]" in str(msgs[-1]["content"])
    assert "ValueError" in str(msgs[-1]["content"])


# ── s09 新增：memory ─────────────────────────────────────────
class SpyMemory:
    def __init__(self):
        self.calls = []
        self.inject = ""
        self.section = ""

    def load_memories(self, messages):
        self.calls.append("load")
        return self.inject

    def build_index_section(self):
        return self.section

    def extract_memories(self, msgs):
        self.calls.append(("extract", msgs))

    def consolidate_memories(self):
        self.calls.append("consolidate")


def test_memory_loaded_at_loop_start():
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    spy = SpyMemory()
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, memory=spy)
    assert "load" in spy.calls


def test_memory_extracted_and_consolidated_at_turn_end():
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    spy = SpyMemory()
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, memory=spy)
    assert any(isinstance(c, tuple) and c[0] == "extract" for c in spy.calls)
    assert "consolidate" in spy.calls


def test_memory_index_in_system_when_present():
    captured = {}

    class CaptureClient:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            captured["system"] = kw.get("system")
            return make_response([text_block("done")], "end_turn")

    spy = SpyMemory()
    spy.section = "Memories available:\n- [X](x.md) — dx"
    agent_loop(client=CaptureClient(), model="m",
               context=ctx(cwd="/work", skills_catalog="c"),
               tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, memory=spy)
    assert "Memories available" in captured["system"]
    assert "coding agent" in captured["system"]


def test_memory_injected_into_user_turn():
    captured = {}

    class CaptureClient:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            captured["messages"] = kw.get("messages")
            return make_response([text_block("done")], "end_turn")

    spy = SpyMemory()
    spy.inject = "MEMCONTENT"
    agent_loop(client=CaptureClient(), model="m", context=ctx(), tools=[], messages=[{"role": "user", "content": "hello"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, memory=spy)
    assert "MEMCONTENT" in str(captured["messages"][0]["content"])
    assert "hello" in str(captured["messages"][0]["content"])


# ── s10 新增：系统提示组装 ──────────────────────────────────
def test_system_prompt_assembled_from_context():
    captured = {}

    class CaptureClient:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            captured["system"] = kw.get("system")
            return make_response([text_block("done")], "end_turn")

    agent_loop(client=CaptureClient(), model="m",
               context=ctx(cwd="/work", skills_catalog="SK"),
               tools=[{"name": "bash", "input_schema": {}},
                      {"name": "read_file", "input_schema": {}}],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert "coding agent" in captured["system"]
    assert "/work" in captured["system"]
    assert "bash" in captured["system"]
    assert "read_file" in captured["system"]
    assert "SK" in captured["system"]
    assert "Memories available" not in captured["system"]  # 无 memory


# ── s11 新增：error recovery ───────────────────────────────
def test_max_tokens_escalates_without_append():
    captured = []

    class Cap(FakeClient):
        def create(self, **kw):
            captured.append(kw.get("max_tokens"))
            return self._r.pop(0)

    client = Cap([
        make_response([text_block("half")], "max_tokens"),  # 触发升级
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert captured[0] == 8000 and captured[1] == 64000  # 升级
    assert len(msgs) == 2  # 截断输出未 append


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
    from s16_team_protocols import recovery
    monkeypatch.setattr(recovery.time, "sleep", lambda s: None)

    class Flaky:
        def __init__(self):
            self.n = 0

        @property
        def messages(self):
            return self

        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise Exception("429 too many requests")
            return make_response([text_block("done")], "end_turn")

    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=Flaky(), model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert "done" in str(msgs[-1]["content"])


# ── s13 新增：后台任务 ─────────────────────────────────────
def test_background_bash_returns_placeholder():
    import threading
    release = threading.Event()

    def slow_run(n, i):
        release.wait(2)  # 阻塞，保持 running，不产生通知
        return "OUT"

    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "echo hi", "run_in_background": True})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=slow_run, trigger=lambda ev, *a: None)
    assert "Background task bg_0001" in msgs[2]["content"][0]["content"]
    release.set()


def test_background_notification_injected_after_results():
    from s16_team_protocols import background
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "old", "command": "echo done", "status": "completed"}
        background.background_results["bg_0001"] = "DONE"
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    user_msg = msgs[2]["content"]
    assert user_msg[0]["type"] == "tool_result"  # results 在前
    assert any(b.get("type") == "text" and "<task_notification>" in b.get("text", "") for b in user_msg)  # 通知在后


def test_no_collect_when_stop_without_tool_use():
    from s16_team_protocols import background
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "old", "command": "c", "status": "completed"}
        background.background_results["bg_0001"] = "DONE"
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert len(msgs) == 2  # user + assistant，无通知注入
    assert "bg_0001" in background.background_tasks  # 未收集


# ── s14 新增：cron 队列消费 ─────────────────────────────────
def test_cron_queue_injected_as_scheduled():
    from s16_team_protocols import cron
    from s16_team_protocols.cron import CronJob
    cron.cron_queue.append(CronJob("cron_1", "* * * * *", "check progress", True, False))
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    # [Scheduled] user 消息已注入
    assert any("[Scheduled] check progress" == str(m.get("content", "")) for m in msgs)


# ── s15 新增：团队工具经 run_tool 分发 ──────────────────────
def test_spawn_teammate_dispatches_via_run_tool():
    client = FakeClient([
        make_response([tool_use_block("t1", "spawn_teammate",
                                      {"name": "alice", "role": "dev", "prompt": "do X"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: calls.append((n, i)) or "Teammate 'alice' spawned as dev",
               trigger=lambda ev, *a: None)
    assert calls == [("spawn_teammate", {"name": "alice", "role": "dev", "prompt": "do X"})]
    assert msgs[2]["content"][0]["content"] == "Teammate 'alice' spawned as dev"


def test_check_inbox_dispatches_via_run_tool():
    client = FakeClient([
        make_response([tool_use_block("t1", "check_inbox", {})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", context=ctx(), tools=[], messages=msgs,
               run_tool=lambda n, i: calls.append((n, i)) or "(inbox empty)",
               trigger=lambda ev, *a: None)
    assert calls == [("check_inbox", {})]
    assert msgs[2]["content"][0]["content"] == "(inbox empty)"
