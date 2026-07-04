import os
from s06_subagent.config import (build_system_prompt, build_sub_system_prompt,
                                  make_tools, make_sub_tools, prepare_env)


def test_make_tools_has_seven_with_task():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob", "todo_write", "task"]


def test_make_sub_tools_has_five_no_task_no_todo():
    names = [t["name"] for t in make_sub_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob"]


def test_build_system_prompt_mentions_task():
    prompt = build_system_prompt("/tmp/x")
    assert "/tmp/x" in prompt
    assert "task" in prompt
    assert "subagent" in prompt


def test_build_sub_system_prompt_mentions_summary():
    prompt = build_sub_system_prompt("/tmp/x")
    assert "/tmp/x" in prompt
    assert "summary" in prompt
    assert "delegate" in prompt


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
