# s03: Permission

po-agent 第三阶段，参照 `learn-claude-code/s03_permission`。在 s02 工具执行前加三道闸门权限管线：硬拒绝 → 规则匹配 → 用户审批。

## 本阶段完成（相对 s02）

在 s02 循环上做了一件核心事：**工具执行前插入 `check_permission()` 三道闸门**。

1. **闸 1 硬拒绝**（仅 bash）：`DENY_LIST`（`rm -rf /`、`sudo`、`mkfs`…）命中 → 直接拒，不执行。
2. **闸 2 规则匹配**：写工作区外 / bash 含 `rm `、`> /etc/`、`chmod 777` → 交闸 3。
3. **闸 3 用户审批**：`input("Allow? [y/N]")`，用户决定。
- 被拒的工具返回 `"Permission denied."` 给模型。
- s02 `run_bash` 里的危险检查**移到闸 1**（`run_bash` 简化）；SYSTEM 改为 "All destructive operations require user approval"；`> 工具名` 改青色。
- **循环核心不变**，只在执行前多一道 `check_permission`，依赖注入（`agent_loop` 接收 `check_permission` 参数）。

## 结构
- `config.py` — env + 5 工具 + 系统提示（需审批）
- `tools.py` — 5 工具 + `run_tool` 分发（`run_bash` 简化）
- `permissions.py` — `DENY_LIST`/`check_deny_list`/`PERMISSION_RULES`/`check_rules`/`ask_user`/`check_permission`
- `agent.py` — `agent_loop`（注入 `check_permission`）
- `cli.py` / `__main__.py` — REPL

## 运行
```sh
source ../.venv/bin/activate
python -m s03_permission
```

## 测试
```sh
pytest s03_permission/tests -v
```
