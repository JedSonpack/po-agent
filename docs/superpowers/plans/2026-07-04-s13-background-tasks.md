# s13 Background Tasks 实现计划

**目标：** s13 Background Tasks——慢操作 daemon 线程异步执行 + `<task_notification>` 注入，行为对齐 `learn-claude-code/s13_background_tasks`。
**架构：** `s13_background_tasks` 包，沿用 s12；新增 `background.py`；bash schema 加 `run_in_background`；`agent_loop` 加后台派发+通知注入。保留 s12 全部。
**规格：** `docs/superpowers/specs/2026-07-04-s13-background-tasks-design.md`（impl 见 §4/§5）

---

## 任务 1：包骨架 + background.py（TDD）

- [ ] `s13_background_tasks/__init__.py`、`tests/__init__.py`
- [ ] **tests/test_background.py**（规格 §7；reset 模块状态 fixture 清 _bg_counter/dicts）
- [ ] 实现 `background.py`（规格 §4）
- [ ] `.venv/bin/pytest s13_background_tasks/tests/test_background.py -v` → 全通过
- [ ] Commit `feat(s13): 实现 background（慢操作后台派发+通知收集）`

## 任务 2：复制 s12 模块（tasks/recovery/config/tools/skills/hooks/todo/subagent/compact/memory/system_prompt/agent/cli + __main__）

- [ ] 12 模块 + 11 测试从 s12 原样复制（sed `s12_task_system/s13_background_tasks`）
- [ ] `.venv/bin/pytest s13_background_tasks/tests -q --ignore=s13_background_tasks/tests/test_background.py` → 全通过
- [ ] Commit `feat(s13): 复制 s12 模块（同 s12）`

## 任务 3：config.py（bash schema）+ tools.py（run_bash 参数）

- [ ] config.py bash schema 加 `run_in_background: boolean`；test_config 断言
- [ ] tools.py `run_bash(command, run_in_background=False)`；test_tools 加参数忽略测试
- [ ] `.venv/bin/pytest s13_background_tasks/tests/test_config.py s13_background_tasks/tests/test_tools.py -v` → 全通过
- [ ] Commit `feat(s13): bash schema 加 run_in_background`

## 任务 4：agent.py（后台派发+通知注入，TDD）

- [ ] **tests/test_agent.py**：s12 sed 复制；加 4 个后台测试（规格 §7）
- [ ] 实现 `agent.py`（规格 §5）
- [ ] `.venv/bin/pytest s13_background_tasks/tests/test_agent.py -v` → 全通过
- [ ] Commit `feat(s13): agent_loop 后台派发+通知注入`

## 任务 5：cli banner + README + 全测 + 冒烟 + push + PROGRESS

- [ ] cli banner `s13: Background Tasks — async slow ops`；`__main__` 已 sed
- [ ] README（`## 本阶段完成（相对 s12）`：background.py；is_slow_operation/should_run_background/start_background_task/collect_background_results；bash run_in_background；agent_loop 后台派发+通知注入；保留 s12 全部）
- [ ] 全测 `pytest s01_*/tests ... s13_background_tasks/tests -v` → 全通过
- [ ] 冒烟 `echo '后台运行 sleep 2 && echo done，同时 glob 列出 *.md' | python -m s13_background_tasks`
- [ ] Commit README + PROGRESS（s13 ✅ + 详情节）
- [ ] `git push origin main`

---

## 自检
**规格覆盖度：** §4 background → 任务 1 ✓；§5 agent → 任务 4 ✓；§6 tools/config → 任务 3 ✓；§8 验收 → 任务 5 ✓。**类型一致：** `start_background_task(block, run_tool) -> str` 一致；`should_run_background(tool_name, tool_input)` 一致；agent_loop 后台分支在 PreToolUse 后、同步前。✓
