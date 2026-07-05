import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from s19_mcp_plugin.compact import (
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
    msgs = [_user_text(str(i)) for i in range(60)]  # 60 msgs
    # tail_start = 60-7 = 53；把 52/53 设成 tool_use/tool_result 对
    msgs[52] = _asst(tu_block("tx"))
    msgs[53] = _user_tool_results(tr_block("tx"))
    out = snip_compact(msgs, max_messages=10)
    # tail_start=53 是 tool_result、前一条 tool_use → tail_start -= 1 → 52
    tr_indices = [i for i, m in enumerate(out) if _is_tool_result_message(m)]
    assert tr_indices
    # tool_result 前一条是 tool_use（不拆对）
    assert _message_has_tool_use(out[tr_indices[0] - 1])
    # snipped 计数 = tail_start(52) - head_end(3) = 49
    assert out[3]["content"] == "[snipped 49 messages]"


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
    compactor.context_limit = 1000
    assert compactor.should_auto_compact([_user_text("x" * 2000)]) is True
    assert compactor.should_auto_compact([_user_text("x")]) is False


def test_is_prompt_too_long():
    assert Compactor.is_prompt_too_long(Exception("Request failed: prompt_too_long")) is True
    assert Compactor.is_prompt_too_long(Exception("too many tokens")) is True
    assert Compactor.is_prompt_too_long(Exception("other error")) is False


def test_run_pipeline_runs_all_three(compactor, monkeypatch):
    calls = []
    monkeypatch.setattr(compactor, "tool_result_budget", lambda m, **k: calls.append("budget"))
    monkeypatch.setattr("s19_mcp_plugin.compact.snip_compact", lambda m, *a, **k: calls.append("snip") or m)
    monkeypatch.setattr("s19_mcp_plugin.compact.micro_compact", lambda m, *a, **k: calls.append("micro"))
    compactor.run_pipeline([_user_text("x")])
    assert calls == ["budget", "snip", "micro"]
