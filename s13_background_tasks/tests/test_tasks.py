import json
import re
import pytest
from s13_background_tasks import tasks
from s13_background_tasks.tasks import (Task, create_task, save_task, load_task, list_tasks,
                                   get_task, can_start, claim_task, complete_task,
                                   run_create_task, run_list_tasks, run_get_task,
                                   run_claim_task, run_complete_task)


@pytest.fixture
def td(tmp_path, monkeypatch):
    d = tmp_path / "tasks"
    d.mkdir()
    monkeypatch.setattr(tasks, "TASKS_DIR", d)
    return d


def test_create_task_persists(td):
    t = create_task("setup schema", "desc", [])
    assert t.status == "pending"
    assert t.owner is None
    assert t.blockedBy == []
    assert re.fullmatch(r"task_\d+_\d{4}", t.id)
    assert (td / f"{t.id}.json").exists()


def test_create_task_with_blockedby(td):
    t = create_task("x", "d", ["task_1_0001"])  # 依赖不存在也照存
    assert t.blockedBy == ["task_1_0001"]


def test_save_load_roundtrip(td):
    t = create_task("x", "d", [])
    loaded = load_task(t.id)
    assert loaded == t


def test_list_tasks_empty(td):
    assert list_tasks() == []


def test_list_tasks_returns_all(td):
    # 同一秒内创建时，顺序由随机 4 位数决定（按文件名序），故只断言集合
    a = create_task("a")
    b = create_task("b")
    c = create_task("c")
    subjects = {t.subject for t in list_tasks()}
    assert subjects == {"a", "b", "c"}


def test_get_task_found(td):
    t = create_task("x", "d", [])
    data = json.loads(get_task(t.id))
    assert data["subject"] == "x"


def test_get_task_missing_raises(td):
    with pytest.raises(FileNotFoundError):
        get_task("task_0_0000")


def test_can_start_no_deps(td):
    t = create_task("x")
    assert can_start(t.id) is True


def test_can_start_missing_dep(td):
    t = create_task("x", blockedBy=["task_1_0001"])
    assert can_start(t.id) is False


def test_can_start_pending_dep(td):
    dep = create_task("dep")
    t = create_task("x", blockedBy=[dep.id])
    assert can_start(t.id) is False


def test_can_start_completed_dep(td):
    dep = create_task("dep")
    dep.status = "completed"
    save_task(dep)
    t = create_task("x", blockedBy=[dep.id])
    assert can_start(t.id) is True


def test_can_start_mixed_deps(td):
    d1 = create_task("d1"); d1.status = "completed"; save_task(d1)
    d2 = create_task("d2")  # pending
    t = create_task("x", blockedBy=[d1.id, d2.id])
    assert can_start(t.id) is False


def test_claim_pending(td):
    t = create_task("x")
    msg = claim_task(t.id)
    assert "Claimed" in msg
    assert load_task(t.id).status == "in_progress"
    assert load_task(t.id).owner == "agent"


def test_claim_with_owner(td):
    t = create_task("x")
    claim_task(t.id, owner="bob")
    assert load_task(t.id).owner == "bob"


def test_claim_non_pending(td):
    t = create_task("x"); t.status = "in_progress"; save_task(t)
    assert "cannot claim" in claim_task(t.id)


def test_claim_blocked(td):
    dep = create_task("dep")  # pending
    t = create_task("x", blockedBy=[dep.id])
    msg = claim_task(t.id)
    assert "Blocked by" in msg
    assert load_task(t.id).status == "pending"  # 不变


def test_complete_in_progress(td):
    t = create_task("x"); claim_task(t.id)
    msg = complete_task(t.id)
    assert "Completed" in msg
    assert load_task(t.id).status == "completed"


def test_complete_non_in_progress(td):
    t = create_task("x")  # pending
    assert "cannot complete" in complete_task(t.id)


def test_complete_reports_unblocked(td):
    schema = create_task("schema"); claim_task(schema.id)
    endpoints = create_task("endpoints", blockedBy=[schema.id])
    msg = complete_task(schema.id)
    assert "Unblocked" in msg
    assert "endpoints" in msg


def test_complete_no_downstream_no_unblocked(td):
    t = create_task("x"); claim_task(t.id)
    msg = complete_task(t.id)
    assert "Unblocked" not in msg


def test_run_list_tasks_empty(td):
    assert run_list_tasks() == "No tasks. Use create_task to add some."


def test_run_list_tasks_format(td):
    t = create_task("x"); claim_task(t.id, owner="bob")
    out = run_list_tasks()
    assert "●" in out  # in_progress icon
    assert t.id in out
    assert "[bob]" in out


def test_run_list_tasks_blockedby(td):
    dep = create_task("dep")
    t = create_task("x", blockedBy=[dep.id])
    out = run_list_tasks()
    assert f"blockedBy: {dep.id}" in out


def test_run_get_task_missing(td):
    assert run_get_task("task_0_0000") == "Error: Task task_0_0000 not found"


def test_run_create_task_returns_msg(td):
    msg = run_create_task("x", "d", [])
    assert "Created" in msg


def test_dag_end_to_end(td):
    schema = create_task("schema")
    endpoints = create_task("endpoints", blockedBy=[schema.id])
    tests = create_task("tests", blockedBy=[endpoints.id])
    # claim schema OK
    assert "Claimed" in claim_task(schema.id)
    # claim endpoints blocked
    assert "Blocked by" in claim_task(endpoints.id)
    # complete schema → endpoints unblocked (not tests)
    msg = complete_task(schema.id)
    assert "endpoints" in msg
    assert "tests" not in msg
    # claim endpoints now OK
    assert "Claimed" in claim_task(endpoints.id)
    # complete endpoints → tests unblocked
    msg = complete_task(endpoints.id)
    assert "tests" in msg


def test_persistence_across_session(td):
    t = create_task("x")
    # 模拟新进程：重新 list
    assert any(tt.id == t.id for tt in list_tasks())
