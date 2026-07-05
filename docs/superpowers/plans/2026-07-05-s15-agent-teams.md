# s15 — Agent Teams 实现计划

> 规格：[`2026-07-05-s15-agent-teams-design.md`](../specs/2026-07-05-s15-agent-teams-design.md)
> 节奏：每任务一 commit（`feat(s15)`/`fix(s15)`/`docs(s15)`/`chore(s15)`），阶段末 push origin/main

## 任务清单

### T1 — 包骨架：复制 s14 → s15 改名
- [x] `cp -r s14_cron_scheduler s15_agent_teams`，全量 sed 改名 `s14_cron_scheduler` → `s15_agent_teams`（含 import / docstring / 字符串 / 测试）
- [x] 删 `s15_agent_teams/__pycache__`、`s15_agent_teams/tests/__pycache__`
- [x] 跑 `pytest s15_agent_teams/tests -q` 确认改名后全绿（应 = 263，与 s14 一致）
- commit `chore(s15): 复制 s14 包并改名`

### T2 — `background.py`：加 `has_pending_background`
- [x] 先写失败测试 `test_background.py::test_has_pending_background_*`（running→False / completed→True / 收集后→False）
- [x] 实现 `has_pending_background()`
- commit `feat(s15): background has_pending_background 非消费式检查`

### T3 — `teams.py`：MessageBus + lead handler + Team 类
- [x] 先写 `test_teams.py`：MessageBus（send/read/peek/消费/隔离/tmp_path）、`run_send_message`/`run_check_inbox`（monkeypatch BUS）
- [x] 实现 `MessageBus` + `BUS` + `active_teammates` + `run_send_message`/`run_check_inbox`
- commit `feat(s15): MessageBus + lead send/check_inbox handler`
- [x] 写 `test_teams.py::Team` 测试：spawn 去重/注册、`_run` mock client（max 轮/inbox 注入/sliding window/summary 提取/发 result/pop active/send_message from=name/PreToolUse 阻塞）
- [x] 实现 `Team` 类（spawn + _run + _make_sub_run_tool）
- commit `feat(s15): Team 类——队友 daemon 线程 + inbox 注入`

### T4 — `tools.py` + `config.py`：接线团队工具
- [x] `tools.py`：`TOOL_HANDLERS` += send_message/check_inbox；新增 `TEAM_HANDLERS`
- [x] `config.py`：`make_tools()` += 3 团队工具（20）；`make_team_tools()` 4 工具
- [x] `test_config.py` 增量：20 工具 / team_tools 4 / bash 无 run_in_background
- commit `feat(s15): tools/config 接线 3 团队工具 + team_tools`

### T5 — `agent.py` + `test_agent.py`：spawn_teammate 经 run_tool 分发
- [x] agent_loop 不变；`test_agent.py` 增 `test_spawn_teammate_dispatches_via_run_tool`（验证 extra 接线，类比 task）
- commit `test(s15): spawn_teammate 经 run_tool 分发`

### T6 — `cli.py`：事件队列 + inbox_poller + wake 注入
- [x] 重构 cli：events queue + input_reader + inbox_poller（peek + has_pending_background）+ 主循环（user/wake/quit）+ run_turn(query=None, inject=None) + "all teammates done" 公告
- [x] 接线 `team = Team(bus=BUS, base_handlers=TEAM_HANDLERS, sub_tools=cfg["team_tools"], ...)` + `make_run_tool(TOOL_HANDLERS, {"task": subagent.run, "spawn_teammate": team.spawn})`
- commit `feat(s15): cli 事件队列 + inbox wake 注入`

### T7 — README + 全测 + 冒烟 + PROGRESS
- [x] `README.md` 带 `## 本阶段完成（相对 s14）`（~200 字）
- [x] `pytest s01_* s02_* ... s15_agent_teams/tests -q` 全绿
- [x] 冒烟 `echo '...' | python -m s15_agent_teams`
- [x] 更新 `PROGRESS.md`（s15 行 ⬜→✅ + 详情节）
- commit `docs(s15): README + PROGRESS`；`git push origin/main`

## 关键代码骨架

### teams.py — Team._run
```python
def _run(self, name, role, prompt):
    system = (f"You are '{name}', a {role}. Use tools to complete tasks. "
              f"Send results via send_message to 'lead'.")
    messages = [{"role": "user", "content": prompt}]
    sub_run_tool = self._make_sub_run_tool(name)
    for _ in range(self.max_turns):
        inbox = self.bus.read_inbox(name)
        if inbox:
            messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox)}</inbox>"})
        try:
            response = self.client.messages.create(
                model=self.model, system=system, messages=messages[-20:],
                tools=self.sub_tools, max_tokens=self.max_tokens)
        except Exception:
            break
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
        results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            blocked = self.trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(blocked)})
                continue
            output = sub_run_tool(block.name, block.input)
            self.trigger("PostToolUse", block, output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})
    summary = _extract_last_text(messages) or "Done."
    self.bus.send(name, "lead", summary, "result")
    active_teammates.pop(name, None)
```

### cli.py — 事件队列主循环
```python
events = queue.Queue()
def input_reader():
    while True:
        try: line = input("\033[36ms15 >> \033[0m")
        except (EOFError, KeyboardInterrupt): events.put(("quit", None)); return
        events.put(("user", line))
def inbox_poller():
    while True:
        time.sleep(1)
        if BUS.peek("lead") or has_pending_background():
            events.put(("wake", None))
threading.Thread(target=input_reader, daemon=True).start()
threading.Thread(target=inbox_poller, daemon=True).start()
start_scheduler(run_turn)  # cron queue_processor 调 run_turn() 消费 cron 队列
had_teammates = False
while True:
    kind, payload = events.get()
    if kind == "quit": break
    if kind == "user":
        if payload.strip().lower() in ("q", "exit", ""): break
        with agent_lock: run_turn(query=payload)
    else:  # wake
        parts, inbox = [], BUS.read_inbox("lead")
        if inbox: parts.append("[Inbox]\n" + "\n".join(f"From {m['from']}: {m['content'][:200]}" for m in inbox))
        parts.extend(collect_background_results())
        if not parts: continue
        with agent_lock: run_turn(inject="\n".join(parts))
    # all-teammates-done 公告
    ...
```
