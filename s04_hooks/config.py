import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv


def prepare_env() -> None:
    """加载 .env；使用自定义 base_url 时移除 AUTH_TOKEN，避免鉴权冲突。"""
    load_dotenv(override=True)
    if os.getenv("ANTHROPIC_BASE_URL"):
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def build_system_prompt(cwd: str) -> str:
    return f"You are a coding agent at {cwd}. Use tools to solve tasks. Act, don't explain."


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
    ]


def load() -> dict[str, Any]:
    """读取 env 并组装运行时依赖。仅在 cli 调用时执行。"""
    prepare_env()
    return {
        "client": Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL")),
        "model": os.environ["MODEL_ID"],
        "system": build_system_prompt(os.getcwd()),
        "tools": make_tools(),
    }
