import json
import re
import pytest
from s18_worktree_isolation import tasks
from s18_worktree_isolation.tasks import (Task, create_task, save_task, load_task, list_tasks,
                                   get_task, can_start, claim_task, complete_task,
                                   scan_unclaimed_tasks,
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


# ── s17 新增：claim owner 检查 + scan_unclaimed_tasks ──
def test_claim_rejects_already_owned(td):
    """owner 检查：status=pending 但已设 owner（竞态窗口）→ 拒绝。"""
    t = create_task("x")
    # 模拟竞态：手动设 owner 但保持 pending（claim 正常会同时设 in_progress）
    task = load_task(t.id)
    task.owner = "alice"
    save_task(task)
    result = claim_task(t.id, owner="bob")
    assert "already owned" in result and "alice" in result
    assert load_task(t.id).owner == "alice"  # 未被 bob 覆盖


def test_claim_normal_flow_sets_in_progress(td):
    """正常 claim 后 status=in_progress；再次 claim 走 status 检查（非 owner 检查）。"""
    t = create_task("x")
    assert claim_task(t.id, owner="alice") == f"Claimed {t.id} (x)"
    result = claim_task(t.id, owner="bob")
    assert "in_progress" in result  # status 检查先于 owner


def test_scan_unclaimed_returns_pending_unowned_startable(td):
    t = create_task("do A")
    unclaimed = scan_unclaimed_tasks()
    assert len(unclaimed) == 1
    assert unclaimed[0]["id"] == t.id
    assert unclaimed[0]["status"] == "pending"


def test_scan_excludes_owned(td):
    t = create_task("do A")
    claim_task(t.id, owner="alice")
    assert scan_unclaimed_tasks() == []


def test_scan_excludes_in_progress_and_completed(td):
    t1 = create_task("a")
    t2 = create_task("b")
    claim_task(t1.id, owner="alice")  # → in_progress
    complete_task(t1.id)              # → completed
    claim_task(t2.id, owner="bob")    # → in_progress
    assert scan_unclaimed_tasks() == []


def test_scan_excludes_blocked(td):
    t1 = create_task("prereq")
    t2 = create_task("dependent", blockedBy=[t1.id])  # t1 未完成 → blocked
    unclaimed = scan_unclaimed_tasks()
    assert [t["id"] for t in unclaimed] == [t1.id]  # 只 t1 可认领


def test_scan_includes_unblocked_after_dep_completes(td):
    t1 = create_task("prereq")
    t2 = create_task("dependent", blockedBy=[t1.id])
    claim_task(t1.id, owner="alice")
    complete_task(t1.id)  # t1 完成 → t2 解锁
    unclaimed = scan_unclaimed_tasks()
    assert [t["id"] for t in unclaimed] == [t2.id]


# ── s18 新增：Task.worktree 字段 ──
def test_task_worktree_defaults_none(td):
    t = create_task("x")
    assert t.worktree is None
    loaded = load_task(t.id)
    assert loaded.worktree is None


def test_task_worktree_persists(td):
    t = create_task("x")
    t.worktree = "auth-refactor"
    save_task(t)
    assert load_task(t.id).worktree == "auth-refactor"


def test_old_task_json_without_worktree_loads(td):
    """旧 JSON（无 worktree 字段）能加载（默认 None）。"""
    import json
    raw = {"id": "task_old", "subject": "old", "description": "",
           "status": "pending", "owner": None, "blockedBy": []}
    (td / "task_old.json").write_text(json.dumps(raw))
    t = load_task("task_old")
    assert t.worktree is None
