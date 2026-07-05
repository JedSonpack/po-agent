# s18: Worktree Isolation

po-agent 第十八阶段，参照 `learn-claude-code/s18_worktree_isolation`。给每个任务**独立 git worktree**（`.worktrees/{name}`，分支 `wt/{name}`）——Alice/Bob 不再互相覆盖 `config.py`。队友认领带 worktree 的任务时自动切 cwd，bash/read/write 在 worktree 下执行。

## 本阶段完成（相对 s17）

在 s17 循环上做了一件核心事：**并行执行的目录隔离**。

1. **`worktrees.py`**（新模块）：
   - **`validate_worktree_name`**：`^[A-Za-z0-9._-]{1,64}$`，拒 `.`/`..`/空/非法。
   - **`run_git(args) -> (ok, output)`**：`subprocess` 跑 git，timeout 30s。
   - **`create_worktree(name, task_id="")`**：validate → 已存在返错 → `git worktree add .worktrees/{name} -b wt/{name} HEAD` → 可选 `bind_task_to_worktree` → log。
   - **`bind_task_to_worktree`**：写 `task.worktree`，**状态保持 pending**（队友 auto-claim 才推进）。
   - **`remove_worktree(name, discard_changes=False)`**：有未提交改动默认拒绝（`_count_worktree_changes` 数 files+commits），`discard_changes=true` 强制 `git worktree remove --force` + `git branch -D`。
   - **`keep_worktree`**：保留分支待 review。
   - **`log_event`**：`.worktrees/events.jsonl` 生命周期审计（create/remove/keep）。
   - 3 lead handler：`run_create_worktree`/`run_remove_worktree`/`run_keep_worktree`。
2. **`tasks.py`**：`Task` 加 `worktree: str | None = None`（向后兼容，旧 JSON 默认 None）。
3. **`tools.py`**：`safe_path`/`run_bash`/`run_read`/`run_write` 加 `cwd` 参数（默认 WORKDIR，worktree 时注入）；`TOOL_HANDLERS` += 3 worktree 工具（→ 26）。
4. **`teams.py` Team `wt_ctx`**：
   - `_run` 创建 `wt_ctx = {"path": None}`，传给 `_make_sub_run_tool` 与 `idle_poll`。
   - `_make_sub_run_tool`：bash/read/write 仅当 `wt_ctx` 指向 worktree 时注入 cwd（无 worktree 原样调 base，兼容 stub）；`claim_task` 经 `_claim_with_wt`（claim + `task.worktree` → 设 `wt_ctx["path"]=WORKTREES_DIR/task.worktree`）；`complete_task` 经 `_complete_reset_wt`（完成 + 重置 wt_ctx）。
   - `idle_poll` auto-claim 也经 `_claim_with_wt` 切 wt_ctx（po-agent 改进：auto-claim 也切 cwd）。
5. **`config.py`**：`make_tools()` += 3 worktree 工具（→ 26）。
- **保留 s17 全部**（自治认领 + 协议 + MessageBus + 事件队列 cli + cron + background + recovery + system_prompt + hooks/nag/compact/memory/skills/subagent）。`agent_loop`/cli 不变。
- 比 s17 多了**目录隔离**：队友在各自 worktree 干活，互不覆盖；keep/remove 收尾可控。

## 结构
- `worktrees.py` — validate/run_git/log_event/create/bind/_count/remove/keep + 3 lead handler
- `tasks.py` — Task.worktree 字段
- `tools.py` — safe_path/run_bash/run_read/run_write 加 cwd + TOOL_HANDLERS 加 3
- `teams.py` — wt_ctx + _claim_with_wt/_complete_reset_wt + _make_sub_run_tool 切 cwd + idle_poll 切
- `config.py` — make_tools 加 3 worktree 工具（26）
- `agent.py` / `cli.py` — 不变
- 其余模块同 s17

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s18_worktree_isolation
```

## 使用示例

```
s18 >> Create a task "write auth.py", then create worktree "auth" bound to it. Spawn alice.
  [task] created task_...: write auth.py
  [worktree] created: auth at .worktrees/auth
  [bind] write auth.py → worktree:auth
  [teammate] alice spawned as backend dev
  [idle] alice auto-claimed: write auth.py    ← 认领带 wt 的任务 → wt_ctx 切 .worktrees/auth
  [teammate alice] write_file: Wrote ... to auth.py   ← 在 .worktrees/auth 下
  [teammate alice] complete_task: Completed ...
```

alice 认领绑 worktree 的任务后，bash/read/write 在 `.worktrees/auth/` 下执行；complete 后 wt_ctx 重置回主目录。Lead 用 `keep_worktree` 保留待 review 或 `remove_worktree` 清理。

## 测试
```sh
pytest s18_worktree_isolation/tests -v
```
