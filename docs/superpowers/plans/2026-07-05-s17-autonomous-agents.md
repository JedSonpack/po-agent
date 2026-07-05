# s17 — Autonomous Agents 实现计划

> 规格：[`2026-07-05-s17-autonomous-agents-design.md`](../specs/2026-07-05-s17-autonomous-agents-design.md)

## 任务
- T1 复制 s16→s17 改名（sed + 用户面字符串 + docstring）；291... 即 s16 的 324 测试全绿 → commit `chore(s17)`
- T2 `tasks.py`：claim owner 检查 + scan_unclaimed_tasks（先失败测试）→ commit `feat(s17): scan_unclaimed_tasks + claim owner 检查`
- T3 `teams.py`：idle_poll + _run WORK→IDLE + 身份重注入 + _make_sub_run_tool 加 3 工具（先失败测试，更新 s16 idle 测试）→ commit `feat(s17): idle_poll + WORK→IDLE→SHUTDOWN 生命周期`
- T4 `tools.py`+`config.py`：TEAM_HANDLERS +3 / make_team_tools 8 → commit `feat(s17): 队友 +3 任务工具（8）`
- T5 README + 全测 + 冒烟 + PROGRESS → commit `docs(s17)`
