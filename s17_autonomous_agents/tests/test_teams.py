"""teams.py 测试——MessageBus + 协议状态机 + lead handler + Team 类（mock client，不发真实 API）。"""
import time
import threading
from types import SimpleNamespace

import pytest

from s17_autonomous_agents import teams
from s17_autonomous_agents.teams import (MessageBus, Team, active_teammates,
                                   run_send_message, run_check_inbox,
                                   ProtocolState, pending_requests, new_request_id,
                                   match_response, consume_lead_inbox,
                                   run_request_shutdown, run_request_plan, run_review_plan,
                                   _teammate_submit_plan)


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
def _reset_active(monkeypatch):
    active_teammates.clear()
    pending_requests.clear()
    # 默认无未认领任务（idle_poll 不自动认领）；自动认领测试单独覆盖
    monkeypatch.setattr(teams, "scan_unclaimed_tasks", lambda: [])
    yield
    active_teammates.clear()
    pending_requests.clear()


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
                trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
    ret = team.spawn("alice", "dev", "do something")
    assert ret == "Teammate 'alice' spawned as dev"
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
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
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
                sub_tools=[], trigger=lambda ev, *a: None, max_turns=25,
                idle_poll_interval=0.01, max_idle_polls=2)
    team._run("alice", "dev", "do")
    assert len(captured[-1]) <= 20  # messages[-20:]


def test_run_send_message_uses_teammate_name(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([
        make_response([tool_use_block("t1", "send_message",
                                      {"to": "lead", "content": "hi from alice"})], "tool_use"),
        make_response([text_block("all done")], "end_turn"),
    ]), model="m", bus=bus, base_handlers={}, sub_tools=[],
       trigger=lambda ev, *a: None,
       idle_poll_interval=0.01, max_idle_polls=2)
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
       sub_tools=[], trigger=trigger,
       idle_poll_interval=0.01, max_idle_polls=2)
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
       sub_tools=[], trigger=lambda ev, *a: events.append(ev) or None,
       idle_poll_interval=0.01, max_idle_polls=2)
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
       sub_tools=[], trigger=lambda ev, *a: None, max_turns=2,
       idle_poll_interval=0.01, max_idle_polls=2)
    team._run("alice", "dev", "do")
    assert bus.read_inbox("lead")[0]["content"] == "partial answer"


def test_run_max_turns_fallback_done(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=AlwaysToolClient(), model="m", bus=bus,
                base_handlers={"bash": lambda command: "OUT"},
                sub_tools=[], trigger=lambda ev, *a: None, max_turns=3,
                idle_poll_interval=0.01, max_idle_polls=2)
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
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
    team._run("alice", "dev", "do")
    assert bus.read_inbox("lead")[0]["content"] == "Done."
    assert "alice" not in active_teammates


# ── s16 协议状态机 ──
def test_bus_send_with_metadata(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    bus.send("lead", "alice", "shut down", "shutdown_request", {"request_id": "req_1"})
    msg = bus.read_inbox("alice")[0]
    assert msg["type"] == "shutdown_request"
    assert msg["metadata"] == {"request_id": "req_1"}


def test_bus_send_default_metadata_empty(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    bus.send("alice", "lead", "hi")
    assert bus.read_inbox("lead")[0]["metadata"] == {}


def test_new_request_id_format():
    rid = new_request_id()
    assert rid.startswith("req_") and len(rid) == 10  # req_ + 6 digits


def test_match_response_approve_and_reject():
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "pending", "")
    match_response("shutdown_response", "req_1", True)
    assert pending_requests["req_1"].status == "approved"
    pending_requests["req_2"] = ProtocolState("req_2", "shutdown", "lead", "alice", "pending", "")
    match_response("shutdown_response", "req_2", False)
    assert pending_requests["req_2"].status == "rejected"


def test_match_response_unknown_id_noop():
    match_response("shutdown_response", "req_unknown", True)
    assert "req_unknown" not in pending_requests


def test_match_response_type_mismatch_noop():
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "pending", "")
    match_response("plan_approval_response", "req_1", True)
    assert pending_requests["req_1"].status == "pending"  # 类型不匹配，不改


def test_match_response_idempotent_when_resolved():
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "approved", "")
    match_response("shutdown_response", "req_1", False)
    assert pending_requests["req_1"].status == "approved"  # 已决议，幂等不改


