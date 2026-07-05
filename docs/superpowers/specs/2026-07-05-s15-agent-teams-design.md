# s15 — Agent Teams 设计规格

> 日期：2026-07-05　阶段：s15_agent_teams　参照：`learn-claude-code/s15_agent_teams`
> 状态：⬜ → 🚧 → ✅　前置：s14（cron 调度，263 测试）

## 问题

"重构整个后端"涉及认证、数据库、API、测试多个模块。单个 agent 的上下文覆盖不了所有模块——修 API 时认证细节已不在上下文里。s06 的子 agent 是**临时工**（叫来干一件事就走，只回总结，不能通信）；有些任务需要能**多轮通信、协作**的队友。

## 解决方案（教学版）

沿用 s14 全部能力，新增三样：

1. **MessageBus**——文件收件箱（`.mailboxes/{agent}.jsonl`）。发消息 = 往对方文件 append 一行 JSON；读消息 = 读文件 + 删除（**消费式**）。
2. **Teammate 线程**——`spawn_teammate` 启动一个 daemon 线程，跑自己的简化循环（4 工具：bash/read_file/write_file/send_message），最多 10 轮，每轮顶上注入 `<inbox>`，完成后发 summary 给 lead。
3. **Lead inbox 注入**——cli 事件队列：input_reader + inbox_poller（peek 非消费式检查），队友消息/后台完成时 wake 一轮 turn，把 `[Inbox]` 注入 history。

子 agent（s06）vs 队友（s15）：

| | s06 子 agent | s15 队友 |
|---|---|---|
| 生命周期 | 一次性，同步返回 | 多轮（限 10 轮），daemon 线程异步 |
| 通信 | 只回传结论 | 文件收件箱，随时通信 |
| 上下文 | 完全隔离 | 通过消息共享 |
| 工具 | 5（bash/read/write/edit/glob） | 4（bash/read/write/send_message） |
| 递归 | 无 task 工具防递归 | 无 spawn_teammate 防组队递归 |

## po-agent 架构对齐

参考 s15 用模块全局 + `agent_loop(messages, context)`。po-agent **不跟随简化**：复制 s14 整包（sed 改名 `s14_cron_scheduler` → `s15_agent_teams`），保留 s14 全部机制（hooks/权限 + TodoNag + Compactor + Subagent + skills + Memory + system_prompt 组装 + recovery + tasks + background + cron），叠加团队机制。DI 演进：`agent_loop` 签名不变。

### 新模块 `teams.py`

**MessageBus**（DI：`mailbox_dir` 可注入，默认 `WORKDIR / ".mailboxes"`）：

```python
class MessageBus:
    def __init__(self, mailbox_dir=None):
        self.dir = Path(mailbox_dir) if mailbox_dir else WORKDIR / ".mailboxes"
        self.dir.mkdir(parents=True, exist_ok=True)
    def send(self, from_agent, to_agent, content, msg_type="message"):
        msg = {"from": from_agent, "to": to_agent, "content": content, "type": msg_type, "ts": time.time()}
        with open(self.dir / f"{to_agent}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
    def read_inbox(self, agent) -> list[dict]:   # 消费式：read + unlink
        inbox = self.dir / f"{agent}.jsonl"
        if not inbox.exists(): return []
        msgs = [json.loads(l) for l in inbox.read_text().splitlines() if l.strip()]
        inbox.unlink()
        return msgs
    def peek(self, agent) -> bool:               # 非消费式：有未读返 True
        inbox = self.dir / f"{agent}.jsonl"
        return inbox.exists() and inbox.stat().st_size > 0
```

模块级 `BUS = MessageBus()`、`active_teammates: dict[str, bool] = {}`。

**Team 类**（DI：client/model/bus/base_handlers/sub_tools/trigger/max_turns=10/max_tokens=8000）—— 类比 `Subagent`，但异步 daemon + inbox 注入：

