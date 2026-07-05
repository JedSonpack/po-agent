"""teams.py 测试——MessageBus + lead handler + Team 类（mock client，不发真实 API）。"""
import time
import threading
from types import SimpleNamespace

import pytest

from s16_team_protocols import teams
from s16_team_protocols.teams import (MessageBus, Team, active_teammates,
                                   run_send_message, run_check_inbox)


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


# ── MessageBus ──
def test_bus_send_read_consumes(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    bus.send("alice", "lead", "hi")
    msgs = bus.read_inbox("lead")
    assert len(msgs) == 1
    assert msgs[0]["from"] == "alice"
    assert msgs[0]["to"] == "lead"
    assert msgs[0]["content"] == "hi"
    assert msgs[0]["type"] == "message"
    assert "ts" in msgs[0]
    # 消费式：读后 unlink
    assert bus.read_inbox("lead") == []
    assert not (tmp_path / "lead.jsonl").exists()


def test_bus_read_empty_missing(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    assert bus.read_inbox("nobody") == []


def test_bus_peek_non_destructive(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    assert bus.peek("lead") is False
    bus.send("alice", "lead", "hi")
    assert bus.peek("lead") is True
    bus.read_inbox("lead")  # consume
    assert bus.peek("lead") is False


def test_bus_isolation_per_agent(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    bus.send("lead", "alice", "do X")
    bus.send("bob", "alice", "do Y")
    bus.send("alice", "lead", "done")
    alice = bus.read_inbox("alice")
    lead = bus.read_inbox("lead")
    assert len(alice) == 2
    assert len(lead) == 1
    assert lead[0]["from"] == "alice"


def test_bus_send_custom_type(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    bus.send("alice", "lead", "result text", "result")
    assert bus.read_inbox("lead")[0]["type"] == "result"


def test_bus_default_dir_created():
    # 默认 mailbox_dir 落在 WORKDIR/.mailboxes（不抛错即可）
    bus = MessageBus()
    assert bus.dir.exists()


# ── lead handlers（monkeypatch 模块 BUS 用 tmp 邮箱）──
@pytest.fixture
def tmp_bus(tmp_path, monkeypatch):
    bus = MessageBus(mailbox_dir=tmp_path)
    monkeypatch.setattr(teams, "BUS", bus)
    return bus


def test_run_send_message_uses_lead_as_from(tmp_bus):
    assert run_send_message("alice", "hello") == "Sent to alice"
    msgs = tmp_bus.read_inbox("alice")
    assert msgs[0]["from"] == "lead"
    assert msgs[0]["content"] == "hello"


def test_run_check_inbox_empty(tmp_bus):
    assert run_check_inbox() == "(inbox empty)"


def test_run_check_inbox_formats_and_consumes(tmp_bus):
    tmp_bus.send("alice", "lead", "done thing")
    tmp_bus.send("bob", "lead", "done other")
    out = run_check_inbox()
    assert "alice" in out and "done thing" in out
    assert "bob" in out and "done other" in out
    assert run_check_inbox() == "(inbox empty)"  # 消费


def test_run_check_inbox_truncates_long(tmp_bus):
    tmp_bus.send("alice", "lead", "x" * 300)
    out = run_check_inbox()
    assert "x" * 200 in out
    assert "x" * 201 not in out


# ── Team ──
@pytest.fixture(autouse=True)
def _reset_active():
    active_teammates.clear()
    yield
    active_teammates.clear()


def _wait_done(name, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if name not in active_teammates:
            return True
        time.sleep(0.01)
    return False


def test_spawn_dedup_returns_exists(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([]), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None)
    active_teammates["alice"] = True
    assert team.spawn("alice", "dev", "do") == "Teammate 'alice' already exists"


def test_spawn_registers_returns_and_finishes(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([make_response([text_block("all done")], "end_turn")]),
                model="m", bus=bus, base_handlers={}, sub_tools=[],
                trigger=lambda ev, *a: None)
    ret = team.spawn("alice", "dev", "do something")
    assert ret == "Teammate 'alice' spawned as dev"
    assert "alice" in active_teammates
    assert _wait_done("alice")
    assert "alice" not in active_teammates  # 完成后 pop
    lead = bus.read_inbox("lead")
    assert len(lead) == 1
    assert lead[0]["from"] == "alice"
    assert lead[0]["type"] == "result"
    assert lead[0]["content"] == "all done"


def test_run_inbox_injected_at_round_top(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    captured = []

    class Cap:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            captured.append(kw.get("messages"))
            return make_response([text_block("ok")], "end_turn")

    team = Team(client=Cap(), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None)
    bus.send("lead", "alice", "status check")
    team._run("alice", "dev", "do")
    inbox_msgs = [m for m in captured[0] if "<inbox>" in str(m.get("content", ""))]
    assert inbox_msgs
    assert "status check" in inbox_msgs[0]["content"]


def test_run_sliding_window_twenty(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    captured = []

    class Cap:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            captured.append(kw.get("messages"))
            return make_response([tool_use_block("t", "bash", {"command": "ls"})], "tool_use")

    team = Team(client=Cap(), model="m", bus=bus,
                base_handlers={"bash": lambda command: "OUT"},
                sub_tools=[], trigger=lambda ev, *a: None, max_turns=25)
    team._run("alice", "dev", "do")
    assert len(captured[-1]) <= 20  # messages[-20:]


def test_run_send_message_uses_teammate_name(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([
        make_response([tool_use_block("t1", "send_message",
                                      {"to": "lead", "content": "hi from alice"})], "tool_use"),
        make_response([text_block("all done")], "end_turn"),
    ]), model="m", bus=bus, base_handlers={}, sub_tools=[],
       trigger=lambda ev, *a: None)
    team._run("alice", "dev", "do")
    lead = bus.read_inbox("lead")
    assert len(lead) == 2  # 循环内 send_message + 完成后 result
    assert lead[0]["from"] == "alice"
    assert lead[0]["content"] == "hi from alice"
    assert lead[1]["type"] == "result"


def test_run_blocked_tool_skips(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    calls = []

    def trigger(ev, *a):
        if ev == "PreToolUse":
            return "Permission denied"
        return None

    team = Team(client=FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ]), model="m", bus=bus,
       base_handlers={"bash": lambda command: calls.append("bash") or "OUT"},
       sub_tools=[], trigger=trigger)
    team._run("alice", "dev", "do")
    assert calls == []  # 阻塞，未执行


def test_run_post_tool_use_hook(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    events = []
    team = Team(client=FakeClient([
        make_response([tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ]), model="m", bus=bus,
       base_handlers={"bash": lambda command: "OUT"},
       sub_tools=[], trigger=lambda ev, *a: events.append(ev) or None)
    team._run("alice", "dev", "do")
    assert "PreToolUse" in events
    assert "PostToolUse" in events


def test_run_summary_reversed_search(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([
        make_response([text_block("partial answer"), tool_use_block("t1", "bash", {"command": "ls"})], "tool_use"),
        make_response([tool_use_block("t2", "bash", {"command": "ls"})], "tool_use"),
    ]), model="m", bus=bus,
       base_handlers={"bash": lambda command: "OUT"},
       sub_tools=[], trigger=lambda ev, *a: None, max_turns=2)
    team._run("alice", "dev", "do")
    assert bus.read_inbox("lead")[0]["content"] == "partial answer"


def test_run_max_turns_fallback_done(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=AlwaysToolClient(), model="m", bus=bus,
                base_handlers={"bash": lambda command: "OUT"},
                sub_tools=[], trigger=lambda ev, *a: None, max_turns=3)
    team._run("alice", "dev", "do")
    assert bus.read_inbox("lead")[0]["content"] == "Done."
    assert "alice" not in active_teammates


def test_run_llm_exception_breaks(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)

    class Boom:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            raise RuntimeError("network down")

    team = Team(client=Boom(), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None)
    team._run("alice", "dev", "do")
    assert bus.read_inbox("lead")[0]["content"] == "Done."
    assert "alice" not in active_teammates
