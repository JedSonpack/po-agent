# s20 — Comprehensive Agent 实现计划

> 规格：[`2026-07-05-s20-comprehensive-design.md`](../specs/2026-07-05-s20-comprehensive-design.md)

## 任务
- T1 复制 s19→s20 改名；387 测试全绿 → commit `chore(s20)`
- T2 `system_prompt.py`：build_context 加 mcp_servers + assemble 加 MCP 段（先失败测试）→ commit `feat(s20): system prompt 加已连接 MCP server 段`
- T3 `mcp.py` ToolPool 加 connected_servers + `agent.py` build_context 注入（先失败测试）→ commit `feat(s20): ToolPool.connected_servers + agent_loop 注入`
- T4 README + 全测 + 综合冒烟 + PROGRESS（20/20）→ commit `docs(s20)`
