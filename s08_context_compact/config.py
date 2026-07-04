import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from s08_context_compact import skills


def prepare_env() -> None:
    """加载 .env；使用自定义 base_url 时移除 AUTH_TOKEN，避免鉴权冲突。"""
    load_dotenv(override=True)
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def build_system_prompt(cwd: str) -> str:
    # s07：SYSTEM 注入技能目录（便宜层，常驻）
    catalog = skills.list_skills()
    return (f"You are a coding agent at {cwd}. "
            f"Skills available:\n{catalog}\n"
            "Use load_skill to get full details when needed.")


def build_sub_system_prompt(cwd: str) -> str:
    # 子 agent 不加载技能——完成任务、返回总结、不再委派
    return (f"You are a coding agent at {cwd}. "
            "Complete the task you were given, then return a concise summary. "
            "Do not delegate further.")


def make_tools() -> list[dict]:
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
    ]


def make_sub_tools() -> list[dict]:
    # 子 agent 5 工具（无 todo_write 无 task 无 load_skill，防递归）
    return [
        {"name": "bash", "description": "Run a shell command.",
         "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file contents.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write content to a file.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace exact text in a file once.",
         "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
        {"name": "glob", "description": "Find files matching a glob pattern.",
         "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    ]


def load() -> dict[str, Any]:
    """读取 env 并组装运行时依赖。先 scan_skills，build_system_prompt 才有目录。"""
    prepare_env()
    skills.scan_skills()
    return {
        "client": Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL")),
        "model": os.environ["MODEL_ID"],
        "system": build_system_prompt(os.getcwd()),
        "tools": make_tools(),
        "sub_system": build_sub_system_prompt(os.getcwd()),
        "sub_tools": make_sub_tools(),
    }