- `spawn(name, role, prompt) -> str`：去重（`name in active_teammates` → 返回已存在）；注册 `active_teammates[name]=True`；起 daemon 线程跑 `_run`；立即返回 `f"Teammate '{name}' spawned as {role}"`。
- `_run(name, role, prompt)`：
  - `system = f"You are '{name}', a {role}. Use tools to complete tasks. Send results via send_message to 'lead'."`
  - `messages = [{"role":"user","content":prompt}]`
  - 每轮顶上 `inbox = self.bus.read_inbox(name)` → 非空则 append `{"role":"user","content":f"<inbox>{json.dumps(inbox)}</inbox>"}`
  - LLM 调用包 try/except（异常 break，与参考一致）；`messages[-20:]` 滑动窗口
  - dispatch thinking 跳过；`stop_reason != "tool_use"` break
  - 工具执行走 PreToolUse/PostToolUse hooks（与 Subagent 一致）；send_message 的 `from` = teammate name
  - 完成后：倒序找 assistant text block 作 summary（fallback `"Done."`）→ `bus.send(name, "lead", summary, "result")` → `active_teammates.pop(name, None)`
- `_make_sub_run_tool(name)`：`base_handlers` + `send_message: lambda to, content: (bus.send(name, to, content), "Sent")[1]`，复用 `make_run_tool`。

**Lead 工具 handler**（3 个）：
- `run_send_message(to, content)`：`BUS.send("lead", to, content)` → `f"Sent to {to}"`（用模块 BUS，from 固定 "lead"）
- `run_check_inbox()`：消费 `BUS.read_inbox("lead")`，空 → `"(inbox empty)"`；非空 → 每条 `[from] content[:200]`
- spawn_teammate → `team.spawn`（绑定方法，经 `make_run_tool` 的 `extra` 接线，类比 `task` → `subagent.run`）

### `background.py` 增量

新增 `has_pending_background() -> bool`（非消费式：有 completed 未收集返 True）——inbox_poller wake 条件用。与参考 s15 一致。

### `tools.py` 增量

- `TOOL_HANDLERS` += `{"send_message": run_send_message, "check_inbox": run_check_inbox}`（静态 handler）
- 新增 `TEAM_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write}`（队友 base handlers，无 edit/glob/send_message——send_message 由 Team 按名绑定）
- spawn_teammate 不进 `TOOL_HANDLERS`（需 Team 实例），cli 经 `make_run_tool(TOOL_HANDLERS, {"task": subagent.run, "spawn_teammate": team.spawn})` 接线

### `config.py` 增量

- `make_tools()` += 3 团队工具（spawn_teammate/send_message/check_inbox）→ **20 工具**（s14 的 17 + 3）
- 新增 `make_team_tools()`：4 工具（bash[仅 command]/read_file/write_file/send_message）——队友工具集，bash 无 run_in_background（与参考一致，队友不派后台）

### `agent.py` —— **不变**

agent_loop 签名与逻辑同 s14。团队工具经 `run_tool` 自动分发；cron 队列消费、background 收集均不变。inbox 注入在 cli 层（turn 前），不在 agent_loop。

### `cli.py` 重构为事件队列（po-agent 改进）

保留 s14 的 `start_scheduler(run_turn)` + `agent_lock`（cron 机制不变）。新增事件队列：

- `events = queue.Queue()`
- `input_reader` daemon：stdin → `("user", line)` / `("quit", None)`
- `inbox_poller` daemon（1s）：`BUS.peek("lead") or has_pending_background()` → `("wake", None)`
- 主循环 `events.get()`：
  - `quit` → break
  - `user` → q/exit/空 break；否则 `with agent_lock: run_turn(query=line)`
  - `wake` → drain `BUS.read_inbox("lead")` + `collect_background_results()`；空则 continue（幂等，已被先前 wake 排干）；非空拼 `[Inbox]\nFrom X: ...` + 通知，`with agent_lock: run_turn(inject=...)`
