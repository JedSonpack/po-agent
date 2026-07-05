# s16 — Team Protocols 实现计划

> 规格：[`2026-07-05-s16-team-protocols-design.md`](../specs/2026-07-05-s16-team-protocols-design.md)
> 节奏：每任务一 commit；阶段末 push（注：push 受策略拦截，见末尾）

## 任务清单

### T1 — 包骨架：复制 s15 → s16 改名
- [ ] `cp -r s15_agent_teams s16_team_protocols`，sed 改名 `s15_agent_teams` → `s16_team_protocols`（含 import/docstring/字符串）；清 __pycache__
- [ ] 用户面字符串 `s15 >>`→`s16 >>`、`s15: Agent Teams`→`s16: Team Protocols`；模块顶 docstring 更新
- [ ] `pytest s16_team_protocols/tests -q` 全绿（= 291，与 s15 一致）
- commit `chore(s16): 复制 s15 包并改名 + 设计规格/计划`

### T2 — `teams.py`：协议状态机 + consume_lead_inbox + lead 工具
- [ ] 先写 `test_teams.py` 增量：MessageBus metadata、new_request_id、match_response（5 case）、consume_lead_inbox（3 case）、run_request_shutdown/request_plan/review_plan、_teammate_submit_plan
- [ ] 实现：`MessageBus.send` 加 metadata；`ProtocolState`+`pending_requests`+`new_request_id`+`match_response`；`consume_lead_inbox`；3 lead 工具 + `_teammate_submit_plan`；`run_check_inbox` 改用 consume_lead_inbox
- commit `feat(s16): ProtocolState + match_response + consume_lead_inbox + 3 lead 协议工具`

### T3 — `Team` 类：idle loop + dispatch
- [ ] 先写 `test_teams.py` 增量：`_handle_inbox_message`（4 case）、`_drain_inbox`、`_idle_wait`（3 case 短 interval）、`_run`（active-turn shutdown / plan 注入 / submit_plan / max_turns / idle shutdown threading）
- [ ] 实现：`_make_sub_run_tool` 加 submit_plan；`_handle_inbox_message`；`_drain_inbox`；`_idle_wait`；`_run` idle loop；构造参数 `idle_poll_interval`/`max_idle_polls`
- commit `feat(s16): Team idle loop + inbox dispatch（shutdown/plan_approval）`

### T4 — `tools.py` + `config.py`：接线协议工具
- [ ] `tools.py`：`TOOL_HANDLERS` += request_shutdown/request_plan/review_plan
- [ ] `config.py`：`make_tools()` += 3（23）；`make_team_tools()` += submit_plan（5）
- [ ] `test_config.py` 增量：23 工具 / team_tools 5
- commit `feat(s16): tools/config 接线 3 协议工具 + submit_plan`

### T5 — `agent.py` + `test_agent.py`：协议工具经 run_tool 分发
- [ ] `test_agent.py` 增 `test_request_shutdown_dispatches_via_run_tool` / `test_review_plan_dispatches_via_run_tool`
- commit `test(s16): 协议工具经 run_tool 分发`

### T6 — `cli.py`：wake 路径用 consume_lead_inbox
- [ ] cli wake 路径 `BUS.read_inbox("lead")` → `consume_lead_inbox(route_protocol=True)`；Team 构造加 idle 参数
- commit `feat(s16): cli wake 路径用 consume_lead_inbox 路由协议响应`

### T7 — README + 全测 + 冒烟 + PROGRESS
- [ ] README `## 本阶段完成（相对 s15）`；`pytest s01..s16 -q` 全绿；冒烟（spawn→idle→request_shutdown→握手）；PROGRESS s16 行+详情
- commit `docs(s16): README + PROGRESS`；push（若策略允许）

## push 策略说明
s15 末 `git push origin main` 被安全策略拦截（"push to default branch"）。s16 末同样会受阻。方案：本地 commit 全部完成；push 由用户决定（用户可 `! git push origin main` 或加 Bash 权限规则）。本阶段不绕过策略。
