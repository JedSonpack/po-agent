"""交互式 REPL：把用户输入喂给 agent_loop，打印工具调用与最终回复。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s01_agent_loop.agent import agent_loop
from s01_agent_loop.config import load
from s01_agent_loop.tools import run_bash


def print_tool_use(command: str, output: str) -> None:
    print(f"\033[33m$ {command}\033[0m")
    print(output[:200])


def main() -> None:
    cfg = load()
    print("s01: Agent Loop")
    print("输入问题，回车发送。输入 q 退出。\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms01 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_bash,
            on_tool_use=print_tool_use,
        )
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
