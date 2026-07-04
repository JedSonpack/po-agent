# s13 Background Tasks — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第十三阶段（对应 `learn-claude-code/s13_background_tasks`）
- 状态：自主模式
- 前置：s12 已完成

## 1. 背景与目标

s12 工具全同步执行——慢命令（pip install 等）阻塞循环。s13 把慢操作丢到 **daemon 线程**异步执行，主循环立即返回占位 `tool_result` 让模型继续；后台完成后把结果格式化为 `<task_notification>` 注入后续轮次的 user 消息。

**目标**：行为对齐 s13 后台任务机制，沿用包 + DI + TDD。新模块 `background.py`（`is_slow_operation`/`should_run_background`/`start_background_task`/`collect_background_results` + 状态字典/锁）；bash schema 加 `run_in_background`；`agent_loop` 加后台派发 + 通知注入。保留 s12 全部。无新工具。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD），后台机制行为严格对齐 |
| 累积结构 | **保留 s12 全部**（tasks + recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent/14 工具）；s13 参考为聚焦简化 loop（去 recovery/hooks/nag/skills/compact/memory/tasks），po-agent 不跟随 |
| 线程模型 | `threading.Thread(daemon=True)`，每后台任务一线程；进程退出即终止 |
| 状态 | `_bg_counter`（自增）+ `background_tasks: dict[bg_id → {tool_use_id, command, status}]` + `background_results: dict[bg_id → output]` + `background_lock = threading.Lock()`。status ∈ running/completed |
| bg_id | `f"bg_{_bg_counter:04d}"`（bg_0001...） |
| is_slow_operation | 非 bash → False；bash 命令小写含关键词任一 → True：install/build/test/deploy/compile/docker build/pip install/npm install/cargo build/pytest/make |
| should_run_background | `run_in_background` 显式优先（True → True）；否则 `is_slow_operation`；None/falsy → 回落启发式 |
| start_background_task | `(block, run_tool) -> bg_id`：注册 running → 启动 daemon worker。worker 调 `run_tool(block.name, block.input)`，**try/except**（po-agent 改进：异常写 `Error: ...` 标 completed，避免参考的静默泄漏）→ 锁内设 completed + results |
| collect_background_results | 锁内找 completed → pop 两个字典 → 格式化 `<task_notification>`（task_id/status/command/summary，summary 截 200）→ 返列表 |
| 通知注入 | 构造 user 消息前 `collect_background_results()`；**results 在前、通知作 text block 在后**（以 code.py 为准） |
| 不复用 tool_use_id | 原始 tool_use 已用占位 tool_result 回复；后台完成是独立事件，用 `<task_notification>` text block 注入（满足一 tool_use 对一 tool_result） |
| bash schema | 加 `run_in_background: boolean`（required 仅 command）；`run_bash(command, run_in_background=False)` 接收但内部忽略（dispatch 层判断） |
| PreToolUse | 后台派发前仍触发（权限检查对后台 bash 也生效）；PostToolUse 仅同步路径触发（后台未完成） |
| agent_loop | s12 + 后台分支 + 通知收集 |

## 3. 结构

```
po-agent/s13_background_tasks/
├── __init__.py
├── background.py     # 新：is_slow_operation/should_run_background/start_background_task/collect_background_results + 状态/锁
├── config.py         # s12 + bash schema 加 run_in_background
├── tools.py          # s12 + run_bash 加 run_in_background 参数（忽略）
├── tasks.py / recovery.py / system_prompt.py / skills.py / hooks.py / todo.py / subagent.py / compact.py / memory.py  # s12 原样
├── agent.py          # s12 + 后台派发 + 通知注入
├── cli.py            # s12 原样
├── __main__.py
├── README.md
└── tests/            # test_background(新) / test_agent(+后台) / test_tools(run_bash 参数) / test_config(bash schema) / 其余 s12 原样
```

## 4. 核心新增：background.py