def test_consume_lead_inbox_routes_protocol_responses(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "pending", "")
    tmp_bus.send("alice", "lead", "Shutting down.", "shutdown_response",
                 {"request_id": "req_1", "approve": True})
    msgs = consume_lead_inbox(route_protocol=True)
    assert len(msgs) == 1
    assert pending_requests["req_1"].status == "approved"  # 路由后状态更新


def test_consume_lead_inbox_no_route_when_disabled(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "pending", "")
    tmp_bus.send("alice", "lead", "Shutting down.", "shutdown_response",
                 {"request_id": "req_1", "approve": True})
    consume_lead_inbox(route_protocol=False)
    assert pending_requests["req_1"].status == "pending"  # 未路由


def test_consume_lead_inbox_empty(tmp_bus):
    assert consume_lead_inbox() == []


def test_run_request_shutdown_creates_state_and_sends(tmp_bus):
    out = run_request_shutdown("alice")
    assert "alice" in out and "req_" in out
    assert len(pending_requests) == 1
    state = next(iter(pending_requests.values()))
    assert state.type == "shutdown" and state.status == "pending"
    assert state.target == "alice"
    msg = tmp_bus.read_inbox("alice")[0]
    assert msg["type"] == "shutdown_request"
    assert msg["metadata"]["request_id"] == state.request_id


def test_run_request_plan_sends_plain_message(tmp_bus):
    assert run_request_plan("alice", "refactor auth") == "Asked alice to submit a plan"
    msg = tmp_bus.read_inbox("alice")[0]
    assert msg["type"] == "message"
    assert "refactor auth" in msg["content"]
    assert len(pending_requests) == 0  # 不创建协议状态


def test_run_review_plan_approve_and_send(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "plan_approval", "bob", "lead", "pending", "plan text")
    out = run_review_plan("req_1", True, "looks good")
    assert "approved" in out
    assert pending_requests["req_1"].status == "approved"
    msg = tmp_bus.read_inbox("bob")[0]
    assert msg["type"] == "plan_approval_response"
    assert msg["metadata"] == {"request_id": "req_1", "approve": True}
    assert msg["content"] == "looks good"


def test_run_review_plan_reject(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "plan_approval", "bob", "lead", "pending", "plan")
    run_review_plan("req_1", False)
    assert pending_requests["req_1"].status == "rejected"


def test_run_review_plan_not_found():
    assert "not found" in run_review_plan("req_x", True).lower()


def test_run_review_plan_already_resolved(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "plan_approval", "bob", "lead", "approved", "plan")
    out = run_review_plan("req_1", False)
    assert "already" in out
    assert pending_requests["req_1"].status == "approved"  # 不改


def test_teammate_submit_plan_creates_state_and_sends(tmp_bus):
    out = _teammate_submit_plan("alice", "I will refactor X then Y")
    assert "req_" in out
    state = next(iter(pending_requests.values()))
    assert state.type == "plan_approval"
    assert state.sender == "alice"
    assert state.payload == "I will refactor X then Y"
    msg = tmp_bus.read_inbox("lead")[0]
    assert msg["type"] == "plan_approval_request"
    assert msg["from"] == "alice"
    assert msg["metadata"]["request_id"] == state.request_id


def test_run_check_inbox_routes_and_tags(tmp_bus):
    pending_requests["req_1"] = ProtocolState("req_1", "shutdown", "lead", "alice", "pending", "")
    tmp_bus.send("alice", "lead", "Shutting down.", "shutdown_response",
                 {"request_id": "req_1", "approve": True})
    out = run_check_inbox()
    assert "alice" in out and "shutdown_response" in out and "req_1" in out
    assert pending_requests["req_1"].status == "approved"  # 路由了
    assert run_check_inbox() == "(inbox empty)"  # 消费了


# ── s16 Team idle loop + dispatch ──
def _team(tmp_path, client, base_handlers=None, trigger=None, **kw):
    """构造 Team，默认短 idle 参数（测试不挂）。kw 覆盖默认。"""
    bus = MessageBus(mailbox_dir=tmp_path)
    defaults = dict(idle_poll_interval=0.01, max_idle_polls=2)
    defaults.update(kw)
    return Team(client=client, model="m", bus=bus,
                base_handlers=base_handlers or {}, sub_tools=[],
                trigger=trigger or (lambda ev, *a: None), **defaults)


