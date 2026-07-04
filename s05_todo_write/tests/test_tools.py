import subprocess
import pytest
import s05_todo_write.tools as tools_mod
from s05_todo_write.tools import (
    run_bash, safe_path, run_read, run_write, run_edit, run_glob, run_tool,
    run_todo_write, _normalize_todos,
)


@pytest.fixture(autouse=True)
def _reset_todos():
    tools_mod.CURRENT_TODOS = []
    yield
    tools_mod.CURRENT_TODOS = []


# ── s04 原样（18 个）─────────────────────────────────────────
def test_safe_command_returns_output():
    assert run_bash("echo hello") == "hello"


def test_empty_output():
    assert run_bash("true") == "(no output)"


def test_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep", timeout=120)
    monkeypatch.setattr("s05_todo_write.tools.subprocess.run", fake_run)
    assert run_bash("sleep 200") == "Error: Timeout (120s)"


def test_output_truncation(monkeypatch):
    class FakeResult:
        stdout = "x" * 60000
        stderr = ""
    monkeypatch.setattr("s05_todo_write.tools.subprocess.run",
                        lambda *a, **k: FakeResult())
    assert len(run_bash("echo big")) == 50000


def test_safe_path_within_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    assert safe_path("foo.txt") == (tmp_path / "foo.txt").resolve()


def test_safe_path_escape_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    with pytest.raises(ValueError):
        safe_path("../escape.txt")


def test_safe_path_absolute_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    with pytest.raises(ValueError):
        safe_path("/etc/passwd")


def test_run_read(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n")
    assert run_read("a.txt") == "line1\nline2\nline3"


def test_run_read_with_limit(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    assert run_read("a.txt", limit=2) == "l1\nl2\n... (3 more lines)"


def test_run_read_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    assert run_read("nope.txt").startswith("Error:")


def test_run_write(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    assert run_write("sub/b.txt", "hello") == "Wrote 5 bytes to sub/b.txt"
    assert (tmp_path / "sub" / "b.txt").read_text() == "hello"


def test_run_edit(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "c.txt").write_text("foo bar baz")
    assert run_edit("c.txt", "bar", "QUX") == "Edited c.txt"
    assert (tmp_path / "c.txt").read_text() == "foo QUX baz"


def test_run_edit_text_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "c.txt").write_text("foo bar")
    assert run_edit("c.txt", "zzz", "y") == "Error: text not found in c.txt"


def test_run_glob(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    assert set(run_glob("*.py").split("\n")) == {"a.py", "b.py"}


def test_run_glob_no_matches(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    assert run_glob("*.nonexistent") == "(no matches)"


def test_run_tool_dispatch_bash(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    assert run_tool("bash", {"command": "echo hi"}) == "hi"


def test_run_tool_dispatch_read_file(monkeypatch, tmp_path):
    monkeypatch.setattr("s05_todo_write.tools.WORKDIR", tmp_path)
    (tmp_path / "x.txt").write_text("content")
    assert run_tool("read_file", {"path": "x.txt"}) == "content"


def test_run_tool_unknown():
    assert run_tool("nope", {}) == "Unknown: nope"


# ── s05 新增：todo_write ─────────────────────────────────────
def test_run_todo_write_basic():
    assert run_todo_write([{"content": "a", "status": "pending"},
                           {"content": "b", "status": "completed"}]) == "Updated 2 tasks"
    assert tools_mod.CURRENT_TODOS == [{"content": "a", "status": "pending"},
                                        {"content": "b", "status": "completed"}]


def test_run_todo_write_json_string():
    assert run_todo_write('[{"content": "x", "status": "in_progress"}]') == "Updated 1 tasks"


def test_run_todo_write_ast_string():
    assert run_todo_write("[{'content': 'y', 'status': 'pending'}]") == "Updated 1 tasks"


def test_run_todo_write_invalid_status():
    assert run_todo_write([{"content": "x", "status": "done"}]) == "Error: todos[0] has invalid status 'done'"


def test_run_todo_write_missing_field():
    assert run_todo_write([{"content": "x"}]) == "Error: todos[0] missing 'content' or 'status'"
    assert run_todo_write([{"status": "pending"}]) == "Error: todos[0] missing 'content' or 'status'"


def test_run_todo_write_not_a_list():
    assert run_todo_write({"content": "x", "status": "pending"}) == "Error: todos must be a list"


def test_run_todo_write_bad_string():
    assert run_todo_write("not json or ast") == "Error: todos must be a list or JSON array string"


def test_run_todo_write_item_not_object():
    assert run_todo_write(["just a string"]) == "Error: todos[0] must be an object"


def test_run_tool_dispatch_todo_write():
    assert run_tool("todo_write", {"todos": [{"content": "z", "status": "pending"}]}) == "Updated 1 tasks"
    assert tools_mod.CURRENT_TODOS == [{"content": "z", "status": "pending"}]
