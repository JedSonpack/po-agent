# s04: Hooks

po-agent 第四阶段，参照 `learn-claude-code/s04_hooks`。把扩展逻辑（权限/日志/大输出/收尾）从循环里移到 hook 上，循环只调 `trigger_hooks()`。

## 本阶段完成（相对 s03）

在 s03 循环上做了一件核心事：**扩展逻辑从循环移到 hook 系统**。

1. **HOOKS 注册表**：4 事件 `UserPromptSubmit`/`PreToolUse`/`PostToolUse`/`Stop`，各挂一串回调。
2. **`register_hook`/`trigger_hooks`**：trigger 按序跑回调，首个返回非 None 即阻止/续跑。
3. **s03 权限逻辑移进 `permission_hook`**（PreToolUse）：循环不再调 `check_permission`，改调 `trigger("PreToolUse", block)`。
4. **5 个 hook**：`context_inject_hook`（UserPromptSubmit 日志）、`permission_hook`（权限）、`log_hook`（调用日志）、`large_output_hook`（PostToolUse 大输出警告）、`summary_hook`（Stop 收尾统计）。
- 循环**无 `check_permission`、无 `on_tool_use`**——日志/权限全在 hook；SYSTEM 回到 s02 的 "Use tools"。
- **循环核心不变**，只是把"执行前检查/执行后处理/退出收尾"换成 `trigger_hooks()` 调用，逻辑全在 hook 回调里。

## 结构
- `config.py` — env + 5 工具 + 系统提示（回 s02）
- `tools.py` — 5 工具 + `run_tool` 分发（同 s03）
- `hooks.py` — `HOOKS`/`register_hook`/`trigger_hooks` + 5 hook 回调 + `register_defaults`
- `agent.py` — `agent_loop`（注入 `trigger`）
- `cli.py` / `__main__.py` — REPL（`register_defaults` + `trigger UserPromptSubmit`）

## 运行
```sh
source ../.venv/bin/activate
python -m s04_hooks
```

## 测试
```sh
pytest s04_hooks/tests -v
```
