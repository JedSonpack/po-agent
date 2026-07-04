# s08 Context Compact 实现计划

> 用 superpowers:executing-plans 逐任务实现。

**目标：** s08 Context Compact——四层压缩管线（snip/micro/budget/summary）+ compact 工具 + reactive 紧急，行为对齐 `learn-claude-code/s08_context_compact`。
**架构：** `s08_context_compact` 包，沿用 s07；新增 `compact.py`（纯函数 + `Compactor` 类）；`agent_loop` 注入 `compact`，加管线 + compact 工具 special-case + reactive try/except。保留 s07 的 hooks/nag。
**规格：** `docs/superpowers/specs/2026-07-04-s08-context-compact-design.md`

从 po-agent 根目录运行，`source .venv/bin/activate`。main 分支，每任务一 commit。

---

## 执行状态

（完成后填写）

---

## 任务 1：包骨架

- [ ] 创建 `s08_context_compact/__init__.py`（`"""s08_context_compact — 四层上下文压缩。"""`）、`tests/__init__.py`（空）
- [ ] 验证 `pytest s08_context_compact -q` → exit 5
- [ ] Commit `chore(s08): 初始化包骨架`

---

## 任务 2：compact.py（TDD，新机制）

**文件：** `tests/test_compact.py`、`compact.py`

