# s12 Task System 实现计划

**目标：** s12 Task System——文件持久化任务图（blockedBy DAG + claim/complete + 5 工具），行为对齐 `learn-claude-code/s12_task_system`。
**架构：** `s12_task_system` 包，沿用 s11；新增 `tasks.py`；5 工具进 `TOOL_HANDLERS`+`make_tools()`（14）。`agent_loop` 不改（任务工具经 run_tool 自动分发）。保留 s11 全部。
**规格：** `docs/superpowers/specs/2026-07-04-s12-task-system-design.md`（impl 见 §4/§5）

---

## 任务 1：包骨架 + tasks.py（TDD）

- [ ] `s12_task_system/__init__.py`、`tests/__init__.py`
- [ ] **tests/test_tasks.py**（tmp_path + monkeypatch TASKS_DIR/WORKDIR；覆盖规格 §7 全部用例）：create/persist/list/get/can_start(5 例)/claim(4 例)/complete(4 例)/run_list_tasks/run_get_task/DAG 端到端/跨会话持久
- [ ] 实现 `tasks.py`（规格 §4）
- [ ] `.venv/bin/pytest s12_task_system/tests/test_tasks.py -v` → 全通过
- [ ] Commit `feat(s12): 实现 tasks（持久化任务图 + DAG + claim/complete）`

---

## 任务 2：复制 s11 模块（recovery/config/tools/skills/hooks/todo/subagent/compact/memory/system_prompt + agent/cli）

- [ ] 11 模块 + 9 测试从 s11 原样复制（sed `s11_error_recovery/s12_task_system`）
- [ ] `.venv/bin/pytest s12_task_system/tests -q --ignore=s12_task_system/tests/test_tasks.py` → 全通过（agent_loop 不改，原测试全绿）
- [ ] Commit `feat(s12): 复制 s11 模块（同 s11）`

---

## 任务 3：config.py + tools.py 加 5 任务工具（TDD）

- [ ] tools.py：`TOOL_HANDLERS` 加 5（import from tasks）；test_tools.py 加 5 分发测试
- [ ] config.py：`make_tools()` 加 5 任务工具 dict（14）；test_config.py 改 make_tools 14
- [ ] `.venv/bin/pytest s12_task_system/tests/test_tools.py s12_task_system/tests/test_config.py -v` → 全通过
- [ ] Commit `feat(s12): 5 任务工具进 TOOL_HANDLERS + make_tools（14）`

---

## 任务 4：cli.py + __main__.py（s11 原样，banner 改 s12）

- [ ] sed 已在任务 2 完成；改 banner `s12: Task System — persistent task graph`
- [ ] `python -c "from s12_task_system.cli import main; print('ok')"`
- [ ] Commit `feat(s12): REPL 入口 banner`

---

## 任务 5：README + 全测 + 冒烟 + push + PROGRESS

- [ ] README（`## 本阶段完成（相对 s11）`：tasks.py；Task dataclass + .tasks/ 持久化 + blockedBy DAG + can_start/claim/complete + 5 工具；agent_loop 不改；保留 s11 全部）
- [ ] 全测 `pytest s01_*/tests ... s12_task_system/tests -v` → 全通过
- [ ] 冒烟 `echo '创建任务 schema、endpoints（依赖 schema），claim schema，complete schema，看 endpoints 是否解锁' | python -m s12_task_system`
- [ ] Commit README + 更新 PROGRESS（s12 ✅ + 详情节）
- [ ] `git push origin main`

---

## 自检
**规格覆盖度：** §4 tasks → 任务 1 ✓；§5 tools/config → 任务 3 ✓；§8 验收 → 任务 5 ✓。**类型一致：** `Task(id,subject,description,status,owner,blockedBy)` 一致；`claim_task(task_id, owner="agent")` 一致；5 工具 schema/handler 名一致。✓
