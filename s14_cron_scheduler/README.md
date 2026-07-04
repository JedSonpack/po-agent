# s14: Cron Scheduler

po-agent 第十四阶段，参照 `learn-claude-code/s14_cron_scheduler`。加**闹钟**：设 cron 表达式，到点调度线程把任务塞进 `cron_queue`，agent 消费并执行。把"触发"与"执行"解耦——独立 daemon 判时间，队列传递，queue processor 在 agent 空闲时拉起一轮 turn。

## 本阶段完成（相对 s13）

在 s13 循环上做了一件核心事：**按时间表自动触发**。

1. **`cron.py`**：
   - **`CronJob`** dataclass（id/cron/prompt/recurring/durable）。
   - **`cron_matches`/`_cron_field_matches`**：5 字段（`*`/`*/N`/`N-M`/`N,M`/`N`）；DOW 换算 `(weekday+1)%7`（Sun=0）；**DOM/DOW OR 语义**（都约束时任一匹配即真）。
   - **`validate_cron`/`_validate_cron_field`**：字段数/界内/step>0/range/非数字校验。
   - **`schedule_job`/`cancel_job`**：注册/删除 + durable 持久化。
   - **`save_durable_jobs`/`load_durable_jobs`**：`.scheduled_tasks.json`，load 时跳过非法 cron。
   - **`_check_and_fire(now)`**（纯函数）：fire 匹配 job，`minute_marker="%Y-%m-%d %H:%M"` 去重（日期感知，防次日跳过），one-shot fire 后删除，recurring 保留。
   - **`cron_scheduler_loop`**（daemon，每秒轮询）+ **`queue_processor_loop`**（agent 空闲 `agent_lock` 可获取时拉起 turn）+ **`agent_lock`**。
   - **`start_scheduler(run_turn)`** 显式启动两个 daemon（**po-agent 改进**：参考在 import 时起线程不可测，po-agent 放 cli 调用）。
   - **3 工具**：run_schedule_cron/run_list_crons/run_cancel_cron。
2. **`agent_loop` 顶部消费 cron 队列**：每轮迭代 `consume_cron_queue()` → 每个 fired job 注入 `{"role":"user","content":"[Scheduled] {prompt}"}`。
3. **cli `run_turn` 闭包 + `start_scheduler` + `agent_lock`**：用户 turn 与 queue_processor 互斥；agent 空闲时 cron 可触发新 turn。
- **保留 s13 全部**（background + tasks + recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent/14 工具）。3 工具进 `TOOL_HANDLERS`+`make_tools`（17）。
- 比 s13 多了**定时自动触发**：到点 agent 自己动，无需人推。

## 结构
- `cron.py` — CronJob + 匹配/校验 + schedule/cancel + 持久化 + _check_and_fire + scheduler/queue processor + agent_lock + 3 run_*
- `agent.py` — `agent_loop`（顶部消费 cron 队列）
- `config.py` — make_tools 加 3 cron 工具（17）
- `tools.py` — TOOL_HANDLERS 加 3 cron handler
- `cli.py` — run_turn 闭包 + start_scheduler + agent_lock
- `background.py` / `tasks.py` / `recovery.py` / `system_prompt.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` — 同 s13

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s14_cron_scheduler
```

## 使用示例

```
s14 >> 用 schedule_cron 安排每分钟任务"检查进度"，然后列出所有 cron 任务
  [assembled] sections: identity, tools, workspace, skills
  [HOOK] schedule_cron(['* * * * *', '检查进度'])
  [cron fire] cron_714647 → 检查进度
  [HOOK] list_crons([])
  ...
```

agent 调 schedule_cron 注册任务，调度线程到点 `[cron fire]`，agent 消费 `[Scheduled]` 消息并执行提示词。重启后 `load_durable_jobs` 恢复 durable 任务。

## 测试
```sh
pytest s14_cron_scheduler/tests -v
```
