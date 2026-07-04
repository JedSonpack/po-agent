import os
from s01_agent_loop.config import build_system_prompt, make_tools, prepare_env


def test_make_tools_is_bash_only():
    tools = make_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "bash"
    assert tools[0]["input_schema"]["required"] == ["command"]


def test_build_system_prompt_includes_cwd():
    prompt = build_system_prompt("/tmp/x")
    assert "/tmp/x" in prompt
    assert "bash" in prompt


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
