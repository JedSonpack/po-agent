# s20: Comprehensive Agent

po-agent 第二十阶段（终点），参照 `learn-claude-code/s20_comprehensive`。**机制很多，循环一个**——把 s01-s19 全部机制归到同一个 `while True`。po-agent 累积式，s19 已含全部机制；s20 加"已连接 MCP server"系统提示段 + 综合冒烟收尾。

## 本阶段完成（相对 s19）

1. **`system_prompt.py`**：`build_context` 加 `mcp_servers` 字段；`assemble_system_prompt` 当 `mcp_servers` 非空 → 追加 `Connected MCP servers: docs, deploy` 段。缓存兼容：`mcp_servers` 进 context → cache key 含它；connect_mcp 后 tool_pool.tools 变 → context.tools 变 → 自动 cache miss → 重组（含 MCP 段）。`get_system_prompt` 的 `[assembled] sections` 日志加 `mcp`。
2. **`mcp.py` ToolPool**：加 `connected_servers` 属性（`list(mcp_clients.keys())`）。
3. **`agent.py`**：`build_context(..., mcp_servers=tool_pool.connected_servers if tool_pool else None)`——tool_pool 提供时把已连接 server 名注入 system prompt。
- **保留 s19 全部（= s01-s19 全部机制）**：工具+权限（s02-s03 hooks）+ hooks（s04）+ todo（s05）+ subagent（s06）+ skills（s07）+ compact（s08）+ memory（s09）+ system_prompt（s10）+ recovery（s11）+ tasks（s12）+ background（s13）+ cron（s14）+ teams（s15）+ protocols（s16）+ autonomous（s17）+ worktree（s18）+ MCP（s19）。**27 工具**。
- 核心循环不变：`while True: LLM → 有 tool_use？是→PreToolUse+权限→分发(builtin/MCP/background)→PostToolUse→tool_result 回 messages→下一轮 / 否→Stop hooks→返回`。

## 循环中各机制的位置
| 位置 | 机制 |
|------|------|
| 用户输入前后 | UserPromptSubmit hooks |
| LLM 前 | cron queue 注入 `[Scheduled]` / background `<task_notification>` / compact 管线 / memory+skills+MCP 组装 system prompt |
| LLM 调用 | recovery（429/529 退避、max_tokens 升级、prompt too long→reactive compact） |
| 工具执行前 | PreToolUse hooks + permission |
| 工具分发 | ToolPool（builtin 27 + mcp__server__tool 动态） |
| 工具执行时 | background dispatch（慢 bash → daemon thread + 占位） |
| 工具执行后 | PostToolUse hooks |
| 停止时 | Stop hooks（统计）+ memory 提取/整合 |

## 结构
- `system_prompt.py` — build_context/assemble 加 mcp_servers 段
- `mcp.py` — ToolPool 加 connected_servers
- `agent.py` — build_context 注入 mcp_servers
- 其余模块同 s19（全部机制共存）

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s20_comprehensive
```

## 综合冒烟
```
s20 >> Plan with todo_write: inspect repo. Then connect docs MCP and search "agent loop". Then glob *.py.
  [assembled] sections: identity, tools, workspace, skills
  [HOOK] todo_write([...])                              ← s05 todo 规划
  ## Current Tasks
  [HOOK] connect_mcp(['docs'])                          ← s19 MCP 连接
  [mcp] connected: docs → ['search', 'get_version']
  [assembled] sections: ..., mcp                        ← s20 MCP 段出现
  [HOOK] mcp__docs__search(['agent loop'])              ← MCP 工具调用
  [docs] Found 3 results for 'agent loop'
  [HOOK] glob(['*.py'])                                 ← s02 工具
  ...
```
todo + MCP + glob 多机制一轮跑通。

## 测试
```sh
pytest s20_comprehensive/tests -v
```

## 终点
s01→s20，代码表面越来越复杂，核心始终是 `while True: LLM → tool_use? → 执行 → 回 messages`。模型负责判断；harness 把环境/工具/权限/记忆/团队/外部能力组织好。**机制很多，循环一个。**
