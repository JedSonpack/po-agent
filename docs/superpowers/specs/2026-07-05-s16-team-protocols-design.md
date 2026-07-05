# s16 — Team Protocols 设计规格

> 日期：2026-07-05　阶段：s16_team_protocols　参照：`learn-claude-code/s16_team_protocols`
> 状态：⬜ → 🚧 → ✅　前置：s15（agent teams，291 测试）

## 问题

s15 队友能干活了，但协调松散：Lead 发消息、队友回复，无结构化协议。两场景暴露问题：
- **关机**：Lead 想让 Alice 关机。直接杀线程 → Alice 写一半的文件留在磁盘。需握手：Lead 发请求，Alice 收尾后确认关机。
- **计划审批**：Bob 想重构认证模块（高风险）。应先让 Lead 看 Bob 计划，审批后再动手。

两场景结构相同：一方发请求、另一方回复、请求与回复经同一 `request_id` 关联；状态机 pending → approved/rejected。

## 解决方案（教学版）

承接 s15 全部，新增三样核心机制 + 队友 idle loop：

1. **ProtocolState**（`request_id`/`type`/`sender`/`target`/`status`/`payload`/`created_at`）+ `pending_requests` dict + `new_request_id()`。
2. **match_response(response_type, request_id, approve)**——经 `request_id` 关联回复与请求，含**类型校验**（shutdown 状态只接 `shutdown_response`；plan_approval 只接 `plan_approval_response`）+ **幂等**（非 pending 跳过）。
3. **consume_lead_inbox(route_protocol=True)**——统一消费：读 lead 邮箱，`_response` 消息经 `match_response` 路由，返回全部消息。`run_check_inbox` 与 cli wake 都调它，避免消息被读走但协议状态没更新。
4. **队友 idle loop**——LLM 返回非 tool_use 后不退出，轮询 inbox：`shutdown_request` → 回复 `shutdown_response` + 退出；`plan_approval_response` → 注入 `[Plan approved/rejected]`；新消息 → 注入继续。
5. **handle_inbox_message**——按 `msg.type` 分发：`shutdown_request`→回复+返 True（停）；`plan_approval_response`→注入；else False。

两种协议一套机制：shutdown（Lead→队友）+ plan_approval（队友→Lead）。教学版**不实现执行门控**（未 approved 时拦截 bash/write）——只演示消息流程。

## po-agent 架构对齐

复制 s15 整包（sed 改名 `s15_agent_teams` → `s16_team_protocols`），保留 s15 全部（MessageBus + Team + 事件队列 cli + cron + background + ...），叠加协议机制。`agent_loop` 不变。

### `teams.py` 增量

- **`MessageBus.send` 加 `metadata: dict = None` 参数**（msg 含 `"metadata": metadata or {}`）。s15 调用不传 metadata 仍兼容。
- **`ProtocolState`** dataclass + `pending_requests: dict` + `new_request_id()`（`req_{rand:06d}`）。
- **`match_response(response_type, request_id, approve)`**：unknown id→no-op；类型不匹配→no-op；非 pending→no-op（幂等）；否则 `status = approved if approve else rejected`。
- **`consume_lead_inbox(route_protocol=True)`**：`msgs = BUS.read_inbox("lead")`；`route_protocol` 时遍历 msgs，`metadata.request_id` 且 `type.endswith("_response")` → `match_response(type, req_id, approve)`；返回 msgs。
- **Lead 工具**（3 个，进 `TOOL_HANDLERS`）：
  - `run_request_shutdown(teammate)`——new_request_id + ProtocolState(shutdown, pending, sender=lead, target=teammate) + `BUS.send("lead", teammate, "Please shut down gracefully.", "shutdown_request", {request_id})`。
  - `run_request_plan(teammate, task)`——`BUS.send("lead", teammate, f"Please submit a plan for: {task}", "message")`（普通消息，无协议状态）。
  - `run_review_plan(request_id, approve, feedback="")`——查 state；非 pending 报错；设 status + `BUS.send("lead", state.sender, feedback or "Approved"/"Rejected", "plan_approval_response", {request_id, approve})`。
