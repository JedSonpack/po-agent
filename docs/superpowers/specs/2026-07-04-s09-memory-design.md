# s09 Memory — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第九阶段（对应 `learn-claude-code/s09_memory`）
- 状态：自主模式
- 前置：s08 已完成

## 1. 背景与目标

s08 的压缩会丢细节。s09 加**持久跨会话记忆**：关键细节存 `.memory/`（MEMORY.md 索引 + 各记忆文件），跨会话存活。
- **SYSTEM 注索引**（便宜，常驻）：每轮把 MEMORY.md 索引（一行一记忆）放系统提示。
- **按需注入**：`load_memories(messages)` 用 LLM 选相关记忆，内容注入当前 user 轮。
- **提取**：每轮结束 `extract_memories(pre_compress)`——LLM 从对话抽 user 偏好/约束/项目事实，写新记忆文件。
- **整合**：记忆数 ≥ 10 时 `consolidate_memories`——LLM 合并去重、删过时。

**目标**：行为对齐 s09 记忆机制，沿用包 + DI + TDD。新机制 `memory.py`（`Memory` 类）；`agent_loop` 注入 `memory`，加：每轮注索引到 system、注入相关记忆到 user 轮、turn 结束提取+整合、pre_compress 快照保真。保留 s08 全部机制（hooks/nag/compact/skills/subagent）。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），记忆机制行为严格对齐 |
| 累积结构 | **保留 s08 全部**（4 事件 hooks + nag + compact 工具 + load_skill + skills + subagent + Compactor）；s09 参考为教学聚焦简化为骨架（去 hooks/nag/skills/compact-tool），po-agent 不跟随——记忆与这些正交 |
| Memory DI | `Memory(*, client, model, memory_dir, max_items=5, consolidate_threshold=10, ...)` 注入 `agent_loop`（`memory=None` 默认） |
| frontmatter 解析 | 复用 `skills._parse_frontmatter`（pyyaml，po-agent s07 起一致；参考用手写解析，行为等价） |
| 记忆文件格式 | `---\nname:...\ndescription:...\ntype:...\n---\n\n{body}`；slug = name 小写空格/斜线转 `-`；type ∈ user/feedback/project/reference |
| 索引格式 | `- [{name}]({filename}) — {desc}` 一行一记忆（≤200 行，教学版不强制） |
| select_relevant | LLM 选索引（JSON 数组）→ filenames；失败回退关键词匹配 name+description；空目录/空 recent → [] |
| extract/consolidate | LLM 抽 JSON 数组 `{name,type,description,body}` → write_memory_file；异常/空 → no-op（不抛） |
| system 集成 | `agent_loop` 把 `memory.build_index_section()` 追加到 base system（含 "Respect user preferences... extract as memory" 引导） |
| 注入 | `memories_content` 在 agent_loop 顶部取一次（per turn）；每轮 build request_messages 时 prepend 到 `messages[memory_turn]`（memory_turn = 末条 string-content user 消息索引）；压缩后若索引失效则跳过 |
| pre_compress | 每轮压缩前 stringify 快照（frozen），turn 结束 `extract_memories(pre_compress)` 保真 |
| 无新工具 | 记忆是内部机制（inject+extract），不加 save_memory 工具（对齐参考）；TOOLS 仍 9 |
| 循环 | s08 + memory 三处集成（system 索引 / user 轮注入 / turn 结束提取+整合） |

## 3. 结构

```
po-agent/s09_memory/
├── __init__.py
├── config.py     # s08 原样（9 工具 + skills 目录提示 + load）；system 索引由 agent_loop 追加
├── tools.py      # s08 原样
├── skills.py     # s08 原样（_parse_frontmatter 复用）
├── hooks.py      # s08 原样
├── todo.py       # s08 原样
├── subagent.py   # s08 原样（extract_text 复用）
├── compact.py    # s08 原样
├── memory.py     # 新：Memory 类（write/read/index/select/load/extract/consolidate + build_index_section）
├── agent.py      # s08 + memory 集成（注入 memory）
├── cli.py        # REPL（接线 Memory）
├── __main__.py
├── README.md
└── tests/        # test_memory(新) / test_compact / test_tools / test_skills / test_hooks / test_todo / test_subagent / test_agent(+memory) / test_config
```

## 4. 核心新增：memory.py

```python
import json, re, time
from pathlib import Path
from s09_memory.skills import _parse_frontmatter
from s09_memory.subagent import extract_text

MEMORY_TYPES = ["user", "feedback", "project", "reference"]
CONSOLIDATE_THRESHOLD = 10


class Memory:
    def __init__(self, *, client, model, memory_dir, max_items=5,
                 consolidate_threshold=CONSOLIDATE_THRESHOLD,
                 select_max_tokens=200, extract_max_tokens=800,
                 consolidate_max_tokens=3000): ...

    def write_memory_file(self, name, mem_type, description, body) -> Path:
        slug = name.lower().replace(" ", "-").replace("/", "-")
        path = self.memory_dir / f"{slug}.md"
        path.write_text(f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n")
        self._rebuild_index()
        return path

    def _rebuild_index(self):  # 扫 *.md（除 MEMORY.md）→ MEMORY.md
    def read_memory_index(self) -> str:  # MEMORY.md 内容或 ""
    def read_memory_file(self, filename) -> str | None:
    def list_memory_files(self) -> list[dict]:  # [{filename,name,description,type,body}]

    def select_relevant_memories(self, messages) -> list[str]:  # LLM 选索引 → filenames；回退关键词
    def load_memories(self, messages) -> str:  # 选 + 读 → <relevant_memories>...</>

    def extract_memories(self, messages) -> None:  # LLM 抽 JSON 数组 → write；空/异常 no-op
    def consolidate_memories(self) -> None:  # >=threshold → LLM 合并，删旧重写

    def build_index_section(self) -> str:  # "\n\nMemories available:\n{index}\n引导" 或 ""
```

