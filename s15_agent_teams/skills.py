"""Skill Loading — 两级按需知识注入：SYSTEM 注目录，load_skill 返全文。"""
from pathlib import Path

import yaml

SKILLS_DIR = Path.cwd() / "skills"
SKILL_REGISTRY: dict[str, dict] = {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (meta, body)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


def scan_skills(skills_dir=None) -> None:
    """扫描 skills_dir（默认 SKILLS_DIR），填充 SKILL_REGISTRY（name/description/content）。"""
    SKILL_REGISTRY.clear()
    d = Path(skills_dir) if skills_dir else SKILLS_DIR
    if not d.exists():
        return
    for sub in sorted(d.iterdir()):
        if not sub.is_dir():
            continue
        manifest = sub / "SKILL.md"
        if manifest.exists():
            raw = manifest.read_text()
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", sub.name)
            desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
            SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}


def list_skills() -> str:
    """列出所有技能（name + 一行描述）——便宜层，常驻 SYSTEM。"""
    if not SKILL_REGISTRY:
        return "(no skills found)"
    return "\n".join(f"- **{s['name']}**: {s['description']}" for s in SKILL_REGISTRY.values())


def load_skill(name: str) -> str:
    """加载技能全文——贵层，按需。注册表查找，不走文件系统（防路径穿越）。"""
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]
