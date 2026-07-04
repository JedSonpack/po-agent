from types import SimpleNamespace
from s01_agent_loop.agent import agent_loop


def make_response(blocks, stop_reason):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def text_block(t):
    return SimpleNamespace(type="text", text=t)


def tool_use_block(bid, command):
    return SimpleNamespace(type="tool_use", id=bid, input={"command": command})


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
               messages=messages, run_tool=lambda c: "")
    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"


def test_tool_use_loop_feeds_result_back():
    client = FakeClient([
        make_response([tool_use_block("t1", "echo hi")], "tool_use"),
        make_response([text_block("all done")], "end_turn"),
    ])
    messages = [{"role": "user", "content": "do it"}]
    seen = []
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=messages, run_tool=lambda c: seen.append(c) or "TOOL_OUT")
    assert len(messages) == 4
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0] == {
        "type": "tool_result", "tool_use_id": "t1", "content": "TOOL_OUT"}
    assert messages[3]["content"][0].text == "all done"
    assert seen == ["echo hi"]
    assert len(client.messages.calls) == 2


def test_on_tool_use_callback_invoked():
    client = FakeClient([
        make_response([tool_use_block("t1", "ls")], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []
    agent_loop(client=client, model="m", system="s", tools=[],
               messages=[{"role": "user", "content": "x"}],
               run_tool=lambda c: "OUT",
               on_tool_use=lambda cmd, out: calls.append((cmd, out)))
    assert calls == [("ls", "OUT")]
