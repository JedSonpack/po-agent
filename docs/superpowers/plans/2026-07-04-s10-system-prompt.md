# s10 System Prompt 实现计划

> 用 superpowers:executing-plans 逐任务实现。

**目标：** s10 System Prompt——运行时段落化组装系统提示 + 缓存 + 每轮重算，行为对齐 `learn-claude-code/s10_system_prompt`。
**架构：** `s10_system_prompt` 包，沿用 s09；新增 `system_prompt.py`；`agent_loop` drop `system` 改 `context`，每轮 `build_context`+`get_system_prompt`。保留 s09 全部机制。
**规格：** `docs/superpowers/specs/2026-07-04-s10-system-prompt-design.md`（impl 完整代码见规格 §4/§5）

从 po-agent 根目录运行，`source .venv/bin/activate`。main 分支，每任务一 commit，阶段末 push。

---

## 任务 1：包骨架

- [ ] `s10_system_prompt/__init__.py`（`"""s10_system_prompt — 运行时组装系统提示。"""`）、`tests/__init__.py`（空）
- [ ] `pytest s10_system_prompt -q` → exit 5
- [ ] Commit `chore(s10): 初始化包骨架`

---

## 任务 2：system_prompt.py（TDD，新机制）

**文件：** `tests/test_system_prompt.py`、`system_prompt.py`（impl 见规格 §4）

- [ ] **test_system_prompt.py**：
```python
import json
import pytest
from s10_system_prompt.system_prompt import (
    assemble_system_prompt, get_system_prompt, build_context, reset_cache,
    PROMPT_SECTIONS, _last_context_key,
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
    # context 含 list，json.dumps 不抛 unhashable
    ctx = {"cwd": "/w", "tools": ["bash", "read_file"], "skills_catalog": "c", "memories": ""}
    get_system_prompt(ctx)  # 不抛
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
    ctx = {"cwd": "/w", "tools": ["bash"], "skills_catalog": "c", "memories": ""}
    get_system_prompt(ctx)
    reset_cache()
    import s10_system_prompt.system_prompt as sp
    assert sp._last_context_key is None
    assert sp._last_prompt is None
```
- [ ] `pytest s10_system_prompt/tests/test_system_prompt.py -v` → FAIL
- [ ] 实现 `system_prompt.py`（规格 §4）
- [ ] `pytest s10_system_prompt/tests/test_system_prompt.py -v` → 全通过
- [ ] Commit `feat(s10): 实现 system_prompt（段落组装+缓存）`

---

## 任务 3：s09 模块复制（tools/skills/hooks/todo/subagent/compact/memory）

- [ ] 7 模块 + 7 测试从 s09 原样复制（sed `s09_memory/s10_system_prompt`）
- [ ] `pytest s10_system_prompt/tests/test_tools.py s10_system_prompt/tests/test_skills.py s10_system_prompt/tests/test_hooks.py s10_system_prompt/tests/test_todo.py s10_system_prompt/tests/test_subagent.py s10_system_prompt/tests/test_compact.py s10_system_prompt/tests/test_memory.py -v` → 全通过
- [ ] Commit `feat(s10): 复制 tools/skills/hooks/todo/subagent/compact/memory（同 s09）`

---

## 任务 4：agent.py（s09 + context 重构，TDD）

**文件：** `tests/test_agent.py`、`agent.py`（impl 见规格 §5）

- [ ] **test_agent.py**：s09 的 16 个测试 sed 复制，签名 `system="s"` → `context={"cwd": ".", "tools": [], "skills_catalog": ""}`；FakeClient 捕获 system kwarg 的测试改为断言含 "coding agent"/workspace。memory 的 4 个测试（SpyMemory）原样。示例关键改动：
```python
# 顶部 helper 不变；所有 agent_loop(...) 调用：
#   system="s"  →  context={"cwd": ".", "tools": [], "skills_catalog": ""}

def test_system_prompt_assembled_and_used():
    client = FakeClient([make_response([text_block("done")], "end_turn")])
    captured = {}
    def cap(**kw): captured["system"] = kw.get("system"); return make_response([text_block("done")], "end_turn")
    c = type("C", (), {"messages": property(lambda s: s), "create": cap})()
    agent_loop(client=c, model="m", context={"cwd": "/work", "tools": [], "skills_catalog": "c"},
               tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None)
    assert "coding agent" in captured["system"]
    assert "/work" in captured["system"]

def test_memory_index_in_system_when_present():
    # SpyMemory.build_index_section 返非空 → assembled system 含 memory 段
    ...
    assert "Memories available" in captured["system"]
```
- [ ] `pytest s10_system_prompt/tests/test_agent.py -v` → FAIL
- [ ] 实现 `agent.py`（规格 §5）
- [ ] `pytest s10_system_prompt/tests/test_agent.py -v` → 16 passed
- [ ] Commit `feat(s10): agent_loop 重构（drop system，改 context + 每轮组装缓存）`

---

## 任务 5：config.py（build_context）

- [ ] sed 复制 s09 config.py；`build_system_prompt` → `build_context`（转调 system_prompt.build_context，catalog=skills.list_skills()）；`load()` 返回 `context`（drop `system`）；test_config.py 改：断言 `build_context` 含 cwd/tools/skills_catalog；`load()` 有 context 无 system
- [ ] `pytest s10_system_prompt/tests/test_config.py -v` → 通过
- [ ] Commit `feat(s10): 实现 config（build_context 取代 build_system_prompt）`

---

## 任务 6：cli.py + __main__.py

- [ ] cli.py（s09 + 传 context）：`agent_loop(..., context=cfg["context"], tools=cfg["tools"], ...)`（drop system）。其余接线同 s09。
- [ ] `__main__.py`：`from s10_system_prompt.cli import main` / `main()`
- [ ] `python -c "from s10_system_prompt.cli import main; print('import ok')"` → ok
- [ ] Commit `feat(s10): 实现 REPL 入口（传 context）`

---

## 任务 7：README + 全测 + 实时冒烟 + push + PROGRESS

- [ ] README（`## 本阶段完成（相对 s09）`：段落化组装；system_prompt.py；PROMPT_SECTIONS+assemble+缓存+build_context；agent_loop drop system 改 context 每轮重算；保留 s09 全部）
- [ ] 全测 `pytest s01_agent_loop/tests s02_tool_use/tests ... s10_system_prompt/tests -v` → 全通过
- [ ] 冒烟 `echo '列出当前目录的 .py 文件' | python -m s10_system_prompt` → `[assembled] sections: identity, tools, workspace, skills`，tool 轮 `[cache hit]`，agent 调工具返回
- [ ] Commit README `docs(s10): 添加阶段 README`
- [ ] 更新 PROGRESS.md（s10 行 ⬜→✅ + 详情节）+ 本计划执行状态块
- [ ] Commit + push `docs(s10): 更新进度总览` && `git push origin main`

---

## 自检

**1. 规格覆盖度：** §4 system_prompt.py → 任务 2 ✓；§5 agent 集成 → 任务 4 ✓；§6 config/cli → 任务 5/6 ✓；§8 验收 → 任务 7 ✓。
**2. 占位符：** 无。
**3. 类型一致性：** `build_context(*, cwd, tools, skills_catalog, memories="")` 规格 §4 定义、任务 2 测试、任务 5 config 转调一致；`agent_loop(*, ..., context, ...)` 规格 §5 定义、任务 4 测试、任务 6 cli 调用一致；`get_system_prompt(context)` agent_loop 每轮调用一致。✓
