# s16: Team Protocols

po-agent 第十六阶段，参照 `learn-claude-code/s16_team_protocols`。给队友加**协议**：结构化请求-响应握手。Lead 调 `request_shutdown` 发关机请求，队友 idle 等待收到后回复 `shutdown_response` 确认，经 `request_id` 关联、`match_response` 路由。把 s15 的松散消息升级成 pending → approved/rejected 状态机。

## 本阶段完成（相对 s15）

在 s15 循环上做了一件核心事：**结构化请求-响应协议**。

1. **`teams.py` 协议状态机**：
   - **`ProtocolState`** dataclass（request_id/type/sender/target/status/payload/created_at）+ `pending_requests` dict + `new_request_id()`。
   - **`match_response(response_type, request_id, approve)`**：经 `request_id` 关联回复与请求，**类型校验**（shutdown 只接 `shutdown_response`，plan_approval 只接 `plan_approval_response`）+ **幂等**（非 pending 跳过）。
   - **`consume_lead_inbox(route_protocol=True)`**：统一消费 lead 邮箱——`_response` 消息经 `match_response` 路由，返全部消息。`run_check_inbox` 与 cli wake 都调它，避免消息被读走但协议状态没更新。
   - **3 lead 协议工具**：`run_request_shutdown`（创建 pending 状态 + 发 shutdown_request）/`run_request_plan`（发普通消息请队友提计划）/`run_review_plan`（设状态 + 发 plan_approval_response）。
   - **`_teammate_submit_plan`**（`bus` 可注入）：队友提计划——创建 plan_approval 状态 + 发 plan_approval_request。
   - **`MessageBus.send` 加 `metadata` 参数**（msg 含 `metadata` 键，向后兼容）。
2. **`Team` 类 idle loop + dispatch**：
   - **`_handle_inbox_message`**：`shutdown_request`→回复 `shutdown_response`+返 True（停）；`plan_approval_response`→注入 `[Plan approved/rejected]`；else False。
   - **`_drain_inbox`**：分离协议消息（dispatch）与非协议（拼 `<inbox>` 注入），返 `(shutdown, got_msg)`。
   - **`_idle_wait`**：LLM 非 tool_use 后轮询 inbox——`shutdown`/`message`/`timeout` 三态。`idle_poll_interval`/`max_idle_polls` 可注入（生产 1s/6000=100min 兜底；测试 0.01s/2）。
   - **`_run` 改 idle loop**：`while not shutdown and turns < max_turns`——turn 顶上 drain（shutdown→break）→ LLM turn → 非 tool_use 则 idle（shutdown/timeout→break，message→continue）→ 执行工具。队友 5 工具（+submit_plan）。
3. **`cli.py` wake 路径**：`BUS.read_inbox("lead")` → `consume_lead_inbox(route_protocol=True)`（路由协议响应 + 返 msgs 注入 `[Inbox]`）。事件队列/inbox_poller/agent_lock/cron 不变。
- **保留 s15 全部**（MessageBus+Team+事件队列 cli+cron+background+tasks+recovery+system_prompt+hooks/nag/compact/memory/skills/subagent）。3 协议工具进 `TOOL_HANDLERS`+`make_tools`（23）；`make_team_tools` 加 submit_plan（5）。`agent_loop` 不变。
- 比 s15 多了**协议握手**：关机/计划审批有 request_id 追溯 + 状态机；队友 idle 等待而非 max_turns 退出，能收 shutdown。

## 结构
- `teams.py` — 协议状态机 + MessageBus(+metadata) + Team(idle loop+dispatch) + 3 lead 协议工具 + _teammate_submit_plan
- `agent.py` — `agent_loop`（不变；协议工具经 run_tool 分发）
- `tools.py` — TOOL_HANDLERS 加 3 协议工具
- `config.py` — make_tools 加 3 协议工具（23）+ make_team_tools 加 submit_plan（5）
- `cli.py` — wake 路径用 consume_lead_inbox
- 其余模块同 s15

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s16_team_protocols
```

## 使用示例

```
s16 >> Spawn alice as a backend dev. Ask her to create config.txt.
  [teammate] alice spawned as backend dev
  [bus] alice → lead: (result) Created config.txt      ← alice 干完活 idle
s16 >> Now request alice to shut down.
  [protocol] shutdown_request → alice (req_004281)
  [protocol] alice approved shutdown (req_004281)      ← alice idle 收到 → 回复
  [protocol] shutdown ✓ (req_004281: approved)         ← consume_lead_inbox 路由 → 状态 approved
  [wake: 1 inbox + 0 background → new turn]
  Alice has shut down gracefully.
```

Lead 调 request_shutdown 发握手请求；alice idle 轮询收到 → 回 shutdown_response；Lead `consume_lead_inbox` 经 `request_id` 路由 → `pending_requests` 转 approved → `[Inbox]` 注入起 turn。关机握手完整：请求 → 确认 → 关机。

## 测试
```sh
pytest s16_team_protocols/tests -v
```
