import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from s19_mcp_plugin import skills
from s19_mcp_plugin.system_prompt import build_context as _build_context


def prepare_env() -> None:
    """加载 .env；使用自定义 base_url 时移除 AUTH_TOKEN，避免鉴权冲突。"""
    load_dotenv(override=True)
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def build_context(cwd: str, tools: list) -> dict:
    """s10：组装用 context（cwd + 工具名 + 技能目录）。memory 索引由 agent_loop 每轮重读注入。"""
    return _build_context(cwd=cwd, tools=tools, skills_catalog=skills.list_skills())


def build_sub_system_prompt(cwd: str) -> str:
    # 子 agent 不加载技能/记忆——完成任务、返回总结、不再委派
    return (f"You are a coding agent at {cwd}. "
            "Complete the task you were given, then return a concise summary. "
            "Do not delegate further.")


def make_tools() -> list[dict]:
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "run_in_background": {"type": "boolean"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in a file once.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        {"name": "glob", "description": "Find files matching a glob pattern.",
         "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
        {"name": "todo_write", "description": "Create and manage a task list for your current coding session.",
         "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object", "properties": {"content": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}}, "required": ["content", "status"]}}}, "required": ["todos"]}},
        {"name": "task", "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
         "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]}},
        # s07: 按需加载技能全文
        {"name": "load_skill", "description": "Load the full content of a skill by name.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
        # s08: 压缩对话历史（循环 special-case，不走 run_tool）
        {"name": "compact", "description": "Summarize earlier conversation to free context space.",
         "input_schema": {"type": "object", "properties": {"focus": {"type": "string"}}}},
        # s12: 任务系统 5 工具
        {"name": "create_task", "description": "Create a new task with optional blockedBy dependencies.",
         "input_schema": {"type": "object", "properties": {"subject": {"type": "string"}, "description": {"type": "string"}, "blockedBy": {"type": "array", "items": {"type": "string"}}}, "required": ["subject"]}},
        {"name": "list_tasks", "description": "List all tasks with status, owner, and dependencies.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "get_task", "description": "Get full details of a specific task by ID.",
         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
        {"name": "claim_task", "description": "Claim a pending task. Sets owner, changes status to in_progress.",
         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
        {"name": "complete_task", "description": "Complete an in-progress task. Reports unblocked downstream tasks.",
         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
        # s14: cron 调度 3 工具
        {"name": "schedule_cron", "description": "Schedule a cron job. cron is 5-field: min hour dom month dow.",
         "input_schema": {"type": "object", "properties": {"cron": {"type": "string"}, "prompt": {"type": "string"}, "recurring": {"type": "boolean"}, "durable": {"type": "boolean"}}, "required": ["cron", "prompt"]}},
        {"name": "list_crons", "description": "List all registered cron jobs.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "cancel_cron", "description": "Cancel a cron job by ID.",
         "input_schema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}},
        # s15: 团队 3 工具（spawn_teammate/send_message/check_inbox）
        {"name": "spawn_teammate", "description": "Spawn a teammate agent in a background thread.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
        {"name": "send_message", "description": "Send a message to a teammate via MessageBus.",
         "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
        {"name": "check_inbox", "description": "Check Lead's inbox. Routes protocol responses automatically.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        # s16: 协议 3 工具（request_shutdown/request_plan/review_plan）
        {"name": "request_shutdown", "description": "Request a teammate to shut down gracefully.",
         "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
        {"name": "request_plan", "description": "Ask a teammate to submit a plan for review.",
         "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}, "task": {"type": "string"}}, "required": ["teammate", "task"]}},
        {"name": "review_plan", "description": "Approve or reject a submitted plan by request_id.",
         "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
        # s18: worktree 3 工具（create/remove/keep）
        {"name": "create_worktree", "description": "Create a git worktree with a dedicated branch; optionally bind to a task.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "task_id": {"type": "string"}}, "required": ["name"]}},
        {"name": "remove_worktree", "description": "Remove a worktree. Refuses if uncommitted changes unless discard_changes.",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "discard_changes": {"type": "boolean"}}, "required": ["name"]}},
        {"name": "keep_worktree", "description": "Keep a worktree for manual review (branch preserved).",
         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    ]


def make_sub_tools() -> list[dict]:
    # 子 agent 5 工具（无 todo_write 无 task 无 load_skill，防递归）
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in a file once.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        {"name": "glob", "description": "Find files matching a glob pattern.",
         "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    ]


def make_team_tools() -> list[dict]:
    # 队友 8 工具（无 edit/glob/todo/task/spawn_teammate——聚焦通信+自治，防递归组队）
    # bash 无 run_in_background；s16 加 submit_plan；s17 加 list_tasks/claim_task/complete_task
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "send_message", "description": "Send a message to another agent.",
         "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}}, "required": ["to", "content"]}},
        {"name": "submit_plan", "description": "Submit a plan for Lead approval.",
         "input_schema": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}},
        {"name": "list_tasks", "description": "List all tasks on the board.",
         "input_schema": {"type": "object", "properties": {}, "required": []}},
        {"name": "claim_task", "description": "Claim a pending task by ID. Sets owner, changes status to in_progress.",
         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
        {"name": "complete_task", "description": "Complete an in-progress task by ID.",
         "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    ]


def load() -> dict[str, Any]:
    """读取 env 并组装运行时依赖。先 scan_skills，build_context 才有目录。"""
    prepare_env()
    skills.scan_skills()
    tools = make_tools()
    return {
        "client": Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL")),
        "model": os.environ["MODEL_ID"],
        "context": build_context(os.getcwd(), tools),
        "tools": tools,
        "sub_system": build_sub_system_prompt(os.getcwd()),
        "sub_tools": make_sub_tools(),
        "team_tools": make_team_tools(),
    }
