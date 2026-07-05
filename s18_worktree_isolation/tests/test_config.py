import os
from s18_worktree_isolation import skills
from s18_worktree_isolation.config import (build_context, build_sub_system_prompt,
                                      make_tools, make_sub_tools, make_team_tools, prepare_env)


def test_make_tools_has_twenty_three_with_protocols():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob",
                     "todo_write", "task", "load_skill", "compact",
                     "create_task", "list_tasks", "get_task", "claim_task", "complete_task",
                     "schedule_cron", "list_crons", "cancel_cron",
                     "spawn_teammate", "send_message", "check_inbox",
                     "request_shutdown", "request_plan", "review_plan"]


def test_make_sub_tools_has_five():
    assert [t["name"] for t in make_sub_tools()] == ["bash", "read_file", "write_file", "edit_file", "glob"]


def test_make_team_tools_has_eight_with_task_tools():
    names = [t["name"] for t in make_team_tools()]
    assert names == ["bash", "read_file", "write_file", "send_message", "submit_plan",
                     "list_tasks", "claim_task", "complete_task"]


def test_team_bash_has_no_run_in_background():
    bash = next(t for t in make_team_tools() if t["name"] == "bash")
    assert "run_in_background" not in bash["input_schema"]["properties"]
    assert bash["input_schema"]["required"] == ["command"]


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


def test_bash_schema_has_run_in_background():
    bash = next(t for t in make_tools() if t["name"] == "bash")
    assert "run_in_background" in bash["input_schema"]["properties"]
    assert bash["input_schema"]["required"] == ["command"]
