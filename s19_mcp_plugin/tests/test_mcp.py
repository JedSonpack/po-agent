"""mcp.py 测试——MCPClient + normalize + connect_mcp + ToolPool（mock，无真实 server）。"""
import pytest
from s19_mcp_plugin import mcp
from s19_mcp_plugin.mcp import (MCPClient, normalize_mcp_name, connect_mcp,
                                MOCK_SERVERS, ToolPool)


@pytest.fixture(autouse=True)
def _reset_clients():
    mcp.mcp_clients.clear()
    yield
    mcp.mcp_clients.clear()


# ── MCPClient ──
def test_client_register_and_call():
    c = MCPClient("docs")
    c.register([{"name": "search", "description": "s", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}],
               {"search": lambda query: f"found {query}"})
    assert c.tools[0]["name"] == "search"
    assert c.call_tool("search", {"query": "auth"}) == "found auth"


def test_client_call_unknown_tool():
    c = MCPClient("x")
    c.register([], {})
    assert "unknown tool" in c.call_tool("nope", {})


def test_client_call_handler_exception():
    c = MCPClient("x")
    c.register([{"name": "boom"}], {"boom": lambda: (_ for _ in ()).throw(ValueError("fail"))})
    assert "MCP error" in c.call_tool("boom", {})


# ── normalize_mcp_name ──
def test_normalize_replaces_special():
    assert normalize_mcp_name("my.server") == "my_server"
    assert normalize_mcp_name("a/b:c") == "a_b_c"
    assert normalize_mcp_name("ok-name_1") == "ok-name_1"


# ── connect_mcp ──
def test_connect_unknown_server():
    out = connect_mcp("ghost")
    assert "Unknown" in out and "Available" in out


def test_connect_docs_discovers_tools():
    out = connect_mcp("docs")
    assert "Connected" in out and "search" in out and "get_version" in out
    assert "docs" in mcp.mcp_clients
    assert len(mcp.mcp_clients["docs"].tools) == 2


def test_connect_dedup():
    connect_mcp("docs")
    out = connect_mcp("docs")
    assert "already connected" in out


def test_mock_servers_present():
    assert "docs" in MOCK_SERVERS and "deploy" in MOCK_SERVERS


# ── ToolPool ──
def test_toolpool_tools_builtin_only():
    pool = ToolPool([{"name": "bash", "input_schema": {}}], {"bash": lambda command: "OUT"})
    names = [t["name"] for t in pool.tools]
    assert names == ["bash"]


def test_toolpool_run_tool_builtin():
    pool = ToolPool([], {"bash": lambda command: f"ran {command}"})
    assert pool.run_tool("bash", {"command": "ls"}) == "ran ls"


def test_toolpool_run_tool_unknown():
    pool = ToolPool([], {})
    assert "Unknown" in pool.run_tool("nope", {})


def test_toolpool_includes_mcp_after_connect():
    pool = ToolPool([{"name": "bash", "input_schema": {}}], {"bash": lambda command: "OUT"})
    connect_mcp("docs")
    names = [t["name"] for t in pool.tools]
    assert "mcp__docs__search" in names
    assert "mcp__docs__get_version" in names


def test_toolpool_dispatches_mcp_tool():
    pool = ToolPool([], {})
    connect_mcp("docs")
    out = pool.run_tool("mcp__docs__search", {"query": "auth"})
    assert "auth" in out  # docs search handler 返回 [docs] Found 3 results for 'auth'


def test_toolpool_extra_handlers():
    pool = ToolPool([], {}, extra={"task": lambda description: f"sub:{description}"})
    assert pool.run_tool("task", {"description": "do X"}) == "sub:do X"


def test_toolpool_normalize_server_name():
    """server 名含特殊字符 → mcp__ 前缀规范化。"""
    # 直接注入一个名字带点的 client
    c = MCPClient("my.server")
    c.register([{"name": "search", "description": "", "inputSchema": {"type": "object", "properties": {}}}],
               {"search": lambda: "ok"})
    mcp.mcp_clients["my.server"] = c
    pool = ToolPool([], {})
    names = [t["name"] for t in pool.tools]
    assert "mcp__my_server__search" in names
    assert pool.run_tool("mcp__my_server__search", {}) == "ok"
