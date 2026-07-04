# s01: Agent Loop

po-agent 第一阶段，参照 `learn-claude-code/s01_agent_loop`。核心：一个 `while` 循环——模型调工具就执行并喂回结果、继续；不调就停。

## 本阶段完成

从零搭起最小可运行的 agent：一个 `while True` 循环 + 一个 bash 工具 + 交互式 REPL。核心机制——模型调工具（`stop_reason == "tool_use"`）就执行并把结果喂回、继续循环，不调就退出。用依赖注入（`agent_loop` 接收 client / run_tool / on_tool_use）让循环可单测，11 个 mock 测试通过。安全只有简陋的危险命令黑名单 + 120s 超时 + 输出截断。这是后续 19 个阶段的基座，**循环本身此后基本不变**。

## 结构
- `config.py` — env 加载、客户端、系统提示、工具定义
- `tools.py` — `run_bash`（危险黑名单 / 120s 超时 / 50000 截断）
- `agent.py` — `agent_loop` 核心循环（依赖注入，可单测）
- `cli.py` / `__main__.py` — 交互式 REPL

## 运行
从 po-agent 根目录：

```sh
source .venv/bin/activate
python -m s01_agent_loop
```

## 测试
从 po-agent 根目录：

```sh
pytest s01_agent_loop/tests -v
```
