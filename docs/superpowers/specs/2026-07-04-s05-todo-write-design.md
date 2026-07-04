# s05 TodoWrite — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第五阶段（对应 `learn-claude-code/s05_todo_write`）
- 状态：自主模式（参考为行为真实来源，用户预授权自主推进）
- 前置：s04 已完成

## 1. 背景与目标

s04 的 agent 能用工具、有权限、有 hook，但跑长任务会跑偏——工具结果不断填上下文，系统提示影响力被稀释，做着做着忘了最初目标。s05 给 agent 一个**规划能力**：`todo_write` 工具让它在动手前列步骤、执行中更新状态；外加一个 nag reminder，连续 3 轮没更新 todo 就注入提醒。

**关键洞察**：`todo_write` 不增加任何执行能力，增加的是规划能力。工具本身不读文件、不跑命令，只维护一个内存里的任务清单。

**目标**：行为对齐 s05，沿用 s01-s04 结构（包 + DI + TDD）。核心新增：`todo_write` 工具（`_normalize_todos` + `run_todo_write` + `CURRENT_TODOS`）+ nag reminder 机制（`TodoNag`）；`agent_loop` 注入可选 `nag`。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），行为严格对齐 |
| 功能范围 | 严格对齐 s05：`todo_write` 工具 + nag reminder（3 轮阈值）+ SYSTEM 规划引导；不加 Task System V2（持久化/依赖图/锁，那是 s12） |
| nag 的 DI | **注入 `TodoNag` 对象**（方案 A），`nag=None` 默认；三方法 `maybe_nag`/`on_round`/`on_todo_write`，状态自管 |
| 测试策略 | TDD + mock；`TodoNag` 单元测；`agent_loop` 用 FakeClient + 真/spy `TodoNag` 测 nag 行为；`nag=None` 时 s04 风格测试原样通过 |
| 同步/异步 | 同步 |
| 与 s04 的关系 | 独立包 `s05_todo_write/`，复制 s04 工具与 hooks，加 todo 机制 |

### nag DI 方案取舍

参考用模块全局 `rounds_since_todo` 硬编码在循环里。考虑过四种：

- **A. 注入 `TodoNag` 对象**（采用）— `maybe_nag(messages)`/`on_round()`/`on_todo_write()`，状态封装在对象里；`nag=None` 默认让 s04 风格测试不改签名即通过。
- B. 注入 3 个 callable — 啰嗦，且状态仍需外部闭包承载。
- C. 硬编码 + 模块全局（同参考）— 简单但测试间全局状态泄漏。
- D. nag 作为新 hook 事件 `PreLLM` — 过度设计，参考刻意把 nag 与 hooks 分开（"保留上一章的最小 hook 结构"）。

选 A：有状态逻辑用对象比散落 callable/全局干净；`nag=None` 默认保持向后兼容。

## 3. 结构

```
po-agent/s05_todo_write/
├── __init__.py
├── config.py     # env + client/MODEL/SYSTEM(加规划引导)/TOOLS(6)/load
├── tools.py      # s04 工具 + CURRENT_TODOS/_normalize_todos/run_todo_write + TOOL_HANDLERS+todo_write
├── todo.py       # 新：TodoNag（maybe_nag/on_round/on_todo_write）
├── agent.py      # agent_loop：注入 nag=None，调 maybe_nag/on_round/on_todo_write
├── cli.py        # REPL（s05 >>，register_defaults + trigger UserPromptSubmit + 构造 TodoNag）
├── __main__.py
├── README.md
└── tests/
    ├── test_tools.py     # +todo_write/_normalize_todos/run_tool 分发
    ├── test_todo.py      # 新：TodoNag
    ├── test_agent.py     # +nag 行为
    └── test_config.py    # 6 工具 + 规划提示
```

## 4. 核心新增

### 4.1 todo_write 工具（tools.py）

- `CURRENT_TODOS: list[dict] = []` — 模块级内存状态（同 s04 的 WORKDIR 模式；测试用 autouse fixture 重置）。
- `_normalize_todos(todos) -> tuple[list | None, str | None]`：
  - 若 `todos` 是 str：先 `json.loads`，失败再 `ast.literal_eval`，都失败返回 `(None, "Error: todos must be a list or JSON array string")`
  - 若非 list：`(None, "Error: todos must be a list")`
  - 逐项校验：必须是 dict；必须有 `content` 和 `status`；`status` 必须在 `("pending","in_progress","completed")`，否则 `(None, f"Error: todos[{i}] ...")`
  - 通过返回 `(todos, None)`
- `run_todo_write(todos) -> str`：normalize，出错返 error；`CURRENT_TODOS = todos`；打印彩色任务表（`## Current Tasks` + 每项 `[icon] content`，icon 按 status 着色）；返回 `f"Updated {len(CURRENT_TODOS)} tasks"`。
- `TOOL_HANDLERS["todo_write"] = run_todo_write`，`run_tool` 自动分发。
- 工具 schema：`todos` 数组，items 为 object，`content`(string) + `status`(string, enum 3 值)，required `["content","status"]`，顶层 required `["todos"]`。

