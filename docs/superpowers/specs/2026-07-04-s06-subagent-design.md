# s06 Subagent — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第六阶段（对应 `learn-claude-code/s06_subagent`）
- 状态：自主模式
- 前置：s05 已完成

## 1. 背景与目标

s05 的 agent 能计划，但大任务（"重构整个认证模块"）放一个对话里会被上下文淹没。s06 给 agent **委派能力**：`task` 工具派一个子 agent，子 agent 拿**全新 `messages[]`**（干净上下文）跑自己的循环，**只返回总结**（中间过程丢弃）。子 agent 没有 `task` 工具 → 不能递归派子。

**目标**：行为对齐 s06，沿用包 + DI + TDD。核心新增：`task` 工具 + `Subagent` 类（fresh messages、max_turns 安全限、`extract_text`、fallback）；`run_tool` 缝演进为 `make_run_tool(handlers, extra)` 工厂（让需要 client 的 task 处理器能在接线时绑定）。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），行为严格对齐 |
| 功能范围 | 严格对齐 s06：`task` 工具 + `spawn_subagent`（fresh messages、max 30 轮、summary only、fallback）+ `extract_text`；SUB_TOOLS 5 个（无 task 无 todo_write，防递归）；不加 Agent 工具/并发/命名 |
| run_tool 缝演进 | s06 引入 `make_run_tool(handlers, extra=None)` 工厂——接线时构造分发器，extra 注入依赖型处理器（`{"task": subagent.run}`）；模块级 `run_tool = make_run_tool(TOOL_HANDLERS)` 供测试 |
| Subagent DI | `Subagent(*, client, model, sub_system, sub_tools, sub_run_tool, trigger, max_turns=30, max_tokens=8000)`；`run(description) -> str` |
| 子 agent 工具 | `SUB_HANDLERS` = 5（bash/read/write/edit/glob，无 todo_write 无 task）；`sub_run_tool = make_run_tool(SUB_HANDLERS)` 注入 |
| hooks | 沿用 po-agent s04/s05 富 hooks（permission/log/large_output/summary/context_inject）；子 agent 经 trigger 跑 PreToolUse/PostToolUse（权限适用子 agent） |
| 循环 | **不变**（同 s05，含 nag）；task 经 run_tool 自动分发 |
| SYSTEM | parent 改为 "For complex sub-problems, use the task tool to spawn a subagent."（对齐参考）；SUB_SYSTEM = "Complete the task... return a concise summary. Do not delegate further." |

### run_tool 缝演进说明

s01 `run_tool(command)` → s02 `run_tool(name, input)` → s03 注入 check → s04 注入 trigger → s05 注入 nag。s06：`task` 处理器需要 client/model（模块加载时拿不到），故 `run_tool` 从"模块级静态函数"演进为"`make_run_tool` 工厂在接线时构造"。`make_run_tool(TOOL_HANDLERS, {"task": subagent.run})` 返回的闭包 dispatch 7 个工具；模块级 `run_tool = make_run_tool(TOOL_HANDLERS)` dispatch 6 个供单测。

## 3. 结构

```
po-agent/s06_subagent/
├── __init__.py
├── config.py     # env + make_tools(7) + make_sub_tools(5) + build_system_prompt + build_sub_system_prompt + load
├── tools.py      # s05 工具(6) + SUB_HANDLERS(5) + make_run_tool(handlers, extra) + run_tool(模块级默认)
├── hooks.py      # s05 原样复制（富 hooks 不变）
├── todo.py       # s05 原样复制（TodoNag）
├── subagent.py   # 新：extract_text + Subagent
├── agent.py      # s05 原样复制（agent_loop + nag，task 自动分发）
├── cli.py        # REPL：构造 Subagent + make_run_tool({"task": subagent.run}) 传入
├── __main__.py
├── README.md
└── tests/        # test_tools(+make_run_tool) / test_hooks / test_todo / test_subagent(新) / test_agent(+task) / test_config
```

## 4. 核心新增

### 4.1 make_run_tool（tools.py）

```python
def make_run_tool(handlers: dict, extra: dict | None = None):
    h = {**handlers, **(extra or {})}
    def run_tool(name: str, input: dict) -> str:
        handler = h.get(name)
        return handler(**input) if handler else f"Unknown: {name}"
    return run_tool

run_tool = make_run_tool(TOOL_HANDLERS)  # 模块级默认（6，供测试）
SUB_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                "edit_file": run_edit, "glob": run_glob}  # 5，无 todo_write 无 task
```

