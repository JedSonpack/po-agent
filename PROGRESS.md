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
| s04 | Hooks | ✅ | [`s04_hooks/`](s04_hooks/) | hook 系统：扩展逻辑（权限/日志/收尾）挂循环上，不写进循环 |
| s05 | TodoWrite | ✅ | [`s05_todo_write/`](s05_todo_write/) | 给 agent 一个任务清单，防止跑偏 |
| s06 | Subagent | ✅ | [`s06_subagent/`](s06_subagent/) | 大任务拆给子 agent，子任务拿干净上下文 |
| s07 | Skill Loading | ✅ | [`s07_skill_loading/`](s07_skill_loading/) | 技能按需加载，用到才读 |
| s08 | Context Compact | ✅ | [`s08_context_compact/`](s08_context_compact/) | 上下文满了想办法压缩腾地方 |
| s09 | Memory | ✅ | [`s09_memory/`](s09_memory/) | 持久记忆层，存压缩会丢的关键细节 |
| s10 | System Prompt | ✅ | [`s10_system_prompt/`](s10_system_prompt/) | 运行时组装系统提示，不硬编码 |
| s11 | Error Recovery | ✅ | [`s11_error_recovery/`](s11_error_recovery/) | 错误重试与恢复策略 |
| s12 | Task System | ✅ | [`s12_task_system/`](s12_task_system/) | 大目标拆成可追踪的小任务 |
| s13 | Background Tasks | ✅ | [`s13_background_tasks/`](s13_background_tasks/) | 慢操作放后台执行 |
| s14 | Cron Scheduler | ✅ | [`s14_cron_scheduler/`](s14_cron_scheduler/) | 按时间表触发任务 |
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

### s04 — Hooks ✅
- 目录：[`s04_hooks/`](s04_hooks/)（config / tools / hooks / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s04-hooks-design.md`](docs/superpowers/specs/2026-07-04-s04-hooks-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s04-hooks.md`](docs/superpowers/plans/2026-07-04-s04-hooks.md)
- 要点：hook 系统（4 事件 UserPromptSubmit/PreToolUse/PostToolUse/Stop + `register_hook`/`trigger_hooks`）；s03 权限逻辑移进 `permission_hook`；`agent_loop` 注入 `trigger`，无 `check_permission`/`on_tool_use`；5 个 hook 回调
- 验收：37/37 测试通过；实时跑通——`[HOOK]` 日志在 UserPromptSubmit/PreToolUse(log)/Stop(summary) 各触发点出现

### s05 — TodoWrite ✅
- 目录：[`s05_todo_write/`](s05_todo_write/)（config / tools / hooks / todo / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s05-todo-write-design.md`](docs/superpowers/specs/2026-07-04-s05-todo-write-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s05-todo-write.md`](docs/superpowers/plans/2026-07-04-s05-todo-write.md)
- 要点：`todo_write` 规划工具（`_normalize_todos` 校验 list/JSON/ast 字符串 + `CURRENT_TODOS` 内存态 + `run_todo_write` 彩色输出）经 `TOOL_HANDLERS` 自动分发；`TodoNag` 机制（连续 3 tool 轮未更新 todo → 注入 `<reminder>`，调 todo_write 归零）注入 `agent_loop`（`nag=None` 默认）；SYSTEM 加 "use todo_write to plan"；hooks 同 s04
- 验收：54/54 测试通过（全量 163）；实时跑通——模型首工具即 `todo_write` 列 5 步，执行中 status `pending→in_progress→completed`，nag 未触发（按时更新），demo_pkg 测试通过

### s06 — Subagent ✅
- 目录：[`s06_subagent/`](s06_subagent/)（config / tools / hooks / todo / subagent / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s06-subagent-design.md`](docs/superpowers/specs/2026-07-04-s06-subagent-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s06-subagent.md`](docs/superpowers/plans/2026-07-04-s06-subagent.md)
- 要点：`task` 工具 + `Subagent` 类（fresh `messages[]`、`max_turns=30` 安全限、`SUB_TOOLS` 5 工具无 task/todo_write 防递归、跑 PreToolUse/PostToolUse hooks、`extract_text` 只返总结、fallback 倒序找 assistant text）；`run_tool` 缝演进为 `make_run_tool(handlers, extra)` 工厂（让需 client 的 task 处理器接线时绑定）；循环不变（task 经 run_tool 自动分发）
- 验收：70/70 测试通过（全量 233）；实时跑通——parent 调 `task` 派子 agent 统计 .py 文件，`[Subagent spawned]`→`[sub] bash`→`[Subagent done]`，parent 只收总结（14 个文件）

