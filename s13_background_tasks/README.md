# s13: Background Tasks

po-agent 第十三阶段，参照 `learn-claude-code/s13_background_tasks`。把慢操作丢到 **daemon 线程**异步执行，主循环立即返回占位 `tool_result`；后台完成后把结果格式化为 `<task_notification>` 注入后续轮次。

## 本阶段完成（相对 s12）

在 s12 循环上做了一件核心事：**慢操作异步化**。

1. **`background.py`**：
   - **`is_slow_operation`**：非 bash → False；bash 命令含 install/build/test/deploy/compile/docker build/pip install/npm install/cargo build/pytest/make 任一 → True。
   - **`should_run_background`**：`run_in_background` 显式优先；否则回落 `is_slow_operation`。
   - **`start_background_task(block, run_tool) -> bg_id`**：daemon 线程执行 `run_tool`，立即返 `bg_0001`；worker **try/except**（异常写 `Error: ...` 标 completed，不泄漏）；锁内设 running→completed + results。
   - **`collect_background_results()`**：pop 已完成任务 → `<task_notification>`（task_id/status/command/summary，summary 截 200）。
   - 状态：`_bg_counter` + `background_tasks`/`background_results` dict + `background_lock`。
2. **bash schema 加 `run_in_background: boolean`**；`run_bash(command, run_in_background=False)` 接收但内部忽略（dispatch 层判断）。
3. **`agent_loop` 集成**：PreToolUse 后、同步执行前判 `should_run_background` → 后台派发 + 占位 `[Background task bg_0001 started] ...` tool_result；构造 user 消息前 `collect_background_results()` → 通知作 text block 追加（**results 在前、通知在后**）。
- **不复用 tool_use_id**：原始 tool_use 已用占位 tool_result 回复；后台完成是独立事件，用 `<task_notification>` text block 注入。
- **保留 s12 全部**（tasks + recovery + 段落化 system prompt + hooks/nag/compact/memory/skills/subagent/14 工具）。无新工具。
- 比 s12 多了**异步**：慢命令不阻塞，后台完成后通知注入。

## 结构
- `background.py` — is_slow_operation/should_run_background/start_background_task/collect_background_results + 状态/锁
- `agent.py` — `agent_loop`（后台派发 + 通知注入）
- `config.py` — bash schema 加 run_in_background
- `tools.py` — run_bash 加 run_in_background 参数（忽略）
- `tasks.py` / `recovery.py` / `system_prompt.py` / `skills.py` / `hooks.py` / `todo.py` / `subagent.py` / `compact.py` / `memory.py` / `cli.py` — 同 s12

## 运行
```sh
source ../.venv/bin/activate   # 或 source .venv/bin/activate
python -m s13_background_tasks
```

## 使用示例

```
s13 >> 后台运行 sleep 2 && echo done，同时用 glob 列出 *.md 文件
  [assembled] sections: identity, tools, workspace, skills
  [background] dispatched bg_0001: sleep 2 && echo done
  [HOOK] glob(['*.md'])
  ...（glob 同步返回，不阻塞）
  [background done] bg_0001: sleep 2 && echo done (...)
  <task_notification>...bg_0001...completed...</task_notification>
```

慢 bash 后台派发（立即返回占位），快操作同步执行；2s 后后台完成，`<task_notification>` 注入下一轮。

## 测试
```sh
pytest s13_background_tasks/tests -v
```