```python
import threading

_bg_counter = 0
background_tasks: dict[str, dict] = {}    # bg_id → {tool_use_id, command, status}
background_results: dict[str, str] = {}   # bg_id → output
background_lock = threading.Lock()

_SLOW_KEYWORDS = ["install", "build", "test", "deploy", "compile",
                  "docker build", "pip install", "npm install",
                  "cargo build", "pytest", "make"]


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    cmd = tool_input.get("command", "").lower()
    return any(kw in cmd for kw in _SLOW_KEYWORDS)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    if tool_input.get("run_in_background"):
        return True
    return is_slow_operation(tool_name, tool_input)


def start_background_task(block, run_tool) -> str:
    """daemon 线程执行 block，立即返 bg_id。worker 异常不泄漏。"""
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    cmd = block.input.get("command", block.name)

    def worker():
        try:
            result = run_tool(block.name, block.input)
        except Exception as e:
            result = f"Error: {type(e).__name__}: {e}"
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = result

    with background_lock:
        background_tasks[bg_id] = {"tool_use_id": block.id, "command": cmd, "status": "running"}
    threading.Thread(target=worker, daemon=True).start()
    print(f"  \033[33m[background] dispatched {bg_id}: {cmd[:40]}\033[0m")
    return bg_id


def collect_background_results() -> list[str]:
    """收集已完成后台任务，pop 并格式化为 <task_notification>。"""
    with background_lock:
        ready_ids = [bid for bid, t in background_tasks.items() if t["status"] == "completed"]
    notifications = []
    for bg_id in ready_ids:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
        print(f"  \033[32m[background done] {bg_id}: {task['command'][:40]} ({len(output)} chars)\033[0m")
    return notifications
```

## 5. agent_loop 集成（agent.py）

s12 agent_loop + 后台分支 + 通知注入（工具执行段）：
```python
from s13_background_tasks.background import should_run_background, start_background_task, collect_background_results

# ... 循环顶部同 s12（ctx/sys_prompt/compact/nag/with_retry/max_tokens）...
        if nag:
            nag.on_round()
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "compact":
                compact.compact_history(messages)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "[Compacted. Conversation history has been summarized.]"})
                break
            blocked = trigger("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(blocked)})
                continue
            # s13: 慢操作后台派发（PreToolUse 后、同步执行前）
            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, run_tool)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"[Background task {bg_id} started] Command: {block.input.get('command', '')}. Result will be available when complete."})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)
            if nag and block.name == "todo_write":
                nag.on_todo_write()
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        # s13: 收集后台通知，作 text block 追加（results 在前、通知在后）
        user_content = list(results)
        notifications = collect_background_results()
        if notifications:
            for notif in notifications:
                user_content.append({"type": "text", "text": notif})
        messages.append({"role": "user", "content": user_content})
```

## 6. tools.py / config.py 改动

- **tools.py**：`run_bash(command: str, run_in_background: bool = False) -> str`（接收忽略）。
- **config.py**：bash schema 加 `"run_in_background": {"type": "boolean"}`（required 仍仅 command）。

## 7. 测试策略

- **test_background.py**（新）：
  - is_slow_operation：install/build/pytest/npm install → True；git status/echo → False；非 bash → False；大小写不敏感
  - should_run_background：run_in_background True（即使 echo）→ True；install 无显式 → True；echo 无显式 → False；run_in_background None → False
  - start_background_task：返 bg_0001；background_tasks[bg_0001] running + tool_use_id + command；连续两次 → bg_0002；worker 用瞬时 mock run_tool → 短暂等待后 completed + results（monkeypatch 或 reset 模块状态）
  - collect_background_results：空 → []；预置 completed → 返 1 条含 `<task_notification>`/`<task_id>bg_0001`/`<summary>`；pop 后不再收；只收 completed（running 留）；summary 截 200
- **test_agent.py**：s12 的 sed 复制；加：
  - bash run_in_background=True → 占位 tool_result `[Background task bg_0001 started]` + background_tasks 含 bg_0001 running（mock run_tool 慢/瞬时）
  - 同步 read_file 不走后台
  - 预置 completed bg → agent_loop 同步 tool 后 user 消息含 `<task_notification>` text block（results 在前、通知在后）
  - stop_reason 非 tool_use → 不 collect（无通知注入）
- **test_tools.py**：run_bash(command, run_in_background=True) → 同步执行（参数不影响）
- **test_config.py**：bash schema 含 run_in_background boolean
- 其余 test_*：s12 原样 sed 改名。

## 8. 行为对齐验收

- 全量测试通过（s01-s13）。
- 实时冒烟：`echo '后台运行 sleep 2 && echo done，同时用 glob 列出 *.md 文件' | python -m s13_background_tasks` → bash 后台派发（`[background] dispatched`），glob 同步返回，2s 后 `<task_notification>` 注入。

## 9. 范围外（YAGNI）

- `stop_background_task`/`get_background_output`/`list_background_tasks` 工具（参考无，模型只能被动等通知）。
- 输出重定向到文件 + 支持读取后续输出（参考 LocalShellTaskState，不实现）。
- 后台状态持久化（纯内存，进程退出丢失）。
