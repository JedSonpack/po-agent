# s19 — MCP Plugin 设计规格

> 日期：2026-07-05　阶段：s19_mcp_plugin　参照：`learn-claude-code/s19_mcp_plugin`
> 前置：s18（worktree isolation，371 测试）

## 问题
s01-s18 所有工具手写。要接 Jira/部署/Notion 等外部服务，不想每个重写。需标准协议——服务实现它，Agent 直接调用。

## 解决方案
MCP（Model Context Protocol）：MCPClient 连接 server、发现工具（tools/list）、调用工具（tools/call）。`connect_mcp` 连接 + 发现，`assemble_tool_pool` 把内置 + MCP 工具组装成池，`mcp__{server}__{tool}` 前缀避免冲突。教学版用 mock handler 模拟 server（真实版 stdio JSON-RPC 子进程）。

## po-agent 实现（复制 s18 → s19，保留全部，叠加 MCP）

### 新模块 `mcp.py`
- `MCPClient`：`name`/`tools`/`_handlers`；`register(tool_defs, handlers)`（模拟 tools/list）、`call_tool(tool_name, args)`（模拟 tools/call，未知工具/异常返 MCP error）。
- `normalize_mcp_name(name)`：非 `[a-zA-Z0-9_-]` → `_`。
- `MOCK_SERVERS`：`{"docs": _mock_server_docs, "deploy": _mock_server_deploy}`（docs: search/get_version；deploy: trigger/status）。
- `mcp_clients: dict`（已连接）。
- `connect_mcp(name)`：dedup → factory 查找（未知列可用）→ 注册 → 返发现工具列表。
- `ToolPool` 类（DI）：`__init__(builtin_tools, builtin_handlers, extra=None)`；`tools` 属性（builtin + mcp 前缀工具，每次读 mcp_clients）；`run_tool(name, input)`（dispatch builtin + extra + mcp）。
- `run_connect_mcp(name)` lead handler。

### `tools.py` / `config.py`
- `TOOL_HANDLERS` += `connect_mcp: run_connect_mcp`（→ 27）。
- `make_tools()` += connect_mcp 工具（→ 27）。

### `agent.py` —— 加 `tool_pool=None` 参数
- 若 `tool_pool` 提供：每轮 while 顶部 `tools = tool_pool.tools`、`run_tool = tool_pool.run_tool`（connect_mcp 后下一轮自动纳入 MCP 工具，无需显式 rebuild）。
- 若 None：用 `tools`/`run_tool` 参数（s18 测试兼容）。
- system_prompt 缓存保留——`context.tools` 变化时 cache key 变 → 自动失效重组（无需像参考那样去掉缓存）。

### `cli.py`
- 构建 `tool_pool = ToolPool(make_tools(), TOOL_HANDLERS, {"task": subagent.run, "spawn_teammate": team.spawn})`，传 `agent_loop(..., tool_pool=tool_pool)`。
- 不再用 `make_run_tool`（ToolPool 取代）。

### 保留 s18 全部
worktree + 自治 + 协议 + MessageBus + 事件队列 cli + cron + background + recovery + system_prompt + hooks/nag/compact/memory/skills/subagent。Teammate 工具不变（MCP 仅 Lead）。

## 测试
- `test_mcp.py`（新）：MCPClient（register/call_tool/未知/异常）、normalize_mcp_name（特殊字符→_）、connect_mcp（dedup/未知/成功发现）、ToolPool（tools 含 mcp__ 前缀/run_tool dispatch/连接后纳入新工具）。
- `test_config.py`：27 工具含 connect_mcp。
- `test_agent.py`：tool_pool 提供时 agent_loop 用 tool_pool.tools/run_tool（connect_mcp 后下轮纳入 MCP 工具）。

## 验收
- 全量 s01–s19 测试通过
- 冒烟：Lead connect_mcp("docs") → 发现 search/get_version → 调 mcp__docs__search 返结果
