"""MCP Plugin — MCPClient（mock tools/list + tools/call）+ ToolPool（动态工具池）+ connect_mcp。

教学版用 Python 函数模拟 server；真实版 stdio JSON-RPC 子进程。mcp__{server}__{tool} 前缀避免冲突。
ToolPool.tools 每次 read mcp_clients（connect_mcp 后下一轮自动纳入新工具）。MCP 工具仅 Lead。
"""
import re

_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')


def normalize_mcp_name(name: str) -> str:
    """非 [a-zA-Z0-9_-] 字符替换为 _（防命名冲突/注入）。"""
    return _DISALLOWED_CHARS.sub('_', name)


class MCPClient:
    """MCP 客户端：连接 server、发现工具、调用工具（mock）。"""

    def __init__(self, name: str):
        self.name = name
        self.tools: list = []
        self._handlers: dict = {}

    def register(self, tool_defs: list, handlers: dict) -> None:
        """模拟 tools/list：注册工具定义 + handler。"""
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        """模拟 tools/call：未知工具/异常返 MCP error。"""
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as e:
            return f"MCP error: {e}"


mcp_clients: dict = {}  # server_name → MCPClient


def _mock_server_docs() -> MCPClient:
    c = MCPClient("docs")
    c.register(
        tool_defs=[
            {"name": "search", "description": "Search documentation. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
            {"name": "get_version", "description": "Get API version. (readOnly)",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        })
    return c


def _mock_server_deploy() -> MCPClient:
    c = MCPClient("deploy")
    c.register(
        tool_defs=[
            {"name": "trigger",
             "description": "Trigger a deployment. (destructive — requires approval in real CC)",
             "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}},
            {"name": "status", "description": "Check deployment status. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}},
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        })
    return c


MOCK_SERVERS = {
    "docs": _mock_server_docs,
    "deploy": _mock_server_deploy,
}


def connect_mcp(name: str) -> str:
    """连接 MCP server：dedup → factory 查找 → 注册 → 返发现工具列表。"""
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    mcp_client = factory()
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    print(f"  \033[31m[mcp] connected: {name} → {tool_names}\033[0m")
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}")


class ToolPool:
    """动态工具池：builtin + extra + MCP（mcp__ 前缀）。tools/run_tool 每次 read mcp_clients，
    connect_mcp 后下一轮自动纳入新工具。"""

    def __init__(self, builtin_tools: list, builtin_handlers: dict, extra: dict = None):
        self.builtin_tools = builtin_tools
        self.builtin_handlers = builtin_handlers
        self.extra = extra or {}

    @property
    def tools(self) -> list:
        tools = list(self.builtin_tools)
        for server_name, client in mcp_clients.items():
            safe_server = normalize_mcp_name(server_name)
            for tdef in client.tools:
                safe_tool = normalize_mcp_name(tdef["name"])
                tools.append({
                    "name": f"mcp__{safe_server}__{safe_tool}",
                    "description": tdef.get("description", ""),
                    "input_schema": tdef.get("inputSchema", {"type": "object", "properties": {}}),
                })
        return tools

    def run_tool(self, name: str, input: dict) -> str:
        h = dict(self.builtin_handlers)
        h.update(self.extra)
        for server_name, client in mcp_clients.items():
            safe_server = normalize_mcp_name(server_name)
            for tdef in client.tools:
                safe_tool = normalize_mcp_name(tdef["name"])
                h[f"mcp__{safe_server}__{safe_tool}"] = (
                    lambda *, c=client, t=tdef["name"], **kw: c.call_tool(t, kw))
        handler = h.get(name)
        return handler(**input) if handler else f"Unknown: {name}"


def run_connect_mcp(name: str) -> str:
    return connect_mcp(name)
