import pytest
from s03_permission import tools, permissions


def test_check_deny_list_hits():
    assert permissions.check_deny_list("rm -rf /tmp") == "Blocked: 'rm -rf /' is on the deny list"
    assert permissions.check_deny_list("sudo ls") == "Blocked: 'sudo' is on the deny list"


def test_check_deny_list_safe():
    assert permissions.check_deny_list("ls -la") is None


def test_check_rules_write_outside(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_rules("write_file", {"path": "/etc/x", "content": "y"}) == "Writing outside workspace"


def test_check_rules_bash_destructive(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_rules("bash", {"command": "rm foo"}) == "Potentially destructive command"
    assert permissions.check_rules("bash", {"command": "ls"}) is None


def test_ask_user_yes(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    assert permissions.ask_user("bash", {"command": "rm x"}, "r") == "allow"


def test_ask_user_no(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    assert permissions.ask_user("bash", {"command": "rm x"}, "r") == "deny"


def test_check_permission_deny_list(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_permission("bash", {"command": "rm -rf /"}) is False


def test_check_permission_rule_allow(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    monkeypatch.setattr(permissions, "ask_user", lambda *a: "allow")
    assert permissions.check_permission("bash", {"command": "rm foo"}) is True


def test_check_permission_rule_deny(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    monkeypatch.setattr(permissions, "ask_user", lambda *a: "deny")
    assert permissions.check_permission("bash", {"command": "rm foo"}) is False


def test_check_permission_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    assert permissions.check_permission("bash", {"command": "ls"}) is True
    assert permissions.check_permission("read_file", {"path": "a.txt"}) is True
