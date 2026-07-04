# po-agent 实现进度

逐步实现 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) 的 20 个阶段。每个阶段是一个**独立自包含包**（学习优先，不累积），走 superpowers 流程：设计规格 → 实现计划 → TDD 执行。

- 参考教程：`../learn-claude-code/sNN_*`
- 每阶段的规格 / 计划：`docs/superpowers/{specs,plans}/`
- 模型：GLM via ARK `/api/coding`（`MODEL_ID=glm-5.2`，见 `.env.example`）
- 状态图例：✅ 已完成　🚧 进行中　⬜ 待开始

## 阶段总览

| 阶段 | 主题 | 状态 | 目录 | 做什么 |
|---|---|---|---|---|
| s01 | Agent Loop | ✅ | [`s01_agent_loop/`](s01_agent_loop/) | `while` 循环 + bash 工具，模型调工具就继续、不调就停 |
| s02 | Tool Use | ✅ | [`s02_tool_use/`](s02_tool_use/) | 5 工具（bash/read/write/edit/glob）+ 查表分发，模型可一次调多个 |
| s03 | Permission | ✅ | [`s03_permission/`](s03_permission/) | 三道闸门权限管线（硬拒绝/规则/审批）插在工具执行前 |
| s04 | Hooks | ⬜ | `s04_hooks/` | 钩子挂在循环上，但不写进循环本身 |
| s05 | TodoWrite | ⬜ | `s05_todo_write/` | 给 agent 一个任务清单，防止跑偏 |
| s06 | Subagent | ⬜ | `s06_subagent/` | 大任务拆给子 agent，子任务拿干净上下文 |
| s07 | Skill Loading | ⬜ | `s07_skill_loading/` | 技能按需加载，用到才读 |
| s08 | Context Compact | ⬜ | `s08_context_compact/` | 上下文满了想办法压缩腾地方 |
| s09 | Memory | ⬜ | `s09_memory/` | 持久记忆层，存压缩会丢的关键细节 |
| s10 | System Prompt | ⬜ | `s10_system_prompt/` | 运行时组装系统提示，不硬编码 |
| s11 | Error Recovery | ⬜ | `s11_error_recovery/` | 错误重试与恢复策略 |
| s12 | Task System | ⬜ | `s12_task_system/` | 大目标拆成可追踪的小任务 |
| s13 | Background Tasks | ⬜ | `s13_background_tasks/` | 慢操作放后台执行 |
| s14 | Cron Scheduler | ⬜ | `s14_cron_scheduler/` | 按时间表触发任务 |
| s15 | Agent Teams | ⬜ | `s15_agent_teams/` | 多 agent 组队协作 |
| s16 | Team Protocols | ⬜ | `s16_team_protocols/` | 队友之间的通信协议 |
| s17 | Autonomous Agents | ⬜ | `s17_autonomous_agents/` | 自治 agent，自己看板、自己认领 |
| s18 | Worktree Isolation | ⬜ | `s18_worktree_isolation/` | git worktree 隔离，并行互不干扰 |
| s19 | MCP Tools | ⬜ | `s19_mcp_plugin/` | 用 MCP 标准协议外接工具 |
| s20 | Comprehensive Agent | ⬜ | `s20_comprehensive/` | 全部机制集成到一个循环 |

## 已完成阶段详情

### s01 — Agent Loop ✅
- 目录：[`s01_agent_loop/`](s01_agent_loop/)（config / tools / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s01-agent-loop-design.md`](docs/superpowers/specs/2026-07-04-s01-agent-loop-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s01-agent-loop.md`](docs/superpowers/plans/2026-07-04-s01-agent-loop.md)
- 要点：核心 `while True` 循环 + bash 工具；`agent_loop` 依赖注入（client / run_tool / on_tool_use 入参）；11/11 测试通过
- 关键发现：ARK `/api/coding` 端点用 `glm-5.2`（`glm-5.1` 返回 404 UnsupportedModel）

### s02 — Tool Use ✅
- 目录：[`s02_tool_use/`](s02_tool_use/)（config / tools / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s02-tool-use-design.md`](docs/superpowers/specs/2026-07-04-s02-tool-use-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s02-tool-use.md`](docs/superpowers/plans/2026-07-04-s02-tool-use.md)
- 要点：5 工具（bash / read_file / write_file / edit_file / glob）+ `TOOL_HANDLERS` 查表分发 + `safe_path` 路径校验；`agent_loop` 注入 `run_tool(name, input)` 分发器；27/27 测试通过
- 验收：实时跑通——模型对“列出 .py 文件”自动选 `glob` 工具（而非 bash），返回 12 个文件并总结

### s03 — Permission ✅
- 目录：[`s03_permission/`](s03_permission/)（config / tools / permissions / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s03-permission-design.md`](docs/superpowers/specs/2026-07-04-s03-permission-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s03-permission.md`](docs/superpowers/plans/2026-07-04-s03-permission.md)
- 要点：三道闸门权限管线（闸1 硬拒绝 / 闸2 规则匹配 / 闸3 用户审批）插在工具执行前；`agent_loop` 注入 `check_permission`；被拒工具返回 `"Permission denied."`；s02 `run_bash` 危险检查移到闸1
- 验收：34/34 测试通过；实时跑通——写工作区内文件过闸直接执行；删文件触发闸2（⚠ Potentially destructive command + Allow?）

---

> 后续每完成一个阶段，更新对应行的状态（⬜→🚧→✅），并在「已完成阶段详情」补一节。
