# s17: Autonomous Agents

po-agent 第十七阶段，参照 `learn-claude-code/s17_autonomous_agents`。给队友加**自治**：空闲时扫任务板自己认领，不用 Lead 手动分配。队友生命周期从两阶段（WORK/退出）变三阶段：WORK → IDLE（轮询 inbox + 任务板，60s 超时）→ SHUTDOWN。

## 本阶段完成（相对 s16）

在 s16 循环上做了一件核心事：**队友自组织认领任务**。

1. **`tasks.py`**：
   - **`claim_task` 加 owner 检查**：`if task.owner: return "already owned by {owner}"`（status 检查后、can_start 前；防并发认领覆盖）。
   - **`scan_unclaimed_tasks()`**：扫 `pending` + 无 owner + `can_start` 的任务（按文件名排序）。
2. **`teams.py` Team WORK→IDLE→SHUTDOWN**：
   - **`idle_poll(name, messages, role)`**（替换 s16 `_idle_wait`）：轮询 `max_idle_polls` 次（`idle_poll_interval` 秒）——① `_drain_inbox`（shutdown→"shutdown"，got_msg→"work"）；② `scan_unclaimed_tasks()` 非空 → `claim_task(id, owner=name)`，`"Claimed" in result` → 注入 `<auto-claimed>` + "work"；超时 → "timeout"。
   - **`_run` 改外循环**：`while not shutdown`：身份重注入（`len(messages) <= 3` → `insert(0, <identity>You are '{name}', role: {role}. Continue your work.</identity>)`）→ WORK 内循环（`max_turns`：drain→LLM→非 tool_use break→执行工具）→ IDLE `idle_poll`（shutdown/timeout→break，work→继续外循环）。结束发 summary result + pop。
   - **`_make_sub_run_tool`** 加 `claim_task`（绑定 `owner=name`）。
   - 构造默认 `idle_poll_interval=5.0`、`max_idle_polls=12`（60s 超时；测试 0.01/2）。
3. **队友 +3 工具**：`list_tasks`/`claim_task`/`complete_task` 进 `TEAM_HANDLERS` + `make_team_tools`（5→8）。
- **保留 s16 全部**（协议状态机 + MessageBus + 事件队列 cli + cron + background + recovery + system_prompt + hooks/nag/compact/memory/skills/subagent）。`agent_loop` 不变。
- 比 s16 多了**自治认领**：队友空闲自己扫板领活，Lead 只管创建任务 + 启动队友；60s 无新任务自动关机。

## 结构
- `tasks.py` — claim owner 检查 + scan_unclaimed_tasks
- `teams.py` — idle_poll + _run WORK→IDLE→SHUTDOWN + 身份重注入 + claim_task 绑定
- `tools.py` — TEAM_HANDLERS 加 3 任务工具
- `config.py` — make_team_tools 加 3 任务工具（8）
- `agent.py` / `cli.py` — 不变
- 其余模块同 s16

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s17_autonomous_agents
```

## 使用示例

```
s17 >> Create 3 tasks: schema, api routes, tests. Then spawn alice and bob as backend devs.
  [task] created task_...: schema
  [task] created task_...: api routes
  [task] created task_...: tests
  [teammate] alice spawned as backend dev
  [teammate] bob spawned as backend dev
  [idle] alice auto-claimed: schema       ← alice 空闲扫板自己领
  [idle] bob auto-claimed: api routes     ← bob 领了另一个
  ...alice 写 schema.sql → complete_task → idle → auto-claimed: tests
  [idle] alice timeout                    ← 60s 无新任务 → 关机
  [all teammates done]
```

Lead 只创建任务 + 启动队友；alice/bob 自己扫板认领不同任务、做完再领下一个、60s 无活自动关机。

## 测试
```sh
pytest s17_autonomous_agents/tests -v
```
