import subprocess
from s01_agent_loop.tools import run_bash


def test_dangerous_command_blocked():
    assert run_bash("rm -rf /") == "Error: Dangerous command blocked"
    assert run_bash("sudo ls") == "Error: Dangerous command blocked"


def test_safe_command_returns_output():
    assert run_bash("echo hello") == "hello"


def test_empty_output():
    assert run_bash("true") == "(no output)"


def test_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="sleep", timeout=120)
    monkeypatch.setattr("s01_agent_loop.tools.subprocess.run", fake_run)
    assert run_bash("sleep 200") == "Error: Timeout (120s)"


def test_output_truncation(monkeypatch):
    class FakeResult:
        stdout = "x" * 60000
        stderr = ""
    monkeypatch.setattr("s01_agent_loop.tools.subprocess.run",
                        lambda *a, **k: FakeResult())
    assert len(run_bash("echo big")) == 50000
