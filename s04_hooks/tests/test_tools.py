import subprocess
import pytest
from s04_hooks.tools import (
    run_bash, safe_path, run_read, run_write, run_edit, run_glob, run_tool,
)


def test_safe_command_returns_output():
    assert run_bash("echo hello") == "hello"


def test_empty_output():
    assert run_bash("true") == "(no output)"


def test_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep", timeout=120)
    monkeypatch.setattr("s04_hooks.tools.subprocess.run", fake_run)
    assert run_bash("sleep 200") == "Error: Timeout (120s)"


def test_output_truncation(monkeypatch):
    class FakeResult:
        stdout = "x" * 60000
        stderr = ""
    monkeypatch.setattr("s04_hooks.tools.subprocess.run",
                        lambda *a, **k: FakeResult())
    assert len(run_bash("echo big")) == 50000


def test_safe_path_within_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    assert safe_path("foo.txt") == (tmp_path / "foo.txt").resolve()


def test_safe_path_escape_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    with pytest.raises(ValueError):
        safe_path("../escape.txt")


def test_safe_path_absolute_raises(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    with pytest.raises(ValueError):
        safe_path("/etc/passwd")


def test_run_read(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "a.txt").write_text("line1\nline2\nline3\n")
    assert run_read("a.txt") == "line1\nline2\nline3"


def test_run_read_with_limit(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    assert run_read("a.txt", limit=2) == "l1\nl2\n... (3 more lines)"


def test_run_read_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    assert run_read("nope.txt").startswith("Error:")


def test_run_write(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    assert run_write("sub/b.txt", "hello") == "Wrote 5 bytes to sub/b.txt"
    assert (tmp_path / "sub" / "b.txt").read_text() == "hello"


def test_run_edit(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "c.txt").write_text("foo bar baz")
    assert run_edit("c.txt", "bar", "QUX") == "Edited c.txt"
    assert (tmp_path / "c.txt").read_text() == "foo QUX baz"


def test_run_edit_text_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "c.txt").write_text("foo bar")
    assert run_edit("c.txt", "zzz", "y") == "Error: text not found in c.txt"


def test_run_glob(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    assert set(run_glob("*.py").split("\n")) == {"a.py", "b.py"}


def test_run_glob_no_matches(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    assert run_glob("*.nonexistent") == "(no matches)"


def test_run_tool_dispatch_bash(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    assert run_tool("bash", {"command": "echo hi"}) == "hi"


def test_run_tool_dispatch_read_file(monkeypatch, tmp_path):
    monkeypatch.setattr("s04_hooks.tools.WORKDIR", tmp_path)
    (tmp_path / "x.txt").write_text("content")
    assert run_tool("read_file", {"path": "x.txt"}) == "content"


def test_run_tool_unknown():
    assert run_tool("nope", {}) == "Unknown: nope"
