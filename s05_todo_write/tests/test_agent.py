from types import SimpleNamespace
from s05_todo_write.agent import agent_loop
from s05_todo_write.todo import TodoNag


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


# ── s04 原样（nag=None）──────────────────────────────────────
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
    assert len(msgs) == 4  # user, assistant(text), user(force), assistant(text)


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


# ── s05 新增：nag ────────────────────────────────────────────
def test_nag_injects_reminder_after_three_rounds():
    # 3 轮 read_file（counter 1→2→3），第 4 轮顶部 nag 注入 reminder，然后 end_turn 退出
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
    # 2 轮 read（counter→2），第 3 轮 todo_write（on_round→3 再 on_todo_write→0），
    # 第 4 轮 read（→1），end。若无 reset，第 4 轮顶部 counter=3 会 nag；有 reset 则不 nag。
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
