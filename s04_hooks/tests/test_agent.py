from types import SimpleNamespace
from s04_hooks.agent import agent_loop


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
