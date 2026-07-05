"""System Prompt — 运行时段落化组装系统提示 + 缓存 + 每轮重算。

便宜优先：identity/tools/workspace/skills 始终拼；memory 段仅索引非空时加。
缓存用 json.dumps(sort_keys=True) 做 key，避免 hash() 的进程随机化与 unhashable 错误。
"""
import json

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: {tools}.",
    "workspace": "Working directory: {cwd}.",
    "skills": "Skills available:\n{catalog}\nUse load_skill to get full details when needed.",
    # memory 段动态来自 Memory.build_index_section()（含引导），无模板
}

_last_context_key = None
_last_prompt = None


def assemble_system_prompt(context: dict) -> str:
    """按真实状态选段拼接。memory/mcp 段仅非空时加入。"""
    sections = [
        PROMPT_SECTIONS["identity"],
        PROMPT_SECTIONS["tools"].format(tools=", ".join(context.get("tools", []))),
        PROMPT_SECTIONS["workspace"].format(cwd=context.get("cwd", "")),
        PROMPT_SECTIONS["skills"].format(catalog=context.get("skills_catalog", "(no skills found)")),
    ]
    if context.get("memories"):
        sections.append(context["memories"])
    mcp_servers = context.get("mcp_servers") or []  # s20: 已连接 MCP server 段
    if mcp_servers:
        sections.append(f"Connected MCP servers: {', '.join(mcp_servers)}")
    return "\n\n".join(sections)


def get_system_prompt(context: dict) -> str:
    """缓存包装：相同 context 命中返回旧 prompt。"""
    global _last_context_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_context_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt unchanged\033[0m")
        return _last_prompt
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)
    loaded = ["identity", "tools", "workspace", "skills"]
    if context.get("memories"):
        loaded.append("memory")
    if context.get("mcp_servers"):
        loaded.append("mcp")
    print(f"  \033[32m[assembled] sections: {', '.join(loaded)}\033[0m")
    return _last_prompt


def build_context(*, cwd, tools, skills_catalog, memories="", mcp_servers=None) -> dict:
    """从组件构造 context。tools 接收 dict 列表或名字列表，统一存名字。s20 加 mcp_servers。"""
    if tools and isinstance(tools[0], dict):
        tools = [t["name"] for t in tools]
    return {"cwd": str(cwd), "tools": list(tools),
            "skills_catalog": skills_catalog, "memories": memories,
            "mcp_servers": list(mcp_servers) if mcp_servers else []}


def reset_cache() -> None:
    """测试间重置模块级缓存槽。"""
    global _last_context_key, _last_prompt
    _last_context_key = None
    _last_prompt = None
