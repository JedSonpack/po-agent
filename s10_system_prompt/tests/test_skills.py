import pytest
import s10_system_prompt.skills as skills_mod
from s10_system_prompt.skills import (_parse_frontmatter, scan_skills, list_skills,
                                       load_skill, SKILL_REGISTRY)


@pytest.fixture(autouse=True)
def _clear_registry():
    SKILL_REGISTRY.clear()
    yield
    SKILL_REGISTRY.clear()


def test_parse_frontmatter_with_meta():
    text = "---\nname: code-review\ndescription: Review code\n---\nbody here"
    meta, body = _parse_frontmatter(text)
    assert meta == {"name": "code-review", "description": "Review code"}
    assert body == "body here"


def test_parse_frontmatter_without_frontmatter():
    text = "# just a doc\nno frontmatter"
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_parse_frontmatter_malformed_yaml():
    text = "---\nname: [unclosed\n---\nbody"
    meta, body = _parse_frontmatter(text)
    assert meta == {}  # 坏 yaml → 空 meta
    assert body == "body"


def test_parse_frontmatter_single_delimiter():
    text = "---\nname: x\n"  # 只有一个 ---
    meta, body = _parse_frontmatter(text)
    assert meta == {}
    assert body == text


def test_scan_skills_populates_registry(tmp_path):
    (tmp_path / "code-review").mkdir()
    (tmp_path / "code-review" / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code\n---\nsteps...")
    (tmp_path / "mcp-builder").mkdir()
    (tmp_path / "mcp-builder" / "SKILL.md").write_text(
        "---\nname: mcp-builder\ndescription: Build MCP servers\n---\nguide...")
    scan_skills(tmp_path)
    assert set(SKILL_REGISTRY) == {"code-review", "mcp-builder"}
    assert SKILL_REGISTRY["code-review"]["content"].startswith("---")
    assert SKILL_REGISTRY["code-review"]["description"] == "Review code"


def test_scan_skills_uses_dir_name_when_no_meta_name(tmp_path):
    (tmp_path / "pdf").mkdir()
    (tmp_path / "pdf" / "SKILL.md").write_text("---\ndescription: Read PDFs\n---\nbody")
    scan_skills(tmp_path)
    assert "pdf" in SKILL_REGISTRY
    assert SKILL_REGISTRY["pdf"]["name"] == "pdf"


def test_scan_skills_missing_dir_clears_registry(tmp_path):
    SKILL_REGISTRY["stale"] = {"name": "stale", "description": "x", "content": "x"}
    scan_skills(tmp_path / "does-not-exist")
    assert SKILL_REGISTRY == {}


def test_scan_skills_skips_non_dir_and_missing_manifest(tmp_path):
    (tmp_path / "not-a-dir.txt").write_text("x")
    (tmp_path / "empty-skill").mkdir()  # 无 SKILL.md
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "SKILL.md").write_text("---\nname: real\n---\nbody")
    scan_skills(tmp_path)
    assert set(SKILL_REGISTRY) == {"real"}


def test_list_skills_empty():
    assert list_skills() == "(no skills found)"


def test_list_skills_with_entries(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "SKILL.md").write_text("---\nname: a\ndescription: A skill\n---\nx")
    scan_skills(tmp_path)
    out = list_skills()
    assert "**a**: A skill" in out


def test_load_skill_found(tmp_path):
    (tmp_path / "cr").mkdir()
    (tmp_path / "cr" / "SKILL.md").write_text("---\nname: cr\ndescription: x\n---\nFULL CONTENT")
    scan_skills(tmp_path)
    assert load_skill("cr") == "---\nname: cr\ndescription: x\n---\nFULL CONTENT"


def test_load_skill_not_found():
    assert load_skill("nope") == "Skill not found: nope"


def test_load_skill_no_path_traversal():
    # 注册表查找，不走文件系统 → 路径穿越也只是 not found
    assert load_skill("../../etc/passwd") == "Skill not found: ../../etc/passwd"
