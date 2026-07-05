import ast
import glob as _glob
import json
import subprocess
from pathlib import Path
from typing import Callable

from s18_worktree_isolation.skills import load_skill
from s18_worktree_isolation.tasks import (run_create_task, run_list_tasks, run_get_task,
                                   run_claim_task, run_complete_task)
from s18_worktree_isolation.cron import run_schedule_cron, run_list_crons, run_cancel_cron
from s18_worktree_isolation.teams import (run_send_message, run_check_inbox,
                                   run_request_shutdown, run_request_plan, run_review_plan)
from s18_worktree_isolation.worktrees import (run_create_worktree, run_remove_worktree,
                                          run_keep_worktree)

WORKDIR = Path.cwd()
TIMEOUT = 120
MAX_OUTPUT = 50000

CURRENT_TODOS: list[dict] = []


def run_bash(command: str, run_in_background: bool = False, cwd=None) -> str:
    # s04：危险检查在 permission_hook（PreToolUse），这里只执行
    # s13：run_in_background 由 agent_loop dispatch 层判断，此处忽略
    # s18：cwd=worktree 路径时在该目录执行（队友 wt_ctx）
    try:
        r = subprocess.run(command, shell=True, cwd=cwd or WORKDIR,
                           capture_output=True, text=True, timeout=TIMEOUT)
        out = (r.stdout + r.stderr).strip()
        return out[:MAX_OUTPUT] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def safe_path(p: str, cwd=None) -> Path:
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_read(path: str, limit: int | None = None, cwd=None) -> str:
    try:
        lines = safe_path(path, cwd).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str, cwd=None) -> str:
    try:
        file_path = safe_path(path, cwd)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    try:
        results = []
        for match in _glob.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
    except Exception as e:
        return f"Error: {e}"


def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None


def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error:
        return error
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m",
                "completed": "\033[32m✓\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"


TOOL_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                 "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
                 "load_skill": load_skill,
                 # s12: 任务系统 5 工具
                 "create_task": run_create_task, "list_tasks": run_list_tasks,
                 "get_task": run_get_task, "claim_task": run_claim_task,
                 "complete_task": run_complete_task,
                 # s14: cron 调度 3 工具
                 "schedule_cron": run_schedule_cron, "list_crons": run_list_crons,
                 "cancel_cron": run_cancel_cron,
                 # s15: 团队 lead handler（spawn_teammate 需 Team 实例，cli 经 extra 接线）
                 "send_message": run_send_message, "check_inbox": run_check_inbox,
                 # s16: 协议 3 工具（request_shutdown/request_plan/review_plan）
                 "request_shutdown": run_request_shutdown, "request_plan": run_request_plan,
                 "review_plan": run_review_plan,
                 # s18: worktree 3 工具
                 "create_worktree": run_create_worktree, "remove_worktree": run_remove_worktree,
                 "keep_worktree": run_keep_worktree}

# s06: 子 agent 用 5 工具（无 todo_write 无 task 无 load_skill，防递归）
SUB_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                "edit_file": run_edit, "glob": run_glob}

# s15/s17: 队友 base handler（bash/read/write + s17 任务工具；send_message 由 Team 按名绑定 from，
# claim_task 由 Team._make_sub_run_tool 重绑 owner=队友名）
TEAM_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                 "list_tasks": run_list_tasks, "claim_task": run_claim_task,
                 "complete_task": run_complete_task}


def make_run_tool(handlers: dict, extra: dict | None = None) -> Callable:
    """接线时构造分发器：handlers + extra（依赖型处理器，如 {"task": subagent.run}）。"""
    h = {**handlers, **(extra or {})}

    def run_tool(name: str, input: dict) -> str:
        handler = h.get(name)
        return handler(**input) if handler else f"Unknown: {name}"

    return run_tool


# 模块级默认分发器（7，含 load_skill；cli 用 make_run_tool(TOOL_HANDLERS, {"task": ...}) 加 task）
run_tool = make_run_tool(TOOL_HANDLERS)
