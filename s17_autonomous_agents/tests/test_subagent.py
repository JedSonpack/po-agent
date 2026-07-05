from types import SimpleNamespace
from s17_autonomous_agents.subagent import Subagent, extract_text


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


class AlwaysToolClient:
    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        return make_response([tool_use_block("t", "bash", {"command": "ls"})], "tool_use")


def test_extract_text_from_string():
    assert extract_text("plain") == "plain"


def test_extract_text_from_blocks():
    assert extract_text([text_block("a"), text_block("b")]) == "a\nb"


def test_extract_text_no_text_blocks():
    assert extract_text([tool_use_block("t", "bash", {})]) == ""


def test_subagent_returns_last_text():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([text_block("all done")], "end_turn"),
    ])
    calls = []
    sub = Subagent(client=client, model="m", sub_system="s", sub_tools=[],
                   sub_run_tool=lambda n, i: calls.append(n) or "OUT",
                   trigger=lambda ev, *a: None)
    assert sub.run("do it") == "all done"
    assert calls == ["bash"]


def test_subagent_blocked_tool_skips_run():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "rm -rf /"})], "tool_use"),
        make_response([text_block("ok")], "end_turn"),
    ])
    calls = []

    def trigger(ev, *a):
        if ev == "PreToolUse":
            return "Permission denied"
        return None

    sub = Subagent(client=client, model="m", sub_system="s", sub_tools=[],
                   sub_run_tool=lambda n, i: calls.append(n) or "OUT", trigger=trigger)
    assert sub.run("do it") == "ok"
    assert calls == []


def test_subagent_post_tool_use_hook():
    client = FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    events = []
    sub = Subagent(client=client, model="m", sub_system="s", sub_tools=[],
                   sub_run_tool=lambda n, i: "OUT",
                   trigger=lambda ev, *a: events.append(ev) or None)
    sub.run("do it")
    assert "PreToolUse" in events
    assert "PostToolUse" in events


def test_subagent_max_turns_fallback():
    sub = Subagent(client=AlwaysToolClient(), model="m", sub_system="s", sub_tools=[],
                   sub_run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, max_turns=3)
    assert sub.run("do it") == "Subagent stopped after 3 turns without final answer."


def test_subagent_backward_search_fallback():
    client = FakeClient([
        make_response([text_block("partial answer"), tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([tool_use_block("t2", "bash", {"command": "ls"})], "tool_use"),
    ])
    sub = Subagent(client=client, model="m", sub_system="s", sub_tools=[],
                   sub_run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, max_turns=2)
    assert sub.run("do it") == "partial answer"