- [ ] **步骤 1：test_compact.py**（纯函数 + Compactor；FakeClient + tmp dirs）
```python
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from s08_context_compact.compact import (
    estimate_size, _block_type, _message_has_tool_use, _is_tool_result_message,
    collect_tool_results, snip_compact, micro_compact, Compactor,
)


def text_block(t): return SimpleNamespace(type="text", text=t)
def tu_block(bid, name="bash", inp=None): return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp or {})
def tr_block(tid, content="x"): return {"type": "tool_result", "tool_use_id": tid, "content": content}


def _asst(*blocks): return {"role": "assistant", "content": list(blocks)}
def _user_tool_results(*blocks): return {"role": "user", "content": list(blocks)}
def _user_text(t): return {"role": "user", "content": t}


class FakeClient:
    def __init__(self, responses): self._r = list(responses)
    @property
    def messages(self): return self
    def create(self, **kw): return self._r.pop(0)


# ── 纯函数 ───────────────────────────────────────────────────
def test_block_type_dict_and_attr():
    assert _block_type({"type": "tool_result"}) == "tool_result"
    assert _block_type(text_block("x")) == "text"


def test_message_has_tool_use():
    assert _message_has_tool_use(_asst(tu_block("t1"))) is True
    assert _message_has_tool_use(_asst(text_block("x"))) is False
    assert _message_has_tool_use(_user_text("x")) is False


def test_is_tool_result_message():
    assert _is_tool_result_message(_user_tool_results(tr_block("t1"))) is True
    assert _is_tool_result_message(_user_text("x")) is False
    assert _is_tool_result_message(_asst(tu_block("t1"))) is False


def test_estimate_size():
    assert estimate_size([{"role": "user", "content": "abc"}]) == len(str([{"role": "user", "content": "abc"}]))


def test_collect_tool_results():
    msgs = [_user_tool_results(tr_block("t1"), tr_block("t2")), _user_text("y"), _user_tool_results(tr_block("t3"))]
    res = collect_tool_results(msgs)
    assert len(res) == 3
    assert res[0] == (0, 0, msgs[0]["content"][0])


def test_snip_compact_under_threshold():
    msgs = [_user_text(str(i)) for i in range(10)]
    assert snip_compact(msgs) is msgs  # <=50 不动


def test_snip_compact_trims_middle():
    msgs = [_user_text(str(i)) for i in range(60)]
    out = snip_compact(msgs, max_messages=10)
    assert len(out) == 10 + 1  # head 3 + [snipped] + tail 7
    assert out[3]["content"] == "[snipped 50 messages]"
    assert out[:3] == msgs[:3]
    assert out[-7:] == msgs[-7:]


def test_snip_compact_does_not_split_tool_pair_at_head():
    # head_end=3，但 messages[2] 是 tool_use → 推进 head_end 越过 tool_result
    msgs = [_user_text("0"), _user_text("1"), _asst(tu_block("t0")),
            _user_tool_results(tr_block("t0")), _user_text("4")]
    msgs += [_user_text(str(i)) for i in range(100, 160)]  # 凑到 >50
    out = snip_compact(msgs, max_messages=10)
    # 头含 0,1,asst(t0),tool_result(t0)（不拆对）
    assert out[0]["content"] == "0"
    assert _message_has_tool_use(out[2])
    assert _is_tool_result_message(out[3])


def test_snip_compact_does_not_split_tool_pair_at_tail():
    msgs = [_user_text(str(i)) for i in range(60)]
    # 把尾部改成 tool_use/result 对
    msgs[-3] = _asst(tu_block("tx"))
    msgs[-2] = _user_tool_results(tr_block("tx"))
    out = snip_compact(msgs, max_messages=10)
    # 尾部 tool_result 前必须有对应 tool_use
    tail = out[out.index([m for m in out if _is_tool_result_message(m)][0]):]
    assert any(_message_has_tool_use(m) for m in out[:out.index(tail[0])])


def test_micro_compact_keeps_recent():
    msgs = [_user_tool_results(tr_block("t1", "x" * 200)),
            _user_tool_results(tr_block("t2", "x" * 200)),
            _user_tool_results(tr_block("t3", "x" * 200))]
    out = micro_compact(msgs, keep_recent=1)
    assert out[0]["content"][0]["content"] == "[Earlier tool result compacted. Re-run if needed.]"
    assert out[-1]["content"][0]["content"] == "x" * 200  # 最近保留


def test_micro_compact_skips_short_content():
    msgs = [_user_tool_results(tr_block("t1", "short")),  # <=120 不动
            _user_tool_results(tr_block("t2", "y" * 200))]
    out = micro_compact(msgs, keep_recent=1)
    assert out[0]["content"][0]["content"] == "short"


def test_micro_compact_under_keep_recent():
    msgs = [_user_tool_results(tr_block("t1", "x" * 200))]
    out = micro_compact(msgs, keep_recent=3)
    assert out[0]["content"][0]["content"] == "x" * 200


# ── Compactor ────────────────────────────────────────────────
@pytest.fixture
def compactor(tmp_path):
    return Compactor(client=FakeClient([SimpleNamespace(content=[text_block("SUMMARY")], stop_reason="end_turn")]),
                     model="m", transcript_dir=tmp_path / "tr", tool_results_dir=tmp_path / "out")


def test_persist_large_output_under_threshold(compactor):
    assert compactor.persist_large_output("t1", "small") == "small"


def test_persist_large_output_persists(compactor, tmp_path):
    big = "x" * (compactor.persist_threshold + 10)
    out = compactor.persist_large_output("t1", big)
    assert out.startswith("<persisted-output>")
    assert "Preview:" in out
    assert (tmp_path / "out" / "t1.txt").exists()
    assert (tmp_path / "out" / "t1.txt").read_text() == big


def test_tool_result_budget_under_max(compactor):
    msgs = [_user_tool_results(tr_block("t1", "x" * 100))]
    compactor.tool_result_budget(msgs, max_bytes=200_000)
    assert msgs[0]["content"][0]["content"] == "x" * 100  # 不动


def test_tool_result_budget_persists_largest(compactor, tmp_path):
    big = "x" * (compactor.persist_threshold + 10)
    msgs = [_user_tool_results(tr_block("t1", big), tr_block("t2", "small"))]
    compactor.tool_result_budget(msgs, max_bytes=100)
    assert msgs[0]["content"][0]["content"].startswith("<persisted-output>")  # 最大被 persist
    assert msgs[0]["content"][1]["content"] == "small"  # 小的不动


def test_tool_result_budget_skips_under_persist_threshold(compactor):
    # 总超 max_bytes 但单个都 <= persist_threshold → 不 persist（无能为力，保持原样）
    msgs = [_user_tool_results(tr_block("t1", "x" * 100), tr_block("t2", "y" * 100))]
    compactor.tool_result_budget(msgs, max_bytes=50)
    # 单个 100 <= persist_threshold(30000) → 跳过，不 persist
    assert msgs[0]["content"][0]["content"] == "x" * 100
    assert msgs[0]["content"][1]["content"] == "y" * 100


def test_compact_history_replaces_messages(compactor, tmp_path):
    msgs = [_user_text("hello"), _asst(text_block("hi"))]
    compactor.compact_history(msgs)
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "[Compacted]" in msgs[0]["content"]
    assert "SUMMARY" in msgs[0]["content"]
    assert (tmp_path / "tr").exists()  # transcript 落盘


def test_reactive_compact_keeps_tail(compactor):
    msgs = [_user_text(f"m{i}") for i in range(10)]
    compactor.reactive_compact(msgs)
    assert msgs[0]["content"].startswith("[Reactive compact]")
    # 保留尾 5
    assert msgs[-5:] == [_user_text(f"m{i}") for i in range(5, 10)]


def test_summarize_history_returns_text(compactor):
    assert compactor.summarize_history([_user_text("x")]) == "SUMMARY"


def test_summarize_history_empty_fallback(tmp_path):
    c = Compactor(client=FakeClient([SimpleNamespace(content=[], stop_reason="end_turn")]),
                  model="m", transcript_dir=tmp_path / "tr", tool_results_dir=tmp_path / "out")
    assert c.summarize_history([_user_text("x")]) == "(empty summary)"


def test_write_transcript(compactor, tmp_path):
    msgs = [_user_text("a"), _asst(text_block("b"))]
    path = compactor.write_transcript(msgs)
    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["role"] == "user"


def test_should_auto_compact(compactor):
    compactor.context_limit = 10
    assert compactor.should_auto_compact([_user_text("x" * 100)]) is True
    assert compactor.should_auto_compact([_user_text("x")]) is False


def test_is_prompt_too_long():
    assert Compactor.is_prompt_too_long(Exception("Request failed: prompt_too_long")) is True
    assert Compactor.is_prompt_too_long(Exception("too many tokens")) is True
    assert Compactor.is_prompt_too_long(Exception("other error")) is False


def test_run_pipeline_runs_all_three(compactor, monkeypatch):
    calls = []
    monkeypatch.setattr(compactor, "tool_result_budget", lambda m, **k: calls.append("budget"))
    monkeypatch.setattr("s08_context_compact.compact.snip_compact", lambda m, **k: calls.append("snip") or m)
    monkeypatch.setattr("s08_context_compact.compact.micro_compact", lambda m, **k: calls.append("micro"))
    compactor.run_pipeline([_user_text("x")])
    assert calls == ["budget", "snip", "micro"]
```
- [ ] **步骤 2：** `pytest s08_context_compact/tests/test_compact.py -v` → FAIL
- [ ] **步骤 3：实现** `compact.py`（见规格 §4）
- [ ] **步骤 4：** `pytest s08_context_compact/tests/test_compact.py -v` → 全通过
- [ ] **步骤 5：Commit** `feat(s08): 实现 Compactor（四层压缩管线）`