def test_handle_inbox_shutdown_replies_and_stops(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([]), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None)
    messages = []
    stop = team._handle_inbox_message("alice", {
        "type": "shutdown_request", "from": "lead", "content": "shut down",
        "metadata": {"request_id": "req_1"}}, messages)
    assert stop is True
    lead = bus.read_inbox("lead")
    assert lead[0]["type"] == "shutdown_response"
    assert lead[0]["metadata"] == {"request_id": "req_1", "approve": True}
    assert lead[0]["from"] == "alice"


def test_handle_inbox_plan_approved_injects(tmp_path):
    team = _team(tmp_path, FakeClient([]))
    messages = []
    stop = team._handle_inbox_message("alice", {
        "type": "plan_approval_response", "from": "lead", "content": "",
        "metadata": {"request_id": "req_1", "approve": True}}, messages)
    assert stop is False
    assert "[Plan approved]" in messages[-1]["content"]


def test_handle_inbox_plan_rejected_injects_feedback(tmp_path):
    team = _team(tmp_path, FakeClient([]))
    messages = []
    team._handle_inbox_message("alice", {
        "type": "plan_approval_response", "from": "lead", "content": "needs tests",
        "metadata": {"request_id": "req_1", "approve": False}}, messages)
    assert "[Plan rejected]" in messages[-1]["content"]
    assert "needs tests" in messages[-1]["content"]


def test_handle_inbox_other_returns_false(tmp_path):
    team = _team(tmp_path, FakeClient([]))
    assert team._handle_inbox_message("alice",
        {"type": "message", "from": "lead", "content": "hi", "metadata": {}}, []) is False


def test_drain_inbox_separates_protocol_and_nonprotocol(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([]), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None)
    bus.send("lead", "alice", "do thing", "message")              # 非协议
    bus.send("lead", "alice", "shut down", "shutdown_request",
             {"request_id": "req_1"})                             # 协议
    messages = []
    shutdown, got_msg = team._drain_inbox("alice", messages)
    assert shutdown is True
    assert got_msg is True  # 非协议消息注入了
    assert "<inbox>" in messages[-1]["content"]
    # 协议消息已回复 shutdown_response
    assert bus.read_inbox("lead")[0]["type"] == "shutdown_response"


def test_drain_inbox_empty(tmp_path):
    team = _team(tmp_path, FakeClient([]))
    assert team._drain_inbox("alice", []) == (False, False)


def test_idle_poll_shutdown(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([]), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=5)
    bus.send("lead", "alice", "shut down", "shutdown_request", {"request_id": "req_1"})
    assert team.idle_poll("alice", [], "dev") == "shutdown"


def test_idle_poll_message(tmp_path):
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([]), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=5)
    bus.send("lead", "alice", "new task", "message")
    messages = []
    assert team.idle_poll("alice", messages, "dev") == "work"
    assert "<inbox>" in messages[-1]["content"]


def test_idle_poll_timeout(tmp_path):
    team = _team(tmp_path, FakeClient([]), max_idle_polls=2)
    assert team.idle_poll("alice", [], "dev") == "timeout"


def test_idle_poll_auto_claim(tmp_path, monkeypatch):
    """idle_poll 扫到未认领任务 → claim → 注入 <auto-claimed> + 返 'work'。"""
    monkeypatch.setattr(teams, "scan_unclaimed_tasks",
                        lambda: [{"id": "task_1", "subject": "do X"}])
    monkeypatch.setattr(teams, "claim_task",
                        lambda task_id, owner="agent": f"Claimed {task_id} (do X)")
    team = _team(tmp_path, FakeClient([]), max_idle_polls=5)
    messages = []
    assert team.idle_poll("alice", messages, "dev") == "work"
    assert "<auto-claimed>" in messages[-1]["content"]
    assert "do X" in messages[-1]["content"]


def test_run_active_turn_shutdown_no_llm(tmp_path):
    """turn 顶上 drain 到 shutdown_request → 回复 + 退出，不调 LLM。"""
    calls = []

    class Boom:
        @property
        def messages(self): return self
        def create(self, **kw):
            calls.append("llm"); return make_response([text_block("x")], "end_turn")

    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=Boom(), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
    bus.send("lead", "alice", "shut down", "shutdown_request", {"request_id": "req_1"})
    team._run("alice", "dev", "do")
    assert calls == []  # 未调 LLM
    lead = bus.read_inbox("lead")
    types = [m["type"] for m in lead]
    assert "shutdown_response" in types
    assert "result" in types  # 退出前发 summary
    assert "alice" not in active_teammates


