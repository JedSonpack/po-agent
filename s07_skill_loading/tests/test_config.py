import os
from s07_skill_loading import skills
from s07_skill_loading.config import (build_system_prompt, build_sub_system_prompt,
                                       make_tools, make_sub_tools, prepare_env)


def test_make_tools_has_eight_with_load_skill():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob",
                     "todo_write", "task", "load_skill"]


def test_make_sub_tools_has_five():
    names = [t["name"] for t in make_sub_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob"]


def test_build_system_prompt_includes_catalog(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", lambda: "- **code-review**: Review code")
    prompt = build_system_prompt("/tmp/x")
    assert "/tmp/x" in prompt
    assert "Skills available" in prompt
    assert "**code-review**: Review code" in prompt
    assert "load_skill" in prompt


def test_build_sub_system_prompt_unchanged():
    prompt = build_sub_system_prompt("/tmp/x")
    assert "summary" in prompt
    assert "delegate" in prompt


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
