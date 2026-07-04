# s07 Skill Loading — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第七阶段（对应 `learn-claude-code/s07_skill_loading`）
- 状态：自主模式
- 前置：s06 已完成

## 1. 背景与目标

s06 的 agent 能委派，但所有知识都得塞进 SYSTEM（贵）或靠模型先验。s07 引入**两级按需知识注入**：
- **Layer 1（便宜，常驻 SYSTEM）**：启动时扫 `skills/` 目录，把技能名 + 一行描述（~100 token/skill）注入 SYSTEM 目录。
- **Layer 2（贵，按需）**：agent 调 `load_skill(name)` → 全文 SKILL.md 经 tool_result 注入（~2000 token/skill）。

**目标**：行为对齐 s07，沿用包 + DI + TDD。核心新增：`skills.py`（`_parse_frontmatter`/`scan_skills`/`list_skills`/`load_skill` + `SKILL_REGISTRY`）+ `load_skill` 工具（静态处理器，读注册表，无需 client）+ SYSTEM 注入目录。循环不变。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），行为严格对齐 |
| 功能范围 | 严格对齐 s07：扫 `skills/` 建 `SKILL_REGISTRY`（name/description/content）；SYSTEM 注目录；`load_skill` 返全文；YAML frontmatter 解析。不加递归加载/技能嵌套/模型选择 |
| load_skill 的 DI | **静态处理器**（读模块 `SKILL_REGISTRY`，无需 client）→ 直接进 `TOOL_HANDLERS`，不走 `make_run_tool` extra（与 task 不同） |
| skills.py 独立 | `skills.py` 不 import tools.py（避免循环）；`SKILLS_DIR = Path.cwd()/"skills"` 独立；`scan_skills(skills_dir=None)` 显式可测 |
| 注册表时机 | `load()` 先 `scan_skills()` 再 `build_system_prompt`（读 `list_skills()`）；cli 调 load() 即触发扫描 |
| 子 agent | 不给 load_skill（SUB_TOOLS 仍 5，无 task/todo_write/load_skill） |
| 循环 | 不变（同 s06）；load_skill 经 run_tool 自动分发 |
| SYSTEM | `build_system_prompt(cwd)` = "You are a coding agent at {cwd}. Skills available:\n{catalog}\nUse load_skill to get full details when needed."；SUB_SYSTEM 同 s06 |

## 3. 结构

```
po-agent/s07_skill_loading/
├── __init__.py
├── config.py     # env + make_tools(8) + make_sub_tools(5) + build_system_prompt(注目录) + build_sub_system_prompt + load(先 scan_skills)
├── tools.py      # s06 工具(6) + load_skill(从 skills.py 导入) + SUB_HANDLERS(5) + make_run_tool + run_tool(默认 7)
├── skills.py     # 新：SKILLS_DIR/SKILL_REGISTRY + _parse_frontmatter + scan_skills + list_skills + load_skill
├── hooks.py      # s06 原样
├── todo.py       # s06 原样
├── subagent.py   # s06 原样
├── agent.py      # s06 原样（task/load_skill 自动分发）
├── cli.py        # REPL（同 s06，load() 内 scan_skills）
├── __main__.py
├── README.md
└── tests/        # test_tools(+load_skill) / test_skills(新) / test_hooks / test_todo / test_subagent / test_agent / test_config
```

## 4. 核心新增

### 4.1 skills.py

```python
import yaml
from pathlib import Path

SKILLS_DIR = Path.cwd() / "skills"
SKILL_REGISTRY: dict[str, dict] = {}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
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
    if not SKILL_REGISTRY:
        return "(no skills found)"
    return "\n".join(f"- **{s['name']}**: {s['description']}" for s in SKILL_REGISTRY.values())


def load_skill(name: str) -> str:
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]
```

### 4.2 tools.py 增量

- `from s07_skill_loading.skills import load_skill`
- `TOOL_HANDLERS` 加 `"load_skill": load_skill`（7 项）
- `SUB_HANDLERS` 不变（5 项，无 load_skill）
- `run_tool = make_run_tool(TOOL_HANDLERS)`（默认 7）；cli 用 `make_run_tool(TOOL_HANDLERS, {"task": subagent.run})`（8）

### 4.3 config.py

- `make_tools()` → 8（s06 的 7 + `load_skill`）。`load_skill` schema：`name`(string)，required `["name"]`，描述 "Load the full content of a skill by name."。
- `make_sub_tools()` → 5（同 s06）。
- `build_system_prompt(cwd)`：`catalog = skills.list_skills()`；返回 "You are a coding agent at {cwd}. Skills available:\n{catalog}\nUse load_skill to get full details when needed."。
- `load()`：先 `skills.scan_skills()`，再组装（system 读 catalog 时注册表已满）。

### 4.4 agent.py / subagent.py / hooks.py / todo.py

均 s06 原样。load_skill 经 run_tool 自动分发，循环不 special-case。

## 5. 测试策略

- **test_skills.py**（新）：`_parse_frontmatter`（有 meta / 无 frontmatter / 坏 yaml）；`scan_skills`（tmp 目录 2 skill / 缺目录 / 无 name 用目录名）；`list_skills`（空 / 有）；`load_skill`（找到返全文 / 未找到 / 路径穿越尝试返 not found）；autouse fixture 清 `SKILL_REGISTRY`。
- **test_tools.py**：s06 的 32 + `TOOL_HANDLERS` 含 load_skill / `SUB_HANDLERS` 无 load_skill / `run_tool("load_skill", {"name":"nope"})` 返 "Skill not found: nope"（注册表空）。
- **test_config.py**：make_tools 8（含 load_skill）；make_sub_tools 5；build_system_prompt（monkeypatch `skills.list_skills` 返目录 → 断言 prompt 含 "Skills available"/目录/"load_skill"）。
- **test_hooks/test_todo/test_subagent/test_agent**：s06 原样（改包名）。

## 6. 行为对齐验收

- 全量测试通过（s01-s07）。
- 实时冒烟：建 `po-agent/skills/{code-review,mcp-builder}/SKILL.md`（带 frontmatter）；`echo '有哪些 skill？加载 code-review 并总结它建议的 review 步骤' | python -m s07_skill_loading` → 观察 SYSTEM 目录里列出 skills，agent 调 `load_skill("code-review")` 拿全文并总结。

## 7. 范围外（YAGNI）

- 技能递归加载、技能间依赖、按模型选技能、技能缓存 — 后续。
- skills/ 目录的创建工具——参考也不提供，靠手建（冒烟时建样本）。
