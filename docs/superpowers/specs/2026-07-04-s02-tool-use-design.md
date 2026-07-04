# s02 Tool Use — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第二阶段（对应 `learn-claude-code/s02_tool_use`）
- 状态：自主模式（用户授权跳过审批，按参考实现）
- 前置：s01 已完成

## 1. 背景与目标

s01 只有一个 bash 工具，读文件要 `cat`、写文件要 `echo >`，模型得把"读这个文件"翻译成 shell 命令。s02 给 agent 加 4 个专用工具（read_file / write_file / edit_file / glob），共 5 个，并用**查表分发**替代 s01 硬编码的 `run_bash`。循环本身不变。

**目标**：行为对齐 s02 参考，沿用 s01 的规范结构（包 + 依赖注入 + TDD）。核心演进：`run_tool` 从"执行 bash"升级为"按名字分发"。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考关系 | 重构改进（沿用 s01 模式：包 + DI + TDD） |
| 功能范围 | 严格对齐 s02：5 工具 + TOOL_HANDLERS 分发 + safe_path 路径校验；不加权限/并发/钩子 |
| 测试策略 | TDD + mock 单测；不发真实 API |
| 同步/异步 | 同步（与参考一致） |
| 与 s01 的关系 | 独立包 `s02_tool_use/`，复制 s01 循环结构，改分发 |

## 3. 结构

```
po-agent/s02_tool_use/
├── __init__.py
├── config.py     # env + client/MODEL/SYSTEM/TOOLS(5 个)/load
├── tools.py      # run_bash + safe_path + run_read/write/edit/glob + TOOL_HANDLERS + run_tool 分发器
├── agent.py      # agent_loop（DI：run_tool(name,input) 分发器注入）
├── cli.py        # REPL（s02 >>，打印 > 工具名）
├── __main__.py
├── README.md
└── tests/
    ├── __init__.py
    ├── test_tools.py
    └── test_agent.py
```

## 4. 核心演进：从 run_bash 到分发器

s01：`run_tool: Callable[[str], str]`，循环里 `run_tool(block.input["command"])`（硬编码 bash）。
s02：`run_tool: Callable[[str, dict], str]`，循环里 `run_tool(block.name, block.input)`（按名字分发）。

分发器在 `tools.py`：

```python
TOOL_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                 "edit_file": run_edit, "glob": run_glob}

def run_tool(name: str, input: dict) -> str:
    handler = TOOL_HANDLERS.get(name)
    return handler(**input) if handler else f"Unknown: {name}"
```

- `**input` 把入参字典按关键字展开，匹配各 handler 签名：`run_bash(command)`、`run_read(path, limit=None)`、`run_write(path, content)`、`run_edit(path, old_text, new_text)`、`run_glob(pattern)`。
- 未知工具 → `"Unknown: {name}"`（与参考一致）。

## 5. 组件职责

### config.py
- `prepare_env()`：同 s01（`load_dotenv(override=True)` + BASE_URL 存在时 pop AUTH_TOKEN）
- `build_system_prompt(cwd)`：`"You are a coding agent at {cwd}. Use tools to solve tasks. Act, don't explain."`（s02 用 "tools" 而非 "bash"）
- `make_tools()`：返回 5 个工具定义（bash / read_file / write_file / edit_file / glob，schema 与参考一致；read_file 有可选 `limit`）
- `load()`：组装 client / model / system / tools

### tools.py
- `WORKDIR = Path.cwd()`（模块级，文件工具的工作目录；测试用 monkeypatch 改）
- `run_bash(command)`：危险黑名单 + `subprocess.run(shell=True, cwd=WORKDIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)` + 截断 50000 + 超时/OS 错误（与 s02 参考一致，比 s01 多了 encoding）
- `safe_path(p) -> Path`：`(WORKDIR / p).resolve()`，若 `not is_relative_to(WORKDIR)` 抛 `ValueError(f"Path escapes workspace: {p}")`
- `run_read(path, limit=None)`：读文本 splitlines；`limit and limit < len(lines)` 时截断为 `lines[:limit]` + 一行 `f"... ({len(lines)-limit} more lines)"`；异常 → `f"Error: {e}"`
- `run_write(path, content)`：safe_path + `parent.mkdir(parents=True, exist_ok=True)` + write_text → `f"Wrote {len(content)} bytes to {path}"`；异常 → `f"Error: {e}"`
- `run_edit(path, old_text, new_text)`：读文本，`old_text not in text` → `f"Error: text not found in {path}"`；否则 `write_text(text.replace(old_text, new_text, 1))` → `f"Edited {path}"`；异常 → `f"Error: {e}"`
- `run_glob(pattern)`：`glob.glob(pattern, root_dir=WORKDIR)`，过滤仍 `is_relative_to(WORKDIR)` 的，`"\n".join` 或 `"(no matches)"`；异常 → `f"Error: {e}"`
- `TOOL_HANDLERS` + `run_tool(name, input)` 分发器（见第 4 节）

