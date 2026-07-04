from types import SimpleNamespace
from s03_permission.agent import agent_loop


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def tool_use_block(bid, name, inp):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)

    def create(self, **kwargs):
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_allowed_tool_runs():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", check_permission=lambda n, i: True)
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "OUT"}


def test_denied_tool_returns_permission_denied():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "rm -rf /"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    run_calls = []
    msgs = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: run_calls.append(n) or "OUT",
               check_permission=lambda n, i: False)
    assert run_calls == []
    assert msgs[2]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "Permission denied."}


def test_on_tool_use_called_before_and_after():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    calls = []

    def on_use(name, output):
        calls.append((name, output))

    agent_loop(client=client, model="m", system="s", tools=[],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", check_permission=lambda n, i: True,
               on_tool_use=on_use)
    assert calls == [("read_file", None), ("read_file", "OUT")]