### s07 — Skill Loading ✅
- 目录：[`s07_skill_loading/`](s07_skill_loading/)（config / tools / skills / hooks / todo / subagent / agent / cli / __main__ + tests + `skills/` 样本）
- 规格：[`docs/superpowers/specs/2026-07-04-s07-skill-loading-design.md`](docs/superpowers/specs/2026-07-04-s07-skill-loading-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s07-skill-loading.md`](docs/superpowers/plans/2026-07-04-s07-skill-loading.md)
- 要点：两级按需知识注入——`skills.py` 扫 `skills/` 建 `SKILL_REGISTRY`（`_parse_frontmatter` 解 YAML）；Layer 1 `build_system_prompt` 注目录（name+描述，常驻）；Layer 2 `load_skill` 工具按需返全文（注册表查找，防路径穿越）；`load_skill` 静态处理器（无需 client）直接进 `TOOL_HANDLERS`；子 agent 不给 load_skill；循环不变
- 验收：86/86 测试通过（全量 319）；实时跑通——SYSTEM 列技能目录，agent 调 `load_skill("code-review")` 拿全文并总结 review 步骤

### s08 — Context Compact ✅
- 目录：[`s08_context_compact/`](s08_context_compact/)（config / tools / compact / skills / hooks / todo / subagent / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s08-context-compact-design.md`](docs/superpowers/specs/2026-07-04-s08-context-compact-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s08-context-compact.md`](docs/superpowers/plans/2026-07-04-s08-context-compact.md)
- 要点：四层压缩管线（`compact.py` 纯函数 snip/micro + `Compactor` 类）——L1 snip(>50 砍中间不拆对)/L2 micro(旧 tool_result 占位)/L3 budget(大结果落盘 `<persisted-output>`)/L4 compact_history(超 50000 → LLM 总结)；`compact` 工具（special-case 不走 run_tool）；reactive_compact（prompt_too_long 重试 1 次）；`Compactor` 注入 `agent_loop`；保留 s07 hooks/nag
- 验收：116/116 测试通过（全量 435）；实时跑通——agent 调 `compact` 工具触发 `[transcript saved: ...]`，messages 被总结替换，报告保留/丢弃内容

### s09 — Memory ✅
- 目录：[`s09_memory/`](s09_memory/)（config / tools / skills / hooks / todo / subagent / compact / memory / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s09-memory-design.md`](docs/superpowers/specs/2026-07-04-s09-memory-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s09-memory.md`](docs/superpowers/plans/2026-07-04-s09-memory.md)
- 要点：持久跨会话记忆（`memory.py` `Memory` 类）——`.memory/` 存记忆文件（YAML frontmatter + body）+ `MEMORY.md` 索引；SYSTEM 注索引（`build_index_section`）；`load_memories` 按需注入相关记忆到 user 轮（LLM 选+关键词回退）；turn 结束 `extract_memories`（LLM 抽 `{name,type,description,body}`）+ `consolidate_memories`（≥10 合并）；`pre_compress` stringify 快照保真；`Memory` 注入 `agent_loop`；保留 s08 全部机制；无新工具
- 关键发现：glm-5.2 是推理模型，memory 的 LLM 调用（select/extract/consolidate）需大 `max_tokens`（2000/4000/4000）——参考的 200/800 会被 thinking 吃光、无 text 输出
- 验收：137/137 测试通过（全量 572）；实时跑通——`[Memory: extracted 3 new memories]`，`.memory/` 落 3 记忆文件 + MEMORY.md 索引

### s10 — System Prompt ✅
- 目录：[`s10_system_prompt/`](s10_system_prompt/)（config / tools / skills / hooks / todo / subagent / compact / memory / system_prompt / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s10-system-prompt-design.md`](docs/superpowers/specs/2026-07-04-s10-system-prompt-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s10-system-prompt.md`](docs/superpowers/plans/2026-07-04-s10-system-prompt.md)
- 要点：运行时段落化组装系统提示（`system_prompt.py`）——`PROMPT_SECTIONS`（identity/tools/workspace/skills）+ memory 段（动态来自 `Memory.build_index_section()`）；`assemble_system_prompt(context)` 选段 `\n\n` 拼（memory 段仅索引非空时加）；`get_system_prompt(context)` 单槽缓存（`json.dumps(sort_keys=True)` key，命中 `[cache hit]`/未命中 `[assembled] sections: ...`）；`build_context` 从组件构造；`agent_loop` **drop `system` 改 `context`**，每轮重算 context（重读 memory 索引）+ 取缓存 prompt；保留 s09 全部机制；无新工具
- 验收：148/148 测试通过（全量 720）；实时跑通——首轮 `[assembled] sections: identity, tools, workspace, skills`，后续 tool 轮 `[cache hit]`，模型调 glob+bash 回答

### s11 — Error Recovery ✅
- 目录：[`s11_error_recovery/`](s11_error_recovery/)（recovery / config / tools / skills / hooks / todo / subagent / compact / memory / system_prompt / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s11-error-recovery-design.md`](docs/superpowers/specs/2026-07-04-s11-error-recovery-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s11-error-recovery.md`](docs/superpowers/plans/2026-07-04-s11-error-recovery.md)
- 要点：LLM 调用韧性外壳（`recovery.py`）——`RecoveryState` 跨迭代跟踪；`with_retry(fn, state)` 429/529 指数退避重试（最多 10 次），529 连续 3 次切 `FALLBACK_MODEL`；`retry_delay`（min(500×2^a,32000)/1000 + 抖动）；`is_prompt_too_long_error`；`agent_loop` LLM 调用包 `with_retry`，`stop_reason=="max_tokens"` → 升级 8K→64K（1 次不 append）→ 续写（3 次），outer except prompt_too_long→reactive_compact（1 次，复用 s08），不可恢复→追加 `[Error]` 优雅返回（s08 raise 改为优雅返回）；保留 s10 全部；无新工具
- 验收：161/161 测试通过（全量 881）；实时跑通——正常路径行为同 s10，recovery 路径异常时自动生效

### s12 — Task System ✅
- 目录：[`s12_task_system/`](s12_task_system/)（tasks / recovery / config / tools / skills / hooks / todo / subagent / compact / memory / system_prompt / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s12-task-system-design.md`](docs/superpowers/specs/2026-07-04-s12-task-system-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s12-task-system.md`](docs/superpowers/plans/2026-07-04-s12-task-system.md)
- 要点：文件持久化任务图（`tasks.py`）——`Task` dataclass（id/subject/description/status/owner/blockedBy）+ `.tasks/{id}.json`；`can_start`（blockedBy 全 completed，缺失=blocked 不抛，不递归）；`claim_task`（pending+can_start→in_progress+owner）/`complete_task`（→completed，扫描报 `Unblocked` 下游）；5 工具 handler 进 `TOOL_HANDLERS`+`make_tools()`（14）；`agent_loop` 不改（任务工具经 run_tool 自动分发）；保留 s11 全部
- 验收：192/192 测试通过（全量 1073）；实时跑通——agent 调 create_task/list_tasks/claim_task/complete_task，`.tasks/` 落 JSON，依赖图解锁下游

### s13 — Background Tasks ✅
- 目录：[`s13_background_tasks/`](s13_background_tasks/)（background / tasks / recovery / config / tools / skills / hooks / todo / subagent / compact / memory / system_prompt / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s13-background-tasks-design.md`](docs/superpowers/specs/2026-07-04-s13-background-tasks-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s13-background-tasks.md`](docs/superpowers/plans/2026-07-04-s13-background-tasks.md)
- 要点：慢操作异步化（`background.py`）——`is_slow_operation`（bash 关键词启发）/`should_run_background`（run_in_background 显式优先）/`start_background_task(block, run_tool)`（daemon 线程，worker try/except 不泄漏）/`collect_background_results`（pop completed → `<task_notification>`，summary 截 200）；bash schema 加 `run_in_background`；`agent_loop` PreToolUse 后判后台派发 + 占位 tool_result，构造 user 消息前收集通知作 text block 追加（results 在前、通知在后）；不复用 tool_use_id；保留 s12 全部；无新工具
- 验收：216/216 测试通过（全量 1289）；实时跑通——`[background] dispatched bg_0001`（sleep 2 后台），glob 同步返回不阻塞

### s14 — Cron Scheduler ✅
- 目录：[`s14_cron_scheduler/`](s14_cron_scheduler/)（cron / background / tasks / recovery / config / tools / skills / hooks / todo / subagent / compact / memory / system_prompt / agent / cli / __main__ + tests）
- 规格：[`docs/superpowers/specs/2026-07-04-s14-cron-scheduler-design.md`](docs/superpowers/specs/2026-07-04-s14-cron-scheduler-design.md)
- 计划：[`docs/superpowers/plans/2026-07-04-s14-cron-scheduler.md`](docs/superpowers/plans/2026-07-04-s14-cron-scheduler.md)
- 要点：按时间表触发（`cron.py`）——`CronJob` dataclass；`cron_matches`/`_cron_field_matches`（5 字段，DOM/DOW OR 语义，dow 换算 `(weekday+1)%7`）；`validate_cron`；`schedule_job`/`cancel_job` + `save/load_durable_jobs`（`.scheduled_tasks.json`，load 跳过非法）；`_check_and_fire(now)` 纯函数（minute_marker 去重，one-shot 删除）+ `cron_scheduler_loop` daemon + `queue_processor_loop`（agent 空闲时拉起 turn）+ `agent_lock`；`start_scheduler(run_turn)` 显式启动（po-agent 改进：import 不起线程）；3 工具；`agent_loop` 顶部 `consume_cron_queue` 注入 `[Scheduled]`；cli `run_turn`+`agent_lock`；保留 s13 全部
- 验收：263/263 测试通过（全量 1552）；实时跑通——`schedule_cron` 注册 → `[cron fire]` 调度线程触发 → agent 消费 `[Scheduled]` 执行提示词

---

> 后续每完成一个阶段，更新对应行的状态（⬜→🚧→✅），并在「已完成阶段详情」补一节。
