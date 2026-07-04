# s10 System Prompt — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第十阶段（对应 `learn-claude-code/s10_system_prompt`）
- 状态：自主模式
- 前置：s09 已完成

## 1. 背景与目标

s09（及之前）的系统提示是 `build_system_prompt(cwd)` 一条 f-string + `agent_loop` 里 `system + memory.build_index_section()` 拼接，硬编码、无缓存。s10 把它拆成**主题段落**，运行时按真实状态（工具列表、workspace、技能目录、记忆索引）组装，并用确定性序列列化做缓存避免重复拼接。

- **段落化**：`PROMPT_SECTIONS`（identity/tools/workspace/skills 模板）+ memory 段（动态来自 `Memory.build_index_section()`）。
- **按状态组装**：`assemble_system_prompt(context)` 选段拼接；memory 段仅在索引非空时加入。
- **缓存**：`get_system_prompt(context)` 用 `json.dumps(sort_keys=True)` 做 cache key，命中打 `[cache hit]`，未命中打 `[assembled] sections: ...`。
- **每轮重算**：`agent_loop` 每轮迭代重读 memory 索引、重组 context、取（缓存的）system prompt——工具可能改变真实状态（如 write_file 写 `.memory/MEMORY.md`），下一轮反映。

**目标**：行为对齐 s10 prompt 组装机制，沿用包 + DI + TDD。新机制 `system_prompt.py`；`agent_loop` **drop `system: str` 入参，改取 `context: dict`**，每轮 `build_context` + `get_system_prompt`。保留 s09 全部机制（hooks/nag/compact/memory/skills/subagent）。无新工具。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），prompt 组装机制行为严格对齐 |
| 累积结构 | **保留 s09 全部**（hooks/权限 + TodoNag + Compactor + Subagent + skills + Memory + 9 工具）；s10 参考为教学聚焦只 3 工具且不重做压缩/技能，po-agent 不跟随 |
| agent_loop 签名 | drop `system: str`，新增 `context: dict`（含 cwd/tools/skills_catalog）。`memories` 不进 context 静态部分——每轮从 `memory.build_index_section()` 动态取，并入 ctx |
| context 内容 | `{"cwd": str, "tools": [names], "skills_catalog": str, "memories": str}`；前三个由 config 一次性构造，memories 每轮重读 |
| 段落 | identity（静态）/ tools（格式化工具名列表）/ workspace（cwd）/ skills（目录，始终含，catalog 可为 "(no skills found)"）/ memory（条件，索引非空才加，内容含引导来自 build_index_section） |
| 缓存 | 模块级单槽 `_last_context_key`/`_last_prompt`；key=`json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)`；命中条件 `key == _last_context_key and _last_prompt`。测试间用 `reset_cache()` 重置 |
| 每轮重组 | `agent_loop` 每轮 `ctx = {**context, "memories": memory.build_index_section() if memory else ""}` → `sys_prompt = get_system_prompt(ctx)`。同 turn 内 memories 稳定 → 迭代 2+ 命中；跨 turn 索引变 → 未命中重组 |
| Memory 不改 | `Memory.build_index_section()` 原样（返回 "" 或含引导的完整段）；assemble 直接 append 为一段 |
| Subagent 不改 | 子 agent 仍用 `sub_system` 字符串，不走段落组装（参考 s10 无 subagent，po-agent 保留 s09 子 agent 原样） |
| s09 注入保留 | `memories_content`（load_memories）注入 user 轮、`memory_turn`、`pre_compress` 快照、turn 结束 extract+consolidate——全部原样 |
| 无新工具 | TOOLS 仍 9（bash/read_file/write_file/edit_file/glob/todo_write/task/load_skill/compact） |

## 3. 结构

