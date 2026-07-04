# s07 Skill Loading 实现计划

> 用 superpowers:executing-plans 逐任务实现。

**目标：** s07 Skill Loading——两级按需知识注入（SYSTEM 注技能目录 + `load_skill` 按需返全文），行为对齐 `learn-claude-code/s07_skill_loading`。
**架构：** `s07_skill_loading` 包，沿用 s06；新增 `skills.py`（注册表 + 扫描 + load）+ tools.py 加 `load_skill` 静态处理器 + SYSTEM 注目录。循环不变。
**规格：** `docs/superpowers/specs/2026-07-04-s07-skill-loading-design.md`

从 po-agent 根目录运行，`source .venv/bin/activate`。main 分支，每任务一 commit。pyyaml 已装。

---

## 执行状态（2026-07-04 完成）

全部 6 个任务完成，s07 86/86 测试通过（全量 s01-s07 319 passed），已推送 origin/main。验收：s07 实时跑通——SYSTEM 列技能目录，agent 调 `load_skill("code-review")` 拿全文并总结 review 步骤。

| 任务 | commit | 说明 |
|---|---|---|
| 1+2 骨架+skills+tools | `9a8b5df` | skills.py + tools.py（含骨架）（48 测试：13 skills + 35 tools） |
| 3 hooks/todo/agent/subagent | `6fc10d9` | s06 原样复制（33 测试） |
| 4 config | `f0de86e` | 8 工具 + 目录提示（5 测试） |
| 5 cli + 样本 skills | `21e66d4` | REPL + skills/code-review、skills/mcp-builder |
| 6 README + 全测 + 冒烟 + push | 后续 docs | 319 passed，冒烟通过，推送 |

---

## 任务 1：包骨架

- [ ] 创建 `s07_skill_loading/__init__.py`（`"""s07_skill_loading — 两级按需技能加载。"""`）、`s07_skill_loading/tests/__init__.py`（空）
- [ ] 验证：`pytest s07_skill_loading -q` → no tests ran（exit 5）
- [ ] Commit：`git add s07_skill_loading/ && git commit -m "chore(s07): 初始化包骨架"`

---

## 任务 2：skills.py + tools.py（TDD）

**文件：** `tests/test_skills.py`、`skills.py`、`tests/test_tools.py`、`tools.py`

- [ ] **步骤 1：test_skills.py**
```python
import pytest
import s07_skill_loading.skills as skills_mod
from s07_skill_loading.skills import (_parse_frontmatter, scan_skills, list_skills,
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
```
- [ ] **步骤 2：** `pytest s07_skill_loading/tests/test_skills.py -v` → FAIL（无模块）
- [ ] **步骤 3：实现** `s07_skill_loading/skills.py`（见规格 §4.1）
- [ ] **步骤 4：** `pytest s07_skill_loading/tests/test_skills.py -v` → 13 passed
- [ ] **步骤 5：test_tools.py**（s06 的 32 个 + load_skill 增量；导入加 `load_skill` 从 tools、`SUB_HANDLERS`/`TOOL_HANDLERS` 已有；末尾加）：
```python
# 顶部 import 调整为：
from s07_skill_loading.tools import (
    run_bash, safe_path, run_read, run_write, run_edit, run_glob, run_tool,
    run_todo_write, _normalize_todos, make_run_tool, SUB_HANDLERS, TOOL_HANDLERS,
)
# ... s06 的 32 个测试原样（WORKDIR monkeypatch 改 s07_skill_loading.tools.WORKDIR）...

# ── s07 新增：load_skill 分发 ────────────────────────────────
def test_tool_handlers_has_load_skill():
    assert "load_skill" in TOOL_HANDLERS


def test_sub_handlers_no_load_skill():
    assert "load_skill" not in SUB_HANDLERS


def test_run_tool_dispatch_load_skill_not_found():
    # 注册表空 → not found
    assert run_tool("load_skill", {"name": "nope"}) == "Skill not found: nope"
```
- [ ] **步骤 6：实现** `s07_skill_loading/tools.py`（s06 tools.py + `from s07_skill_loading.skills import load_skill` + `TOOL_HANDLERS` 加 `"load_skill": load_skill`；SUB_HANDLERS 不变；`run_tool = make_run_tool(TOOL_HANDLERS)`）
- [ ] **步骤 7：** `pytest s07_skill_loading/tests/test_tools.py -v` → 35 passed（32 + 3）
- [ ] **步骤 8：Commit** `feat(s07): 实现 skills + tools（s06 + load_skill）`

---

## 任务 3：hooks/todo/agent/subagent（s06 原样复制）

**文件：** `tests/test_hooks.py`+`hooks.py`、`tests/test_todo.py`+`todo.py`、`tests/test_agent.py`+`agent.py`、`tests/test_subagent.py`+`subagent.py`

- [ ] 4 个模块 + 测试从 s06 原样复制，导入改 `s07_skill_loading`，WORKDIR monkeypatch 改 `s07_skill_loading.tools.WORKDIR`
- [ ] `pytest s07_skill_loading/tests/test_hooks.py s07_skill_loading/tests/test_todo.py s07_skill_loading/tests/test_agent.py s07_skill_loading/tests/test_subagent.py -v` → 33 passed（12+6+7+8）
- [ ] Commit：`feat(s07): 复制 hooks/todo/agent/subagent（同 s06）`

---

## 任务 4：config.py（TDD，8 工具 + 目录提示）

**文件：** `tests/test_config.py`、`config.py`

