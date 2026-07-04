# s02: Tool Use

po-agent 第二阶段，参照 `learn-claude-code/s02_tool_use`。在 s01 的循环上加 5 个工具 + 查表分发。循环本身不变，只把"硬编码 run_bash"换成 `run_tool(name, input)` 分发。

## 本阶段完成（相对 s01）

在 s01 循环上做了一件核心事：**从"一个工具"扩到"五个工具 + 查表分发"**。

1. **工具 1→5**：新增 `read_file`/`write_file`/`edit_file`/`glob`，模型不再靠 `cat`/`echo`/`find` 拼 shell。
2. **执行方式**：s01 硬编码 `run_bash(command)` → s02 `run_tool(name, input)` 查 `TOOL_HANDLERS` 字典分发。加工具只需注册一条映射。
3. **新增 `safe_path`**：文件工具路径必须留在 WORKDIR 内（沙箱）；但 `bash` 仍不受限——这是 s03 要补的安全缺口。
4. **细节**：`run_bash` 加 utf-8 encoding、系统提示改 "Use tools"、日志改打 `> 工具名`。

**循环核心（`while` + `stop_reason`）一行没改**，变的只是"执行工具"那一步。

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

## 使用示例

```
s02 >> 列出工作区里的 Python 文件
```

模型这次选 `glob` 工具（pattern `*.py`）而不是用 bash 拼 `find`——查表分发让模型挑最合适的工具，返回文件列表后总结。再试：

```
s02 >> 建一个 hi.txt 写 "hello"，然后读出来
```

模型依次调 `write_file` → `read_file`，观察 5 个工具（bash/read_file/write_file/edit_file/glob）各自怎么用。文件工具路径被 `safe_path` 锁在工作区内。

## 测试
```sh
pytest s02_tool_use/tests -v
```