def test_run_plan_approval_injected_then_idle(tmp_path):
    """turn 顶上 drain 到 plan_approval_response → 注入 [Plan approved] → LLM turn → idle 退出。"""
    captured = []

    class Cap:
        @property
        def messages(self): return self
        def create(self, **kw):
            captured.append(kw.get("messages"))
            return make_response([text_block("ok")], "end_turn")

    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=Cap(), model="m", bus=bus, base_handlers={},
                sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
    bus.send("lead", "alice", "", "plan_approval_response",
             {"request_id": "req_1", "approve": True})
    team._run("alice", "dev", "do")
    # 首轮 LLM 的 messages 含 [Plan approved] 注入
    assert any("[Plan approved]" in str(m.get("content", "")) for m in captured[0])


def test_run_submit_plan_creates_state(tmp_path):
    """队友调 submit_plan 工具 → 创建 plan_approval 状态 + 发 plan_approval_request。"""
    team = _team(tmp_path, FakeClient([
        make_response([tool_use_block("t1", "submit_plan", {"plan": "refactor X"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ]), base_handlers={})
    team._run("alice", "dev", "do")
    assert len(pending_requests) == 1
    state = next(iter(pending_requests.values()))
    assert state.type == "plan_approval"
    assert state.sender == "alice"
    assert state.payload == "refactor X"
    # plan_approval_request 发到 lead 邮箱
    lead = team.bus.read_inbox("lead")
    assert any(m["type"] == "plan_approval_request" for m in lead)


def test_run_idle_shutdown_via_thread(tmp_path):
    """spawn 后 alice 跑完 end_turn → idle；发 shutdown_request → alice 退出。"""
    bus = MessageBus(mailbox_dir=tmp_path)
    team = Team(client=FakeClient([make_response([text_block("working")], "end_turn")]),
                model="m", bus=bus, base_handlers={}, sub_tools=[],
                trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=10000)
    team.spawn("alice", "dev", "do")
    # 给 alice 一点时间进入 idle
    time.sleep(0.05)
    assert "alice" in active_teammates  # 还在 idle
    bus.send("lead", "alice", "shut down", "shutdown_request", {"request_id": "req_1"})
    assert _wait_done("alice", timeout=2.0)
    lead = bus.read_inbox("lead")
    types = [m["type"] for m in lead]
    assert "shutdown_response" in types
    assert "result" in types


# ── s17 新增：身份重注入 + auto-claim WORK→IDLE 循环 ──
def test_run_identity_reinjected_when_messages_short(tmp_path):
    """WORK 阶段顶上：messages 过短（≤3，模拟压缩后）→ 注入 <identity>。"""
    captured = []

    class Cap:
        @property
        def messages(self): return self
        def create(self, **kw):
            captured.append(kw.get("messages"))
            return make_response([text_block("ok")], "end_turn")

    team = Team(client=Cap(), model="m", bus=MessageBus(mailbox_dir=tmp_path),
                base_handlers={}, sub_tools=[], trigger=lambda ev, *a: None,
                idle_poll_interval=0.01, max_idle_polls=2)
    team._run("alice", "backend", "do")
    # 首轮 WORK 的 messages 含 <identity>（初始 messages=[prompt] len 1 ≤ 3）
    assert any("<identity>" in str(m.get("content", "")) for m in captured[0])
    assert "backend" in str(captured[0][0]["content"])


def test_run_auto_claim_cycle(tmp_path, monkeypatch):
    """IDLE 扫到任务 → auto-claim → 新 WORK phase 跑 → IDLE 超时退出。"""
    scan_calls = []

    def fake_scan():
        scan_calls.append(1)
        # 第一次 IDLE 返回任务；之后返回空（claim 后任务不在了）
        return [{"id": "task_1", "subject": "do X"}] if len(scan_calls) == 1 else []

    monkeypatch.setattr(teams, "scan_unclaimed_tasks", fake_scan)
    monkeypatch.setattr(teams, "claim_task",
                        lambda task_id, owner="agent": f"Claimed {task_id} (do X)")
    team = _team(tmp_path, FakeClient([
        make_response([text_block("working on claimed task")], "end_turn"),  # WORK1（初始）
        make_response([text_block("done X")], "end_turn"),                    # WORK2（auto-claim 后）
    ]), max_idle_polls=2)
    messages_snapshot = []
    team._run("alice", "backend", "do")
    # auto-claimed 消息在 messages 里
    lead = team.bus.read_inbox("lead")
    assert lead[-1]["type"] == "result"
    assert "done X" in lead[-1]["content"]
