"""交互式 REPL（s03）：执行前过权限管线，> 工具名（青色）。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s03_permission.agent import agent_loop
from s03_permission.config import load
from s03_permission.tools import run_tool
from s03_permission.permissions import check_permission


def print_tool_use(name: str, output) -> None:
    if output is None:
        print(f"\033[36m> {name}\033[0m")
    else:
        print(str(output)[:200])


def main() -> None:
    cfg = load()
    print("s03: Permission")
    print("输入问题，回车发送。输入 q 退出。\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms03 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            check_permission=check_permission, on_tool_use=print_tool_use,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