### 4.2 Subagent（subagent.py）

- `extract_text(content) -> str`：content 非 list → `str(content)`；list → 拼接所有 `type=="text"` 块的 `.text`（`"\n".join`）。
- `Subagent(*, client, model, sub_system, sub_tools, sub_run_tool, trigger, max_turns=30, max_tokens=8000)`。
- `run(description) -> str`：
  - 打印 `[Subagent spawned]`；`messages = [{"role":"user","content":description}]`（fresh）。
  - `for _ in range(max_turns)`：`client.messages.create(model, system=sub_system, messages, tools=sub_tools, max_tokens)`；append assistant；`stop_reason != "tool_use"` → break；否则遍历 tool_use blocks：trigger PreToolUse（blocked → tool_result with str(blocked)、continue）、`sub_run_tool(name, input)`、trigger PostToolUse、打印 `[sub] {name}: {output[:100]}`、append tool_result；append user results。
  - fallback：`result = extract_text(messages[-1]["content"])`；若空，倒序找 assistant 的 text；仍空 → `f"Subagent stopped after {max_turns} turns without final answer."`。
  - 打印 `[Subagent done]`；return result（**整段 messages 丢弃**）。

### 4.3 config.py

- `make_tools()` → 7（s05 的 6 + `task`）。`task` schema：`description`(string)，required `["description"]`，描述 "Launch a subagent to handle a complex subtask. Returns only the final conclusion."。
- `make_sub_tools()` → 5（bash/read/write/edit/glob；read_file 无 limit 项——对齐参考 SUB_TOOLS）。
- `build_system_prompt(cwd)` = `"You are a coding agent at {cwd}. For complex sub-problems, use the task tool to spawn a subagent."`。
- `build_sub_system_prompt(cwd)` = `"You are a coding agent at {cwd}. Complete the task you were given, then return a concise summary. Do not delegate further."`。
- `load()` 返回 client/model/system/tools/sub_system/sub_tools。

### 4.4 cli.py 接线

```python
register_defaults()
cfg = load()
subagent = Subagent(client=cfg["client"], model=cfg["model"], sub_system=cfg["sub_system"],
                    sub_tools=cfg["sub_tools"], sub_run_tool=make_run_tool(SUB_HANDLERS),
                    trigger=trigger_hooks)
run_tool = make_run_tool(TOOL_HANDLERS, {"task": subagent.run})
agent_loop(..., run_tool=run_tool, nag=TodoNag())
```

### 4.5 agent.py

s05 `agent_loop` 原样（含 nag）。task 经 `run_tool` 自动分发，循环不 special-case task。

## 5. 测试策略

- **test_tools.py**：s05 的 27 + `make_run_tool` 默认 dispatch 6 / extra 加 task / unknown；`SUB_HANDLERS` 5 项无 todo_write。
- **test_subagent.py**（新）：`extract_text`（string/list/无 text 块）；`run` 正常返回末尾 text + 跑了工具；blocked by hook 不跑工具；PostToolUse 触发；max_turns fallback（max_turns=3 + 永远 tool_use → fallback 串）；backward-search fallback（max_turns=2，首轮有 text 次轮无 → 返首轮 text）。
- **test_agent.py**：s05 的 6（nag）+ task 经 run_tool 分发测试。
- **test_config.py**：make_tools 7（含 task）；make_sub_tools 5（无 todo_write 无 task）；build_system_prompt 含 "task"/"subagent"；build_sub_system_prompt 含 "summary"/"delegate"。
- **test_hooks.py / test_todo.py**：s05 原样（改包名）。

## 6. 行为对齐验收

- 全量测试通过（s01-s06）。
- 实时冒烟（`python -m s06_subagent`）：让 parent 派子 agent 做只读子任务（如"用 task 工具派子 agent 统计 s05_todo_write/ 下 .py 文件数并总结"）。观察 `[Subagent spawned]` → `[sub] ...` → `[Subagent done]`，parent 收到总结。用只读子任务避免审批（子 agent 的 permission_hook 在管道遇 EOF 会崩）。

## 7. 范围外（YAGNI）

- Agent 工具的并发/命名/流式输出、多级递归、子 agent 的 todo_write — 后续阶段。
- 子 agent 的 Stop/UserPromptSubmit hook — 参考只跑 PreToolUse/PostToolUse。
