"""交互式 REPL（s04）：扩展逻辑挂在 hook 上，循环只调 trigger。"""
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass

from s04_hooks.agent import agent_loop
from s04_hooks.config import load
from s04_hooks.tools import run_tool
from s04_hooks.hooks import trigger_hooks, register_defaults


def main() -> None:
    register_defaults()
    cfg = load()
    print("s04: Hooks — extension logic on hooks, loop stays clean")
    print("Type a question, press Enter. Type q to quit.\n")
    history: list = []
    while True:
        try:
            query = input("\033[36ms04 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(
            client=cfg["client"], model=cfg["model"], system=cfg["system"],
            tools=cfg["tools"], messages=history, run_tool=run_tool,
            trigger=trigger_hooks,
        )
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