- [ ] **步骤 1：测试**
```python
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
```
- [ ] **步骤 2：** `pytest s07_skill_loading/tests/test_config.py -v` → FAIL
- [ ] **步骤 3：实现** `s07_skill_loading/config.py`（s06 + load_skill 工具 + 目录提示 + load() 先 scan_skills）：
```python
import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from s07_skill_loading import skills


def prepare_env() -> None:
    load_dotenv(override=True)
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def build_system_prompt(cwd: str) -> str:
    catalog = skills.list_skills()
    return (f"You are a coding agent at {cwd}. "
            f"Skills available:\n{catalog}\n"
            "Use load_skill to get full details when needed.")


def build_sub_system_prompt(cwd: str) -> str:
    return (f"You are a coding agent at {cwd}. "
            "Complete the task you were given, then return a concise summary. "
            "Do not delegate further.")


def make_tools() -> list[dict]:
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in a file once.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        {"name": "glob", "description": "Find files matching a glob pattern.",
         "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
        {"name": "todo_write", "description": "Create and manage a task list for your current coding session.",
         "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, "required": ["todos"]}},
        {"name": "task", "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
         "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}},
        # s07: 按需加载技能全文
        {"name": "load_skill", "description": "Load the full content of a skill by name.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    ]


def make_sub_tools() -> list[dict]:
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in a file once.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        {"name": "glob", "description": "Find files matching a glob pattern.",
         "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    ]


def load() -> dict[str, Any]:
    prepare_env()
    skills.scan_skills()  # 先扫描，build_system_prompt 才有目录
    return {
        "client": Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL")),
        "model": os.environ["MODEL_ID"],
        "system": build_system_prompt(os.getcwd()),
        "tools": make_tools(),
        "sub_system": build_sub_system_prompt(os.getcwd()),
        "sub_tools": make_sub_tools(),
    }
```
- [ ] **步骤 4：** `pytest s07_skill_loading/tests/test_config.py -v` → 5 passed
- [ ] **步骤 5：Commit** `feat(s07): 实现 config（8 工具 + 目录提示）`

---

## 任务 5：cli.py + __main__.py + 样本 skills/

**文件：** `cli.py`、`__main__.py`、`skills/code-review/SKILL.md`、`skills/mcp-builder/SKILL.md`

- [ ] **步骤 1：cli.py**（同 s06，load() 内 scan_skills）
```python
"""交互式 REPL（s07）：s06 + load_skill 按需加载技能。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s07_skill_loading.agent import agent_loop
from s07_skill_loading.config import load
from s07_skill_loading.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s07_skill_loading.hooks import trigger_hooks, register_defaults
from s07_skill_loading.todo import TodoNag
from s07_skill_loading.subagent import Subagent


def main() -> None:
    register_defaults()
    cfg = load()  # load() 内 scan_skills
    subagent = Subagent(
        client=cfg["client"], model=cfg["model"], sub_system=cfg["sub_system"],
        sub_tools=cfg["sub_tools"], sub_run_tool=make_run_tool(SUB_HANDLERS),
        trigger=trigger_hooks,
    )
    run_tool = make_run_tool(TOOL_HANDLERS, {"task": subagent.run})
    nag = TodoNag()
    print("s07: Skill Loading — catalog in SYSTEM, content on demand")
    print("Type a question, press Enter. Type q to quit.\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms07 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            trigger=trigger_hooks, nag=nag,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
```
`__main__.py`：
```python
from s07_skill_loading.cli import main

main()
```
- [ ] **步骤 2：样本 skills/**（`skills/code-review/SKILL.md`、`skills/mcp-builder/SKILL.md`，带 frontmatter + 几行 body）
- [ ] **步骤 3：** `python -c "from s07_skill_loading.cli import main; print('import ok')"` → `import ok`
- [ ] **步骤 4：Commit** `feat(s07): 实现 REPL 入口 + 样本 skills`

---

## 任务 6：README + 全测 + 实时冒烟 + push + PROGRESS

- [ ] **步骤 1：README**（`## 本阶段完成（相对 s06）`：两级知识注入；skills.py 扫描注册表；SYSTEM 注目录；load_skill 静态处理器；循环不变）
- [ ] **步骤 2：全测** `pytest s01_agent_loop/tests s02_tool_use/tests s03_permission/tests s04_hooks/tests s05_todo_write/tests s06_subagent/tests s07_skill_loading/tests -v` → 全通过
- [ ] **步骤 3：实时冒烟** `echo '有哪些 skill？加载 code-review 并总结它建议的代码 review 步骤' | python -m s07_skill_loading` → SYSTEM 目录列 skills，agent 调 `load_skill("code-review")` 拿全文并总结
- [ ] **步骤 4：Commit README** `docs(s07): 添加阶段 README`
- [ ] **步骤 5：更新 PROGRESS.md**（s07 行 ⬜→✅ + 详情节）
- [ ] **步骤 6：更新计划执行状态块**
- [ ] **步骤 7：Commit + push** `docs(s07): 更新进度总览与计划执行状态` && `git push origin main`

---

## 自检

**1. 规格覆盖度：** §4.1 skills.py → 任务 2 ✓；§4.2 tools 增量 → 任务 2 ✓；§4.3 config → 任务 4 ✓；§4.4 s06 原样 → 任务 3 ✓；§6 验收 → 任务 6 ✓。
**2. 占位符：** 无；每步有完整代码。
**3. 类型一致性：** `scan_skills(skills_dir=None)`/`list_skills()`/`load_skill(name)` 签名一致；`build_system_prompt(cwd)` 调 `skills.list_skills()`；`TOOL_HANDLERS` 含 load_skill（7），cli extra 加 task（8）；SUB_HANDLERS 5（无 load_skill/task/todo_write）。✓