### 4.2 TodoNag（todo.py）— 新机制模块

```python
class TodoNag:
    def __init__(self, threshold: int = 3,
                 reminder: str = "<reminder>Update your todos.</reminder>"):
        self.rounds_since_todo = 0
        self.threshold = threshold
        self.reminder = reminder
    def maybe_nag(self, messages) -> str | None:
        if self.rounds_since_todo >= self.threshold and messages:
            self.rounds_since_todo = 0
            return self.reminder
        return None
    def on_round(self) -> None:       # 每个 tool 轮 +1
        self.rounds_since_todo += 1
    def on_todo_write(self) -> None:  # 调 todo_write 归零
        self.rounds_since_todo = 0
```

### 4.3 agent_loop（agent.py）

签名加 `nag=None`（在 `trigger` 之后、`max_tokens` 之前）：

```python
def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger, nag=None, max_tokens=8000) -> None:
    while True:
        if nag:                                   # s05: nag reminder（LLM 调用前）
            reminder = nag.maybe_nag(messages)
            if reminder:
                messages.append({"role": "user", "content": reminder})
        response = client.messages.create(...)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            force = trigger("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        if nag:                                   # s05: tool 轮计数（处理 block 前）
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            blocked = trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":  # s05: todo_write 归零
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```

**计数时序与参考严格一致**：`on_round` 在确认 tool_use 后、处理 block 前调（参考 `rounds_since_todo += 1` 位置）；`on_todo_write` 在跑完 todo_write block 后调（参考 `if block.name == "todo_write": rounds_since_todo = 0`）；`maybe_nag` 在循环顶、LLM 调用前调（参考 `if rounds_since_todo >= 3 and messages:` 位置）。一轮内若调了 todo_write：先 `on_round`(+1) 再 `on_todo_write`(=0)，净效果 0，与参考一致。

## 5. 组件职责

### config.py
- `make_tools()` 返回 6 工具（s04 的 5 + `todo_write`）。
- `build_system_prompt(cwd)` = `"You are a coding agent at {cwd}. Before starting any multi-step task, use todo_write to plan your steps. Update status as you go."`（对齐参考 SYSTEM；去掉 s04 的 "Use tools to solve tasks. Act, don't explain."，换成规划引导）。
- `load()` 不变（nag 在 cli 构造，无 env 依赖）。

### tools.py
- 复制 s04 全部工具（run_bash/safe_path/run_read/write/edit/glob + TOOL_HANDLERS + run_tool）。
- 新增 `CURRENT_TODOS`/`_normalize_todos`/`run_todo_write`，`TOOL_HANDLERS["todo_write"] = run_todo_write`。

### todo.py
- 仅 `TodoNag` 类（nag/planning-nudge 机制；类比 s03 permissions.py、s04 hooks.py 是各阶段新机制模块）。

### agent.py
- s04 `agent_loop` + 可选 `nag` 参数及三处调用点。

### cli.py
- s04 REPL + `from s05_todo_write.todo import TodoNag`；`agent_loop(..., nag=TodoNag())`。

## 6. 测试策略

- **test_tools.py**：s04 的 18 个 + `run_todo_write` 正常/字符串解析/校验错误 + `run_tool("todo_write", ...)` 分发。autouse fixture 重置 `CURRENT_TODOS`。
- **test_todo.py**（新）：`TodoNag.maybe_nag` 阈值前返 None、达阈值返 reminder 并归零、`messages` 空不 nag、`on_round` 递增、`on_todo_write` 归零。
- **test_agent.py**：s04 的 4 个（`nag=None`）+ nag 注入测试（FakeClient 喂 3 轮 tool_use 无 todo_write → 第 4 轮 messages 里出现 reminder；调 todo_write → 计数归零不 nag）。
- **test_config.py**：`make_tools()` 6 工具且含 `todo_write`；`build_system_prompt` 含 `todo_write` 与 `plan`。

## 7. 行为对齐验收

- 全量测试通过（s01-s05）。
- 实时冒烟（`python -m s05_todo_write`）：给多步任务（如"在工作区建 demo_pkg：__init__.py + utils.py + tests"），观察首工具调用是否 `todo_write`、TODO 步骤数、执行中 status 从 pending→in_progress→completed。用不触发审批的 prompt（写工作区内文件），避免管道时序问题。

## 8. 范围外（YAGNI）

- Task System V2（文件持久化、`blockedBy` 依赖图、并发锁、四工具拆分、TaskCreated/TaskCompleted hook）— s12。
- `activeForm` 字段（CC spinner 用）— 教学版终端不需要。
- nag 阈值/reminder 文案可配置化 — 默认值即参考值，不过度抽象。
