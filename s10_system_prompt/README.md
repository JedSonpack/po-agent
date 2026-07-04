# s10: System Prompt

po-agent 第十阶段，参照 `learn-claude-code/s10_system_prompt`。把硬编码的系统提示拆成**主题段落**，运行时按真实状态（工具列表、workspace、技能目录、记忆索引）组装，并用确定性序列化做缓存避免重复拼接。

## 本阶段完成（相对 s09）

在 s09 循环上做了一件核心事：**系统提示从"一条 f-string"变成"段落组装 + 缓存 + 每轮重算"**。

1. **`system_prompt.py`**：
   - **`PROMPT_SECTIONS`**（identity/tools/workspace/skills 模板）+ memory 段（动态来自 `Memory.build_index_section()`）。
   - **`assemble_system_prompt(context)`**：选段 `\n\n` 拼接；identity/tools/workspace/skills 始终含，memory 段仅索引非空时加。
   - **`get_system_prompt(context)`**：`json.dumps(sort_keys=True)` 做 cache key 的单槽缓存——命中打 `[cache hit]`，未命中打 `[assembled] sections: ...`。
   - **`build_context(*, cwd, tools, skills_catalog, memories="")`**：从组件构造 context（tools 接 dict 列表或名字列表，统一存名字）。
2. **`agent_loop` 重构**：drop `system: str` 入参 → 改取 `context: dict`；每轮迭代 `build_context`（重读 memory 索引）+ `get_system_prompt`（缓存）。同 turn 内 memory 索引稳定 → 迭代 2+ 命中缓存；跨 turn 索引变 → 重组装。把 s09 的 `sys_prompt = system + memory.build_index_section()` 收进 `assemble_system_prompt`。
- **保留 s09 全部**（hooks/权限 + TodoNag + Compactor + Subagent + skills + Memory + 9 工具）——组装机制与这些正交共存。无新工具。
- 比 s09 多了**运行时按状态组装 + 缓存**：工具写了 `.memory/MEMORY.md`，下一轮 system 自动多出 memory 段。

## 结构
- `config.py` — `build_context` 取代 `build_system_prompt`；`load()` 返回 `context`（drop `system`）
- `system_prompt.py` — 段落组装 + 缓存 + build_context + reset_cache
- `tools.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` — 同 s09
- `agent.py` — `agent_loop`（drop `system`，改 `context`，每轮 build_context + get_system_prompt）
- `cli.py` / `__main__.py` — REPL（传 context）

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s10_system_prompt
```

## 使用示例

问一个会触发工具的问题：

```
s10 >> 列出当前目录的 .py 文件
  [assembled] sections: identity, tools, workspace, skills
  [cache hit] system prompt unchanged
  [HOOK] UserPromptSubmit: working in ...
> glob
  ...
```

首轮 `[assembled]` 拼出 4 段（无 `.memory` 时无 memory 段）；后续 tool 轮 `[cache hit]`。预置 `.memory/MEMORY.md` 后再跑，`[assembled] sections: identity, tools, workspace, skills, memory`——运行时按真实状态组装。

## 测试
```sh
pytest s10_system_prompt/tests -v
```
