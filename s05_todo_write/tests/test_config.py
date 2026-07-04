import os
from s05_todo_write.config import build_system_prompt, make_tools, prepare_env


def test_make_tools_has_six_tools():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob", "todo_write"]


def test_build_system_prompt_uses_todo_write():
    prompt = build_system_prompt("/tmp/x")
    assert "/tmp/x" in prompt
    assert "todo_write" in prompt
    assert "plan" in prompt


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
