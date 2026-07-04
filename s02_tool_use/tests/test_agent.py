from types import SimpleNamespace
from s02_tool_use.agent import agent_loop


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_use_block(bid, name, input):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=input)


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def test_no_tool_use_exits_immediately():
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    messages = [{"role": "user", "content": "hi"}]
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=messages, run_tool=lambda name, inp: "")
    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"


def test_single_tool_call_dispatches_by_name():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a.txt"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []

    def fake_run_tool(name, inp):
        calls.append((name, inp))
        return "FILE_CONTENT"

    messages = [{"role": "user", "content": "do it"}]
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=messages, run_tool=fake_run_tool)
    assert calls == [("read_file", {"path": "a.txt"})]
    assert messages[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "t1", "content": "FILE_CONTENT"}
    assert len(client.messages.calls) == 2


def test_multiple_tool_calls_in_one_response():
    client = FakeClient([
        make_response([
            tool_use_block("t1", "read_file", {"path": "a.py"}),
            tool_use_block("t2", "glob", {"pattern": "*.py"}),
        ], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    calls = []

    def fake_run_tool(name, inp):
        calls.append((name, inp))
        return f"OUT:{name}"

    messages = [{"role": "user", "content": "x"}]
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=messages, run_tool=fake_run_tool)
    assert calls == [
        ("read_file", {"path": "a.py"}),
        ("glob", {"pattern": "*.py"}),
    ]
    results = messages[2]["content"]
    assert results[0] == {"type": "tool_result", "tool_use_id": "t1", "content": "OUT:read_file"}
    assert results[1] == {"type": "tool_result", "tool_use_id": "t2", "content": "OUT:glob"}


def test_on_tool_use_called_with_name():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda name, inp: "OUT",
               on_tool_use=lambda name, out: calls.append((name, out)))
    assert calls == [("bash", "OUT")]
