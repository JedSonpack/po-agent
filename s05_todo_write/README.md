# s05: TodoWrite

po-agent 第五阶段，参照 `learn-claude-code/s05_todo_write`。给 agent 一个任务清单（`todo_write` 工具）+ nag reminder，防止长任务跑偏。

## 本阶段完成（相对 s04）

在 s04 循环上做了一件核心事：**给 agent 规划能力**。

1. **`todo_write` 工具**：输入带状态的 todos 列表（`pending`/`in_progress`/`completed`），`_normalize_todos` 接受 list 或 JSON/ast 字符串并逐项校验；存进内存 `CURRENT_TODOS`，打印彩色任务表，返回 `Updated N tasks`。经 `TOOL_HANDLERS` 自动分发，循环不动。
2. **`TodoNag` 机制**：连续 3 个 tool 轮未调 `todo_write`，循环顶部注入 `<reminder>Update your todos.</reminder>` 并归零；调 `todo_write` 归零计数。
3. **SYSTEM 提示**加 "Before starting any multi-step task, use todo_write to plan your steps. Update status as you go."
- **循环核心不变**——新工具自动走 `TOOL_HANDLERS` 分发；nag 通过注入的 `TodoNag` 对象（`nag=None` 默认）挂在循环三处（顶部 `maybe_nag`、tool 轮 `on_round`、todo_write `on_todo_write`），不写死在循环里。
- 比 s04 多了**规划能力**：todo_write 不增加执行能力，增加的是"先列步骤再动手"的能力。

## 结构
- `config.py` — env + 6 工具 + 规划提示 + `load`
- `tools.py` — s04 工具 + `CURRENT_TODOS`/`_normalize_todos`/`run_todo_write` + `run_tool`
- `hooks.py` — 同 s04（hook 系统不变）
- `todo.py` — `TodoNag`（maybe_nag/on_round/on_todo_write）
- `agent.py` — `agent_loop`（注入 `nag=None`）
- `cli.py` / `__main__.py` — REPL（`register_defaults` + `trigger UserPromptSubmit` + 构造 `TodoNag`）

## 运行
```sh
source ../.venv/bin/activate
python -m s05_todo_write
```

## 测试
```sh
pytest s05_todo_write/tests -v
```