- **`run_check_inbox`** 改用 `consume_lead_inbox(route_protocol=True)`，格式带 `[type] req:id` 标签。
- **`_teammate_submit_plan(from_name, plan)`**——new_request_id + ProtocolState(plan_approval, pending, sender=from_name, target=lead, payload=plan) + `BUS.send(from_name, "lead", plan, "plan_approval_request", {request_id})`。返 `f"Plan submitted ({req_id}). Waiting for approval..."`。
- **`Team` 类演进**：
  - `_make_sub_run_tool(name)` 加 `submit_plan: lambda plan: _teammate_submit_plan(name, plan)`。
  - `_handle_inbox_message(name, msg, messages) -> bool`：`shutdown_request`→`bus.send(name, "lead", "Shutting down gracefully.", "shutdown_response", {request_id, approve:True})` + 返 True；`plan_approval_response`→approve 注入 `[Plan approved] Proceed with the task.` / reject 注入 `[Plan rejected] Feedback: {content}`；else False。
  - `_drain_inbox(name, messages) -> (shutdown: bool, got_msg: bool)`：读 inbox，分离协议消息（dispatch via `_handle_inbox_message`，shutdown 置位）与非协议（拼 `<inbox>` 注入）。
  - `_idle_wait(name, messages) -> str`（`"shutdown"/"message"/"timeout"`）：轮询 `max_idle_polls` 次（`idle_poll_interval` 秒），每次 `_drain_inbox`；shutdown→"shutdown"；got_msg→"message"；耗尽→"timeout"。
  - `_run(name, role, prompt)` 改 idle loop：`while not shutdown and turns < max_turns`：顶上 `_drain_inbox`（shutdown→break）→ LLM turn（异常 break）→ 非 tool_use 则 `_idle_wait`（shutdown→break；timeout→break；message→continue）→ 执行工具。结束发 summary result + pop active_teammates。
  - 新增构造参数 `idle_poll_interval=1.0`、`max_idle_polls=6000`（生产 100min 兜底；测试用 0.01/3）。

### `tools.py` / `config.py` 增量
- `TOOL_HANDLERS` += `request_shutdown`/`request_plan`/`review_plan`（静态）。
- `make_tools()` += 3 协议工具 → **23 工具**（s15 的 20 + 3）。
- `make_team_tools()` += `submit_plan` → **5 工具**。

### `agent.py` —— 不变
协议工具经 `run_tool` 分发；cron/background 不变。

### `cli.py` 增量
保留 s15 事件队列（input_reader + inbox_poller + wake + "all teammates done"）。**wake 路径** `BUS.read_inbox("lead")` → `consume_lead_inbox(route_protocol=True)`（路由协议响应 + 返回 msgs 注入 `[Inbox]`）。Team 构造加 `idle_poll_interval`/`max_idle_polls`（生产默认）。`run_turn`/`agent_lock`/cron 不变。

### 保留 s15 全部
MessageBus（+metadata）+ Team + 事件队列 cli + cron + background + tasks + recovery + system_prompt + hooks/nag/compact/memory/skills/subagent。无机制删减。

## 测试计划（mock 化）

### `tests/test_teams.py`（增量）
- MessageBus.send 带 metadata（read_inbox 返回 msg 含 metadata 键）
- `new_request_id` 格式 `req_XXXXXX`
- `match_response`：unknown id no-op / 类型不匹配 no-op / 非 pending 幂等 / approve→approved / reject→rejected
- `consume_lead_inbox`：路由 `_response` 消息（match_response 被调）/ route_protocol=False 不路由 / 空 inbox 返 []
- `run_request_shutdown`：创建 pending_requests 条目 + 发 shutdown_request（含 request_id）
- `run_request_plan`：发普通 message
- `run_review_plan`：approve/reject 设状态 + 发 plan_approval_response；not found；already resolved
- `_teammate_submit_plan`：创建 plan_approval 状态 + 发 plan_approval_request
- `Team._handle_inbox_message`：shutdown_request→回复+True；plan approve→注入 [Plan approved]；reject→注入 [Plan rejected]；other→False
- `Team._drain_inbox`：协议消息 dispatch + 非协议注入 `<inbox>`；shutdown 置位
- `Team._idle_wait`（短 interval + 小 max_polls）：shutdown→"shutdown"；message→"message"；timeout→"timeout"
- `Team._run`（mock client）：active-turn shutdown；plan_approval 注入；submit_plan；max_turns fallback；idle 收 shutdown 退出（threading + 短 interval）

### `tests/test_config.py`（增量）
- `make_tools()` 23 工具含 request_shutdown/request_plan/review_plan
- `make_team_tools()` 5 工具含 submit_plan

### `tests/test_agent.py`（增量）
- `request_shutdown`/`review_plan` 经 run_tool 分发

## 验收
- 全量 s01–s16 测试通过（s15 291 + s16 新增 ≈ 320+）
- 实时冒烟：spawn alice → 她创建文件后 idle → Lead 调 request_shutdown → alice 回复 shutdown_response → Lead `consume_lead_inbox` 路由 → `pending_requests` 转 approved → `[all teammates done]`

## 风险
- **idle loop 测试**：`time.sleep` + 线程，用 `idle_poll_interval=0.01`/`max_idle_polls=3` 缩短；核心协议逻辑（match_response/consume/handle）纯函数测，idle 仅 1 个 threading 测试
- **max_idle_polls 兜底**：生产 6000（100min）防真无限挂；daemon 线程进程退出即杀
- **glm-5.2 推理模型**：teammate max_tokens=8000（足够 thinking+输出）；submit_plan/review_plan 不涉 LLM
- **metadata 向后兼容**：s15 的 send 调用不传 metadata → 默认 {}，s15 测试（复制到 s16）仍通过
