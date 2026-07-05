"""worktrees.py 测试——validate/run_git/create/bind/remove/keep/log_event（mock git）。"""
import json
import pytest
from s20_comprehensive import worktrees
from s20_comprehensive.worktrees import (validate_worktree_name, run_git, log_event,
                                            create_worktree, bind_task_to_worktree,
                                            remove_worktree, keep_worktree,
                                            _count_worktree_changes)
from s20_comprehensive import tasks


@pytest.fixture
def wtd(tmp_path, monkeypatch):
    """tmp worktrees dir + tmp tasks dir。"""
    wd = tmp_path / "worktrees"
    wd.mkdir()
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", wd)
    td = tmp_path / "tasks"
    td.mkdir()
    monkeypatch.setattr(tasks, "TASKS_DIR", td)
    return wd


# ── validate_worktree_name ──
def test_validate_empty():
    assert validate_worktree_name("") == "Worktree name cannot be empty"


def test_validate_dotdot():
    assert "not a valid" in validate_worktree_name("..")


def test_validate_dot():
    assert "not a valid" in validate_worktree_name(".")


def test_validate_invalid_chars():
    assert validate_worktree_name("auth refactor") is not None  # 空格
    assert validate_worktree_name("a/b") is not None  # 斜杠
    assert validate_worktree_name("é") is not None  # 非ASCII


def test_validate_valid():
    assert validate_worktree_name("auth-refactor") is None
    assert validate_worktree_name("feat_1.v2") is None
    assert validate_worktree_name("a" * 64) is None


def test_validate_too_long():
    assert validate_worktree_name("a" * 65) is not None


# ── run_git ──
def test_run_git_success(monkeypatch):
    from types import SimpleNamespace

    class FakeProc:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    monkeypatch.setattr(worktrees.subprocess, "run", lambda *a, **k: FakeProc())
    ok, out = run_git(["status"])
    assert ok is True and "ok" in out


def test_run_git_failure(monkeypatch):
    from types import SimpleNamespace

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(worktrees.subprocess, "run", lambda *a, **k: FakeProc())
    ok, out = run_git(["bad"])
    assert ok is False and "boom" in out


# ── create_worktree ──
def test_create_invalid_name(wtd):
    assert "Error:" in create_worktree("a b")


def test_create_already_exists(wtd, monkeypatch):
    (wtd / "auth").mkdir()
    assert "already exists" in create_worktree("auth")


def test_create_git_fail(wtd, monkeypatch):
    monkeypatch.setattr(worktrees, "run_git", lambda args: (False, "git refused"))
    assert "Git error" in create_worktree("auth")


def test_create_success(wtd, monkeypatch):
    calls = []
    monkeypatch.setattr(worktrees, "run_git",
                        lambda args: calls.append(args) or (True, ""))
    out = create_worktree("auth-refactor")
    assert "created" in out and "auth-refactor" in out
    assert calls[0][:2] == ["worktree", "add"]  # git worktree add
    assert "-b" in calls[0] and "wt/auth-refactor" in calls[0]


def test_create_binds_task(wtd, monkeypatch):
    monkeypatch.setattr(worktrees, "run_git", lambda args: (True, ""))
    t = tasks.create_task("do auth")
    assert t.worktree is None
    create_worktree("auth", task_id=t.id)
    assert tasks.load_task(t.id).worktree == "auth"
    assert tasks.load_task(t.id).status == "pending"  # bind 不改状态


def test_create_logs_event(wtd, monkeypatch):
    monkeypatch.setattr(worktrees, "run_git", lambda args: (True, ""))
    t = tasks.create_task("do auth")
    create_worktree("auth", task_id=t.id)
    events = (wtd / "events.jsonl").read_text().splitlines()
    assert len(events) == 1
    ev = json.loads(events[0])
    assert ev["type"] == "create" and ev["worktree"] == "auth" and ev["task_id"] == t.id


# ── bind_task_to_worktree ──
def test_bind_writes_worktree_keeps_pending(wtd):
    t = tasks.create_task("x")
    bind_task_to_worktree(t.id, "auth")
    loaded = tasks.load_task(t.id)
    assert loaded.worktree == "auth"
    assert loaded.status == "pending"


# ── _count_worktree_changes ──
def test_count_changes(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, stdout): self.stdout = stdout; self.stderr = ""

    outputs = iter([FakeProc("M file1.py\n?? file2.py\n"), FakeProc("abc123 fix\n")])
    monkeypatch.setattr(worktrees.subprocess, "run", lambda *a, **k: next(outputs))
    files, commits = _count_worktree_changes(tmp_path)
    assert files == 2 and commits == 1


def test_count_changes_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(worktrees.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    assert _count_worktree_changes(tmp_path) == (-1, -1)


# ── remove_worktree ──
def test_remove_invalid_name(wtd):
    assert validate_worktree_name("a b") in remove_worktree("a b")


def test_remove_not_found(wtd):
    assert "not found" in remove_worktree("ghost")


def test_remove_refuses_with_changes(wtd, monkeypatch):
    (wtd / "auth").mkdir()
    monkeypatch.setattr(worktrees, "_count_worktree_changes", lambda p: (2, 1))
    out = remove_worktree("auth")
    assert "discard_changes" in out or "keep_worktree" in out


def test_remove_with_discard(wtd, monkeypatch):
    (wtd / "auth").mkdir()
    monkeypatch.setattr(worktrees, "_count_worktree_changes", lambda p: (2, 1))
    calls = []
    monkeypatch.setattr(worktrees, "run_git", lambda args: calls.append(args) or (True, ""))
    out = remove_worktree("auth", discard_changes=True)
    assert "removed" in out
    assert any(a[:2] == ["worktree", "remove"] for a in calls)
    assert any(a[:2] == ["branch", "-D"] for a in calls)


def test_remove_clean(wtd, monkeypatch):
    (wtd / "auth").mkdir()
    monkeypatch.setattr(worktrees, "_count_worktree_changes", lambda p: (0, 0))
    monkeypatch.setattr(worktrees, "run_git", lambda args: (True, ""))
    assert "removed" in remove_worktree("auth")


# ── keep_worktree ──
def test_keep_worktree(wtd):
    out = keep_worktree("auth")
    assert "kept" in out and "wt/auth" in out
    ev = json.loads((wtd / "events.jsonl").read_text().strip())
    assert ev["type"] == "keep"


def test_keep_invalid_name(wtd):
    assert validate_worktree_name("a b") in keep_worktree("a b")