---

## 任务 3：s07 模块复制（tools/skills/hooks/todo/subagent）

**文件：** `tools.py`、`skills.py`、`hooks.py`、`todo.py`、`subagent.py` + 对应 tests

- [ ] 5 个模块 + 5 个测试从 s07 原样复制，导入改 `s08_context_compact`，WORKDIR monkeypatch 改 `s08_context_compact.tools.WORKDIR`
- [ ] `pytest s08_context_compact/tests/test_tools.py s08_context_compact/tests/test_skills.py s08_context_compact/tests/test_hooks.py s08_context_compact/tests/test_todo.py s08_context_compact/tests/test_subagent.py -v` → 全通过（35+13+12+6+8=74）
- [ ] Commit `feat(s08): 复制 tools/skills/hooks/todo/subagent（同 s07）`

---

## 任务 4：agent.py（s07 + 压缩集成，TDD）

**文件：** `tests/test_agent.py`、`agent.py`

- [ ] **步骤 1：test_agent.py**（s07 的 7 个 `compact=None` + 压缩测试；用 SpyCompactor）
```python
from types import SimpleNamespace
from s08_context_compact.agent import agent_loop
from s08_context_compact.todo import TodoNag


def make_response(blocks, stop_reason): return SimpleNamespace(content=blocks, stop_reason=stop_reason)
def tool_use_block(bid, name, inp): return SimpleNamespace(type="tool_use", id=bid, name=name, input=inp)
def text_block(t): return SimpleNamespace(type="text", text=t)


class FakeClient:
    def __init__(self, responses): self._r = list(responses)
    @property
    def messages(self): return self
    def create(self, **kw): return self._r.pop(0)


class SpyCompactor:
    context_limit = 50_000
    max_reactive_retries = 1
    def __init__(self): self.calls = []; self.size = 0
    def run_pipeline(self, m): self.calls.append("pipeline")
    def should_auto_compact(self, m): return self.size > self.context_limit
    def compact_history(self, m): self.calls.append("compact"); m[:] = [{"role": "user", "content": "[Compacted]\n\nSUM"}]
    def is_prompt_too_long(self, e): return False
    def reactive_compact(self, m): self.calls.append("reactive")


# ── s07 原样 7 个（compact=None）─────────────────────────────
# test_allowed_tool_runs / test_blocked_tool_skips_run / test_stop_hook_force_continues /
# test_post_tool_use_called / test_nag_injects_reminder_after_three_rounds /
# test_todo_write_resets_nag_counter / test_task_dispatches_via_run_tool
# （从 s07 test_agent.py 原样复制，导入改 s08_context_compact）


# ── s08 新增：压缩 ───────────────────────────────────────────
def test_compact_tool_triggers_compact_history():
    client = FakeClient([
        make_response([tool_use_block("t1", "compact", {})], "tool_use"),
        make_response([text_block("after compact")], "end_turn"),
    ])
    msgs = [{"role": "user", "content": "x"}]
    spy = SpyCompactor()
    agent_loop(client=client, model="m", system="s", tools=[], messages=msgs,
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "compact" in spy.calls
    assert any("[Compacted]" in str(m.get("content", "")) for m in msgs)


def test_pipeline_runs_each_iteration():
    client = FakeClient([
        make_response([tool_use_block("t1", "read_file", {"path": "a"})], "tool_use"),
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    agent_loop(client=client, model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert spy.calls.count("pipeline") >= 2  # 每轮都跑


def test_auto_compact_when_over_limit():
    client = FakeClient([
        make_response([text_block("done")], "end_turn"),
    ])
    spy = SpyCompactor()
    spy.size = 99999  # > context_limit
    agent_loop(client=client, model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "compact" in spy.calls  # auto-compact 触发


def test_reactive_compact_on_prompt_too_long():
    class FlakyClient:
        def __init__(self): self.n = 0
        @property
        def messages(self): return self
        def create(self, **kw):
            self.n += 1
            if self.n == 1:
                raise Exception("prompt_too_long")
            return make_response([text_block("ok")], "end_turn")
    spy = SpyCompactor()
    spy.is_prompt_too_long = lambda e: True
    agent_loop(client=FlakyClient(), model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
               run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
    assert "reactive" in spy.calls


def test_reactive_does_not_swallow_unrelated_error():
    class BoomClient:
        @property
        def messages(self): return self
        def create(self, **kw): raise ValueError("network down")
    spy = SpyCompactor()
    with pytest.raises(ValueError):
        agent_loop(client=BoomClient(), model="m", system="s", tools=[], messages=[{"role": "user", "content": "x"}],
                   run_tool=lambda n, i: "OUT", trigger=lambda ev, *a: None, compact=spy)
```
（顶部加 `import pytest`）
- [ ] **步骤 2：** `pytest s08_context_compact/tests/test_agent.py -v` → FAIL
- [ ] **步骤 3：实现** `agent.py`（见规格 §5）
- [ ] **步骤 4：** `pytest s08_context_compact/tests/test_agent.py -v` → 12 passed（7 + 5）
- [ ] **步骤 5：Commit** `feat(s08): agent_loop 集成压缩管线 + compact 工具 + reactive`

