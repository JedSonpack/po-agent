# s03 Permission — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第三阶段（对应 `learn-claude-code/s03_permission`）
- 状态：自主模式（用户授权跳过审批）
- 前置：s02 已完成

## 1. 背景与目标

s02 的 file tools 受 `safe_path` 保护，但 bash 不受限制，`rm -rf /` 能跑。s03 在工具执行前加**三道闸门权限管线**：硬拒绝 → 规则匹配 → 用户审批。循环结构不变，只在执行前插一道 `check_permission`。

**目标**：行为对齐 s03 参考，沿用 s01/s02 的规范结构（包 + DI + TDD）。核心新增：`permissions.py` 模块 + `agent_loop` 注入 `check_permission`。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（包 + DI + TDD） |
| 功能范围 | 严格对齐 s03：三道闸门 + `check_permission` 插在执行前；不加 hooks/多来源规则/YoloClassifier |
| 测试策略 | TDD + mock 单测；`ask_user` 的 `input()` 用 monkeypatch；`check_permission` 注入假函数测 agent_loop |
| 同步/异步 | 同步 |
| 与 s02 的关系 | 独立包 `s03_permission/`，复制 s02 工具，加 permissions 模块 |

## 3. 结构

```
po-agent/s03_permission/
├── __init__.py
├── config.py        # env + client/MODEL/SYSTEM(改)/TOOLS(5)/load
├── tools.py         # run_bash(简化,无 DANGEROUS) + safe_path + run_read/write/edit/glob + TOOL_HANDLERS + run_tool
├── permissions.py   # 新：DENY_LIST + check_deny_list + PERMISSION_RULES + check_rules + ask_user + check_permission
├── agent.py         # agent_loop：+ check_permission 参数，执行前检查，deny → "Permission denied."
├── cli.py           # REPL（s03 >>）
├── __main__.py
├── README.md
└── tests/
    ├── test_tools.py
    ├── test_permissions.py   # 新
    └── test_agent.py
```

## 4. 核心新增：三道闸门（permissions.py）

s02 直接执行工具；s03 在执行前过 `check_permission(name, input) -> bool`：

- **闸 1 硬拒绝**（仅 bash）：`DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]`，`check_deny_list(command) -> str|None`。命中 → 打印 ⛔ → 返回 False。
- **闸 2 规则匹配**：`PERMISSION_RULES`，每条 `{tools, check(args)->bool, message}`，`check_rules(tool_name, args) -> str|None`。命中 → 进闸 3。
  - 规则 1：`write_file`/`edit_file` 写工作区外（`not (WORKDIR/path).is_relative_to(WORKDIR)`）→ "Writing outside workspace"
  - 规则 2：`bash` 含 `["rm ", "> /etc/", "chmod 777"]` → "Potentially destructive command"
- **闸 3 用户审批**：`ask_user(tool_name, args, reason) -> "allow"|"deny"`，打印 ⚠ + `input("Allow? [y/N] ")`。
- **管线** `check_permission(name, input) -> bool`：bash 先过闸 1（命中返回 False）；再过闸 2（命中调 `ask_user`，deny 返回 False）；都不过 → True。

`run_bash` 的危险检查**移到闸 1**（s02 在 run_bash 内检查，s03 改为闸 1 检查），故 s03 的 `run_bash` 简化（不再有 DANGEROUS 列表），与 s03 参考一致。

## 5. 组件职责

### config.py
- `prepare_env()`/`build_system_prompt(cwd)`/`make_tools()`/`load()`：同 s02，但 SYSTEM = `"You are a coding agent at {cwd}. All destructive operations require user approval."`

### tools.py
- `WORKDIR = Path.cwd()`
- `run_bash(command)`：**简化**（与 s03 参考一致）——`subprocess.run(shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)` + 截断 50000 + 超时/空输出。**无 DANGEROUS 检查**（移到闸 1）。
- `safe_path`/`run_read`/`run_write`/`run_edit`/`run_glob`/`TOOL_HANDLERS`/`run_tool`：同 s02

