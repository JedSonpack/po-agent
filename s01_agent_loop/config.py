# config.py —— 环境与客户端配置
#
# 这个模块负责"加载"运行时需要的东西：读取 .env 里的密钥/模型、构造 anthropic 客户端、
# 定义系统提示和工具。重点：导入本模块时不会读取环境变量（避免测试时强依赖 .env），
# 真正的读取发生在调用 load() 时——这样测试可以直接 import 本模块而不报错。

import os
from typing import Any  # Any 表示"任意类型"，用在 dict 的值类型标注上

from anthropic import Anthropic  # anthropic 官方 SDK 的客户端类
from dotenv import load_dotenv   # 把 .env 文件里的键值对加载进 os.environ


def prepare_env() -> None:
    """加载 .env；使用自定义 base_url 时移除 AUTH_TOKEN，避免鉴权冲突。"""
    # load_dotenv() 把当前目录(及上层)的 .env 内容读进 os.environ（环境变量字典）。
    # override=True：.env 里的值会覆盖已存在的同名环境变量。
    load_dotenv(override=True)
    # 用了自定义 base_url（ARK 等第三方端点）时，移除 AUTH_TOKEN——
    # 那些端点用 x-api-key（即 ANTHROPIC_API_KEY）鉴权，留着 AUTH_TOKEN 反而可能冲突。
    if os.getenv("ANTHROPIC_BASE_URL"):
        # os.environ.pop(key, None)：删除该环境变量；第二个参数 None 表示
        # "如果它不存在也不报错"（没有 None 的话，键不存在会抛 KeyError）。
        os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


def build_system_prompt(cwd: str) -> str:
    """构造系统提示。cwd 会被塞进提示里，告诉模型它在哪个目录工作。"""
    # f"..." 是 f-string：{cwd} 会被替换成变量 cwd 的值。
    return f"You are a coding agent at {cwd}. Use bash to solve tasks. Act, don't explain."


def make_tools() -> list[dict]:
    """定义模型可用的工具。s01 只有一个 bash 工具。"""
    # list[dict] 表示"元素是 dict 的 list"。这里返回一个 list，里面套一个 dict。
    return [{
        "name": "bash",  # 工具名，模型靠它识别要调哪个工具
        "description": "Run a shell command.",
        "input_schema": {  # 工具入参的 JSON Schema：告诉模型这个工具接受什么参数
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],  # command 是必填参数
        },
    }]


def load() -> dict[str, Any]:
    """读取 env 并组装运行时依赖。仅在 cli 调用时执行，避免导入时读 env。"""
    # dict[str, Any] 表示"键是 str、值是任意类型"的 dict。
    prepare_env()
    return {
        # Anthropic(base_url=...) 构造客户端。不传 api_key 时，
        # SDK 会自动从环境变量 ANTHROPIC_API_KEY 读取密钥。
        "client": Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL")),
        # os.environ[k] 取环境变量；如果 MODEL_ID 不存在会抛 KeyError。
        "model": os.environ["MODEL_ID"],
        "system": build_system_prompt(os.getcwd()),  # os.getcwd() 取当前工作目录
        "tools": make_tools(),
    }
