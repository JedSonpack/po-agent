# s20 — Comprehensive Agent 设计规格

> 日期：2026-07-05　阶段：s20_comprehensive　参照：`learn-claude-code/s20_comprehensive`
> 前置：s19（MCP plugin，387 测试）

## 问题
前 19 章每章一个机制。真实 Agent 需同时拥有全部：工具+权限、hooks、todo+任务图、技能+记忆+prompt 组装、压缩+恢复、后台+cron、团队+协议+自治、worktree、MCP。难点不是堆功能，是看清各机制在循环中的位置。

## po-agent 现状
po-agent **累积式**——s19 已包含全部 s01-s18 机制（不像参考 s19 省略 permission/hooks/todo/skill/compact/recovery/background/cron）。所以 s20 不是补回省略的机制，而是：① 加参考 s20 的"MCP 已连接 server"系统提示段（让模型看到当前外部能力）；② 综合冒烟验证所有机制共存；③ 收尾。

## s20 实现（复制 s19 → s20，加 MCP 提示段）

### `system_prompt.py`
- `build_context(*, cwd, tools, skills_catalog, memories="", mcp_servers=None)`：加 `mcp_servers` 字段。
- `assemble_system_prompt`：当 `context.get("mcp_servers")` 非空 → 追加 `"Connected MCP servers: {', '.join(names)}"` 段。
- 缓存兼容：`mcp_servers` 进 context → cache key 含它；connect_mcp 后 tool_pool.tools 变 → context.tools 变 → 自动 cache miss → 重组（含 MCP 段）。非 MCP 场景 mcp_servers=None → 无该段，key 稳定不抖动。

### `mcp.py` ToolPool
- 加 `connected_servers` 属性：`list(mcp_clients.keys())`。

### `agent.py`
- `build_context(..., mcp_servers=tool_pool.connected_servers if tool_pool else None)`（tool_pool 提供时注入已连接 server 名）。

### `config.py` / `tools.py` / `cli.py` —— 不变（s19 已 27 工具 + ToolPool 接线）

### 保留 s19 全部（= s01-s19 全部机制）
工具+权限（s02-s03 hooks）+ hooks（s04）+ todo（s05）+ subagent（s06）+ skills（s07）+ compact（s08）+ memory（s09）+ system_prompt（s10）+ recovery（s11）+ tasks（s12）+ background（s13）+ cron（s14）+ teams（s15）+ protocols（s16）+ autonomous（s17）+ worktree（s18）+ MCP（s19）。27 工具。

## 测试
- `test_system_prompt.py`：assemble 含 mcp_servers 段 / 无 mcp_servers 不含；build_context mcp_servers 字段；cache（mcp_servers 变→miss）。
- `test_mcp.py`：ToolPool.connected_servers。
- `test_agent.py`：tool_pool 提供时 system prompt 含 MCP 段（connect_mcp 后）。
- `test_config.py`：27 工具（同 s19，确认无回归）。

## 验收
- 全量 s01–s20 测试通过
- 综合冒烟（多机制共存）：todo_write 规划 + connect_mcp + mcp__docs__search + bash glob，一轮跑通
- PROGRESS 标 s20 ✅（20/20 阶段完成）