- `run_turn(query=None, inject=None)`：持锁；query → UserPromptSubmit hook + append user；inject → append user（[Inbox]/[Scheduled]）；调 agent_loop；打印末尾 text。`start_scheduler(run_turn)` 传给 cron queue_processor（无参调用 → 纯 agent_loop 消费 cron 队列，与 s14 一致）
- "all teammates done" 公告：`active_teammates` 非空时记 `had_teammates=True`；空且 had_teammates 且无 inbox/无 pending bg → 打印 `[all teammates done]`，重置

**锁模型**：main 线程与 cron queue_processor 都调 `run_turn`，经 `agent_lock` 串行。`run_turn` 内部 `with agent_lock`（与 s14 main 的 `with agent_lock: run_turn` 等价；queue_processor 已 `acquire(blocking=False)` 后调 `run_turn()`——**注意**：为避免不可重入死锁，`run_turn` 不再自带锁，由调用方持锁。即 main 用 `with agent_lock: run_turn(...)`，queue_processor 维持 s14 的 `acquire/blocking` 模式调 `run_turn()`）。

> 决策：`run_turn` 不持锁（与 s14 一致），调用方持锁。main 线程 `with agent_lock: run_turn(...)`；cron `queue_processor_loop` 沿用 s14 `agent_lock.acquire(blocking=False)` + `run_turn()`。

### 保留 s14 全部

hooks/权限 + TodoNag + Compactor + Subagent + skills + Memory + system_prompt + recovery + tasks + background + cron。无机制删减。

## 测试计划（mock 化，不发真实 API）

### `tests/test_teams.py`（新）
- MessageBus：send→read_inbox 消费性（读后 unlink）、peek 非消费、空 inbox、跨 agent 隔离、`tmp_path` 隔离
- `run_send_message`：from=lead，写对方邮箱（monkeypatch `teams.BUS` 用 tmp bus）
- `run_check_inbox`：空/格式/消费/截断 200
- `Team.spawn`：去重（同名返已存在）、注册 active_teammates、返回格式
- `Team._run`（mock client）：max 10 轮/inbox 注入/sliding window `[-20:]`/summary 提取（倒序 assistant text）/完成发 result 给 lead + pop active_teammates；send_message from=teammate name；PreToolUse 阻塞跳过
- wake 注入格式 + 幂等（空 drain continue）

### `tests/test_background.py`（增量）
- `has_pending_background`：running→False、completed→True、收集后→False

### `tests/test_config.py`（增量）
- `make_tools()` 20 工具含 spawn_teammate/send_message/check_inbox
- `make_team_tools()` 4 工具，bash 无 run_in_background

### `tests/test_agent.py`（增量）
- `spawn_teammate` 经 run_tool 分发（类比 `test_task_dispatches_via_run_tool`）—— 验证 extra 接线

## 验收
- 全量 s01–s15 测试通过（s14 263 + s15 新增 ≈ 285+）
- 实时冒烟：`echo 'Spawn alice as a backend developer. Ask her to create schema.sql with a users table.' | python -m s15_agent_teams`——Lead 调 spawn_teammate，alice 线程跑 bash/write_file，完成发 result，Lead wake 注入 `[Inbox]`

## 风险
- **daemon 线程测试**：聚焦纯函数（MessageBus）+ mock client 的 `Team._run`（同步跑 `_run` 而非 `spawn`，验证循环体）；`spawn` 的线程行为用 Event 等待验证注册/完成
- **read+unlink 竞态**：教学版已知（多线程同读可能丢消息），po-agent 用 `BUS` 单 lead 消费者 + 队友各消费自己邮箱，竞态窗口小；标注不修（与参考一致）
- **glm-5.2 推理模型**：teammate 的 LLM 调用 `max_tokens=8000`（足够 thinking + 输出）；冒烟确认 teammate 能产出 text summary
- **cli 事件队列与 cron 协同**：cron queue_processor 调 `run_turn()`（无参）走 agent_loop 消费 cron 队列；main 线程 user/wake 走 `run_turn(query=)/(inject=)`。`agent_lock` 串行两者。冒烟确认 cron fire 与队友 wake 不互锁