### agent.py
```python
def agent_loop(*, client, model, system, tools, messages, run_tool,
               max_tokens=8000, on_tool_use=None) -> None:
    while True:
        response = client.messages.create(model=model, system=system, messages=messages,
                                          tools=tools, max_tokens=max_tokens)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_tool(block.name, block.input)   # s02：按名字分发
                if on_tool_use:
                    on_tool_use(block.name, output)           # s02：日志带工具名
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```
与 s01 唯二不同：`run_tool(block.name, block.input)`（原 `run_tool(block.input["command"])`）、`on_tool_use(block.name, output)`（原 `(command, output)`）。

### cli.py
- readline 修复（同 s01）
- `print_tool_use(name, output)`：`print(f"\033[33m> {name}\033[0m")` + `print(str(output)[:200])`（s02 用 `> 工具名`，s01 用 `$ 命令`）
- `main()`：`s02 >> ` 提示符；调 `agent_loop` 传 `run_tool=run_tool`（从 tools 导入分发器）、`on_tool_use=print_tool_use`；轮末打印最终 text 块

### __main__.py
- `from s02_tool_use.cli import main; main()`

## 6. 数据流
```
用户输入 → cli 追加 user msg → agent_loop:
  client.messages.create(tools) → assistant content（可能含多个 tool_use 块）
  stop_reason == "tool_use"?
    是 → 每个 tool_use 块：run_tool(block.name, block.input) 查表分发 → 组装 tool_result → 追加 user msg → 循环
    否 → 返回
→ cli 打印最终 text 块
```

## 7. 错误处理（严格对齐 s02）
- `run_bash`：危险→`"Error: Dangerous command blocked"`；超时→`"Error: Timeout (120s)"`；OS 错误→`f"Error: {e}"`；截断 50000；空→`"(no output)"`
- `safe_path`：路径逃逸→`ValueError`，被各 file tool 的 `except Exception` 捕获 → `f"Error: {e}"`
- `run_read/write/edit/glob`：任何异常 → `f"Error: {e}"`；`run_edit` 文本不存在 → `f"Error: text not found in {path}"`
- 未知工具名 → `f"Unknown: {name}"`
- `agent_loop`：不加 catch；API 异常上抛（与 s01/s02 一致）
- `cli`：仅 `input()` 处捕获 EOF/Ctrl-C（与 s02 一致）

## 8. 测试

### test_tools.py（用 monkeypatch 把 `tools.WORKDIR` 指向 `tmp_path`）
- `run_bash`：危险拦截 / 安全命令 / 超时（mock）/ 截断 / 空输出（沿用 s01 的 5 个）
- `safe_path`：正常返回 Path / `..` 逃逸抛 ValueError / 绝对路径抛 ValueError
- `run_read`：读文件 / limit 截断 + "... (N more lines)" / 不存在 → "Error: ..."
- `run_write`：写文件 + 返回 "Wrote N bytes to {path}" / 父目录自动创建
- `run_edit`：替换 → "Edited {path}" / old 不存在 → "Error: text not found in {path}"
- `run_glob`：匹配 / 无匹配 → "(no matches)"
- `run_tool` 分发器：bash / read_file 各一条 / 未知工具 → "Unknown: {name}"

### test_agent.py（fake client + fake run_tool）
- 不调工具 → 退出
- 单工具调用 → `run_tool(name, input)` 被调，结果喂回，第二轮退出
- **一次返回多个 tool_use** → `run_tool` 按顺序调用每个，各自 tool_result 组装
- `on_tool_use(name, output)` 被调
- 未知工具名经由 `run_tool` 处理（fake `run_tool` 返回 "Unknown: ..."，结果照常喂回）

不发真实 API。REPL 手动冒烟 + 验收实时跑通。

## 9. 运行
从 po-agent 根目录：`python -m s02_tool_use`

## 10. 非目标（YAGNI）
- 不加权限系统（s03）
- 不加并发执行（参考按原始顺序逐个执行；CC 的分区并发不实现）
- 不加钩子（s04）
- 不加流式、结果落盘、Zod 验证
