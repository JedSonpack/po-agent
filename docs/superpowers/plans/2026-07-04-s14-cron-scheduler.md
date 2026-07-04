# s14 Cron Scheduler 实现计划

**目标：** s14 Cron Scheduler——cron 表达式调度（daemon 线程 fire → cron_queue → agent 消费注入 `[Scheduled]`），行为对齐 `learn-claude-code/s14_cron_scheduler`。
**架构：** `s14_cron_scheduler` 包，沿用 s13；新增 `cron.py`；3 工具进 `TOOL_HANDLERS`+`make_tools`（17）；`agent_loop` 顶部消费队列；cli `run_turn`+`start_scheduler`+`agent_lock`。线程显式启动。保留 s13 全部。
**规格：** `docs/superpowers/specs/2026-07-04-s14-cron-scheduler-design.md`（impl 见 §4/§5/§6）

---

## 任务 1：包骨架 + cron.py（TDD）

- [ ] `s14_cron_scheduler/__init__.py`、`tests/__init__.py`
- [ ] **tests/test_cron.py**（规格 §7；reset fixture 清 scheduled_jobs/cron_queue/_last_fired；tmp_path monkeypatch DURABLE_PATH）
- [ ] 实现 `cron.py`（规格 §4）
- [ ] `.venv/bin/pytest s14_cron_scheduler/tests/test_cron.py -v` → 全通过
- [ ] Commit `feat(s14): 实现 cron（匹配/校验/调度/持久化 + 3 工具）`

## 任务 2：复制 s13 模块（background/tasks/recovery/config/tools/skills/hooks/todo/subagent/compact/memory/system_prompt/agent/cli + __main__）

- [ ] 13 模块 + 12 测试从 s13 原样复制（sed `s13_background_tasks/s14_cron_scheduler`）
- [ ] `.venv/bin/pytest s14_cron_scheduler/tests -q --ignore=s14_cron_scheduler/tests/test_cron.py` → 全通过
- [ ] Commit `feat(s14): 复制 s13 模块（同 s13）`

## 任务 3：config.py + tools.py 加 3 cron 工具

- [ ] config.py make_tools 加 3 cron 工具（17）；test_config 改 17
- [ ] tools.py TOOL_HANDLERS 加 3（import from cron）；test_tools 加 3 分发测试
- [ ] `.venv/bin/pytest s14_cron_scheduler/tests/test_config.py s14_cron_scheduler/tests/test_tools.py -v` → 全通过
- [ ] Commit `feat(s14): 3 cron 工具进 TOOL_HANDLERS + make_tools（17）`

## 任务 4：agent.py（顶部消费 cron 队列，TDD）

- [ ] test_agent.py：s13 sed 复制；加 cron 注入测试（预填 cron_queue → `[Scheduled]` user 消息）
- [ ] 实现 agent.py（规格 §5）
- [ ] `.venv/bin/pytest s14_cron_scheduler/tests/test_agent.py -v` → 全通过
- [ ] Commit `feat(s14): agent_loop 顶部消费 cron 队列`

## 任务 5：cli.py（run_turn + start_scheduler + agent_lock）

- [ ] cli.py（规格 §6）：run_turn 闭包 + start_scheduler + `with agent_lock`
- [ ] `python -c "from s14_cron_scheduler.cli import main; print('ok')"`
- [ ] Commit `feat(s14): REPL 接线 start_scheduler + agent_lock`

## 任务 6：README + 全测 + 冒烟 + push + PROGRESS

- [ ] README（`## 本阶段完成（相对 s13）`：cron.py；CronJob + 匹配（DOM/DOW OR）/校验 + schedule/cancel + 持久化 + _check_and_fire + scheduler/queue processor + agent_lock；3 工具；agent_loop 顶部消费；cli run_turn+start_scheduler；线程显式启动；保留 s13 全部）
- [ ] 全测 `pytest s01_*/tests ... s14_cron_scheduler/tests -v` → 全通过
- [ ] 冒烟 `echo '用 schedule_cron 安排每分钟任务"检查进度"，然后列出所有 cron 任务' | python -m s14_cron_scheduler`
- [ ] Commit README + PROGRESS（s14 ✅ + 详情节）
- [ ] `git push origin main`

---

## 自检
**规格覆盖度：** §4 cron → 任务 1 ✓；§5 agent → 任务 4 ✓；§6 config/tools/cli → 任务 3/5 ✓；§8 验收 → 任务 6 ✓。**类型一致：** `schedule_job(cron, prompt, recurring=True, durable=True) -> CronJob|str` 一致；`_check_and_fire(now)` 纯函数；`start_scheduler(run_turn)` cli 调用；`agent_loop` 顶部 `consume_cron_queue`。✓
