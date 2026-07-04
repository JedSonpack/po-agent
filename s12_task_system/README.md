# s12: Task System

po-agent 第十二阶段，参照 `learn-claude-code/s12_task_system`。加**文件持久化的任务图**：每个任务一个 `.tasks/{id}.json`，`blockedBy` 声明依赖（DAG），状态跨会话保留，可认领/追踪/解锁。

## 本阶段完成（相对 s11）

在 s11 循环上做了一件核心事：**可追踪的持久任务系统（与 s05 TodoWrite 不同）**。

1. **`tasks.py`**：
   - **`Task` dataclass**（id/subject/description/status/owner/blockedBy）；status ∈ pending/in_progress/completed；`.tasks/{id}.json` 持久化。
   - **`can_start`**：blockedBy 全 completed 才 True；缺失依赖=blocked（不抛）；不递归。
   - **`claim_task`**：pending+can_start → owner+in_progress；非 pending 拒绝；blocked 报 `"Blocked by: [...]"`。
   - **`complete_task`**：in_progress→completed；扫描下游（pending 且 blockedBy 非空且 can_start）报 `"Unblocked: ..."`（不自动 claim）。
   - **5 工具 handler**：run_create_task/run_list_tasks（图标 ○/●/✓ + owner + blockedBy）/run_get_task/run_claim_task/run_complete_task。
2. **5 工具进 `TOOL_HANDLERS` + `make_tools()`（共 14）**：create_task/list_tasks/get_task/claim_task/complete_task。
- **`agent_loop` 不改**——任务工具静态 handler，经 run_tool 自动分发（同 todo_write/load_skill）。
- **保留 s11 全部**（recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent）。
- 比 s11 多了**跨会话持久 + 依赖图**：大目标拆成可追踪、可解锁的任务，重启还在。

## 结构
- `tasks.py` — Task + 持久化 + can_start/claim/complete + 5 run_* handler
- `tools.py` — TOOL_HANDLERS 加 5 任务 handler
- `config.py` — make_tools 加 5 任务工具（14）
- `recovery.py` / `system_prompt.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` / `agent.py` / `cli.py` — 同 s11

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s12_task_system
```

## 使用示例

```
s12 >> 创建任务 schema、endpoints（依赖 schema），claim schema，complete schema，看 endpoints 是否解锁
  [assembled] sections: identity, tools, workspace, skills
  [task] created task_..._....: schema
  [task] created task_..._....: endpoints
  [HOOK] create_task([...])
  ...
  [HOOK] claim_task([...])
  [HOOK] complete_task([...])
```

agent 调 create_task×2 + claim_task + complete_task，complete 报告 `Unblocked: endpoints`——依赖图自动解锁下游。

## 测试
```sh
pytest s12_task_system/tests -v
```
