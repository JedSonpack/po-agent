from types import SimpleNamespace
import pytest
from s18_worktree_isolation import hooks, tools


def _block(name, **inp):
    return SimpleNamespace(type="tool_use", id="b1", name=name, input=inp)


@pytest.fixture(autouse=True)
def _clear_hooks():
    for ev in hooks.HOOKS:
        hooks.HOOKS[ev] = []
    yield
    for ev in hooks.HOOKS:
        hooks.HOOKS[ev] = []


def test_trigger_returns_first_non_none():
    hooks.register_hook("PreToolUse", lambda b: None)
    hooks.register_hook("PreToolUse", lambda b: "BLOCK")
    hooks.register_hook("PreToolUse", lambda b: "SHOULD_NOT_REACH")
    assert hooks.trigger_hooks("PreToolUse", _block("bash", command="ls")) == "BLOCK"


def test_trigger_returns_none_when_all_none():
    hooks.register_hook("PreToolUse", lambda b: None)
    assert hooks.trigger_hooks("PreToolUse", _block("bash", command="ls")) is None


def test_permission_deny_list():
    assert hooks.permission_hook(_block("bash", command="rm -rf /")) == "Permission denied by deny list"


def test_permission_destructive_allowed(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert hooks.permission_hook(_block("bash", command="rm foo")) is None


def test_permission_destructive_denied(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert hooks.permission_hook(_block("bash", command="rm foo")) == "Permission denied by user"


def test_permission_write_outside_denied(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert hooks.permission_hook(_block("write_file", path="/etc/x", content="y")) == "Permission denied by user"


def test_permission_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert hooks.permission_hook(_block("bash", command="ls")) is None
    assert hooks.permission_hook(_block("read_file", path="a.txt")) is None


def test_log_hook_returns_none():
    assert hooks.log_hook(_block("bash", command="ls")) is None


def test_large_output_hook_returns_none():
    assert hooks.large_output_hook(_block("bash", command="ls"), "x" * 200000) is None
    assert hooks.large_output_hook(_block("bash", command="ls"), "small") is None


def test_summary_hook_returns_none():
    msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]}]
    assert hooks.summary_hook(msgs) is None


def test_context_inject_hook_returns_none():
    assert hooks.context_inject_hook("hello") is None


def test_register_defaults_registers_five():
    hooks.register_defaults()
    assert len(hooks.HOOKS["UserPromptSubmit"]) == 1
    assert len(hooks.HOOKS["PreToolUse"]) == 2
    assert len(hooks.HOOKS["PostToolUse"]) == 1
    assert len(hooks.HOOKS["Stop"]) == 1
