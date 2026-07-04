# s02: Tool Use

po-agent 第二阶段，参照 `learn-claude-code/s02_tool_use`。在 s01 的循环上加 5 个工具 + 查表分发。循环本身不变，只把"硬编码 run_bash"换成 `run_tool(name, input)` 分发。

## 结构
- `config.py` — env + 5 工具定义 + 系统提示
- `tools.py` — run_bash / safe_path / run_read / run_write / run_edit / run_glob + TOOL_HANDLERS + run_tool 分发器
- `agent.py` — `agent_loop`（DI：run_tool 分发器注入）
- `cli.py` / `__main__.py` — REPL

## 运行
```sh
source ../.venv/bin/activate
python -m s02_tool_use
```

## 测试
```sh
pytest s02_tool_use/tests -v
```