---

## 任务 5：config.py（TDD，9 工具）

**文件：** `tests/test_config.py`、`config.py`

- [ ] **步骤 1：测试**（s07 的 5 个 + make_tools 改 9 含 compact）
```python
import os
from s08_context_compact import skills
from s08_context_compact.config import (build_system_prompt, build_sub_system_prompt,
                                         make_tools, make_sub_tools, prepare_env)


def test_make_tools_has_nine_with_compact():
    names = [t["name"] for t in make_tools()]
    assert names == ["bash", "read_file", "write_file", "edit_file", "glob",
                     "todo_write", "task", "load_skill", "compact"]


def test_make_sub_tools_has_five():
    assert [t["name"] for t in make_sub_tools()] == ["bash", "read_file", "write_file", "edit_file", "glob"]


def test_build_system_prompt_includes_catalog(monkeypatch):
    monkeypatch.setattr(skills, "list_skills", lambda: "- **code-review**: Review code")
    prompt = build_system_prompt("/tmp/x")
    assert "Skills available" in prompt and "load_skill" in prompt


def test_build_sub_system_prompt_unchanged():
    assert "summary" in build_sub_system_prompt("/tmp/x")


def test_prepare_env_pops_auth_token_when_base_url_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    prepare_env()
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ
```
- [ ] **步骤 2：** `pytest s08_context_compact/tests/test_config.py -v` → FAIL
- [ ] **步骤 3：实现** `config.py`（s07 + compact 工具 schema；load 不变——Compactor 在 cli 构造）。`compact` schema：
```python
{"name": "compact", "description": "Summarize earlier conversation to free context space.",
 "input_schema": {"type": "object", "properties": {"focus": {"type": "string"}}}},
```
- [ ] **步骤 4：** `pytest s08_context_compact/tests/test_config.py -v` → 5 passed
- [ ] **步骤 5：Commit** `feat(s08): 实现 config（9 工具含 compact）`

