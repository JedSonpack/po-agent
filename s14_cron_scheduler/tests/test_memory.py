from pathlib import Path
from types import SimpleNamespace
import pytest
from s14_cron_scheduler.memory import Memory


def text_block(t): return SimpleNamespace(type="text", text=t)


class FakeClient:
    def __init__(self, responses): self._r = list(responses)
    @property
    def messages(self): return self
    def create(self, **kw): return self._r.pop(0)


@pytest.fixture
def mem(tmp_path):
    return Memory(client=FakeClient([]), model="m", memory_dir=tmp_path / "mem")


def test_write_memory_file_creates_file_and_index(mem, tmp_path):
    p = mem.write_memory_file("User Pref Tabs", "user", "prefers tabs", "always use tabs")
    assert p.name == "user-pref-tabs.md"
    assert p.exists()
    raw = p.read_text()
    assert "name: User Pref Tabs" in raw
    assert "type: user" in raw
    assert "always use tabs" in raw
    idx = (tmp_path / "mem" / "MEMORY.md").read_text()
    assert "[User Pref Tabs](user-pref-tabs.md)" in idx
    assert "prefers tabs" in idx


def test_read_memory_index_empty(mem):
    assert mem.read_memory_index() == ""


def test_read_memory_index_after_write(mem):
    mem.write_memory_file("X", "user", "desc x", "body x")
    assert "[X]" in mem.read_memory_index()


def test_read_memory_file_found_and_missing(mem):
    mem.write_memory_file("X", "user", "d", "b")
    assert "b" in mem.read_memory_file("x.md")
    assert mem.read_memory_file("nope.md") is None


def test_list_memory_files(mem):
    mem.write_memory_file("A", "user", "da", "ba")
    mem.write_memory_file("B", "feedback", "db", "bb")
    files = mem.list_memory_files()
    assert len(files) == 2
    assert {f["name"] for f in files} == {"A", "B"}


def test_build_index_section_empty(mem):
    assert mem.build_index_section() == ""


def test_build_index_section_with_entries(mem):
    mem.write_memory_file("A", "user", "da", "ba")
    sec = mem.build_index_section()
    assert "Memories available:" in sec
    assert "[A]" in sec
    assert "extract it as a memory" in sec


def test_select_relevant_memories_via_llm(mem):
    mem.write_memory_file("Tabs Pref", "user", "prefers tabs indentation", "use tabs")
    mem.write_memory_file("PDF Tool", "reference", "how to read pdfs", "use pdf skill")
    # sorted: pdf-tool.md=0, tabs-pref.md=1；LLM 选 Tabs Pref → [1]
    mem.client = FakeClient([SimpleNamespace(content=[text_block("[1]")], stop_reason="end_turn")])
    selected = mem.select_relevant_memories([{"role": "user", "content": "I love tabs"}])
    assert selected == ["tabs-pref.md"]


def test_select_relevant_memories_fallback_keywords(mem):
    mem.write_memory_file("Tabs Pref", "user", "prefers tabs indentation", "use tabs")
    mem.write_memory_file("PDF Tool", "reference", "how to read pdfs", "use pdf skill")
    mem.client = FakeClient([])  # create 触发异常 → 回退关键词
    selected = mem.select_relevant_memories([{"role": "user", "content": "tabs are great"}])
    assert "tabs-pref.md" in selected


def test_select_relevant_memories_empty_dir(mem):
    assert mem.select_relevant_memories([{"role": "user", "content": "x"}]) == []


def test_load_memories_wraps_content(mem):
    mem.write_memory_file("X", "user", "dx", "bodyX")
    mem.client = FakeClient([SimpleNamespace(content=[text_block("[0]")], stop_reason="end_turn")])
    out = mem.load_memories([{"role": "user", "content": "x"}])
    assert out.startswith("<relevant_memories>")
    assert out.endswith("</relevant_memories>")
    assert "bodyX" in out


def test_load_memories_none_selected(mem):
    mem.write_memory_file("X", "user", "dx", "bodyX")
    mem.client = FakeClient([SimpleNamespace(content=[text_block("[]")], stop_reason="end_turn")])
    assert mem.load_memories([{"role": "user", "content": "x"}]) == ""


def test_extract_memories_writes_new(mem):
    mem.client = FakeClient([SimpleNamespace(content=[text_block(
        '[{"name":"new-pref","type":"user","description":"likes spaces","body":"use spaces"}]'
    )], stop_reason="end_turn")])
    mem.extract_memories([{"role": "user", "content": "remember I like spaces"}])
    assert (mem.memory_dir / "new-pref.md").exists()
    assert "[new-pref]" in mem.read_memory_index()


def test_extract_memories_empty_noop(mem):
    mem.client = FakeClient([SimpleNamespace(content=[text_block("[]")], stop_reason="end_turn")])
    mem.extract_memories([{"role": "user", "content": "hi"}])
    assert mem.list_memory_files() == []


def test_extract_memories_exception_noop(mem):
    mem.client = FakeClient([])  # create 会 IndexError
    mem.extract_memories([{"role": "user", "content": "hi"}])  # 不抛
    assert mem.list_memory_files() == []


def test_consolidate_memories_under_threshold_noop(mem):
    mem.write_memory_file("A", "user", "da", "ba")
    mem.consolidate_memories()  # 1 < 10
    assert len(mem.list_memory_files()) == 1


def test_consolidate_memories_merges(mem):
    for i in range(10):
        mem.write_memory_file(f"M{i}", "user", f"d{i}", f"b{i}")
    assert len(mem.list_memory_files()) == 10
    mem.client = FakeClient([SimpleNamespace(content=[text_block(
        '[{"name":"merged","type":"user","description":"all","body":"combined"}]'
    )], stop_reason="end_turn")])
    mem.consolidate_memories()
    files = mem.list_memory_files()
    assert len(files) == 1
    assert files[0]["name"] == "merged"
