# s06: Subagent

po-agent 第六阶段，参照 `learn-claude-code/s06_subagent`。给 agent **委派能力**：`task` 工具派一个子 agent，子 agent 拿全新 `messages[]`（干净上下文）跑自己的循环，只返回总结（中间过程丢弃）。子 agent 没有 `task` 工具 → 不能递归派子。

## 本阶段完成（相对 s05）

在 s05 循环上做了一件核心事：**给 agent 委派能力（上下文隔离）**。

1. **`task` 工具 + `Subagent` 类**：`Subagent.run(description)` 用全新 `messages=[{"role":"user","content":description}]` 跑自己的循环（`max_turns=30` 安全限），用 `SUB_TOOLS`（5 工具，无 `task` 无 `todo_write` → 防递归），跑 hooks（PreToolUse/PostToolUse，权限适用子 agent），**只返回 `extract_text` 总结**，整段 messages 丢弃。
2. **`extract_text(content)`** 助手：从 content blocks 提取文本。
3. **fallback**：safety limit 命中且末消息无 text → 倒序找 assistant text；仍无 → `"Subagent stopped after N turns without final answer."`。
4. **`run_tool` 缝演进为 `make_run_tool(handlers, extra)` 工厂**：`task` 处理器需要 client（模块加载时拿不到），故 `run_tool` 从模块级静态函数演进为接线时构造的闭包；`cli` 用 `make_run_tool(TOOL_HANDLERS, {"task": subagent.run})` 装配 7 工具分发器。
- **循环核心不变**——`task` 经 `run_tool` 自动分发，循环不 special-case；nag/hooks/todo_write 全保留。
- 比 s05 多了**委派能力**：大任务拆给子 agent，子任务拿干净上下文不互相污染。

## 结构
- `config.py` — env + `make_tools`(7) + `make_sub_tools`(5) + 双提示 + `load`
- `tools.py` — s05 工具(6) + `SUB_HANDLERS`(5) + `make_run_tool` + 模块级 `run_tool`
- `hooks.py` / `todo.py` — 同 s05
- `subagent.py` — `extract_text` + `Subagent`（fresh messages、max_turns、summary only）
- `agent.py` — `agent_loop`（同 s05，task 自动分发）
- `cli.py` / `__main__.py` — REPL（接线 `Subagent` + `make_run_tool({"task": ...})`）

## 运行
```sh
source ../.venv/bin/activate
python -m s06_subagent
```

## 测试
```sh
pytest s06_subagent/tests -v
```
