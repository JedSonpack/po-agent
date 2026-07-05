# s18 — Worktree Isolation 实现计划

> 规格：[`2026-07-05-s18-worktree-isolation-design.md`](../specs/2026-07-05-s18-worktree-isolation-design.md)

## 任务
- T1 复制 s17→s18 改名；334 测试全绿 → commit `chore(s18)`
- T2 `tasks.py`：Task 加 worktree 字段（先失败测试）→ commit `feat(s18): Task.worktree 字段`
- T3 `worktrees.py`：validate/run_git/log_event/create/bind/_count/remove/keep + 3 lead handler（先失败测试，monkeypatch run_git）→ commit `feat(s18): worktrees.py + 3 lead 工具`
- T4 `tools.py`：safe_path/run_bash/run_read/run_write 加 cwd 参数 + TOOL_HANDLERS 加 3 → commit `feat(s18): 工具 cwd 参数 + 接线 worktree 工具`
- T5 `teams.py`：wt_ctx + _make_sub_run_tool 切 cwd + idle_poll 切 wt_ctx（先失败测试）→ commit `feat(s18): 队友 wt_ctx 切 worktree cwd`
- T6 `config.py`：make_tools 加 3 worktree 工具（26）+ test_config → commit `feat(s18): config 接线 worktree 工具`
- T7 README + 全测 + 冒烟 + PROGRESS → commit `docs(s18)`