### permissions.py（新）
- `from s03_permission import tools`（规则里用 `tools.WORKDIR`，便于测试 monkeypatch）
- `DENY_LIST`/`check_deny_list`/`PERMISSION_RULES`/`check_rules`/`ask_user`/`check_permission`（见第 4 节）

### agent.py
```python
def agent_loop(*, client, model, system, tools, messages, run_tool,
               check_permission,              # s03 新增：(name, input) -> bool
               max_tokens=8000, on_tool_use=None) -> None:
    while True:
        response = client.messages.create(...)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if on_tool_use:
                on_tool_use(block.name, None)          # 打印 > 工具名（青色）
            if not check_permission(block.name, block.input):
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "Permission denied."})
                continue
            output = run_tool(block.name, block.input)
            if on_tool_use:
                on_tool_use(block.name, output)        # 打印输出
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```
`on_tool_use(name, output)`：`output is None` 表示"工具调用开始"（打印 `> name`），`output` 是字符串表示"结果"（打印输出）。这与 s03 参考"先打 `> name` 再 ⛔/输出"的顺序一致。

### cli.py
- `print_tool_use(name, output)`：`output is None` → `print(f"\033[36m> {name}\033[0m")`（青色，s03 参考）；否则 `print(str(output)[:200])`
- `main()`：`s03 >>` 提示符；传 `run_tool=run_tool`、`check_permission=check_permission`（从 permissions 导入）、`on_tool_use=print_tool_use`

### __main__.py
- `from s03_permission.cli import main; main()`

## 6. 数据流
```
用户输入 → cli → agent_loop:
  client.messages.create → assistant content（含 tool_use 块）
  stop_reason == "tool_use"?
    是 → 每个 tool_use 块：
      on_tool_use(name, None) 打印 > name
      check_permission(name, input)?
        否 → tool_result = "Permission denied."，跳过执行
        是 → output = run_tool(name, input)；on_tool_use(name, output)
      组装 tool_result → 追加 user msg → 循环
    否 → 返回
```

## 7. 错误处理（严格对齐 s03）
- 闸 1 命中 → 打印 `⛔ {reason}`，`check_permission` 返回 False → tool_result = `"Permission denied."`
- 闸 2 命中 + 用户拒绝 → `check_permission` 返回 False → `"Permission denied."`
- 闸 2 命中 + 用户允许 → 继续执行
- 三闸都过 → 正常执行
- `run_bash`/file tools 的错误处理同 s02（但 run_bash 无 DANGEROUS）
- `agent_loop` 不加 catch；API 异常上抛

## 8. 测试

### test_tools.py（monkeypatch `tools.WORKDIR` → tmp_path）
- `run_bash`：安全命令 / 超时（mock）/ 截断 / 空输出（**无 dangerous 测试**——移到 test_permissions）
- `safe_path`/`run_read`/`run_write`/`run_edit`/`run_glob`/`run_tool`：同 s02

### test_permissions.py（新）
- `check_deny_list`：命中各 DENY_LIST 模式 → 返回原因；安全命令 → None
- `check_rules`：写工作区外 → "Writing outside workspace"；bash 含 "rm " → "Potentially destructive command"；安全 → None（monkeypatch `tools.WORKDIR`）
- `ask_user`：monkeypatch `input` 返回 "y" → "allow"；"n"/空 → "deny"
- `check_permission`：deny-list 命中 → False（不问用户）；规则命中 + 用户 "y" → True；规则命中 + 用户 "n" → False；都不过 → True（monkeypatch `permissions.ask_user` 与 `input`）

### test_agent.py（fake client + fake run_tool + fake check_permission）
- `check_permission` 返回 True → 正常执行 run_tool
- `check_permission` 返回 False → tool_result = `"Permission denied."`，不调 run_tool
- `on_tool_use(name, None)` 在 check 前调用，`on_tool_use(name, output)` 在执行后调用（允许时）

不发真实 API。REPL 手动冒烟 + 验收实时跑通。

## 9. 运行
从 po-agent 根目录：`python -m s03_permission`

## 10. 非目标（YAGNI）
- 不加 hooks（s04）
- 不加多来源规则（CC 的 8 个来源）/ YoloClassifier / 权限冒泡
- 不加 Zod/passthrough
