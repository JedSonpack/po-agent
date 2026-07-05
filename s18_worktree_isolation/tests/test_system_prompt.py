import pytest
from s18_worktree_isolation.system_prompt import (
    assemble_system_prompt, get_system_prompt, build_context, reset_cache,
    PROMPT_SECTIONS,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_cache()
    yield
    reset_cache()


def test_assemble_no_memory_four_sections():
    ctx = {"cwd": "/w", "tools": ["bash", "read_file"], "skills_catalog": "(no skills found)", "memories": ""}
    out = assemble_system_prompt(ctx)
    parts = out.split("\n\n")
    assert len(parts) == 4
    assert "coding agent" in parts[0]
    assert "bash, read_file" in parts[1]
    assert "/w" in parts[2]
    assert "(no skills found)" in parts[3]
    assert "Memories available" not in out


def test_assemble_with_memory_five_sections():
    ctx = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "cat",
           "memories": "Memories available:\n- [X](x.md) — dx"}
    out = assemble_system_prompt(ctx)
    parts = out.split("\n\n")
    assert len(parts) == 5
    assert "Memories available" in parts[4]


def test_assemble_formats_tools_workspace_skills():
    ctx = {"cwd": "/path", "tools": ["a", "b", "c"], "skills_catalog": "SK", "memories": ""}
    out = assemble_system_prompt(ctx)
    assert "a, b, c" in out
    assert "/path" in out
    assert "SK" in out


def test_get_system_prompt_cache_hit():
    ctx = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "c", "memories": ""}
    p1 = get_system_prompt(ctx)
    p2 = get_system_prompt(ctx)
    assert p1 == p2


def test_get_system_prompt_reassembles_on_change():
    ctx1 = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "c", "memories": ""}
    p1 = get_system_prompt(ctx1)
    ctx2 = {**ctx1, "memories": "Memories available:\n- [X](x.md)"}
    p2 = get_system_prompt(ctx2)
    assert p1 != p2
    assert "Memories available" in p2


def test_cache_key_handles_nested_and_unhashable():
    ctx = {"cwd": "/w", "tools": ["bash", "read_file"], "skills_catalog": "c", "memories": ""}
    get_system_prompt(ctx)  # 不抛 unhashable
    get_system_prompt(ctx)  # 命中


def test_cache_key_sort_keys_order_independent():
    a = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "c", "memories": ""}
    b = {"skills_catalog": "c", "memories": "", "cwd": "/w", "tools": ["bash"]}
    p1 = get_system_prompt(a)
    p2 = get_system_prompt(b)
    assert p1 == p2


def test_build_context_from_tool_dicts():
    tools = [{"name": "bash", "input_schema": {}}, {"name": "read_file", "input_schema": {}}]
    ctx = build_context(cwd="/w", tools=tools, skills_catalog="c")
    assert ctx["tools"] == ["bash", "read_file"]
    assert ctx["cwd"] == "/w"
    assert ctx["skills_catalog"] == "c"
    assert ctx["memories"] == ""


def test_build_context_from_name_list():
    ctx = build_context(cwd="/w", tools=["bash"], skills_catalog="c", memories="m")
    assert ctx["tools"] == ["bash"]
    assert ctx["memories"] == "m"


def test_reset_cache_clears_slot():
    import s18_worktree_isolation.system_prompt as sp
    ctx = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "c", "memories": ""}
    get_system_prompt(ctx)
    reset_cache()
    assert sp._last_context_key is None
    assert sp._last_prompt is None
