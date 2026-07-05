# s19: MCP Plugin

po-agent 第十九阶段，参照 `learn-claude-code/s19_mcp_plugin`。给 Agent 装个**插件系统**：外部服务通过 MCP 标准协议接入，Agent 发现（tools/list）+ 调用（tools/call），不需为每个服务重写工具。`connect_mcp` 连接 server，工具以 `mcp__{server}__{tool}` 前缀加入动态工具池。

## 本阶段完成（相对 s18）

在 s18 循环上做了一件核心事：**外部工具标准协议接入**。

1. **`mcp.py`**（新模块）：
   - **`MCPClient`**：`name`/`tools`/`_handlers`；`register(tool_defs, handlers)`（模拟 tools/list）、`call_tool(tool_name, args)`（模拟 tools/call，未知/异常返 MCP error）。
   - **`normalize_mcp_name`**：非 `[a-zA-Z0-9_-]` → `_`。
   - **`MOCK_SERVERS`**：`docs`（search/get_version，readOnly）+ `deploy`（trigger/status，destructive/readOnly）。教学版 mock；真实版 stdio JSON-RPC 子进程。
   - **`connect_mcp(name)`**：dedup → factory 查找（未知列可用）→ 注册 → 返发现工具列表。
   - **`ToolPool`** 类（DI）：`builtin_tools` + `builtin_handlers` + `extra`；`tools` 属性每次 read `mcp_clients`（builtin + `mcp__{server}__{tool}` 前缀）；`run_tool` dispatch builtin+extra+mcp。connect_mcp 后下一轮自动纳入新工具。
   - `run_connect_mcp` lead handler。
2. **`tools.py`/`config.py`**：`TOOL_HANDLERS` += `connect_mcp`（→ 27）；`make_tools()` += connect_mcp（→ 27）。
3. **`agent.py`**：加 `tool_pool=None` 参数。提供时每轮 while 顶部 `tools = tool_pool.tools`、`run_tool = tool_pool.run_tool`（connect_mcp 后下轮自动纳入 MCP 工具，无需显式 rebuild）。未提供时用 `tools`/`run_tool` 参数（s18 测试兼容）。system_prompt 缓存保留——`context.tools` 变化时 cache key 变 → 自动失效。
4. **`cli.py`**：`ToolPool(cfg["tools"], TOOL_HANDLERS, {"task":..., "spawn_teammate":...})` 取代 `make_run_tool`，传 `tool_pool=tool_pool`。
- **保留 s18 全部**（worktree + 自治 + 协议 + MessageBus + 事件队列 cli + cron + background + recovery + system_prompt + hooks/nag/compact/memory/skills/subagent）。Teammate 工具不变（MCP 仅 Lead）。
- 比 s18 多了**插件扩展**：任意语言实现的 MCP server 接入即用，`mcp__` 前缀防冲突。

## 结构
- `mcp.py` — MCPClient + normalize + MOCK_SERVERS + connect_mcp + ToolPool + run_connect_mcp
- `agent.py` — agent_loop 加 tool_pool 参数（每轮刷新）
- `tools.py` — TOOL_HANDLERS 加 connect_mcp
- `config.py` — make_tools 加 connect_mcp（27）
- `cli.py` — ToolPool 接线
- 其余模块同 s18

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s19_mcp_plugin
```

## 使用示例

```
s19 >> Connect to the docs MCP server and search for "auth".
  [mcp] connected: docs → ['search', 'get_version']      ← connect_mcp 发现工具
  [assembled] sections: identity, tools, workspace, skills   ← 工具池变了 → 重组 prompt
  [HOOK] mcp__docs__search(['auth'])                      ← mcp__docs__ 前缀工具可用了
  [docs] Found 3 results for 'auth'                       ← MCP server 返回
```

Lead 调 connect_mcp("docs") 发现 search/get_version；下一轮工具池含 `mcp__docs__search`/`mcp__docs__get_version`；模型调 `mcp__docs__search` → MCPClient.call_tool → mock server 返回结果。

## 测试
```sh
pytest s19_mcp_plugin/tests -v
```
