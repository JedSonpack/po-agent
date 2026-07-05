# s15: Agent Teams

po-agent 第十五阶段，参照 `learn-claude-code/s15_agent_teams`。加**队友**：Lead 调 `spawn_teammate` 启动 daemon 线程队友，各自跑简化循环，经文件收件箱（`.mailboxes/*.jsonl`）异步通信。把"一次性子 agent"升级成"多轮通信队友"——Lead 收件箱有消息就 wake 一轮 turn 注入 `[Inbox]`。

## 本阶段完成（相对 s14）

在 s14 循环上做了一件核心事：**多 agent 组队异步协作**。

1. **`teams.py`**：
   - **`MessageBus`**：文件收件箱（`.mailboxes/{agent}.jsonl`）；`send`=append、`read_inbox`=读+unlink（消费式）、`peek`=非消费式（inbox_poller wake 条件）。`mailbox_dir` 可注入（测试用 tmp_path）。
   - **`Team` 类**（DI：client/model/bus/base_handlers/sub_tools/trigger）：`spawn(name,role,prompt)` 起 daemon 线程跑 `_run`——4 工具（bash/read/write/send_message），max 10 轮，每轮顶上注入 `<inbox>`，`messages[-20:]` 滑动窗口，完成后倒序取 assistant text 作 summary 发 `result` 给 lead + pop `active_teammates`。`send_message` 的 `from`=队友名（per-spawn 绑定）；无 spawn_teammate 防组队递归。
   - **3 lead 工具**：`run_send_message`（from 固定 lead）/`run_check_inbox`（消费 lead 邮箱）/`spawn_teammate`（=team.spawn，cli 经 `make_run_tool` 的 `extra` 接线）。
2. **`background.py`** 加 `has_pending_background()`（非消费式，inbox_poller wake 条件）。
3. **`cli.py` 重构为事件队列**：input_reader + inbox_poller（1s，`BUS.peek("lead") or has_pending_background()` → wake）；wake 排干 lead inbox + 后台通知，拼 `[Inbox]` 注入 history 起一轮 turn；"all teammates done" 公告。`run_turn(query=None,inject=None)` 不持锁，main 与 cron queue_processor 经 `agent_lock` 串行（s14 cron 机制不变）。
- **保留 s14 全部**（cron + background + tasks + recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent）。3 工具进 `TOOL_HANDLERS`+`make_tools`（20）；新增 `make_team_tools`（4）。`agent_loop` 不变。
- 比 s14 多了**异步队友通信**：队友在后台线程干活、随时通过文件邮箱汇报，Lead 收件箱有消息就自动 wake。

## 结构
- `teams.py` — MessageBus + Team 类 + 3 lead handler
- `agent.py` — `agent_loop`（不变；团队工具经 run_tool 分发，inbox 注入在 cli 层）
- `background.py` — 加 `has_pending_background`
- `config.py` — make_tools 加 3 团队工具（20）+ make_team_tools（4）
- `tools.py` — TOOL_HANDLERS 加 send_message/check_inbox + TEAM_HANDLERS
- `cli.py` — 事件队列 + inbox_poller + wake 注入 + Team 接线
- `cron.py` / `tasks.py` / `recovery.py` / `system_prompt.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` — 同 s14

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s15_agent_teams
```

## 使用示例

```
s15 >> Spawn alice as a backend developer. Ask her to create schema.sql with a users table.
  [teammate] alice spawned as backend developer
  [bus] alice → lead: CREATE TABLE users (...)   ← alice 在后台线程干活、汇报
  [teammate] alice finished
  [wake: 1 inbox + 0 background → new turn]      ← inbox_poller 触发 wake
  Alice has completed her task! ...               ← Lead 收到 alice 结果并总结
  [all teammates done]
```

Lead 调 spawn_teammate 起 alice 线程，alice 自己跑 LLM + write_file，完成后发 result 到 lead 邮箱；inbox_poller 检测到 → wake Lead 注入 `[Inbox]` 起一轮 turn。

## 测试
```sh
pytest s15_agent_teams/tests -v
```