---

## 任务 6：cli.py + __main__.py

**文件：** `cli.py`、`__main__.py`

- [ ] **步骤 1：cli.py**（s07 + 接线 Compactor）
```python
"""交互式 REPL（s08）：s07 + 四层压缩管线。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s08_context_compact.agent import agent_loop
from s08_context_compact.config import load
from s08_context_compact.tools import TOOL_HANDLERS, SUB_HANDLERS, make_run_tool
from s08_context_compact.hooks import trigger_hooks, register_defaults
from s08_context_compact.todo import TodoNag
from s08_context_compact.subagent import Subagent
from s08_context_compact.compact import Compactor


def main() -> None:
    register_defaults()
    cfg = load()
    subagent = Subagent(client=cfg["client"], model=cfg["model"], sub_system=cfg["sub_system"],
                        sub_tools=cfg["sub_tools"], sub_run_tool=make_run_tool(SUB_HANDLERS),
                        trigger=trigger_hooks)
    run_tool = make_run_tool(TOOL_HANDLERS, {"task": subagent.run})
    nag = TodoNag()
    compactor = Compactor(client=cfg["client"], model=cfg["model"])
    print("s08: Context Compact — four-layer compaction pipeline")
    print("Type a question, press Enter. Type q to quit.\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms08 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(client=cfg["client"], model=cfg["model"], system=cfg["system"],
                   tools=cfg["tools"], messages=history, run_tool=run_tool,
                   trigger=trigger_hooks, nag=nag, compact=compactor)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
```
`__main__.py`：`from s08_context_compact.cli import main` / `main()`
- [ ] **步骤 2：** `python -c "from s08_context_compact.cli import main; print('import ok')"` → ok
- [ ] **步骤 3：Commit** `feat(s08): 实现 REPL 入口`

---

## 任务 7：README + 全测 + 实时冒烟 + push + PROGRESS

- [ ] **README**（`## 本阶段完成（相对 s07）`：四层管线 + compact 工具 + reactive；Compactor 注入；保留 hooks/nag；循环加管线）
- [ ] **全测** `pytest s01_*/tests ... s08_context_compact/tests -v` → 全通过
- [ ] **冒烟** `echo '先用 read_file 读 s07_skill_loading/README.md，再调用 compact 工具压缩对话历史，告诉我压缩后还剩什么。' | python -m s08_context_compact` → read_file 工具结果 + `[transcript saved: ...]` + 压缩后报告
- [ ] **Commit README** `docs(s08): 添加阶段 README`
- [ ] **更新 PROGRESS.md** + **计划执行状态块**
- [ ] **Commit + push** `docs(s08): 更新进度总览与计划执行状态` && `git push origin main`

---

## 自检

**1. 规格覆盖度：** §4 compact.py → 任务 2 ✓；§5 agent 集成 → 任务 4 ✓；§6 config → 任务 5 ✓；§7 cli → 任务 6 ✓；§9 验收 → 任务 7 ✓。
**2. 占位符：** 无。
**3. 类型一致性：** `Compactor` 方法签名（run_pipeline/should_auto_compact/compact_history/is_prompt_too_long/reactive_compact/max_reactive_retries）任务 2 定义、任务 4 agent 调用、任务 6 cli 构造一致；`agent_loop(*, ..., nag=None, compact=None)` 一致；compact 工具在 make_tools（9）不在 TOOL_HANDLERS（special-case）。✓