```
po-agent/s10_system_prompt/
├── __init__.py
├── config.py        # build_context 取代 build_system_prompt；load() 返回 context（drop system）
├── tools.py         # s09 原样
├── skills.py        # s09 原样
├── hooks.py         # s09 原样
├── todo.py          # s09 原样
├── subagent.py      # s09 原样（sub_system 字符串不变）
├── compact.py       # s09 原样
├── memory.py        # s09 原样
├── system_prompt.py # 新：PROMPT_SECTIONS + assemble_system_prompt + get_system_prompt(缓存) + build_context + reset_cache
├── agent.py         # s09 + context 重构（drop system，每轮 build_context+get_system_prompt）
├── cli.py           # REPL（传 context）
├── __main__.py
├── README.md
└── tests/           # test_system_prompt(新) / test_agent(改 context) / test_config(改 build_context) / 其余 s09 原样
```

## 4. 核心新增：system_prompt.py

```python
import json

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: {tools}.",
    "workspace": "Working directory: {cwd}.",
    "skills": "Skills available:\n{catalog}\nUse load_skill to get full details when needed.",
    # memory 段动态来自 Memory.build_index_section()（含引导），无模板
}

_last_context_key = None
_last_prompt = None


def assemble_system_prompt(context: dict) -> str:
    """按真实状态选段拼接。memory 段仅索引非空时加入。"""
    sections = [
        PROMPT_SECTIONS["identity"],
        PROMPT_SECTIONS["tools"].format(tools=", ".join(context.get("tools", []))),
        PROMPT_SECTIONS["workspace"].format(cwd=context.get("cwd", "")),
        PROMPT_SECTIONS["skills"].format(catalog=context.get("skills_catalog", "(no skills found)")),
    ]
    if context.get("memories"):
        sections.append(context["memories"])
    return "\n\n".join(sections)


def get_system_prompt(context: dict) -> str:
    """缓存包装：相同 context 命中返回旧 prompt。"""
    global _last_context_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_context_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt unchanged\033[0m")
        return _last_prompt
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)
    loaded = ["identity", "tools", "workspace", "skills"]
    if context.get("memories"):
        loaded.append("memory")
    print(f"  \033[32m[assembled] sections: {', '.join(loaded)}\033[0m")
    return _last_prompt


def build_context(*, cwd, tools, skills_catalog, memories="") -> dict:
    """从组件构造 context。tools 接收 dict 列表或名字列表，统一存名字。"""
    if tools and isinstance(tools[0], dict):
        tools = [t["name"] for t in tools]
    return {"cwd": str(cwd), "tools": list(tools),
            "skills_catalog": skills_catalog, "memories": memories}


def reset_cache() -> None:
    """测试间重置模块级缓存槽。"""
    global _last_context_key, _last_prompt
    _last_context_key = None
    _last_prompt = None
```

## 5. agent_loop 集成（agent.py）

s09 agent_loop + context 重构：drop `system`，新增 `context`；每轮重算 ctx + 取缓存 prompt。
```python
from s10_system_prompt.system_prompt import build_context, get_system_prompt

def agent_loop(*, client, model, context, tools, messages, run_tool, trigger,
               nag=None, compact=None, memory=None, max_tokens: int = 8000) -> None:
    reactive_retries = 0
    memories_content = memory.load_memories(messages) if memory else ""
    memory_turn = (len(messages) - 1) if (memory and messages
                                          and isinstance(messages[-1].get("content"), str)) else None
    while True:
        pre_compress = ([{"role": m.get("role", ""), "content": _stringify(m.get("content", ""))}
                         for m in messages] if memory else None)
        # s10: 每轮重算 context（重读 memory 索引）+ 组装 system prompt（缓存）
        ctx = build_context(cwd=context.get("cwd", ""), tools=tools,
                            skills_catalog=context.get("skills_catalog", ""),
                            memories=(memory.build_index_section() if memory else ""))
        sys_prompt = get_system_prompt(ctx)
        if compact:
            compact.run_pipeline(messages)
            if compact.should_auto_compact(messages):
                print("[auto compact]")
                compact.compact_history(messages)
        if nag:
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        try:
            request_messages = messages
            if memory and memories_content and memory_turn is not None and memory_turn < len(messages):
                request_messages = messages.copy()
                request_messages[memory_turn] = {
                    **messages[memory_turn],
                    "content": memories_content + "\n\n" + messages[memory_turn]["content"],
                }
            response = client.messages.create(
                model=model, system=sys_prompt, messages=request_messages,
                tools=tools, max_tokens=max_tokens,
            )
            reactive_retries = 0
        except Exception as e:
            if (compact and compact.is_prompt_too_long(e)
                    and reactive_retries < compact.max_reactive_retries):
                print("[reactive compact]")
                compact.reactive_compact(messages)
                reactive_retries += 1
                continue
            raise
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            if memory:
                memory.extract_memories(pre_compress)
                memory.consolidate_memories()
            force = trigger("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        if nag:
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "compact":
                compact.compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. Conversation history has been summarized.]"})
                break
            blocked = trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```
