# s04 Hooks — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第四阶段（对应 `learn-claude-code/s04_hooks`）
- 状态：自主模式
- 前置：s03 已完成

## 1. 背景与目标

s03 的权限检查硬编码在循环里。每加一个检查（日志、git add、输出检查）都要改 `agent_loop`。s04 把扩展逻辑移到 **hook** 上：循环只调 `trigger_hooks(event, ...)`，具体逻辑全在 hook 回调里。s03 的权限逻辑包装成 PreToolUse hook。

**目标**：行为对齐 s04，沿用 s01-s03 结构（包 + DI + TDD）。核心新增：`hooks.py`（HOOKS 注册表 + 5 个 hook 回调）；`agent_loop` 注入 `trigger`（trigger_hooks 可调用对象），不再有 `check_permission`/`on_tool_use`。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD） |
| 功能范围 | 严格对齐 s04：4 事件 hook 系统 + s03 权限逻辑移进 permission_hook；不加 27 事件/stopHookActive/HookResult 14 字段 |
| 测试策略 | TDD + mock；`trigger` 注入假函数测 agent_loop；hook 回调单独测（monkeypatch input） |
| 同步/异步 | 同步 |
| 与 s03 的关系 | 独立包 `s04_hooks/`，复制 s03 工具，加 hooks 模块；无 permissions.py（逻辑移进 hook） |

## 3. 结构

```
po-agent/s04_hooks/
├── __init__.py
├── config.py     # env + client/MODEL/SYSTEM(回 s02 的)/TOOLS(5)/load
├── tools.py      # 同 s03（run_bash 简化 + safe_path + file tools + run_tool）
├── hooks.py      # 新：HOOKS + register_hook + trigger_hooks + 5 个 hook 回调 + register_defaults
├── agent.py      # agent_loop：注入 trigger，调 PreToolUse/PostToolUse/Stop
├── cli.py        # REPL（s04 >>，register_defaults + trigger UserPromptSubmit）
├── __main__.py
├── README.md
└── tests/
    ├── test_tools.py
    ├── test_hooks.py     # 新
    └── test_agent.py
```

## 4. 核心新增：hook 系统（hooks.py）

- `HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}`
- `register_hook(event, callback)`：追加到列表
- `trigger_hooks(event, *args) -> result | None`：按序调用回调，首个返回非 None 即返回它（阻止），全 None 则 None
- 5 个 hook 回调（与 s04 参考一致）：
  - `context_inject_hook(query)` — UserPromptSubmit：打印工作目录日志，返回 None
  - `permission_hook(block)` — PreToolUse：**s03 权限逻辑移到这里**。bash 命中 `DENY_LIST`（6 项，**无 `> /dev/sda`**）→ 返回 `"Permission denied by deny list"`；bash 含 `DESTRUCTIVE`（`["rm ", "> /etc/", "chmod 777"]`）→ `input("Allow? [y/N]")`，拒绝 → `"Permission denied by user"`；`write_file`/`edit_file` 写工作区外 → 询问，拒绝 → `"Permission denied by user"`；否则 None
  - `log_hook(block)` — PreToolUse：打印 `[HOOK] {name}({args 预览})`，返回 None
  - `large_output_hook(block, output)` — PostToolUse：`len > 100000` 打印警告，返回 None
  - `summary_hook(messages)` — Stop：统计 tool_result 数打印，返回 None
- `register_defaults()`：注册上述 5 个（cli 启动时调，不在导入时注册——便于测试）

## 5. 组件职责

### config.py
- 同 s02/s03，但 `build_system_prompt(cwd)` = `"You are a coding agent at {cwd}. Use tools to solve tasks. Act, don't explain."`（s04 回到 s02 的，非 s03 的 "approval"）

### tools.py
- 同 s03（`run_bash` 简化无 DANGEROUS——危险检查在 permission_hook；safe_path + file tools + run_tool）

### hooks.py
- 见第 4 节。`permission_hook` 用 `from s04_hooks import tools` 引用 `tools.WORKDIR`（便于测试 monkeypatch）

### agent.py
```python
def agent_loop(*, client, model, system, tools, messages, run_tool,
               trigger, max_tokens: int = 8000) -> None:
    while True:
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            force = trigger("Stop", messages)        # Stop hook 可强制续跑
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            blocked = trigger("PreToolUse", block)   # s04: hook 替代 check_permission
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue
            output = run_tool(block.name, block.input)
            trigger("PostToolUse", block, output)    # s04: 执行后 hook
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```
**无 `on_tool_use`、无 `check_permission`**——日志/权限全在 hook 里（严格对齐 s04：循环不打印工具名/输出，log_hook 打印调用，output 不打印只给模型）。

### cli.py
- `register_defaults()`（在 main 里调）
- `main()`：`s04 >>` 提示符；`trigger_hooks("UserPromptSubmit", query)` 后追加 user msg；`agent_loop(..., trigger=trigger_hooks)`；轮末打印最终 text

### __main__.py
- `from s04_hooks.cli import main; main()`

## 6. 数据流
```
用户输入 → cli: trigger("UserPromptSubmit", query) → agent_loop:
  client.messages.create → assistant content
  stop_reason != "tool_use"?
    是(做完) → force = trigger("Stop", messages); force 则注入续跑，否则退出
    否(调工具) → 每个 tool_use 块：
      blocked = trigger("PreToolUse", block)  # 跑 permission_hook + log_hook
      blocked → tool_result = str(blocked)，跳过执行
      否则 → output = run_tool(name, input); trigger("PostToolUse", block, output)  # 跑 large_output_hook
      组装 tool_result → 追加 user msg → 循环
```

## 7. 错误处理（严格对齐 s04）
- PreToolUse hook 返回非 None（permission_hook 拒绝）→ tool_result = 该字符串，跳过执行
- Stop hook 返回非 None → 注入为 user msg 续跑（教学版续跑，无 stopHookActive 防循环）
- run_bash/file tools 错误同 s03
- agent_loop 不加 catch；API 异常上抛

## 8. 测试

### test_tools.py（同 s03，18 个）
- run_bash 安全/超时/截断/空 + safe_path(3) + run_read(3) + run_write + run_edit(2) + run_glob(2) + run_tool(3)

### test_hooks.py（新）
- `register_hook`/`trigger_hooks`：注册返回值的 hook → trigger 返回它；返回 None → None；多 hook 首个非 None 胜出
- `permission_hook`：deny-list 命中 → "Permission denied by deny list"；destructive + input "y" → None；destructive + "n" → "Permission denied by user"；write 外 + "n" → 拒绝；安全 → None（monkeypatch `builtins.input`、`tools.WORKDIR`）
- `log_hook`/`large_output_hook`/`summary_hook`/`context_inject_hook`：返回 None（large_output 用大/小输出）

### test_agent.py（fake client + fake run_tool + fake trigger）
- trigger 返回 None（PreToolUse）→ run_tool 执行；trigger 返回 "blocked" → tool_result="blocked"，不调 run_tool
- Stop：trigger 返回 None → 退出；trigger 返回 "force" → 注入续跑（下一轮 end_turn 退出）
- PostToolUse：trigger 被调时含 ("PostToolUse", block, output)

不发真实 API。REPL 手动冒烟 + 验收实时跑通。

## 9. 运行
从 po-agent 根目录：`python -m s04_hooks`

## 10. 非目标（YAGNI）
- 不加 27 事件（只 4 个）/ HookResult 14 字段 / stopHookActive 防循环
- 不加 hook allow vs deny/ask 不变式（无 settings.json 层）
