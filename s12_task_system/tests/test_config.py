import os
from s12_task_system import skills
from s12_task_system.config import (build_context, build_sub_system_prompt,
                                      make_tools, make_sub_tools, prepare_env)


def test_make_tools_has_nine_with_compact():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob",
                     "todo_write", "task", "load_skill", "compact"]


def test_make_sub_tools_has_five():
    assert [t["name"] for t in make_sub_tools()] == ["bash", "read_file", "write_file", "edit_file", "glob"]


def test_build_context_includes_catalog(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", lambda: "- **code-review**: Review code")
    tools = make_tools()
    ctx = build_context("/tmp/x", tools)
    assert ctx["cwd"] == "/tmp/x"
    assert ctx["tools"] == [t["name"] for t in tools]
    assert "code-review" in ctx["skills_catalog"]
    assert ctx["memories"] == ""


def test_build_sub_system_prompt_unchanged():
    assert "summary" in build_sub_system_prompt("/tmp/x")


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
