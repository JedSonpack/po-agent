# s18 — Worktree Isolation 设计规格

> 日期：2026-07-05　阶段：s18_worktree_isolation　参照：`learn-claude-code/s18_worktree_isolation`
> 前置：s17（autonomous agents，334 测试）

## 问题
s17 队友都在同一目录工作——Alice/Bob 都改 `config.py` 互相覆盖，无法干净回滚。解决了"谁干什么/怎么通信"，没解决"在哪干"。

## 解决方案
Git worktree 给每个任务独立目录 + 独立分支（`.worktrees/{name}`，分支 `wt/{name}`）。沿用 s17 全部，新增：`worktrees.py`（create/remove/keep/bind/validate + 事件日志）、`Task.worktree` 字段、队友 `wt_ctx`（认领带 worktree 的任务时切 cwd，bash/read/write 在 worktree 下执行）、3 lead 工具。

## po-agent 实现（复制 s17 → s18，保留全部，叠加隔离）

### 新模块 `worktrees.py`
- `WORKTREES_DIR = WORKDIR / ".worktrees"`、`VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')`。
- `validate_worktree_name(name) -> str|None`：空/`.`/`..`/不匹配正则 → 错误消息；合法 → None。
- `run_git(args) -> (bool, str)`：`subprocess.run(["git"]+args, cwd=WORKDIR, timeout=30)`，返 (returncode==0, output[:5000])。
- `log_event(event_type, worktree_name, task_id="")`：append `events.jsonl`。
- `create_worktree(name, task_id="") -> str`：validate → 已存在返错 → `git worktree add .worktrees/{name} -b wt/{name} HEAD` → 失败返 Git error → task_id 则 `bind_task_to_worktree` → log create。
- `bind_task_to_worktree(task_id, worktree_name)`：`task.worktree = worktree_name; save_task`（状态保持 pending）。
- `_count_worktree_changes(path) -> (files, commits)`：`git status --porcelain` + `git log @{push}..HEAD`；异常 → (-1,-1)。
- `remove_worktree(name, discard_changes=False) -> str`：validate → 不存在返错 → 非 discard 时 `_count_worktree_changes`，files>0 or commits>0 → 拒绝（提示 discard_changes/keep）→ `git worktree remove --force` + `git branch -D wt/{name}` → log remove。
- `keep_worktree(name) -> str`：validate → log keep → 返保留消息。
- 3 lead handler：`run_create_worktree`/`run_remove_worktree`/`run_keep_worktree`。

### `tasks.py`
- `Task` 加 `worktree: str | None = None`（向后兼容，旧 JSON 无此字段默认 None）。

### `tools.py`
- `safe_path(p, cwd=None)`：base = cwd or WORKDIR，路径锁在 base 内。
- `run_bash(command, run_in_background=False, cwd=None)`：`cwd or WORKDIR`。
- `run_read(path, limit=None, cwd=None)` / `run_write(path, content, cwd=None)`：`safe_path(path, cwd)`。
- `TOOL_HANDLERS` += `create_worktree`/`remove_worktree`/`keep_worktree`（3，→ 26）。

### `teams.py` Team `wt_ctx`
- `_run` 创建 `wt_ctx = {"path": None}`，传给 `_make_sub_run_tool(name, wt_ctx)` 与 `idle_poll(name, messages, role, wt_ctx)`。
- `_make_sub_run_tool`：bash/read/write 用 `wt_ctx["path"]` 作 cwd；`claim_task` 绑定 owner=name 且 `task.worktree` → 设 `wt_ctx["path"]=str(WORKTREES_DIR/task.worktree)`；`complete_task` 完成后 `wt_ctx["path"]=None`。
- `idle_poll(name, messages, role, wt_ctx=None)`：auto-claim 时若 `task.get("worktree")` 且 wt_ctx → 设 wt_ctx（po-agent 改进：auto-claim 也切 cwd）。wt_ctx=None 时只认领不切（s17 测试兼容）。

### `config.py`
- `make_tools()` += 3 worktree 工具（→ 26）。

### `agent.py` / `cli.py` —— 不变

## 测试
- `test_worktrees.py`（新）：validate（空/`.`/`..`/非法/合法）、run_git（mock subprocess）、create（mock git 成功/失败/已存在/bind）、bind（task.worktree 写入+状态 pending）、remove（有改动拒绝/discard 强制/不存在/成功）、keep、log_event、_count_worktree_changes（mock）。用 tmp git repo 或 monkeypatch run_git。
- `test_tasks.py`：Task.worktree 字段（默认 None；bind 后写入）。
- `test_tools.py`：run_bash/safe_path cwd 参数（路径锁在 cwd 内）。
- `test_teams.py`：wt_ctx 切换（claim 带 worktree 任务 → bash 在 worktree cwd；complete → 重置）；idle_poll auto-claim 切 wt_ctx。
- `test_config.py`：26 工具含 worktree 3。

## 验收
- 全量 s01–s18 测试通过
- 冒烟：Lead create task + create_worktree（bind）→ spawn alice → alice 认领带 wt 的任务 → 在 `.worktrees/{name}` 下工作 → complete → keep/remove
