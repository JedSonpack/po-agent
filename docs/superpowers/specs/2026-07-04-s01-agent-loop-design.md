# s01 Agent Loop — 设计规格

- 日期：2026-07-04
- 阶段：po-agent 第一阶段（对应 `learn-claude-code/s01_agent_loop`）
- 状态：已批准

## 1. 背景与目标

在 po-agent 中实现第一阶段：基础 agent loop，参照 `learn-claude-code/s01_agent_loop`（137 行单文件教学实现）。核心概念——一个 `while True` 循环：模型调用工具就执行并把结果喂回去、继续；不调用就退出。

**目标**：行为与 s01 参考实现一致，但用规范结构重写（包结构 + 依赖注入 + 类型标注 + TDD），为 s02-s20 的机制叠加打好可测的底子。

## 2. 决策

| 项 | 决策 |
|---|---|
| 与参考实现关系 | 重构改进（参照概念，规范重写，不照搬） |
| 功能范围 | 严格对齐 s01：bash 工具 + REPL + 核心循环 + 危险黑名单 + 120s 超时；不加新功能 |
| 测试策略 | TDD + mock 单测；不发真实 API |
| 同步/异步 | 同步（与参考一致） |

## 3. 结构

包结构，按职责拆分：

```
po-agent/s01_agent_loop/
├── __init__.py
├── config.py     # env 加载 + client/MODEL/SYSTEM/TOOLS
├── tools.py      # run_bash（危险拦截/超时/截断）
├── agent.py      # agent_loop 核心循环（依赖注入）
├── cli.py        # REPL 入口 + readline + 打印
├── __main__.py   # python -m s01_agent_loop
├── README.md
└── tests/
    ├── __init__.py
    ├── test_tools.py
    └── test_agent.py
```

测试与实现同包 co-located，便于阶段隔离。导入用包路径 `from s01_agent_loop.agent import agent_loop`，避免跨阶段模块名冲突（s02 也会有 `tools.py`）。

## 4. 核心改进：依赖注入

参考 `code.py` 用模块级全局 `client/MODEL/SYSTEM/TOOLS`，`agent_loop(messages)` 隐式依赖，难以单测。重构为依赖注入：

```python
# agent.py
def agent_loop(*, client, model, system, tools, messages, run_tool,
               max_tokens=8000, on_tool_use=None):
    while True:
        response = client.messages.create(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = run_tool(block.input["command"])
                if on_tool_use:
                    on_tool_use(block.input["command"], output)
                results.append({"type": "tool_result",
                                "tool_use_id": block.id, "content": output})
        messages.append({"role": "user", "content": results})
```

- `client` 入参 → 测试传 mock，不发真实 API
- `run_tool` 入参 → 测试可替换；`tools.run_bash` 仍独立可测
- `on_tool_use` 回调 → 把参考里的彩色 print 抽到 cli，循环本身无副作用
- 行为与参考一致：stop_reason 判断、tool_result 组装、消息追加

## 5. 组件职责

### config.py
- `load_dotenv(override=True)`
- 若 `ANTHROPIC_BASE_URL` 存在，`os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)`（与参考一致，避免 ARK 端点用错鉴权）
- `client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))`
- `MODEL = os.environ["MODEL_ID"]`
- `SYSTEM = f"You are a coding agent at {os.getcwd()}. Use bash to solve tasks. Act, don't explain."`
- `TOOLS = [...]`（仅 bash 工具，schema 与参考一致）

### tools.py
- `run_bash(command: str) -> str`
- 危险黑名单：`["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]`（与参考一致，不改）
- `subprocess.run(command, shell=True, cwd=os.getcwd(), capture_output=True, text=True, timeout=120)`
- 输出 `out = (r.stdout + r.stderr).strip()`，截断 50000，空→`"(no output)"`
- `TimeoutExpired`→`"Error: Timeout (120s)"`；`FileNotFoundError/OSError`→`f"Error: {e}"`

### agent.py
- `agent_loop(...)` 如上
- 纯循环逻辑，所有依赖从参数进

### cli.py
- readline 修复（macOS libedit 中文输入，4 行 parse_and_bind，ImportError 容错）
- `main()`：REPL，提示 `s01 >> `，`q/exit/空` 退出，`EOFError/KeyboardInterrupt` 退出
- 维护 `history` 列表，每轮追加 user msg 并调 `agent_loop`
- `on_tool_use` 回调：彩色打印命令与输出前 200 字符（与参考一致）
- 轮末打印最终 assistant text 块

### __main__.py
- `from s01_agent_loop.cli import main; main()`

## 6. 数据流

```
用户输入 → cli 追加 user msg → agent_loop:
  client.messages.create(tools) → assistant content
  stop_reason == "tool_use"?
    是 → 每个 tool_use 块 run_bash → 组装 tool_result → 追加 user msg → 循环
    否 → 返回
→ cli 打印最终 text 块
```

## 7. 错误处理

严格对齐 s01，不扩展：
- `run_bash`：危险命令→`"Error: Dangerous command blocked"`；超时→`"Error: Timeout (120s)"`；OS 错误→`f"Error: {e}"`；截断 50000；空→`"(no output)"`
- `agent_loop`：不加 catch（参考也没在 loop 里 catch API 错误）；API 异常上抛至 cli
- `cli`：仅在 `input()` 处捕获 `EOFError/KeyboardInterrupt`（与参考一致），**不额外捕获 API 错误**——API 错误像参考一样上抛、终止 REPL

## 8. 测试

### test_tools.py
- 危险命令被拦截（返回 `"Error: Dangerous command blocked"`）
- 安全命令返回真实输出（如 `echo hello`）
- 超时分支：mock `subprocess.run` 抛 `TimeoutExpired`，验证返回 `"Error: Timeout (120s)"`
- 输出截断：构造 >50000 字符输出，验证截断
- 空输出→`"(no output)"`

### test_agent.py
用 fake client（`messages.create` 返回预设 response 对象，含 `content` 与 `stop_reason`）：
- 不调工具（`stop_reason != "tool_use"`）→ 立即返回，messages 仅追加 1 条 assistant
- 调工具→run_tool 执行→tool_result 喂回→第二轮不调工具→退出；验证 messages 序列正确
- tool_result 的 `tool_use_id` 与 `content` 正确
- `on_tool_use` 回调被调用

不发真实 API。REPL 手动冒烟。

依赖：补装 `pytest`（`uv pip install pytest`）。

## 9. 运行

从 po-agent 根目录：

```
python -m s01_agent_loop
```

行为与参考 `python s01_agent_loop/code.py` 一致。

## 10. 非目标（YAGNI）

- 不加新工具（s02 才加）
- 不加权限系统（s03 才加）
- 不加 max_turns / 压缩 / 钩子 / 子智能体（后续阶段）
- 不加流式（参考非流式）
- 不改黑名单内容（严格对齐）
