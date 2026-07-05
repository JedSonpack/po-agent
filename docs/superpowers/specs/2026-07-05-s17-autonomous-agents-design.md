# s17 — Autonomous Agents 设计规格

> 日期：2026-07-05　阶段：s17_autonomous_agents　参照：`learn-claude-code/s17_autonomous_agents`
> 前置：s16（team protocols，324 测试）

## 问题
s16 队友等 Lead 分配任务——看板上 10 个未认领任务，Lead 得手动 assign 10 次。不能扩展。队友应自己看板、自己认领、做完再找下一个。

## 解决方案
沿用 s16 全部，新增：**scan_unclaimed_tasks**（扫可认领任务）、**claim_task owner 检查**（拒绝已 owned）、**idle_poll**（空闲轮询 inbox + 任务板，自动认领）、队友 **WORK→IDLE→SHUTDOWN** 三阶段生命周期、**身份重注入**（压缩后）。队友 +3 工具（list_tasks/claim_task/complete_task，8 工具）。

## po-agent 实现（复制 s16 → s17，保留全部，叠加自治）

### `tasks.py`
- `claim_task` 加 owner 检查：`if task.owner: return f"Task {task_id} already owned by {task.owner}"`（status 检查后、can_start 前）。
- 新增 `scan_unclaimed_tasks() -> list[dict]`：`pending` + `not owner` + `can_start`（按文件名排序）。

### `teams.py`
- **`idle_poll(name, messages, role) -> str`**（替换 s16 `_idle_wait`）：轮询 `max_idle_polls` 次（`idle_poll_interval` 秒）：① `_drain_inbox`（shutdown→"shutdown"，got_msg→"work"）；② `scan_unclaimed_tasks()` 非空 → `claim_task(task["id"], name)`，`"Claimed" in result` → 注入 `<auto-claimed>Task {id}: {subject}</auto-claimed>` + "work"；超时 → "timeout"。
- **`_run` 改 WORK→IDLE 外循环**：`while not shutdown`：身份重注入（`len(messages) <= 3` → `insert(0, <identity>You are '{name}', role: {role}. Continue your work.</identity>)`）→ WORK 内循环（`max_turns`：drain→LLM→非 tool_use break→执行工具；drain 到 shutdown 则 break）→ 若 shutdown break → IDLE `idle_poll`（shutdown/timeout→break，work→继续外循环）。结束发 summary result + pop。
- `_make_sub_run_tool` 加 `list_tasks`/`claim_task`（绑定 `owner=name`）/`complete_task`。
- 构造参数 `idle_poll_interval=5.0`、`max_idle_polls=12`（60s/5s；测试 0.01/2）。

### `tools.py` / `config.py`
- `TEAM_HANDLERS` += `list_tasks`/`claim_task`/`complete_task`（claim_task 在 _make_sub_run_tool 按 name 重绑）。
- `make_team_tools()` += 3 → **8 工具**（bash/read/write/send_message/submit_plan/list_tasks/claim_task/complete_task）。`make_tools()` 不变（23，lead 早有 task 工具）。

### `agent.py` / `cli.py` —— 不变

## 测试
- `test_tasks.py`：scan_unclaimed（pending+无 owner+can_start / 排除 owned·in_progress·blocked·missing dep）、claim owner 检查（拒绝已 owned）
- `test_teams.py`：idle_poll（shutdown/msg/auto-claim/timeout）、_run WORK→IDLE→SHUTDOWN（max_turns WORK→IDLE→超时退出；idle 收 shutdown 退出；身份重注入）、auto-claim 集成
- `test_config.py`：make_team_tools 8 工具

## 验收
- 全量 s01–s17 测试通过
- 冒烟：Lead create 2 tasks → spawn alice+bob → 二者 idle 自动认领不同任务 → 完成 → 60s 超时关机