`_stringify` 模块级 helper 同 s09。

## 6. config.py / cli.py

- **config.py**：`build_system_prompt(cwd)` → `build_context(cwd, tools, skills_catalog)`：
```python
def build_context(cwd: str, tools: list) -> dict:
    from s10_system_prompt.system_prompt import build_context as _bc
    return _bc(cwd=cwd, tools=tools, skills_catalog=skills.list_skills())
```
（config 模块函数名也叫 `build_context`，转调 system_prompt 的；或直接在 load 里调 system_prompt.build_context。为清晰，config 暴露 `build_context`。）`load()` 返回 `context`（drop `system`），保留 `sub_system`/`sub_tools`。
- **cli.py**：`agent_loop(..., context=cfg["context"], tools=cfg["tools"], ...)`（drop `system=cfg["system"]`）。其余同 s09。

## 7. 测试策略

- **test_system_prompt.py**（新）：
  - `assemble_system_prompt` 无 memory → 4 段（identity/tools/workspace/skills）`\n\n` 拼，不含 "Memories available"
  - 有 memory → 5 段，含 memory 内容
  - tools/workspace/skills 格式化（工具名列表、cwd、catalog）
  - `get_system_prompt` 相同 context 命中（`reset_cache` 后第一次 `[assembled]`，第二次 `[cache hit]`，返回相等）
  - context 变化（加 memory）→ 未命中重组，返回含 memory
  - 缓存 key 用 json.dumps：嵌套 list/dict 不抛 unhashable；同内容不同 key 顺序命中（sort_keys）
  - `build_context`：dict 列表→名字列表；名字列表→原样；memories 默认 ""
  - `reset_cache` 清槽
- **test_agent.py**：s09 的 16 个 sed 复制，`system="s"` → `context={"cwd": ".", "tools": [], "skills_catalog": ""}`；FakeClient 捕获 `system` kwarg 断言组装内容（含 "coding agent"/workspace）。memory 测试（SpyMemory）原样。
- **test_config.py**：s09 的 sed 复制，`build_system_prompt` → `build_context` 断言（含 cwd/tools/skills_catalog）；`load()` 返回 context（无 system）。
- 其余 test_*（tools/skills/hooks/todo/subagent/compact/memory）：s09 原样 sed 改名。

## 8. 行为对齐验收

- 全量测试通过（s01-s10）。
- 实时冒烟：`echo '列出当前目录的 .py 文件' | python -m s10_system_prompt` → 首轮 `[assembled] sections: identity, tools, workspace, skills`（无 .memory 时无 memory 段），后续 tool 轮 `[cache hit]`；agent 正常调工具。再预置 `.memory/MEMORY.md` 跑一轮 → `[assembled] sections: ..., memory`。

## 9. 范围外（YAGNI）

- CC 真实的 API 级 prompt cache（`SYSTEM_PROMPT_DYNAMIC_BOUNDARY`、cache scope）、section 注册缓存、`getSystemPrompt(tools, model, ...)` 返回 `string[]` —— 参考 s10 不实现，po-agent 也不实现。
- 子 agent 的段落化系统提示（保留 s09 简单 sub_system 字符串）。
- LRU 缓存（单槽足够教学）。
