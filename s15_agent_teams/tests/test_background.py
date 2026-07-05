import time
import threading
import pytest
from types import SimpleNamespace
from s15_agent_teams import background
from s15_agent_teams.background import (is_slow_operation, should_run_background,
                                             start_background_task, collect_background_results,
                                             has_pending_background)


@pytest.fixture(autouse=True)
def _reset():
    background._bg_counter = 0
    background.background_tasks.clear()
    background.background_results.clear()
    yield
    background._bg_counter = 0
    background.background_tasks.clear()
    background.background_results.clear()


def block(name="bash", inp=None, bid="b1"):
    return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp or {})


def _wait_completed(bg_id, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with background.background_lock:
            if background.background_tasks.get(bg_id, {}).get("status") == "completed":
                return True
        time.sleep(0.01)
    return False


# ── is_slow_operation ──
def test_is_slow_install():
    assert is_slow_operation("bash", {"command": "pip install torch"}) is True


def test_is_slow_build():
    assert is_slow_operation("bash", {"command": "npm run build"}) is True


def test_is_slow_pytest():
    assert is_slow_operation("bash", {"command": "pytest -x"}) is True


def test_is_slow_case_insensitive():
    assert is_slow_operation("bash", {"command": "PIP INSTALL"}) is True


def test_is_not_slow():
    assert is_slow_operation("bash", {"command": "git status"}) is False
    assert is_slow_operation("bash", {"command": "echo hello"}) is False


def test_is_slow_non_bash():
    assert is_slow_operation("read_file", {"path": "x"}) is False


# ── should_run_background ──
def test_should_run_explicit_true():
    assert should_run_background("bash", {"command": "echo hi", "run_in_background": True}) is True


def test_should_run_explicit_false_falls_back_to_heuristic():
    assert should_run_background("bash", {"command": "pip install x", "run_in_background": False}) is True


def test_should_run_neither():
    assert should_run_background("bash", {"command": "echo hi"}) is False


def test_should_run_none():
    assert should_run_background("bash", {"command": "echo hi", "run_in_background": None}) is False


# ── start_background_task ──
def test_start_returns_bg_id_and_registers():
    started = threading.Event()
    release = threading.Event()

    def slow_run(n, i):
        started.set()
        release.wait(2)  # 阻塞保持 running
        return "OUT"

    b = block(inp={"command": "echo hi"})
    bg_id = start_background_task(b, slow_run)
    assert bg_id == "bg_0001"
    assert started.wait(2)  # 等 worker 进入
    with background.background_lock:
        assert background.background_tasks[bg_id]["status"] == "running"
        assert background.background_tasks[bg_id]["tool_use_id"] == "b1"
        assert background.background_tasks[bg_id]["command"] == "echo hi"
    release.set()
    assert _wait_completed(bg_id)


def test_start_increments_counter():
    start_background_task(block(inp={"command": "a"}), lambda n, i: "OUT")
    bg2 = start_background_task(block(inp={"command": "b"}, bid="b2"), lambda n, i: "OUT")
    assert bg2 == "bg_0002"


def test_worker_completes_with_result():
    b = block(inp={"command": "echo done"})
    bg_id = start_background_task(b, lambda n, i: "RESULT")
    assert _wait_completed(bg_id)
    with background.background_lock:
        assert background.background_results[bg_id] == "RESULT"


def test_worker_catches_exception():
    def boom(n, i):
        raise ValueError("fail")
    bg_id = start_background_task(block(inp={"command": "x"}), boom)
    assert _wait_completed(bg_id)
    with background.background_lock:
        assert "Error" in background.background_results[bg_id]
        assert "ValueError" in background.background_results[bg_id]


# ── collect_background_results ──
def test_collect_empty():
    assert collect_background_results() == []


def test_collect_completed_format():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "echo hi", "status": "completed"}
        background.background_results["bg_0001"] = "hello world"
    notifs = collect_background_results()
    assert len(notifs) == 1
    n = notifs[0]
    assert "<task_notification>" in n
    assert "<task_id>bg_0001</task_id>" in n
    assert "<status>completed</status>" in n
    assert "<command>echo hi</command>" in n
    assert "<summary>hello world</summary>" in n


def test_collect_pops():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "completed"}
        background.background_results["bg_0001"] = "out"
    collect_background_results()
    assert "bg_0001" not in background.background_tasks
    assert collect_background_results() == []


def test_collect_only_completed():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "running"}
    assert collect_background_results() == []
    assert "bg_0001" in background.background_tasks  # running 保留


def test_collect_summary_truncates():
    long_out = "x" * 500
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "completed"}
        background.background_results["bg_0001"] = long_out
    n = collect_background_results()[0]
    assert "<summary>" + "x" * 200 + "</summary>" in n


# ── s15 新增：has_pending_background ──
def test_has_pending_background_empty():
    assert has_pending_background() is False


def test_has_pending_background_running_false():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "running"}
    assert has_pending_background() is False


def test_has_pending_background_completed_true():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "completed"}
        background.background_results["bg_0001"] = "DONE"
    assert has_pending_background() is True


def test_has_pending_background_after_collect_false():
    with background.background_lock:
        background.background_tasks["bg_0001"] = {"tool_use_id": "b1", "command": "c", "status": "completed"}
        background.background_results["bg_0001"] = "DONE"
    collect_background_results()
    assert has_pending_background() is False