**select_relevant_memories**：取最近 3 条 user 文本（≤2000 字符）→ catalog `{i}: {name} — {desc}` → LLM 返 JSON 整数数组 → 映射 filenames（≤max_items）；异常/空回退关键词（recent 中 >3 字符的词匹配 name+description 小写）。

**extract_memories**：取最近 10 条对话 stringify → prompt 抽 `{name,type,description,body}` 数组（含 existing 描述防重复）→ 每条 desc+body 非空则 write_memory_file → 打印 `[Memory: extracted N new memories]`。

**consolidate_memories**：files >= threshold → catalog → prompt 合并（去重/删过时/≤30）→ 删所有非 MEMORY.md 文件 → 重写。

## 5. agent_loop 集成（agent.py）

s08 agent_loop + memory 三处：
```python
def agent_loop(*, client, model, system, tools, messages, run_tool, trigger,
               nag=None, compact=None, memory=None, max_tokens=8000):
    reactive_retries = 0
    memories_content = memory.load_memories(messages) if memory else ""
    memory_turn = (len(messages) - 1) if (memory and messages and isinstance(messages[-1].get("content"), str)) else None
    sys_prompt = system + (memory.build_index_section() if memory else "")
    while True:
        pre_compress = ([{"role": m.get("role", ""), "content": _stringify(m.get("content", ""))} for m in messages]
                        if memory else None)
        if compact:
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):
                print("[auto compact]"); compact.compact_history(messages)
        if nag:
            reminder = nag.maybe_nag(messages)
            if reminder: messages.append({"role": "user", "content": reminder})
        try:
            request_messages = messages
            if memory and memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {**messages[memory_turn],
                                                 "content": memories_content + "\n\n" + messages[memory_turn]["content"]}
            response = client.messages.create(model=model, system=sys_prompt, messages=request_messages,
                                              tools=tools, max_tokens=max_tokens)
            reactive_retries = 0
        except Exception as e:
            if compact and compact.is_prompt_too_long(e) and reactive_retries < compact.max_reactive_retries:
                print("[reactive compact]"); compact.reactive_compact(messages); reactive_retries += 1; continue
            raise
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            if memory:
                memory.extract_memories(pre_compress)
                memory.consolidate_memories()
            force = trigger("Stop", messages)
            if force: messages.append({"role": "user", "content": force}); continue
            return
        if nag: nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use": continue
            if block.name == "compact":  # s08
                compact.compact_history(messages)
                results.append({..."[Compacted. ...]"}); break
            blocked = trigger("PreToolUse", block)
            if blocked: results.append({...blocked}); continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write": nag.on_todo_write()
            results.append({...output})
        messages.append({"role": "user", "content": results})
```
`_stringify(content)`：str→原样；list→拼 text 块；其他→str。模块级 helper。

## 6. config.py / cli.py

- config.py：s08 原样（9 工具 + skills 目录提示）。build_system_prompt 不含 memory 索引（agent_loop 追加）。
- cli.py：s08 + `memory = Memory(client=cfg["client"], model=cfg["model"], memory_dir=Path.cwd()/".memory")`；`agent_loop(..., memory=memory)`。Memory 构造时确保 memory_dir 存在。

## 7. 测试策略

- **test_memory.py**（新）：write_memory_file（slug/文件/索引重建）；read_memory_index/read_memory_file/list_memory_files；build_index_section（有/无）；select_relevant_memories（FakeClient 返 JSON → filenames / 异常回退关键词 / 空目录 → []）；load_memories（包 `<relevant_memories>`）；extract_memories（FakeClient 返 JSON 数组 → 写文件 / 空 / 异常 no-op）；consolidate_memories（<threshold no-op / >=threshold 重写）。tmp_path memory_dir + FakeClient。
- **test_agent.py**：s08 的 12 个（memory=None）+ memory 注入（SpyMemory 记 load）/ turn 结束提取（SpyMemory 记 extract + consolidate）/ system 含索引。
- 其余 test_*：s08 原样（改包名）。

## 8. 行为对齐验收

- 全量测试通过（s01-s09）。
- 实时冒烟：`echo '请记住：我最喜欢用 spaces 缩进、绝不用 tabs。' | python -m s09_memory` → turn 结束 `[Memory: extracted N new memories]`，`.memory/` 落记忆文件 + MEMORY.md 索引；再跑一轮验证索引在 SYSTEM（或直接查 .memory/）。

## 9. 范围外（YAGNI）

- 记忆的向量检索/嵌入、按 type 分目录、MEMORY.md 200 行硬上限、active memory vs archival 分层、记忆版本号 — 后续/教学简化。
- save_memory 工具（参考也内部提取，无工具）。
