"""交互式 REPL（s02）：打印 > 工具名，调 agent_loop 用 run_tool 分发。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s02_tool_use.agent import agent_loop
from s02_tool_use.config import load
from s02_tool_use.tools import run_tool


def print_tool_use(name: str, output: str) -> None:
    print(f"\033[33m> {name}\033[0m")
    print(str(output)[:200])


def main() -> None:
    cfg = load()
    print("s02: Tool Use — 在 s01 基础上加了 4 个工具")
    print("输入问题，回车发送。输入 q 退出。\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms02 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            on_tool_use=print_tool_use,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
